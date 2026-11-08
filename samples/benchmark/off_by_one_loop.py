def sum_first_n(items, n):
    total = 0
    for i in range(1, n):
        total += items[i]
    return total
