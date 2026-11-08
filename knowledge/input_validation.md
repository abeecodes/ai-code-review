# Input validation

## Validate at boundaries
Check type, range, length and format of every external input before use. Reject negative amounts, empty strings, None, and values larger than expected. Raise ValueError with a clear message rather than continuing with bad data.

## Business-rule validation
Financial and quantity functions must reject negative values and prevent results that break invariants, such as a withdrawal larger than the balance leaving a negative balance.

## Path traversal
Never join user input directly into file paths. Resolve the path and check it stays inside the allowed directory.
