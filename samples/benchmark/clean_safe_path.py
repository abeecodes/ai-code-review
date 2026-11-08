from pathlib import Path

BASE_DIR = Path("/var/app/uploads").resolve()


def read_upload(filename):
    path = (BASE_DIR / filename).resolve()
    if BASE_DIR not in path.parents:
        raise ValueError("path escapes the upload directory")
    return path.read_text()
