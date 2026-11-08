# Unsafe deserialization and risky APIs

## pickle and yaml
pickle.loads and yaml.load on untrusted data can execute arbitrary code (CWE-502). Fix: use json, or yaml.safe_load.

## Weak cryptography
MD5 and SHA1 are not suitable for passwords. Use bcrypt, scrypt or argon2 for passwords and the secrets module for tokens. random is not cryptographically secure.

## Debug mode and assert
Do not rely on assert for validation, since asserts are removed with python -O. Never ship debug=True web servers.
