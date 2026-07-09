"""
Voltix backend — SECURITY-FIXED VERSION
=========================================
What changed vs. the original server.py, and why:

1. /api/users no longer exists as a public endpoint that dumps the whole
   table. Passwords are NEVER sent to the client, ever, under any role.
2. Passwords are hashed with bcrypt before storage. Login compares hashes,
   not plaintext.
3. Every write endpoint (create/delete product, place/advance order,
   admin actions) requires a valid session token AND checks the caller's
   role server-side. The frontend can no longer just "pretend" to be an
   admin or seller.
4. The old hardcoded admin/seller signup code ("VOLTIX") is gone. Instead,
   new accounts default to role='buyer'. Promoting someone to seller/admin
   is a server-side action (see /api/admin/promote) that itself requires
   an existing admin's session token — i.e. the first admin has to be
   created directly in the database (see create_first_admin.py below),
   and after that, admins promote people through the app, not a public
   signup form.
5. CORS is restricted to your actual frontend origin instead of "*".
6. Session tokens are random, stored server-side with an expiry, and
   checked on every protected request (simple bearer-token pattern —
   swap for JWT/Flask-Login later if you want, but this is a solid
   minimum).
7. Rate limiting added on /api/login and /api/signup to slow down brute
   force / spam signups.

You will need to: `pip install flask flask-cors bcrypt flask-limiter`
"""

import sqlite3
import bcrypt
import secrets
import time
import os
from flask import Flask, request, jsonify, g
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)

# --- CORS: lock this down to your real frontend domain ---
ALLOWED_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "https://sakthivelk150706-ctrl.github.io")
CORS(app, resources={r"/api/*": {"origins": ALLOWED_ORIGIN}}, supports_credentials=True)

limiter = Limiter(get_remote_address, app=app, default_limits=["200 per hour"])

DB_PATH = os.environ.get("DB_PATH", "voltix.db")

# In-memory session store: {token: {"user_id":..., "role":..., "expires":...}}
# For production, move this to a "sessions" table in SQLite (or Redis) so it
# survives restarts. In-memory is fine to start.
SESSIONS = {}
SESSION_TTL_SECONDS = 60 * 60 * 12  # 12 hours


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
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
        """CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, category TEXT, price REAL, stock INTEGER,
            source TEXT, source_url TEXT, description TEXT,
            seller_id INTEGER
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER, buyer_id INTEGER, quantity INTEGER,
            status TEXT DEFAULT 'placed', payment_verified INTEGER DEFAULT 0,
            created_at REAL
        )"""
    )
    db.commit()
    db.close()


# ---------- auth helpers ----------

def make_session(user_row):
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = {
        "user_id": user_row["id"],
        "role": user_row["role"],
        "expires": time.time() + SESSION_TTL_SECONDS,
    }
    return token


def get_session():
    """Reads the Authorization: Bearer <token> header. Returns session dict or None."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth.split(" ", 1)[1]
    session = SESSIONS.get(token)
    if not session:
        return None
    if session["expires"] < time.time():
        SESSIONS.pop(token, None)
        return None
    return session


def require_role(*roles):
    """Use as: session = require_role('admin', 'seller'); if session is None: return 401 response"""
    session = get_session()
    if session is None:
        return None, (jsonify({"error": "Not authenticated"}), 401)
    if roles and session["role"] not in roles:
        return None, (jsonify({"error": "Not authorized"}), 403)
    return session, None


# ---------- auth endpoints ----------

@app.route("/api/signup", methods=["POST"])
@limiter.limit("10 per hour")
def signup():
    data = request.get_json(force=True) or {}
    email = (data.get("email") or "").strip().lower()
    name = (data.get("name") or "").strip()
    password = data.get("password") or ""

    if not email or not password or len(password) < 8:
        return jsonify({"error": "Email and an 8+ character password are required"}), 400

    db = get_db()
    existing = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
    if existing:
        return jsonify({"error": "An account with this email already exists"}), 409

    pass_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    # NOTE: every new signup is a 'buyer'. There is no client-supplied role field,
    # and no verification code that grants elevated access. This is intentional.
    cur = db.execute(
        "INSERT INTO users (email, name, pass_hash, role) VALUES (?,?,?, 'buyer')",
        (email, name, pass_hash),
    )
    db.commit()
    user_row = db.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone()
    token = make_session(user_row)
    return jsonify({"token": token, "role": user_row["role"], "name": user_row["name"]})


@app.route("/api/login", methods=["POST"])
@limiter.limit("10 per minute")
def login():
    data = request.get_json(force=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    db = get_db()
    user_row = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()

    # Always run bcrypt.checkpw even on a "user not found" path in a real
    # hardened version (to avoid timing attacks revealing valid emails).
    # Keeping it simple here, but worth doing later.
    if not user_row or not bcrypt.checkpw(password.encode("utf-8"), user_row["pass_hash"].encode("utf-8")):
        return jsonify({"error": "Invalid email or password"}), 401

    token = make_session(user_row)
    return jsonify({"token": token, "role": user_row["role"], "name": user_row["name"]})


@app.route("/api/logout", methods=["POST"])
def logout():
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        SESSIONS.pop(auth.split(" ", 1)[1], None)
    return jsonify({"ok": True})


@app.route("/api/me", methods=["GET"])
def me():
    session = get_session()
    if session is None:
        return jsonify({"error": "Not authenticated"}), 401
    db = get_db()
    user_row = db.execute("SELECT id, email, name, role FROM users WHERE id=?", (session["user_id"],)).fetchone()
    return jsonify(dict(user_row))


# ---------- admin: promote a user (admin-only, server-side gated) ----------

@app.route("/api/admin/promote", methods=["POST"])
def promote():
    session, err = require_role("admin")
    if err:
        return err
    data = request.get_json(force=True) or {}
    target_email = (data.get("email") or "").strip().lower()
    new_role = data.get("role")
    if new_role not in ("buyer", "seller", "delivery", "admin"):
        return jsonify({"error": "Invalid role"}), 400

    db = get_db()
    db.execute("UPDATE users SET role=? WHERE email=?", (new_role, target_email))
    db.commit()
    return jsonify({"ok": True})


# ---------- products ----------

@app.route("/api/products", methods=["GET"])
def list_products():
    db = get_db()
    rows = db.execute("SELECT * FROM products").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/products", methods=["POST"])
def create_product():
    session, err = require_role("seller", "admin")
    if err:
        return err
    data = request.get_json(force=True) or {}
    db = get_db()
    cur = db.execute(
        "INSERT INTO products (name, category, price, stock, source, source_url, description, seller_id) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            data.get("name"), data.get("category"), data.get("price"), data.get("stock"),
            data.get("source"), data.get("source_url"), data.get("description"),
            session["user_id"],
        ),
    )
    db.commit()
    return jsonify({"id": cur.lastrowid})


@app.route("/api/products/<int:product_id>", methods=["DELETE"])
def delete_product(product_id):
    session, err = require_role("seller", "admin")
    if err:
        return err
    db = get_db()
    product = db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    if not product:
        return jsonify({"error": "Not found"}), 404
    # Sellers can only delete their own listings; admins can delete anything.
    if session["role"] == "seller" and product["seller_id"] != session["user_id"]:
        return jsonify({"error": "Not authorized"}), 403
    db.execute("DELETE FROM products WHERE id=?", (product_id,))
    db.commit()
    return jsonify({"ok": True})


# ---------- orders ----------

@app.route("/api/orders", methods=["POST"])
def create_order():
    session, err = require_role("buyer", "seller", "admin")
    if err:
        return err
    data = request.get_json(force=True) or {}
    product_id = data.get("product_id")
    quantity = int(data.get("quantity", 1))

    db = get_db()
    product = db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    if not product or product["stock"] < quantity:
        return jsonify({"error": "Product unavailable or insufficient stock"}), 400

    # IMPORTANT: payment_verified starts at 0. Stock is NOT decremented here.
    # Stock should only decrement, and the order only move to 'confirmed',
    # once your payment gateway's webhook confirms the payment server-side.
    # Plug your gateway's verification call in where the TODO is below.
    cur = db.execute(
        "INSERT INTO orders (product_id, buyer_id, quantity, status, payment_verified, created_at) "
        "VALUES (?,?,?, 'pending_payment', 0, ?)",
        (product_id, session["user_id"], quantity, time.time()),
    )
    db.commit()
    return jsonify({"order_id": cur.lastrowid, "status": "pending_payment"})


@app.route("/api/orders/<int:order_id>/verify_payment", methods=["POST"])
def verify_payment(order_id):
    """
    TODO: Replace this with your real payment gateway's server-side
    verification (e.g. Razorpay webhook signature check, or a call to
    the gateway's "verify payment" API using the payment_id the gateway
    gives you). Do NOT mark payment_verified=1 just because the client
    says so — that is the exact bug that was in the original code.
    """
    session, err = require_role("buyer", "admin")
    if err:
        return err
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        return jsonify({"error": "Not found"}), 404

    # -------- placeholder: wire real gateway verification here --------
    payment_confirmed_by_gateway = False  # never leave this hardcoded True
    # --------------------------------------------------------------------

    if not payment_confirmed_by_gateway:
        return jsonify({"error": "Payment not verified by gateway yet"}), 402

    product = db.execute("SELECT * FROM products WHERE id=?", (order["product_id"],)).fetchone()
    db.execute("UPDATE products SET stock = stock - ? WHERE id=?", (order["quantity"], product["id"]))
    db.execute("UPDATE orders SET status='confirmed', payment_verified=1 WHERE id=?", (order_id,))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/orders/<int:order_id>/advance", methods=["POST"])
def advance_order(order_id):
    session, err = require_role("delivery", "admin")
    if err:
        return err
    data = request.get_json(force=True) or {}
    new_status = data.get("status")
    if new_status not in ("shipped", "out_for_delivery", "delivered"):
        return jsonify({"error": "Invalid status"}), 400
    db = get_db()
    db.execute("UPDATE orders SET status=? WHERE id=?", (new_status, order_id))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/orders/mine", methods=["GET"])
def my_orders():
    session, err = require_role("buyer", "seller", "admin", "delivery")
    if err:
        return err
    db = get_db()
    rows = db.execute("SELECT * FROM orders WHERE buyer_id=?", (session["user_id"],)).fetchall()
    return jsonify([dict(r) for r in rows])


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
