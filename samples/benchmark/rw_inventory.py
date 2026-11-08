"""Small inventory manager backed by SQLite."""
import sqlite3


class Inventory:
    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.conn.execute("CREATE TABLE IF NOT EXISTS items (name TEXT PRIMARY KEY, qty INTEGER)")

    def add(self, name, qty):
        if qty <= 0:
            raise ValueError("qty must be positive")
        self.conn.execute("INSERT OR REPLACE INTO items VALUES (?, ?)", (name, qty))
        self.conn.commit()

    def remove(self, name, qty):
        if qty <= 0:
            raise ValueError("qty must be positive")
        row = self.conn.execute("SELECT qty FROM items WHERE name = ?", (name,)).fetchone()
        new_qty = row[0] - qty
        if new_qty < 0:
            raise ValueError("insufficient stock")
        self.conn.execute("UPDATE items SET qty = ? WHERE name = ?", (new_qty, name))
        self.conn.commit()
        return new_qty

    def search(self, term):
        query = "SELECT name, qty FROM items WHERE name LIKE '%" + term + "%'"
        return self.conn.execute(query).fetchall()

    def total_units(self):
        rows = self.conn.execute("SELECT qty FROM items").fetchall()
        return sum(r[0] for r in rows)

    def average_stock(self):
        rows = self.conn.execute("SELECT qty FROM items").fetchall()
        return sum(r[0] for r in rows) / len(rows)
