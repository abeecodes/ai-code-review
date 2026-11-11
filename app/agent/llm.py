"""Provider-agnostic LLM client: JSON output, response cache, token/call accounting."""
import contextvars
import hashlib
import json
import re
from pathlib import Path

from app.core.config import settings

DEFAULT_MODELS = {
    "groq": "openai/gpt-oss-120b",
    "ollama": "qwen2.5-coder:7b",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-5",
}

_usage = contextvars.ContextVar("llm_usage", default=None)
_clients = {}


def new_usage() -> dict:
    """Start accounting for one review. The dict is shared with every graph node of that review."""
    d = {"llm_calls": 0, "cache_hits": 0, "input_tokens": 0, "output_tokens": 0}
    _usage.set(d)
    return d


def _add(**kw):
    d = _usage.get()
    if d is not None:
        for k, v in kw.items():
            d[k] += v


def model_name(provider: str | None = None) -> str:
    prov = provider or settings.llm_provider
    prov_model = getattr(settings, f"{prov}_model", "")
    return prov_model or settings.llm_model or DEFAULT_MODELS.get(prov, "")


def _require_key(env_name: str, value: str) -> str:
    """Fail with a message that names the real setting (the openai library only mentions OPENAI_API_KEY)."""
    if not (value or "").strip():
        raise ValueError(f"{env_name} is not set. Add it to your .env file, or use LLM_PROVIDER=ollama.")
    return value


def get_client(provider: str | None = None):
    """Reuse persistent API clients with connection pooling."""
    prov = provider or settings.llm_provider
    if prov == "anthropic":
        api_key = _require_key("ANTHROPIC_API_KEY", settings.anthropic_api_key)
        key = ("anthropic", api_key)
        if key not in _clients:
            from anthropic import AsyncAnthropic

            _clients[key] = AsyncAnthropic(api_key=api_key)
        return _clients[key]

    from openai import AsyncOpenAI

    if prov == "groq":
        api_key = _require_key("GROQ_API_KEY", settings.groq_api_key)
        key = ("groq", api_key, "https://api.groq.com/openai/v1")
        if key not in _clients:
            _clients[key] = AsyncOpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
        return _clients[key]
    elif prov == "ollama":
        key = ("ollama", settings.ollama_base_url)
        if key not in _clients:
            _clients[key] = AsyncOpenAI(api_key="ollama", base_url=settings.ollama_base_url)
        return _clients[key]
    elif prov == "openai":
        api_key = _require_key("OPENAI_API_KEY", settings.openai_api_key)
        key = ("openai", api_key)
        if key not in _clients:
            _clients[key] = AsyncOpenAI(api_key=api_key)
        return _clients[key]
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {prov}")


def _find_balanced_json(text: str) -> list[str]:
    """Extract all balanced {...} or [...] blocks, properly ignoring braces inside strings."""
    blocks = []
    stack = []
    start = -1
    in_string = False
    escape = False

    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in ("{", "["):
            if not stack:
                start = i
            stack.append(ch)
        elif ch in ("}", "]"):
            if stack:
                matching = "{" if ch == "}" else "["
                if stack[-1] == matching:
                    stack.pop()
                    if not stack and start != -1:
                        blocks.append(text[start : i + 1])
                        start = -1
    return blocks


def extract_json(text: str):
    """Robustly parse JSON from raw LLM output, handling markdown fences, prose, and raw newlines."""
    text = text.strip()
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.M).strip()
    candidates = [clean, text]

    # Balanced brace extraction to isolate JSON objects from preambles/postambles
    balanced = _find_balanced_json(text)
    if balanced:
        candidates.extend(sorted(balanced, key=len, reverse=True))

    match = re.search(r"\{.*\}", text, re.S)
    if match and match.group(0) not in candidates:
        candidates.append(match.group(0))

    last = None
    for cand in candidates:
        for variant in (cand, _repair_escapes(cand)):
            # strict=False permits literal unescaped newlines/tabs inside code strings
            for strict in (False, True):
                try:
                    return json.loads(variant, strict=strict)
                except (json.JSONDecodeError, TypeError) as e:
                    last = e
    raise last


def _repair_escapes(text: str) -> str:
    """Models often put a bare backslash in code strings (for example in a regex).
    JSON only allows \\" \\\\ \\/ \\b \\f \\n \\r \\t \\uXXXX, so any other backslash is doubled."""
    return re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", text)


def _status_code(exc: Exception):
    """HTTP status of a provider error: the exception attribute when present, else a leading 'NNN' / 'Error code: NNN'.
    (Searching the whole message would mistake '4012 tokens' for a 401.)"""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    m = re.match(r"\s*(?:Error code:\s*)?(\d{3})\b", str(exc))
    return int(m.group(1)) if m else None


def _format_provider_error(provider: str, exc: Exception) -> str:
    msg = str(exc)
    exc_type = type(exc).__name__
    if isinstance(exc, ValueError) and "API_KEY" in msg:
        return msg  # already a clear "X_API_KEY is not set" message
    status = _status_code(exc)
    if "ConnectError" in exc_type or "ConnectionRefused" in msg or "APIConnectionError" in exc_type:
        if provider == "ollama":
            return f"Cannot connect to Ollama at {settings.ollama_base_url}. Ensure the Ollama daemon is running ('ollama serve')."
        return f"Cannot connect to LLM provider '{provider}'. Check network connection and endpoint URL."
    if "AuthenticationError" in exc_type or status in (401, 403):
        return f"Authentication failed for provider '{provider}'. Check that your API key is valid."
    if "NotFoundError" in exc_type or status == 404:
        m = model_name(provider)
        if provider == "ollama":
            return f"Model '{m}' was not found in Ollama. Pull it first with: 'ollama pull {m}'."
        return f"Model '{m}' was not found on provider '{provider}'. Check the model name for this provider."
    if "RateLimitError" in exc_type or status == 429:
        return f"Rate limit exceeded for provider '{provider}'. Please wait a moment before trying again."
    return f"LLM provider '{provider}' error ({exc_type}): {msg}"


async def check_llm_connection(provider: str | None = None) -> dict:
    """Ping the configured provider to verify connectivity and credentials."""
    prov = provider or settings.llm_provider
    m = model_name(prov)
    try:
        client = get_client(prov)
        if prov == "anthropic":
            await client.messages.create(
                model=m, max_tokens=5, messages=[{"role": "user", "content": "ping"}],
            )
        else:
            await client.chat.completions.create(
                model=m, max_tokens=5, messages=[{"role": "user", "content": "ping"}],
            )
        return {"status": "ok", "provider": prov, "model": m}
    except Exception as exc:
        return {"status": "error", "provider": prov, "model": m, "error": _format_provider_error(prov, exc)}


def _json_mode_unsupported(exc: Exception) -> bool:
    msg = str(exc).lower()
    if any(k in msg for k in ("response_format", "json_object", "json mode", "json_schema")):
        return True
    return _status_code(exc) == 400 and "format" in msg


async def _complete(system: str, user: str) -> tuple:
    """Return (text, input_tokens, output_tokens)."""
    provider = settings.llm_provider
    m = model_name(provider)
    try:
        if provider == "anthropic":
            client = get_client("anthropic")
            resp = await client.messages.create(
                model=m, max_tokens=4096, system=system,
                messages=[{"role": "user", "content": user}],
            )
            text = "".join(b.text for b in resp.content if b.type == "text")
            usage = getattr(resp, "usage", None)
            return (text, getattr(usage, "input_tokens", 0) or 0, getattr(usage, "output_tokens", 0) or 0)

        client = get_client(provider)
        kwargs = {
            "model": m,
            "temperature": 0.1,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        # Enforce JSON mode for OpenAI-compatible APIs when supported. Retry without it ONLY when the server says
        # the option is unsupported; auth, rate-limit and connection errors must not be repeated blindly.
        try:
            resp = await client.chat.completions.create(**kwargs, response_format={"type": "json_object"})
        except Exception as exc:
            if not _json_mode_unsupported(exc):
                raise
            resp = await client.chat.completions.create(**kwargs)
        usage = getattr(resp, "usage", None)
        return (resp.choices[0].message.content or "",
                getattr(usage, "prompt_tokens", 0) or 0, getattr(usage, "completion_tokens", 0) or 0)
    except Exception as exc:
        raise RuntimeError(_format_provider_error(provider, exc)) from exc


def _cache_path(system: str, user: str) -> Path:
    key = hashlib.sha256(f"{settings.llm_provider}|{model_name()}|{system}|{user}".encode()).hexdigest()
    return Path(settings.cache_dir) / f"{key}.json"


async def complete_json(system: str, user: str, retries: int = 2) -> dict:
    """Call the LLM and parse JSON. Identical prompts are served from the on-disk cache."""
    path = _cache_path(system, user)
    if settings.llm_cache and path.exists():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and "data" in cached:
                data = cached["data"]
                tin = cached.get("input_tokens", 0)
                tout = cached.get("output_tokens", 0)
            else:
                data = cached
                tin, tout = 0, 0
            if isinstance(data, dict):
                _add(cache_hits=1, input_tokens=tin, output_tokens=tout)
                return data
        except (OSError, json.JSONDecodeError):
            pass

    last_err = None
    for attempt in range(retries + 1):
        prompt = user if attempt == 0 else user + "\n\nYour previous reply was not a valid JSON object. Return ONLY one JSON object."
        raw, tin, tout = await _complete(system, prompt)
        _add(llm_calls=1, input_tokens=tin, output_tokens=tout)
        try:
            data = extract_json(raw)
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
        if not isinstance(data, dict):  # valid JSON of the wrong shape (a list, a string) is not an answer
            last_err = ValueError(f"expected a JSON object, got {type(data).__name__}")
            continue
        if settings.llm_cache:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                cache_record = {
                    "data": data,
                    "input_tokens": tin,
                    "output_tokens": tout,
                }
                path.write_text(json.dumps(cache_record), encoding="utf-8")
            except OSError:
                pass
        return data
    raise ValueError(f"LLM returned invalid JSON after {retries + 1} attempts: {last_err}")


async def close_clients():
    """Close pooled API clients (called when the application shuts down)."""
    for client in list(_clients.values()):
        try:
            await client.close()
        except Exception:  # noqa: BLE001
            pass
    _clients.clear()


def set_model(provider: str, model: str):
    """Select provider and model at run time. Provider-specific variables (GROQ_MODEL, ...) take priority in
    model_name(), so they must be overwritten too, otherwise an old value in .env silently wins."""
    settings.llm_provider = provider
    settings.llm_model = model
    if hasattr(settings, f"{provider}_model"):
        setattr(settings, f"{provider}_model", model)
