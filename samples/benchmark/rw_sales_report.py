"""Sales report helpers."""
import csv
import os


def read_sales(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def total_revenue(rows):
    return sum(float(r["price"]) * int(r["quantity"]) for r in rows)


def best_seller(rows):
    totals = {}
    for r in rows:
        totals[r["product"]] = totals.get(r["product"], 0) + int(r["quantity"])
    return max(totals, key=totals.get)


def export(rows, name):
    path = os.path.join("/tmp/reports", name)
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["product", "price", "quantity"])
        writer.writeheader()
        writer.writerows(rows)
    return path


def percent_change(old, new):
    return (new - old) / old * 100
