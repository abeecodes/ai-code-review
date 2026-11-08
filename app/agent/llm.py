"""Provider-agnostic LLM client: JSON output, response cache, token/call accounting."""
import contextvars
import hashlib
import json
import re
from pathlib import Path

from app.core.config import settings

DEFAULT_MODELS = {
    "groq": "llama-3.3-70b-versatile",
    "ollama": "qwen2.5-coder:7b",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-5-5",
}

_usage = contextvars.ContextVar("llm_usage", default=None)


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


def model_name() -> str:
    return settings.llm_model or DEFAULT_MODELS.get(settings.llm_provider, "")


def extract_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.M).strip()
    candidates = [text]
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        candidates.append(match.group(0))
    last = None
    for cand in candidates:
        for variant in (cand, _repair_escapes(cand)):
            try:
                return json.loads(variant)
            except json.JSONDecodeError as e:
                last = e
    raise last


def _repair_escapes(text: str) -> str:
    """Models often put a bare backslash in code strings (for example in a regex).
    JSON only allows \\" \\\\ \\/ \\b \\f \\n \\r \\t \\uXXXX, so any other backslash is doubled."""
    return re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", text)


async def _complete(system: str, user: str) -> tuple:
    """Return (text, input_tokens, output_tokens)."""
    provider = settings.llm_provider
    if provider == "anthropic":
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        resp = await client.messages.create(
            model=model_name(), max_tokens=4096, system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        return text, resp.usage.input_tokens, resp.usage.output_tokens

    from openai import AsyncOpenAI

    if provider == "groq":
        client = AsyncOpenAI(api_key=settings.groq_api_key, base_url="https://api.groq.com/openai/v1")
    elif provider == "ollama":
        client = AsyncOpenAI(api_key="ollama", base_url=settings.ollama_base_url)
    elif provider == "openai":
        client = AsyncOpenAI(api_key=settings.openai_api_key)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider}")
    resp = await client.chat.completions.create(
        model=model_name(), temperature=0.1,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    usage = getattr(resp, "usage", None)
    return (resp.choices[0].message.content or "",
            getattr(usage, "prompt_tokens", 0) or 0, getattr(usage, "completion_tokens", 0) or 0)


def _cache_path(system: str, user: str) -> Path:
    key = hashlib.sha256(f"{settings.llm_provider}|{model_name()}|{system}|{user}".encode()).hexdigest()
    return Path(settings.cache_dir) / f"{key}.json"


async def complete_json(system: str, user: str, retries: int = 2) -> dict:
    """Call the LLM and parse JSON. Identical prompts are served from the on-disk cache."""
    path = _cache_path(system, user)
    if settings.llm_cache and path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            _add(cache_hits=1)
            return data
        except (OSError, json.JSONDecodeError):
            pass

    last_err = None
    for attempt in range(retries + 1):
        prompt = user if attempt == 0 else user + "\n\nYour previous reply was not valid JSON. Return ONLY one valid JSON object."
        raw, tin, tout = await _complete(system, prompt)
        _add(llm_calls=1, input_tokens=tin, output_tokens=tout)
        try:
            data = extract_json(raw)
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
        if settings.llm_cache:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data), encoding="utf-8")
            except OSError:
                pass
        return data
    raise ValueError(f"LLM returned invalid JSON after {retries + 1} attempts: {last_err}")
