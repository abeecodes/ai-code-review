# Maintainability and code quality

## Function size and complexity
Functions longer than about 40 lines or with cyclomatic complexity above 10 are hard to test. Split them into smaller functions with one responsibility.

## Naming and PEP 8
Use snake_case for functions and variables, PascalCase for classes, and meaningful names. Avoid single-letter names except loop counters. Keep lines under 100 characters.

## Magic numbers and duplication
Replace unexplained literals with named constants. Extract repeated code into helpers (DRY).

## Docstrings and type hints
Document public functions and add type hints so tools and reviewers can catch mistakes early.
