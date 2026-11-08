import traceback


def handle_request(handler, payload):
    try:
        return {"ok": True, "data": handler(payload)}
    except Exception:
        return {"ok": False, "error": traceback.format_exc()}
