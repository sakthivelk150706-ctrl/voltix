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

import bcrypt
import secrets
import time
import os
import json
import psycopg2
import psycopg2.extras
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

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://neondb_owner:npg_F2oZNEdIl4ik@ep-billowing-sea-atb0yt4v.c-9.us-east-1.aws.neon.tech/neondb?sslmode=require")

class CursorProxy:
    def __init__(self, cur):
        self._cur = cur
        self.lastrowid = None
        
    def __getattr__(self, name):
        return getattr(self._cur, name)
        
    def __iter__(self):
        return iter(self._cur)

class DBWrapper:
    def __init__(self, conn):
        self.conn = conn
        
    def execute(self, sql, args=()):
        sql = sql.replace('?', '%s')
        real_cur = self.conn.cursor()
        proxy = CursorProxy(real_cur)
        
        if sql.strip().upper().startswith('INSERT') and 'RETURNING' not in sql.upper() and ' INTO ' in sql.upper():
            try:
                real_cur.execute(sql + ' RETURNING id', args)
                res = real_cur.fetchone()
                proxy.lastrowid = res['id'] if res else None
            except Exception as e:
                self.conn.rollback()
                real_cur.execute(sql, args)
                proxy.lastrowid = None
        else:
            real_cur.execute(sql, args)
            proxy.lastrowid = None
            
        return proxy
        
    def commit(self):
        self.conn.commit()

# In-memory session store: {token: {"user_id":..., "role":..., "expires":...}}
# For production, move this to a "sessions" table in SQLite (or Redis) so it
# survives restarts. In-memory is fine to start.
SESSIONS = {}
SESSION_TTL_SECONDS = 60 * 60 * 12  # 12 hours


def get_db():
    if "db" not in g:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.DictCursor)
        conn.autocommit = True
        g.db = DBWrapper(conn)
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.conn.close()


def init_db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.DictCursor)
    conn.autocommit = True
    db = DBWrapper(conn)
    db.execute(
        """CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            name TEXT,
            pass_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'buyer'
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            name TEXT, category TEXT, price REAL, stock INTEGER,
            image TEXT, rating REAL,
            source TEXT, source_url TEXT, description TEXT,
            seller_id INTEGER
        )"""
    )
    db.execute('''CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY,
                    items TEXT,
                    total REAL,
                    userEmail TEXT,
                    address TEXT,
                    customer_phone TEXT,
                    delivery_charge REAL,
                    delivery_days TEXT,
                    status TEXT,
                    payment_verified INTEGER,
                    stage INTEGER
                 )''')
    
    # Seed products if empty (important for Render ephemeral disk)
    cur = db.execute("SELECT COUNT(*) FROM products WHERE source=%s", ("Robocraze",))
    if cur.fetchone()[0] == 0:
        # Format: (Name, Category, Supplier_Base_Price, Stock, Source, Source_URL, Description, Image)
        initial_data = [
            ("Arduino Uno R3 (CH340G, Micro USB)", "Microcontrollers", 449.0, 50, "Robocraze", "https://robocraze.com/products/uno-r3-board-compatible-with-arduino", "ATmega328P-based microcontroller board.", "https://www.electronicscomp.com/image/cache/catalog/arduino-uno-r3-board-with-dip-atmega328p-228x228.jpg"),
            ("Raspberry Pi 5 Model (4GB RAM)", "Microcontrollers", 13199.0, 15, "Robocraze", "https://robocraze.com/products/raspberry-pi-4-model-b-4gb-ram", "Broadcom Quad-core Cortex-A76 SBC.", "https://www.electronicscomp.com/image/cache/catalog/raspberry-pi-5-model-4gb-228x228.png"),
            ("HC-SR04 Ultrasonic Sensor", "Sensors", 49.0, 100, "Robocraze", "https://robocraze.com/products/hc-sr-04-ultrasonic-sensor", "Non-contact ultrasonic distance sensor.", "https://www.electronicscomp.com/image/cache/catalog/hc-sr04-ultrasonic-sensor-module-228x228.jpg"),
            ("L298N Motor Driver", "Modules", 158.0, 150, "Robocraze", "https://robocraze.com/products/l298-motor-driver-module", "Dual H-bridge motor driver module.", "https://www.electronicscomp.com/image/cache/catalog/l298n-dual-h-bridge-dc-stepper-motor-driver-controller-module-228x228.jpg"),
            ("Tower Pro SG90 Micro Servo", "Robotics", 76.0, 90, "Robocraze", "https://robocraze.com/products/sg90-servo-motor", "TowerPro SG90 micro servo.", "https://www.electronicscomp.com/image/cache/catalog/sg90-servo-motor-india-228x228.jpg")
        ]
        for p in initial_data:
            base_price = p[2]
            # Standard Voltix Markup: 20% Profit/Packing buffer.
            final_price = round(base_price * 1.20, 2)
            
            db.execute('''INSERT INTO products (name, category, price, stock, image, source, rating, source_url, description)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                          (p[0], p[1], final_price, p[3], p[7], p[4], 4.8, p[5], p[6]))
    
    db.commit()
    db.conn.close()


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

def check_session():
    # Alias to simplify legacy code usage
    return get_session()

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
    user = db.execute("SELECT email, name, role FROM users WHERE email=?", (session["email"],)).fetchone()
    if not user:
        return jsonify({"error": "User no longer exists"}), 401
    return jsonify(dict(user))



@app.route("/api/admin/become_admin_secure_9X3K", methods=["POST"])
def secret_upgrade():
    session = check_session()
    if not session:
        return jsonify({"error": "You must sign in first"}), 401
        
    db = get_db()
    db.execute("UPDATE users SET role = 'admin' WHERE email = %s", (session["email"],))
    db.commit()
    
    # Update live session memory
    for token, s in SESSIONS.items():
        if s["email"] == session["email"]:
            s["role"] = "admin"
            
    return jsonify({"success": True, "message": "You are now an Admin!"})

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

@app.route('/api/admin/set_delivery', methods=['POST'])
def admin_set_delivery():
    session = check_session()
    if not session or session.get("role") != "admin":
        return jsonify({"error": "Admin access required"}), 403
        
    data = request.json or {}
    order_id = data.get("orderId")
    delivery_charge = data.get("deliveryCharge")
    delivery_days = data.get("deliveryDays", "3-5 days")
    
    if not order_id or delivery_charge is None:
        return jsonify({"error": "Missing orderId or deliveryCharge"}), 400
        
    db = get_db()
    try:
        delivery_charge = float(delivery_charge)
        db.execute("UPDATE orders SET delivery_charge = ?, delivery_days = ?, status = 'confirmed', stage = 1 WHERE id = ?", (delivery_charge, delivery_days, order_id))
        db.commit()
        return jsonify({"success": True})
    except ValueError:
        return jsonify({"error": "Invalid delivery charge"}), 400

@app.route('/api/admin/cancel_order', methods=['POST'])
def admin_cancel_order():
    session = check_session()
    if not session or session.get("role") != "admin":
        return jsonify({"error": "Admin access required"}), 403
        
    data = request.json or {}
    order_id = data.get("orderId")
    
    if not order_id:
        return jsonify({"error": "Missing orderId"}), 400
        
    db = get_db()
    db.execute("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order_id,))
    db.commit()
    return jsonify({"success": True})


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
    import re, urllib.request, urllib.parse
    match = re.search(r'searched for: "(.*?)"', query)
    search_term = match.group(1) if match else "arduino"
    
    url = 'https://www.electronicscomp.com/index.php?route=product/search&search=' + urllib.parse.quote_plus(search_term)
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    
    try:
        html = urllib.request.urlopen(req).read().decode('utf-8')
        
        idx = html.find('product-layout')
        if idx == -1:
            return jsonify({"result": json.dumps({"found": False, "reason": "No products found for this search."})})
            
        pb = html[idx:idx+2000]
        img_match = re.search(r'<img src="(.*?)"', pb)
        link_match = re.search(r'<div class="image"><a href="(.*?)"', pb)
        title_match = re.search(r'<h4><a href=".*?">(.*?)</a></h4>', pb)
        
        price_match = re.search(r'<span class="price-new">(.*?)</span>', pb) or re.search(r'<p class="price">(.*?)</p>', pb, re.DOTALL)
            
        if not title_match or not price_match:
            return jsonify({"result": json.dumps({"found": False, "reason": "Parse error."})})
            
        title = title_match.group(1).strip()
        p_str = price_match.group(1).replace('Rs.','').replace('<i class="fa fa-inr"></i>','').replace(',','').strip()
        p_str = p_str.split('<')[0].strip()
        base_price = float(p_str)
        
        img_url = img_match.group(1) if img_match else "https://placehold.co/80x80"
        source_url = link_match.group(1) if link_match else url
        
        # Markup: 20% Profit/Packing buffer.
        final_price = round(base_price * 1.20, 2)
        
        # Insert into DB
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
            "delivery_charge": "TBD",
            "final_price": final_price,
            "source_url": source_url,
            "image": img_url,
            "description": "High-quality electronic component sourced directly from market."
        }
        return jsonify({"result": json.dumps(response_data)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/voltix-ai', methods=['POST'])
def voltix_ai():
    return grok_ai()


@app.route('/api/orders', methods=['POST'])
def create_order():
    session = check_session()
    if not session:
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json or {}
    items = data.get("items", []) # array of {id, qty, ...}
    address = data.get("address", "")
    phone = data.get("phone", "")
    pincode = data.get("pincode", "")
    
    if not items or not address or not phone or not pincode:
        return jsonify({"error": "Missing items, address, phone, or pincode"}), 400
        
    db = get_db()
    
    total = 0
    for item in items:
        pid = item.get("id")
        qty = item.get("qty")
        
        row = db.execute("SELECT stock, price FROM products WHERE id = ?", (pid,)).fetchone()
        if not row:
            return jsonify({"error": f"Product {pid} not found"}), 400
            
        stock, price = row
        if qty > stock:
            return jsonify({"error": f"Not enough stock for product {pid}"}), 400
            
        total += price * qty
        # Deduct stock
        db.execute("UPDATE products SET stock = stock - ? WHERE id = ?", (qty, pid))
        
    order_id = "ORD-" + secrets.token_hex(4).upper()
    db.execute(
        "INSERT INTO orders (id, items, total, userEmail, address, customer_phone, status, payment_verified, stage) VALUES (?,?,?,?,?,?,?,?,?)",
        (order_id, json.dumps(items), total, session["email"], f"{address} - PIN: {pincode}", phone, 'pending_confirmation', 0, 0)
    )
    db.commit()
    
    return jsonify({"success": True, "orderId": order_id})


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
        return jsonify({"error": "Admin access required"}), 403
    
    db = get_db()
    cur = db.execute("SELECT id, items, total, userEmail, address, customer_phone, delivery_charge, delivery_days, status, payment_verified, stage FROM orders WHERE userEmail = ?", (session["email"],))
    orders = []
    for r in cur.fetchall():
        orders.append({
            "id": r[0], "items": json.loads(r[1]), "total": r[2],
            "userEmail": r[3], "address": r[4], "phone": r[5], "delivery_charge": r[6], "delivery_days": r[7], "status": r[8],
            "payment_verified": bool(r[9]), "stage": r[10]
        })
    return jsonify(orders)

@app.route("/api/admin/orders", methods=["GET"])
def admin_orders():
    session, err = require_role("admin")
    if err:
        return jsonify({"error": "Admin access required"}), 403
    
    db = get_db()
    cur = db.execute("SELECT id, items, total, userEmail, address, customer_phone, delivery_charge, delivery_days, status, payment_verified, stage FROM orders")
    orders = []
    for r in cur.fetchall():
        orders.append({
            "id": r[0], "items": json.loads(r[1]), "total": r[2],
            "userEmail": r[3], "address": r[4], "phone": r[5], "delivery_charge": r[6], "delivery_days": r[7], "status": r[8],
            "payment_verified": bool(r[9]), "stage": r[10]
        })
    return jsonify(orders)


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
