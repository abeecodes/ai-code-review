"""Probe how well the sandbox contains hostile test code.

  python -m eval.sandbox_isolation --mode subprocess
  python -m eval.sandbox_isolation --mode docker        (needs Docker + `docker build -f Dockerfile.sandbox -t code-review-sandbox .`)

Each probe is a test that tries something it should not be able to do. Results are written to
eval/isolation_<mode>.md. Run it with internet access, otherwise the network probe is inconclusive.
"""
import argparse
import os
import socket
import time
from pathlib import Path

from app.core.config import settings
from app.sandbox import runner

TARGET = "def noop():\n    return 1\n"
LEAK_FILE = Path("eval/.isolation_leak.txt").resolve()


def probes() -> list:
    leak = repr(str(LEAK_FILE))
    return [
        ("Network access", "PASS if connection fails", """
import socket, pytest, target
def test_f1_malicious_network():
    with pytest.raises(OSError):
        socket.create_connection(("1.1.1.1", 53), timeout=3)
""", False),
        ("Secrets in environment", "PASS if no key/token visible", """
import os, target
def test_f1_malicious_env():
    leaked = [k for k in os.environ if "KEY" in k.upper() or "TOKEN" in k.upper() or "SECRET" in k.upper()]
    assert not leaked, leaked
""", False),
        ("Write to host path outside sandbox", "PASS if host file not created", f"""
import target
def test_f1_malicious_write():
    with open({leak}, "w") as fh:
        fh.write("escaped")
""", True),
        ("Infinite loop", "PASS if reported as a timeout", """
import target
def test_f1_malicious_loop():
    while True:
        pass
""", False),
        ("Hanging test (per-test timeout)", "PASS if reported as timeout quickly", """
import time, target
def test_f1_malicious_hang():
    time.sleep(300)
""", False),
        ("Memory bomb (1.5 GB)", "PASS if allocation is refused or killed", """
import target
def test_f1_large_input_memory():
    block = b"x" * (1536 * 1024 * 1024)
    assert len(block) == 0
""", False),
        ("Dangerous import in test code", "PASS if blocked before running", """
import subprocess, target
def test_f1_malicious_import():
    pass
""", None),
    ]


def _host_online() -> bool:
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=3).close()
        return True
    except OSError:
        return False


def run_probe(name, code, check_host, os_env):
    started = time.perf_counter()
    blocked_check = check_host is None
    res = runner.run_tests(TARGET, code, "python", check_blocked=blocked_check)
    secs = time.perf_counter() - started
    status = res[0]["status"] if res else "none"
    msg = res[0]["message"][:60].replace("\n", " ") if res else ""

    if "Network" in name:
        if not _host_online():
            verdict = "INCONCLUSIVE"
            msg = "host has no internet, so a blocked connection proves nothing; rerun online"
        else:
            verdict = "ISOLATED" if status == "passed" else "LEAK"
    elif "Secrets" in name:
        verdict = "ISOLATED" if status == "passed" else "LEAK"
    elif "Write" in name:
        verdict = "LEAK" if LEAK_FILE.exists() else "ISOLATED"
        LEAK_FILE.unlink(missing_ok=True)
    elif "Infinite" in name:
        verdict = "CONTAINED" if status == "timeout" else "NOT CONTAINED"
    elif "Hanging" in name:
        verdict = "CONTAINED" if status == "timeout" and secs < settings.per_test_timeout + 15 else "NOT CONTAINED"
    elif "Memory" in name:
        verdict = "CONTAINED" if status != "passed" else "NOT CONTAINED"
    else:
        verdict = "BLOCKED" if status == "error" and "blocked" in msg else "NOT BLOCKED"
    return verdict, status, secs, msg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["subprocess", "docker"], default=settings.sandbox_mode)
    ap.add_argument("--skip-memory", action="store_true", help="skip the 1.5 GB allocation probe")
    args = ap.parse_args()
    settings.sandbox_mode = args.mode
    os.environ["PROBE_SECRET_KEY"] = "do-not-leak"  # a fake secret the sandbox must not expose

    rows = []
    for name, expect, code, check_host in probes():
        if args.skip_memory and "Memory" in name:
            continue
        print(f"probing: {name} ...", flush=True)
        verdict, status, secs, msg = run_probe(name, code, check_host, None)
        rows.append((name, expect, verdict, status, secs, msg))

    lines = [f"# Sandbox isolation probes — mode: {args.mode}", "",
             "| Probe | Pass condition | Verdict | Test status | Seconds | Detail |", "|---|---|---|---|---|---|"]
    lines += [f"| {n} | {e} | **{v}** | {s} | {t:.1f} | {m} |" for n, e, v, s, t, m in rows]
    good = sum(v in ("ISOLATED", "CONTAINED", "BLOCKED") for _, _, v, *_ in rows)
    lines += ["", f"{good}/{len(rows)} probes contained ({sum(v == 'INCONCLUSIVE' for _, _, v, *_ in rows)} inconclusive).",
              "Note: the subprocess mode is expected to leak on network and file-system probes; that is why Docker mode exists."]
    out = Path(f"eval/isolation_{args.mode}.md")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
