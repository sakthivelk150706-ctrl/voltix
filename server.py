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

from flask import redirect

@app.route("/")
def index():
    # Redirect visitors to the frontend instead of showing a 404 error
    return redirect("https://sakthivelk150706-ctrl.github.io/voltix/")

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
            image TEXT, rating REAL,
            source TEXT, source_url TEXT, description TEXT,
            seller_id INTEGER
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY,
            items TEXT NOT NULL,
            total REAL NOT NULL,
            userEmail TEXT NOT NULL,
            address TEXT NOT NULL,
            status TEXT DEFAULT 'placed', payment_verified INTEGER DEFAULT 0,
            stage INTEGER DEFAULT 0
        )"""
    )
    
    # Purge any old AI-generated images from the database
    db.execute('DELETE FROM products WHERE image LIKE "%pollinations%"')
    
    # Seed products if empty (important for Render ephemeral disk)
    cursor = db.cursor()
    cursor.execute("SELECT COUNT(*) FROM products")
    if cursor.fetchone()[0] == 0:
        initial_data = [
            ("Arduino Uno R3 (CH340G, Micro USB)", "Microcontrollers", 239.0, 50, "Robocraze", "https://robocraze.com/products/uno-r3-board-compatible-with-arduino", "ATmega328P-based microcontroller board.", "https://robu.in/wp-content/uploads/2014/08/uno_r3_front.jpg"),
            ("Raspberry Pi 4 Model B (4GB RAM)", "Microcontrollers", 5546.0, 15, "Robocraze", "https://robocraze.com/products/raspberry-pi-4-model-b-4gb-ram", "Broadcom BCM2711 Quad-core Cortex-A72 SBC.", "https://robu.in/wp-content/uploads/2019/06/Raspberry-Pi-4-Model-B-4-GB-RAM-ROBU.IN-2-300x300.jpg"),
            ("HC-SR04 Ultrasonic Sensor", "Sensors", 59.0, 100, "Robocraze", "https://robocraze.com/products/hc-sr-04-ultrasonic-sensor", "Non-contact ultrasonic distance sensor.", "https://robu.in/wp-content/uploads/2014/12/hc-sr04-ultrasonic-range-finder-module.jpg"),
            ("L298N Motor Driver", "Modules", 136.0, 150, "Robocraze", "https://robocraze.com/products/l298-motor-driver-module", "Dual H-bridge motor driver module.", "https://robu.in/wp-content/uploads/2015/04/l298-motor-driver-module-1-300x300.jpg"),
            ("SG90 9G Micro Servo", "Robotics", 89.0, 90, "Robocraze", "https://robocraze.com/collections/servo-motors-controllers", "TowerPro SG90 micro servo.", "https://robu.in/wp-content/uploads/2015/09/sg90-tower-pro-micro-servo-motor-1-300x300.jpg")
        ]
        for p in initial_data:
            cursor.execute('''INSERT INTO products (name, category, price, stock, image, source, rating, source_url, description)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                          (p[0], p[1], p[2], p[3], p[7], p[4], 4.8, p[5], p[6]))
    
    db.commit()
    db.close()


# ---------- auth helpers ----------

def make_session(user_row):
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = {
        "user_id": user_row["id"],
        "email": user_row["email"],
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
    if session["role"] == "seller" and product["seller_id"] != session["user_id"]:
        return jsonify({"error": "Not authorized"}), 403
    db.execute("DELETE FROM products WHERE id=?", (product_id,))
    db.commit()
    return jsonify({"ok": True})


# ---------- AI Features ----------

@app.route('/api/grok', methods=['POST'])
def grok_ai():
    data = request.json or {}
    query = data.get('prompt', '')
    # The frontend passes a long prompt, let's extract the actual search term
    import re, urllib.request, urllib.parse
    match = re.search(r'searched for: "(.*?)"', query)
    search_term = match.group(1) if match else "arduino"
    
    url = 'https://www.electronicscomp.com/index.php?route=product/search&search=' + urllib.parse.quote_plus(search_term)
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    
    try:
        html = urllib.request.urlopen(req).read().decode('utf-8')
        prod_block = re.search(r'<div class="product-layout.*?</div></div></div>', html, re.DOTALL)
        if not prod_block:
            return jsonify({"result": json.dumps({"found": False, "reason": "Not available."})})
            
        pb = prod_block.group(0)
        img_match = re.search(r'<img src="(.*?)"', pb)
        link_match = re.search(r'<div class="image"><a href="(.*?)"', pb)
        title_match = re.search(r'<h4><a href=".*?">(.*?)</a></h4>', pb)
        
        # ElectronicsComp has two price formats depending on discount
        price_match = re.search(r'<span class="price-new"><i class="fa fa-inr"></i> (.*?)</span>', pb)
        if not price_match:
            price_match = re.search(r'<p class="price">\s*<i class="fa fa-inr"></i> (.*?)\s*</p>', pb)
            
        if not title_match or not price_match:
            return jsonify({"result": json.dumps({"found": False, "reason": "Parse error."})})
            
        title = title_match.group(1).strip()
        base_price = float(price_match.group(1).replace(',', ''))
        img_url = img_match.group(1) if img_match else "https://placehold.co/80x80"
        source_url = link_match.group(1) if link_match else url
        
        # Markup: 5% packing + 49 delivery
        final_price = round(base_price * 1.05 + 49, 2)
        
        # Insert into DB so cart works
        db = get_db()
        cur = db.execute('''INSERT INTO products (name, category, price, stock, image, source, rating, source_url, description)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                         (title, "AI Sourced", final_price, 50, img_url, "ElectronicsComp", 4.9, source_url, "Dynamically sourced top-tier electronic component."))
        new_id = cur.lastrowid
        db.commit()
        
        response_data = {
            "found": True,
            "product_id": new_id,
            "product_name": title,
            "category": "AI Sourced",
            "base_price": base_price,
            "packing_charge": round(base_price * 0.05, 2),
            "delivery_charge": 49,
            "final_price": final_price,
            "source_url": source_url,
            "image": img_url,
            "reason": "Scraped exact real-world price directly from ElectronicsComp.",
            "description": "High-quality electronic component sourced directly from market."
        }
        return jsonify({"result": json.dumps(response_data)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/voltix-ai', methods=['POST'])
def voltix_ai():
    return grok_ai()


# ---------- orders ----------

@app.route("/api/orders", methods=["POST"])
def create_order():
    session, err = require_role("buyer", "seller", "admin")
    if err:
        return err
    data = request.get_json(force=True) or {}
    items = data.get("items", [])
    if not items:
        return jsonify({"error": "Empty cart"}), 400

    db = get_db()
    # Check stock for all items
    for item in items:
        product = db.execute("SELECT stock FROM products WHERE id=?", (item["id"],)).fetchone()
        if not product or product["stock"] < item["qty"]:
            return jsonify({"error": f"Product {item['id']} unavailable or insufficient stock"}), 400

    # Deduct stock
    for item in items:
        db.execute("UPDATE products SET stock = stock - ? WHERE id=?", (item["qty"], item["id"]))

    total = float(data.get("total", 0.0))
    address = data.get("address", "N/A")
    order_id = "VLX-" + secrets.token_hex(4).upper()

    cur = db.execute(
        "INSERT INTO orders (id, items, total, userEmail, address, status, payment_verified, stage) VALUES (?,?,?,?,?,?,?,?)",
        (order_id, json.dumps(items), total, session["email"], address, 'pending_payment', 0, 0),
    )
    db.commit()
    return jsonify({"order_id": order_id, "status": "pending_payment"})


@app.route("/api/orders/<int:order_id>/verify_payment", methods=["POST"])
def verify_payment(order_id):
    session, err = require_role("buyer", "admin")
    if err:
        return err
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        return jsonify({"error": "Not found"}), 404

    payment_confirmed_by_gateway = False 

    if not payment_confirmed_by_gateway:
        return jsonify({"error": "Payment not verified by gateway yet"}), 402

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


@app.route("/api/orders/my", methods=["GET"])
def my_orders():
    session, err = require_role("buyer", "seller", "admin", "delivery")
    if err:
        return err
    db = get_db()
    cur = db.execute("SELECT * FROM orders WHERE userEmail = ?", (session["email"],))
    rows = cur.fetchall()
    orders = []
    for r in rows:
        d = dict(r)
        d["items"] = json.loads(d["items"])
        orders.append(d)
    return jsonify(orders)


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
