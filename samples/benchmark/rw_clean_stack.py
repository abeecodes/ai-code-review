"""A bounded stack."""


class Stack:
    def __init__(self, limit):
        if limit <= 0:
            raise ValueError("limit must be positive")
        self.limit = limit
        self.items = []

    def push(self, item):
        if len(self.items) >= self.limit:
            raise OverflowError("stack is full")
        self.items.append(item)

    def pop(self):
        if not self.items:
            raise IndexError("stack is empty")
        return self.items.pop()

    def peek(self):
        if not self.items:
            raise IndexError("stack is empty")
        return self.items[-1]

    def __len__(self):
        return len(self.items)
