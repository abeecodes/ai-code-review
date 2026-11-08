def parse_int(text, default=0):
    try:
        return int(text)
    except ValueError:
        return default
