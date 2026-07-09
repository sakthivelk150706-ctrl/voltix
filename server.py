import os
import json
import sqlite3
import urllib.parse
import urllib.request
import traceback
from functools import wraps
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
import datetime

PORT = int(os.environ.get("PORT", 8080))
DB_FILE = 'voltix.db'
SECRET_KEY = os.environ.get('SECRET_KEY', 'super-secret-voltix-key-for-jwt')

app = Flask(__name__)
# Restrict CORS to specific origins in production, allow all for dev
allowed_origins = ["https://sakthivelk150706-ctrl.github.io", "http://127.0.0.1:5500", "http://localhost:5500"]
CORS(app, resources={r"/api/*": {"origins": allowed_origins}})

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS products
                 (id INTEGER PRIMARY KEY, name TEXT, category TEXT, price REAL, stock INTEGER, image TEXT, source TEXT, rating REAL, source_url TEXT, description TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (email TEXT PRIMARY KEY, name TEXT, pass TEXT, role TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS orders
                 (id TEXT PRIMARY KEY, items TEXT, total REAL, stage INTEGER, userEmail TEXT, address TEXT)''')
    
    # Run migrations if needed
    c.execute("PRAGMA table_info(products)")
    columns = [column[1] for column in c.fetchall()]
    if 'source_url' not in columns:
        c.execute("ALTER TABLE products ADD COLUMN source_url TEXT DEFAULT ''")
    if 'description' not in columns:
        c.execute("ALTER TABLE products ADD COLUMN description TEXT DEFAULT ''")
    
    c.execute("PRAGMA table_info(orders)")
    order_cols = [column[1] for column in c.fetchall()]
    if 'address' not in order_cols:
        c.execute("ALTER TABLE orders ADD COLUMN address TEXT DEFAULT ''")
    
    conn.commit()
    conn.close()

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            parts = request.headers['Authorization'].split()
            if len(parts) == 2 and parts[0] == 'Bearer':
                token = parts[1]
        
        if not token:
            return jsonify({"error": "Authentication token is missing"}), 401

        try:
            data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            current_user = {"email": data["email"], "role": data["role"]}
        except Exception as e:
            return jsonify({"error": "Invalid or expired token"}), 401

        return f(current_user, *args, **kwargs)
    return decorated

def require_role(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(current_user, *args, **kwargs):
            if current_user['role'] not in roles:
                return jsonify({"error": "Unauthorized role"}), 403
            return f(current_user, *args, **kwargs)
        return decorated
    return decorator

# --- ROUTES ---

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email', '').strip().lower()
    password = data.get('pass', '')

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
    conn.close()

    if not user or not check_password_hash(user['pass'], password):
        return jsonify({"error": "Invalid email or password"}), 401

    token = jwt.encode({
        "email": user['email'],
        "role": user['role'],
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=7)
    }, SECRET_KEY, algorithm="HS256")

    return jsonify({
        "token": token,
        "user": {"name": user['name'], "email": user['email'], "role": user['role']}
    })

@app.route('/api/users', methods=['POST'])
def signup():
    data = request.json
    email = data.get('email', '').strip().lower()
    name = data.get('name', '').strip()
    password = data.get('pass', '')
    role = data.get('role', 'buyer')

    # Security: Don't allow signing up as admin from the public API
    if role == 'admin':
        return jsonify({"error": "Admin role must be provisioned manually."}), 403

    hashed_password = generate_password_hash(password)

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute('INSERT INTO users (email, name, pass, role) VALUES (?,?,?,?)',
                  (email, name, hashed_password, role))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": "User already exists"}), 400
    conn.close()
    
    # Auto-login after signup
    token = jwt.encode({
        "email": email,
        "role": role,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=7)
    }, SECRET_KEY, algorithm="HS256")
    
    return jsonify({
        "success": True,
        "token": token,
        "user": {"name": name, "email": email, "role": role}
    })

@app.route('/api/users', methods=['GET'])
@require_auth
@require_role('admin')
def get_users(current_user):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    rows = conn.execute('SELECT email, name, role FROM users').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/products', methods=['GET'])
def get_products():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    rows = conn.execute('SELECT * FROM products').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/products', methods=['POST'])
@require_auth
@require_role('admin', 'seller')
def create_product(current_user):
    data = request.json
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    image_url = data.get('image', '')
    if image_url == '' or 'pollinations.ai' in image_url:
        try:
            from duckduckgo_search import DDGS
            safe_name = data['name'].replace(' ', '_').replace('&', 'and').replace('/', '_').replace('(', '').replace(')', '')
            filepath = f"images/{safe_name}.jpg"
            if not os.path.exists(filepath) and not os.path.exists("images"):
                os.makedirs("images", exist_ok=True)
            if not os.path.exists(filepath):
                results = list(DDGS().images(f"{data['name']} electronic component top down white background", max_results=2))
                if results:
                    req = urllib.request.Request(results[0]['image'], headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req, timeout=5) as response, open(filepath, 'wb') as out_file:
                        out_file.write(response.read())
            image_url = f"/{filepath}"
        except Exception as e:
            print(f"Dynamic image search failed: {e}")
    
    c.execute('INSERT INTO products (name, category, price, stock, image, source, rating, source_url, description) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
              (data['name'], data.get('category', 'Components'), data['price'], data.get('stock', 50), image_url, data.get('source', 'AI Sourced'), data.get('rating', 4.8), data.get('source_url', ''), data.get('description', 'High-quality electronic component sourced for Voltix & CO.')))
    new_id = c.lastrowid
    conn.commit()
    conn.close()
    return jsonify({"success": True, "id": new_id})

@app.route('/api/products/delete', methods=['POST'])
@require_auth
@require_role('admin', 'seller')
def delete_product(current_user):
    data = request.json
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('DELETE FROM products WHERE id = ?', (data['id'],))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route('/api/orders', methods=['GET'])
@require_auth
def get_orders(current_user):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    if current_user['role'] in ['admin', 'delivery']:
        rows = conn.execute('SELECT * FROM orders').fetchall()
    else:
        rows = conn.execute('SELECT * FROM orders WHERE userEmail = ?', (current_user['email'],)).fetchall()
    
    orders = []
    for r in rows:
        d = dict(r)
        d['items'] = json.loads(d['items'])
        orders.append(d)
    conn.close()
    return jsonify(orders)

@app.route('/api/orders', methods=['POST'])
@require_auth
def create_order(current_user):
    data = request.json
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    items_str = json.dumps(data['items'])
    # Force the userEmail to be the authenticated user's email
    user_email = current_user['email']
    c.execute('INSERT INTO orders (id, items, total, stage, userEmail, address) VALUES (?,?,?,?,?,?)',
              (data['id'], items_str, data['total'], data.get('stage', 0), user_email, data.get('address', 'No address provided')))
    for item in data['items']:
        c.execute('UPDATE products SET stock = stock - ? WHERE id = ?', (item['qty'], item['id']))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route('/api/orders/advance', methods=['POST'])
@require_auth
@require_role('admin', 'delivery')
def advance_order(current_user):
    data = request.json
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('UPDATE orders SET stage = stage + 1 WHERE id = ?', (data['id'],))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route('/api/grok', methods=['POST'])
def grok_ai():
    data = request.json
    try:
        prompt_encoded = urllib.parse.quote(data['prompt'])
        req = urllib.request.Request(
            "https://text.pollinations.ai/prompt/" + prompt_encoded + "?json=true&model=openai",
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(req) as response:
            res_body = response.read().decode('utf-8')
        return jsonify({"result": res_body})
    except Exception as e:
        err_msg = str(e)
        if hasattr(e, 'read'):
            try:
                err_msg += " Body: " + e.read().decode('utf-8')
            except Exception:
                pass
        return jsonify({"error": err_msg}), 500

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=PORT)
