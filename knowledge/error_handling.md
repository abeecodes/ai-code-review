# Error handling and robustness

## Fail fast with clear errors
Raise specific exceptions (ValueError, TypeError) with helpful messages instead of returning magic values such as -1 or None silently.

## Security of error messages
Do not return stack traces or SQL errors to users. Log details server-side and return a generic message.

## Idempotence and defaults
Functions should not modify their arguments unexpectedly. Return new values instead of mutating inputs unless documented.
