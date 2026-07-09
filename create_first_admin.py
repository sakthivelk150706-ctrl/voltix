"""
Run this ONCE, locally, against your database, to create your first admin
account. After that, use the app's /api/admin/promote endpoint (logged in
as an admin) to promote other accounts — never expose a client-side
"admin code" again.

Usage:
    pip install bcrypt
    python create_first_admin.py
"""

import sqlite3
import bcrypt
import getpass

DB_PATH = "voltix.db"

email = input("Admin email: ").strip().lower()
name = input("Admin name: ").strip()
password = getpass.getpass("Admin password (min 8 chars): ")

if len(password) < 8:
    raise SystemExit("Password too short.")

pass_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

db = sqlite3.connect(DB_PATH)
db.execute(
    """CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        name TEXT,
        pass_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'buyer'
    )"""
)
db.execute(
    "INSERT INTO users (email, name, pass_hash, role) VALUES (?,?,?, 'admin')",
    (email, name, pass_hash),
)
db.commit()
db.close()
print(f"Admin account created for {email}.")
