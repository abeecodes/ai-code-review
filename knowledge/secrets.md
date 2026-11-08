# Secrets and credentials management

## Hardcoded secrets
API keys, passwords and tokens written in source code leak through version control and logs (CWE-798). Fix: read secrets from environment variables or a secrets manager, e.g. os.environ["API_KEY"], keep .env files out of git, and rotate any key that was committed.

## Logging sensitive data
Never log passwords, tokens or full credit card numbers. Mask or omit them before logging.
