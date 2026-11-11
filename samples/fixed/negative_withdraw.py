def withdraw(balance, amount):
    if amount < 0:
        raise ValueError("amount must not be negative")
    return balance - amount
