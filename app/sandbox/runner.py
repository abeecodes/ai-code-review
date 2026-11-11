"""Run generated tests against submitted code in an isolated temp directory.

Python tests run with pytest, JavaScript tests with Node's built-in test runner.

SANDBOX_MODE=subprocess : temp dir, run timeout, per-test timeout, secrets scrubbed from the environment,
                          (POSIX) resource limits. NOT a security boundary.
SANDBOX_MODE=docker     : the same inside a container with no network, read-only root, dropped capabilities,
                          memory/CPU/pid limits (recommended).
"""
import os
import re
import signal
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from app.core.config import settings

BLOCKED_PY = re.compile(
    r"\b(subprocess|socket|shutil|requests|urllib|http\.client|ctypes|os\.system|"
    r"os\.remove|os\.rmdir|os\.unlink|rmtree|__import__)\b"
)
BLOCKED_JS = re.compile(
    r"(child_process|require\(\s*['\"](?:node:)?(?:net|http|https|http2|dgram|dns|tls|worker_threads|cluster|vm)['\"]\s*\)"
    r"|process\.exit|process\.kill|\beval\(|new Function|\bfetch\(|import\s*\("
    r"|fs\.(?:rm|rmSync|unlink|unlinkSync|rmdir|rmdirSync|writeFile|writeFileSync|appendFile|appendFileSync))"
)
_NAME_RE = re.compile(r"test_(f\d+)_", re.I)
CATEGORIES = ["normal", "boundary", "empty", "invalid_type", "large_input", "malicious"]
_SECRET_VAR = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH)", re.I)

# Gives every Python test its own time limit (works on Windows too, unlike signal.alarm).
CONFTEST = '''
import os
import threading

import pytest

_LIMIT = float(os.environ.get("PER_TEST_TIMEOUT", "5"))


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_call(item):
    original = item.runtest

    def guarded():
        box = {}

        def run():
            try:
                original()
            except BaseException as exc:  # noqa: BLE001
                box["exc"] = exc

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(_LIMIT)
        if worker.is_alive():
            raise TimeoutError("per-test timeout after %ss" % _LIMIT)
        if "exc" in box:
            raise box["exc"]

    item.runtest = guarded
'''


def is_blocked(test_code: str, language: str = "python"):
    """Return the offending text if the generated tests use a disallowed module/call, else None."""
    m = (BLOCKED_JS if language == "javascript" else BLOCKED_PY).search(test_code)
    return m.group(0) if m else None


def count_tests(test_code: str, language: str = "python") -> int:
    pattern = r"\btest\s*\(" if language == "javascript" else r"^\s*(?:async\s+)?def\s+test_"
    return len(re.findall(pattern, test_code, re.M))


def _finding_id(test_name: str):
    m = _NAME_RE.search(test_name)
    return m.group(1).lower() if m else None


def _category(test_name: str) -> str:
    """Read the category from the name pattern test_<id>_<category>_<description>.
    The category must come right after the finding id, so a word like 'empty' inside a description
    cannot override it."""
    low = test_name.lower()
    m = re.match(r"test_f\d+_(\w+?)(?=_|$)", low)
    if not m:
        return "normal"
    rest = low[m.end(1) - len(m.group(1)):]
    for c in sorted(CATEGORIES, key=len, reverse=True):
        if rest.startswith(c + "_") or rest == c:
            return c
    return "normal"


def _sandbox_row(status: str, msg: str) -> list:
    return [{"name": "sandbox", "finding_id": None, "category": "normal", "status": status, "message": msg}]


def _error(msg: str) -> list:
    return _sandbox_row("error", msg)


def _clean_env() -> dict:
    """Copy of the environment without anything that looks like a secret (API keys, tokens, passwords)."""
    return {k: v for k, v in os.environ.items() if not _SECRET_VAR.search(k)}


def _limits(language: str):  # POSIX only
    def apply():
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (settings.sandbox_timeout, settings.sandbox_timeout))
        resource.setrlimit(resource.RLIMIT_FSIZE, (10 << 20, 10 << 20))
        if language == "python":  # V8 reserves a lot of address space, so no RLIMIT_AS for Node
            resource.setrlimit(resource.RLIMIT_AS, (1 << 30, 1 << 30))
    return apply


def _parse_junit(path: Path) -> list:
    results = []
    root = ET.parse(path).getroot()
    for tc in root.findall(".//testcase"):
        name = tc.get("name", "")
        failure, error = tc.find("failure"), tc.find("error")
        if failure is not None:
            status, body = "failed", failure.text or failure.get("message") or ""
        elif error is not None:
            status, body = "error", error.text or error.get("message") or ""
        else:
            status, body = "passed", ""
        msg = body.strip()
        if status != "passed" and ("per-test timeout" in msg or "timed out" in msg.lower()):
            status = "timeout"
        results.append({"name": name, "finding_id": _finding_id(name), "category": _category(name),
                        "status": status, "message": msg[-400:]})  # the end of a traceback holds the cause
    return results


def _ensure_exports(code: str) -> str:
    """Make top-level functions importable from the test file if the code has no exports."""
    if "module.exports" in code or re.search(r"\bexports\.", code):
        return code
    names = re.findall(r"^\s*(?:async\s+)?function\s+(\w+)", code, re.M)
    names += re.findall(r"^\s*(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\(|function|\w+\s*=>)", code, re.M)
    names += re.findall(r"^\s*class\s+(\w+)", code, re.M)
    names = list(dict.fromkeys(names))
    return code + (f"\nmodule.exports = {{ {', '.join(names)} }};\n" if names else "")


def _command(language: str, tmp: str, container_name: str, collect_only: bool = False) -> list:
    docker = settings.sandbox_mode == "docker"
    if language == "javascript":
        inner = ["node" if docker else settings.node_binary, "--test", "--test-reporter=junit",
                 "--test-reporter-destination=report.xml", "test_target.js"]
    elif collect_only:  # import the test file (and target.py) without running any test
        inner = ["python" if docker else sys.executable, "-m", "pytest", "--collect-only", "-q",
                 "-p", "no:cacheprovider", "test_target.py"]
    else:
        inner = ["python" if docker else sys.executable, "-m", "pytest", "-q", "--junitxml=report.xml",
                 "-p", "no:cacheprovider", "test_target.py"]
    if not docker:
        return inner
    return ["docker", "run", "--rm", "--name", container_name, "--network", "none", "--read-only",
            "--tmpfs", "/tmp", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", "64", "--memory", "256m", "--cpus", "1",
            "-e", f"PER_TEST_TIMEOUT={settings.per_test_timeout}",
            "-v", f"{tmp}:/work", "-w", "/work", settings.sandbox_image, *inner]


def _kill_tree(proc: subprocess.Popen):
    """Kill the process AND everything it started (a timeout must not leave grandchildren running)."""
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)  # the child leads its own session (start_new_session=True)
        else:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    except OSError:
        proc.kill()


def _run_capture(cmd: list, cwd: str, timeout: float, **kwargs) -> subprocess.CompletedProcess:
    if os.name == "posix":
        kwargs["start_new_session"] = True
    else:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", **kwargs)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def _execute(language: str, tmp: str, collect_only: bool = False) -> subprocess.CompletedProcess:
    """Run pytest / node inside `tmp` with the configured isolation (subprocess or Docker).
    Collection and execution share this path, so Docker mode never runs submitted code on the host."""
    container = f"cr-sandbox-{uuid.uuid4().hex[:8]}"
    cmd = _command(language, tmp, container, collect_only)
    kwargs = {}
    if settings.sandbox_mode != "docker":
        env = _clean_env()
        env["PER_TEST_TIMEOUT"] = str(settings.per_test_timeout)
        if language == "python":
            env["PYTHONPATH"] = tmp
            env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        kwargs["env"] = env
        if os.name == "posix":
            kwargs["preexec_fn"] = _limits(language)
    timeout = min(30, settings.sandbox_timeout) if collect_only else settings.sandbox_timeout
    try:
        return _run_capture(cmd, tmp, timeout, **kwargs)
    except subprocess.TimeoutExpired:
        if settings.sandbox_mode == "docker":
            subprocess.run(["docker", "kill", container], capture_output=True)
        raise


def _write_files(tmp: str, code: str, test_code: str, language: str):
    tmp_path = Path(tmp)
    if language == "javascript":
        (tmp_path / "target.js").write_text(_ensure_exports(code), encoding="utf-8")
        (tmp_path / "test_target.js").write_text(test_code, encoding="utf-8")
    else:
        (tmp_path / "target.py").write_text(code, encoding="utf-8")
        (tmp_path / "test_target.py").write_text(test_code, encoding="utf-8")
        (tmp_path / "conftest.py").write_text(CONFTEST, encoding="utf-8")


def collect_error(code: str, test_code: str, language: str = "python"):
    """None if pytest can load the generated file, otherwise the end of its error output.
    Importing the test file imports the submitted code, so this runs in the same sandbox as the tests."""
    if language != "python":
        return None
    with tempfile.TemporaryDirectory() as tmp:
        _write_files(tmp, code, test_code, language)
        try:
            proc = _execute(language, tmp, collect_only=True)
        except subprocess.TimeoutExpired:
            return "loading the test file timed out"
        except FileNotFoundError as e:
            return f"sandbox could not start: {e}"
    if proc.returncode in (0, 5):  # 5 = loaded but no tests, which count_tests already rejects
        return None
    return (proc.stdout + proc.stderr).strip()[-400:]


def run_tests(code: str, test_code: str, language: str = "python", check_blocked: bool = True) -> list:
    """Run generated tests against `code`. Returns one dict per test, or a single 'sandbox' row on failure."""
    if check_blocked:
        bad = is_blocked(test_code, language)
        if bad:
            return _error(f"Generated tests were blocked: they use a disallowed module or call ({bad.strip()[:40]}).")

    with tempfile.TemporaryDirectory() as tmp:
        _write_files(tmp, code, test_code, language)
        try:
            proc = _execute(language, tmp)
        except subprocess.TimeoutExpired:
            return _sandbox_row("timeout", f"Test run exceeded {settings.sandbox_timeout}s and was killed.")
        except FileNotFoundError as e:
            return _error(f"Sandbox could not start: {e}")

        report = Path(tmp) / "report.xml"
        if not report.exists():
            return _error(f"No report written (exit {proc.returncode}): {(proc.stdout + proc.stderr)[-300:]}")
        try:
            results = _parse_junit(report)
        except ET.ParseError as e:
            return _error(f"Could not parse report: {e}")
        return results or _error("Report contained no test cases.")
