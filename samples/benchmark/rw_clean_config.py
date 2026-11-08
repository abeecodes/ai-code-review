"""Parse simple key=value configuration text."""


def parse_config(text):
    result = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"line {number}: expected key=value")
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def get_int(config, key, default):
    value = config.get(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer") from exc
