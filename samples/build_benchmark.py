"""Builds samples/benchmark/* and samples/ground_truth.json.

Each source below marks a seeded defect with a trailing  #@bug <id> <category>  (or //@bug for JavaScript).
The marker is STRIPPED from the written file, so the reviewer never sees the answer, and the line number of
every defect is recorded automatically in ground_truth.json.

Run from the project root:  python samples/build_benchmark.py
To add your own file: append it to SOURCES with markers, then re-run.
"""
import ast
import json
import re
from pathlib import Path

OUT = Path("samples/benchmark")
MARK = re.compile(r"^(.*?)\s*(?:#|//)@bug (\S+) (\S+)\s*$")

SOURCES = {}


def add(name, src):
    SOURCES[name] = src.strip("\n") + "\n"


# ---------------------------------------------------------------- Python, one seeded defect each
add("sql_injection_concat.py", '''
def get_user(conn, username):
    query = "SELECT id, name FROM users WHERE name = '" + username + "'"  #@bug sqli injection
    return conn.execute(query).fetchall()
''')
add("sql_injection_fstring.py", '''
def find_orders(conn, customer_id, status):
    query = f"SELECT * FROM orders WHERE customer_id = {customer_id} AND status = '{status}'"  #@bug sqli injection
    cursor = conn.cursor()
    cursor.execute(query)
    return cursor.fetchall()
''')
add("command_injection_os_system.py", '''
import os


def ping_host(host):
    return os.system("ping -c 1 " + host)  #@bug cmdi injection
''')
add("command_injection_shell.py", '''
import subprocess


def archive(folder_name):
    cmd = "tar -czf backup.tar.gz " + folder_name
    subprocess.run(cmd, shell=True, check=False)  #@bug cmdi injection
    return "backup.tar.gz"
''')
add("eval_user_input.py", '''
def calculate(expression):
    return eval(expression)  #@bug eval injection
''')
add("exec_dynamic.py", '''
def run_plugin(source_code, context):
    exec(source_code, context)  #@bug exec injection
    return context.get("result")
''')
add("hardcoded_api_key.py", '''
API_KEY = "FAKEKEY_51H8fakeKEY1234567890abcdef"  #@bug secret secrets


def get_headers():
    return {"Authorization": "Bearer " + API_KEY}
''')
add("hardcoded_db_password.py", '''
def connection_string(host):
    password = "Sup3rS3cret!2024"  #@bug secret secrets
    return f"postgresql://admin:{password}@{host}/app"
''')
add("password_logging.py", '''
import logging

logger = logging.getLogger(__name__)


def login(username, password):
    logger.info("login attempt user=%s password=%s", username, password)  #@bug logpw secrets
    return username == "admin"
''')
add("division_by_zero_average.py", '''
def average(numbers):
    return sum(numbers) / len(numbers)  #@bug div0 boundary
''')
add("off_by_one_loop.py", '''
def sum_first_n(items, n):
    total = 0
    for i in range(1, n):  #@bug off1 boundary
        total += items[i]
    return total
''')
add("off_by_one_slice.py", '''
def last_n(items, n):
    return items[len(items) - n - 1:]  #@bug off1 boundary
''')
add("none_not_handled.py", '''
def display_name(user):
    return user.get("name").title()  #@bug none boundary
''')
add("float_equality.py", '''
def is_balanced(total):
    return 0.1 + 0.2 == total  #@bug float pitfall
''')
add("mutable_default.py", '''
def add_item(item, bucket=[]):  #@bug mutdef pitfall
    bucket.append(item)
    return bucket
''')
add("bare_except.py", '''
def parse_int(text):
    try:
        return int(text)
    except:  #@bug bare pitfall
        pass
''')
add("file_not_closed.py", '''
def read_config(path):
    f = open(path)  #@bug leak pitfall
    data = f.read()
    return data
''')
add("is_literal.py", '''
def is_ok(status):
    if status is "ok":  #@bug islit pitfall
        return True
    return False
''')
add("negative_withdraw.py", '''
def withdraw(balance, amount):
    return balance - amount  #@bug negamt validation
''')
add("discount_unvalidated.py", '''
def apply_discount(price, percent):
    return price - price * percent / 100  #@bug pct validation
''')
add("path_traversal.py", '''
import os

BASE_DIR = "/var/app/uploads"


def read_upload(filename):
    path = os.path.join(BASE_DIR, filename)  #@bug traversal validation
    with open(path) as fh:
        return fh.read()
''')
add("assert_validation.py", '''
def set_age(user, age):
    assert 0 <= age <= 150, "invalid age"  #@bug assert validation
    user["age"] = age
    return user
''')
add("pickle_loads.py", '''
import pickle


def load_session(blob):
    return pickle.loads(blob)  #@bug pickle deserialization
''')
add("md5_password.py", '''
import hashlib


def hash_password(password):
    return hashlib.md5(password.encode()).hexdigest()  #@bug md5 crypto
''')
add("random_token.py", '''
import random
import string


def make_reset_token(length=32):
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choice(alphabet) for _ in range(length))  #@bug rnd crypto
''')
add("insecure_tempfile.py", '''
import tempfile


def scratch_path():
    return tempfile.mktemp()  #@bug mktemp crypto
''')
add("traceback_leak.py", '''
import traceback


def handle_request(handler, payload):
    try:
        return {"ok": True, "data": handler(payload)}
    except Exception:
        return {"ok": False, "error": traceback.format_exc()}  #@bug leak errorhandling
''')
add("mutates_argument.py", '''
def smallest(items):
    items.sort()  #@bug mutarg errorhandling
    return items[0]
''')

# ------------------------------------------------- Python, realistic modules with 2-3 seeded defects
add("rw_inventory.py", '''
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
        new_qty = row[0] - qty  #@bug inv_none boundary
        if new_qty < 0:
            raise ValueError("insufficient stock")
        self.conn.execute("UPDATE items SET qty = ? WHERE name = ?", (new_qty, name))
        self.conn.commit()
        return new_qty

    def search(self, term):
        query = "SELECT name, qty FROM items WHERE name LIKE '%" + term + "%'"  #@bug inv_sqli injection
        return self.conn.execute(query).fetchall()

    def total_units(self):
        rows = self.conn.execute("SELECT qty FROM items").fetchall()
        return sum(r[0] for r in rows)

    def average_stock(self):
        rows = self.conn.execute("SELECT qty FROM items").fetchall()
        return sum(r[0] for r in rows) / len(rows)  #@bug inv_div0 boundary
''')
add("rw_text_utils.py", '''
"""Text helper functions."""
import hashlib
import re


def slugify(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def word_frequencies(text):
    counts = {}
    for word in re.findall(r"[a-z']+", text.lower()):
        counts[word] = counts.get(word, 0) + 1
    return counts


def top_words(text, n=3, seen=[]):  #@bug text_mut pitfall
    freq = word_frequencies(text)
    ranked = sorted(freq, key=freq.get, reverse=True)
    seen.extend(ranked[:n])
    return ranked[:n]


def fingerprint(text):
    return hashlib.md5(text.encode()).hexdigest()  #@bug text_md5 crypto


def truncate(text, limit):
    return text[:limit]
''')
add("rw_lru_cache.py", '''
"""Tiny LRU cache."""
import pickle
from collections import OrderedDict


class LRUCache:
    def __init__(self, capacity):
        self.capacity = capacity
        self.data = OrderedDict()

    def get(self, key, default=None):
        if key not in self.data:
            return default
        self.data.move_to_end(key)
        return self.data[key]

    def put(self, key, value):
        self.data[key] = value
        self.data.move_to_end(key)
        if len(self.data) >= self.capacity:  #@bug lru_off1 boundary
            self.data.popitem(last=False)

    def load(self, path):
        with open(path, "rb") as fh:
            self.data = pickle.load(fh)  #@bug lru_pickle deserialization

    def __len__(self):
        return len(self.data)
''')
add("rw_sales_report.py", '''
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
    return max(totals, key=totals.get)  #@bug rep_empty boundary


def export(rows, name):
    path = os.path.join("/tmp/reports", name)  #@bug rep_traversal validation
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["product", "price", "quantity"])
        writer.writeheader()
        writer.writerows(rows)
    return path


def percent_change(old, new):
    return (new - old) / old * 100  #@bug rep_div0 boundary
''')

# ---------------------------------------------------------------------- Python, clean (no defects)
add("clean_sql_param.py", '''
def get_user(conn, username):
    query = "SELECT id, name FROM users WHERE name = ?"
    return conn.execute(query, (username,)).fetchall()
''')
add("clean_literal_eval.py", '''
import ast


def parse_literal(text):
    return ast.literal_eval(text)
''')
add("clean_env_secret.py", '''
import os


def get_headers():
    key = os.environ["API_KEY"]
    return {"Authorization": "Bearer " + key}
''')
add("clean_validated_withdraw.py", '''
def withdraw(balance, amount):
    if amount <= 0:
        raise ValueError("amount must be positive")
    if amount > balance:
        raise ValueError("insufficient funds")
    return balance - amount
''')
add("clean_safe_average.py", '''
def average(numbers):
    if not numbers:
        raise ValueError("numbers must not be empty")
    return sum(numbers) / len(numbers)
''')
add("clean_safe_path.py", '''
from pathlib import Path

BASE_DIR = Path("/var/app/uploads").resolve()


def read_upload(filename):
    path = (BASE_DIR / filename).resolve()
    if BASE_DIR not in path.parents:
        raise ValueError("path escapes the upload directory")
    return path.read_text()
''')
add("clean_with_open.py", '''
def read_config(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()
''')
add("clean_specific_except.py", '''
def parse_int(text, default=0):
    try:
        return int(text)
    except ValueError:
        return default
''')
add("clean_default_none.py", '''
def add_item(item, bucket=None):
    if bucket is None:
        bucket = []
    bucket.append(item)
    return bucket
''')
add("clean_secure_token.py", '''
import hashlib
import secrets


def make_reset_token():
    return secrets.token_urlsafe(32)


def fingerprint(text):
    return hashlib.sha256(text.encode()).hexdigest()
''')
add("rw_clean_stack.py", '''
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
''')
add("rw_clean_config.py", '''
"""Parse simple key=value configuration text."""


def parse_config(text):
    result = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"line {number}: expected key=value")
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def get_int(config, key, default):
    value = config.get(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer") from exc
''')

# --------------------------------------------------------------------------------------- JavaScript
add("js_eval_input.js", '''
function calculate(expression) {
  return eval(expression); //@bug js_eval injection
}

module.exports = { calculate };
''')
add("js_command_injection.js", '''
const { execSync } = require('child_process');

function listDir(dir) {
  return execSync('ls ' + dir).toString(); //@bug js_cmdi injection
}

module.exports = { listDir };
''')
add("js_average_empty.js", '''
function average(numbers) {
  const total = numbers.reduce((a, b) => a + b, 0);
  return total / numbers.length; //@bug js_avg boundary
}

module.exports = { average };
''')
add("js_hardcoded_secret.js", '''
const API_KEY = 'FAKEKEY_51H8fakeKEY1234567890abcdef'; //@bug js_secret secrets

function authHeader() {
  return { Authorization: 'Bearer ' + API_KEY };
}

module.exports = { authHeader };
''')
add("js_clean_sum.js", '''
function sum(numbers) {
  if (!Array.isArray(numbers)) {
    throw new TypeError('numbers must be an array');
  }
  return numbers.reduce((a, b) => a + b, 0);
}

module.exports = { sum };
''')
add("js_clean_greeting.js", '''
function greet(name = 'world') {
  if (typeof name !== 'string') {
    throw new TypeError('name must be a string');
  }
  return `Hello, ${name}!`;
}

module.exports = { greet };
''')


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*"):
        old.unlink()
    truth = {}
    for name, src in SOURCES.items():
        lines, defects = [], []
        for i, line in enumerate(src.splitlines(), start=1):
            m = MARK.match(line)
            if m:
                line = m.group(1)
                defects.append({"id": m.group(2), "category": m.group(3), "line": i})
            lines.append(line)
        text = "\n".join(lines) + "\n"
        (OUT / name).write_text(text, encoding="utf-8")
        language = "javascript" if name.endswith(".js") else "python"
        if language == "python":
            ast.parse(text)
        truth[name] = {"language": language, "clean": not defects, "defects": defects}
    Path("samples/ground_truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
    n_def = sum(len(v["defects"]) for v in truth.values())
    print(f"{len(truth)} files ({sum(v['clean'] for v in truth.values())} clean), {n_def} seeded defects")


if __name__ == "__main__":
    build()
