import hashlib
import os


def hash_password(password):
    salt = os.urandom(16)
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000).hex()