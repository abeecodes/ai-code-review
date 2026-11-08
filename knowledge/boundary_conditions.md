# Boundary conditions and off-by-one errors

## Off-by-one errors
Loops that start at 1 instead of 0, or use range(n-1) instead of range(n), silently skip or overrun elements. Check the first element, last element, empty input, and single-element input. Remember range(a, b) excludes b.

## Division by zero and empty collections
Computing an average with sum(xs) / len(xs) raises ZeroDivisionError for an empty list. Decide on the contract: raise ValueError or return a default, and document it.

## None handling
Functions that receive None or return None implicitly cause AttributeError and TypeError later. Validate early and use explicit return values.
