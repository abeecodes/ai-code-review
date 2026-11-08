# JavaScript pitfalls

## eval and Function constructor
eval(), new Function() and setTimeout with a string run arbitrary code (code injection). Fix: parse data with JSON.parse, or use a dedicated expression parser. Never evaluate user input.

## Command injection with child_process
child_process.exec and execSync run a shell, so input containing ; or && executes extra commands. Fix: use execFile or spawn with an argument array and no shell, and validate input against an allow-list.

## Loose equality and NaN
== performs type coercion, so 0 == "" and null == undefined are true. Use ===. Dividing by an empty array length gives NaN or Infinity; validate empty input before computing an average.

## Hardcoded secrets
API keys in source code leak through version control. Read them from process.env and keep .env files out of git.

## Prototype pollution and unsafe object merge
Merging user-controlled objects can set __proto__ or constructor. Use Object.create(null), Map, or validate keys before merging.
