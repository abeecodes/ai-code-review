# Common Python pitfalls

## Mutable default arguments
def f(x, items=[]) shares one list across all calls, so data leaks between calls. Fix: use items=None and create a new list inside the function when it is None.

## Bare except and swallowed errors
except: or except Exception: pass hides bugs and makes failures invisible. Catch specific exceptions and handle or log them.

## Resource leaks
Files, sockets and database connections must be closed. Use with statements (context managers).

## Comparing with is
Use == for value comparison. Use is only for None, True and False.
