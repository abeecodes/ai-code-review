import hashlib
import secrets


def make_reset_token():
    return secrets.token_urlsafe(32)


def fingerprint(text):
    return hashlib.sha256(text.encode()).hexdigest()
