# Injection flaws (OWASP A03)

## SQL injection
Building SQL by concatenating or formatting user input lets attackers change the query, for example the input ' OR '1'='1 returns every row. Fix: use parameterised queries, e.g. cursor.execute("SELECT * FROM users WHERE name = ?", (name,)). Never use f-strings or + to build SQL.

## OS command injection
Passing user input to os.system, os.popen or subprocess with shell=True lets attackers append commands using ; && or |. Fix: use subprocess.run with a list of arguments and shell=False, validate input against an allow-list, and use shlex.quote only as a last resort.

## Code injection via eval and exec
eval(), exec() and compile() on user-controlled strings execute arbitrary Python. Fix: use ast.literal_eval for literals, or a dedicated parser for arithmetic. Never eval untrusted input.
