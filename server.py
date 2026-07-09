import http.server
import socketserver
import sqlite3
import json
import urllib.request
import urllib.parse
import os

PORT = 8080
DB_FILE = 'voltix.db'
GROK_API_KEY = os.environ.get('GROK_API_KEY', 'xai-fake-key')

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS products
                 (id INTEGER PRIMARY KEY, name TEXT, category TEXT, price REAL, stock INTEGER, image TEXT, source TEXT, rating REAL, source_url TEXT, description TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (email TEXT PRIMARY KEY, name TEXT, pass TEXT, role TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS orders
                 (id TEXT PRIMARY KEY, items TEXT, total REAL, stage INTEGER, userEmail TEXT, address TEXT)''')
    
    # Check if we need to migrate
    c.execute("PRAGMA table_info(products)")
    columns = [column[1] for column in c.fetchall()]
    if 'source_url' not in columns:
        c.execute("ALTER TABLE products ADD COLUMN source_url TEXT DEFAULT 'https://www.robu.in/'")
    if 'description' not in columns:
        c.execute("ALTER TABLE products ADD COLUMN description TEXT DEFAULT 'High-quality electronic component sourced for Voltix & CO.'")
    
    c.execute("PRAGMA table_info(orders)")
    order_cols = [column[1] for column in c.fetchall()]
    if 'address' not in order_cols:
        c.execute("ALTER TABLE orders ADD COLUMN address TEXT DEFAULT ''")
    
    c.execute('SELECT count(*) FROM products')
    if c.fetchone()[0] == 0:
        import urllib.parse
        products = [
            ("Arduino Uno R3", "Microcontrollers", 250.0, 120, "🧠", "Robu.in", 4.8, "https://robu.in/product/arduino-uno-r3-ch340g/", "The standard microcontroller board based on the ATmega328P. It has 14 digital input/output pins, 6 analog inputs, a 16 MHz ceramic resonator, a USB connection, and a power jack."),
            ("ESP32 Development Board", "Microcontrollers", 280.0, 85, "📡", "Robocraze", 4.9, "https://robocraze.com/products/esp32-development-board", "A powerful Wi-Fi and Bluetooth system-on-chip microcontroller, ideal for Internet of Things (IoT) projects and smart home automation applications."),
            ("Raspberry Pi 4 Model B (4GB)", "Microcontrollers", 3200.0, 15, "🍓", "Silverline", 4.9, "https://www.silverlineelectronics.in/", "A high-performance single-board computer featuring a 64-bit quad-core processor, dual-display support at resolutions up to 4K, hardware video decode, and dual-band wireless LAN."),
            ("Arduino Nano V3.0", "Microcontrollers", 180.0, 200, "💎", "Robu.in", 4.7, "https://robu.in/product/arduino-nano-v3-0/", "A small, complete, and breadboard-friendly microcontroller board based on the ATmega328. It offers similar functionality to the Arduino Uno but in a compact form factor."),
            ("ESP8266 NodeMCU CP2102", "Microcontrollers", 150.0, 150, "🌐", "Robocraze", 4.6, "https://robocraze.com/products/nodemcu-esp8266", "An open-source firmware and development kit that helps you to prototype your IoT product. Powered by the ESP8266 Wi-Fi chip and CP2102 USB-to-UART bridge."),
            ("Ultrasonic Sensor HC-SR04", "Sensors", 45.0, 300, "🦇", "Robu.in", 4.8, "https://robu.in/product/hc-sr04/", "An ultrasonic distance sensor providing 2cm to 400cm non-contact measurement functionality with a ranging accuracy that can reach up to 3mm."),
            ("DHT11 Temp & Humidity Sensor", "Sensors", 55.0, 250, "🌡️", "Robocraze", 4.5, "https://robocraze.com/products/dht11", "A basic, ultra low-cost digital temperature and humidity sensor. It uses a capacitive humidity sensor and a thermistor to measure the surrounding air."),
            ("PIR Motion Sensor HC-SR501", "Sensors", 60.0, 180, "🚶", "Robu.in", 4.7, "https://robu.in/product/hc-sr501/", "A passive infrared sensor which allows you to sense motion. Ideal for security systems, automated lighting, and interactive installations."),
            ("MPU6050 Gyro & Accelerometer", "Sensors", 90.0, 120, "🎯", "Robu.in", 4.8, "https://robu.in/product/mpu-6050/", "A 6-axis MotionTracking device that combines a 3-axis gyroscope, 3-axis accelerometer, and a Digital Motion Processor into a single small package."),
            ("Soil Moisture Sensor", "Sensors", 35.0, 400, "🌱", "Robocraze", 4.4, "https://robocraze.com/products/soil-moisture-sensor", "A simple water sensor that can be used to detect soil moisture. It outputs an analog voltage proportional to the volumetric water content of the soil."),
        ]
        
        # Transform the emojis into realistic AI image URLs before inserting!
        processed_products = []
        for p in products:
            safe_name = p[0].replace(' ', '_').replace('&', 'and').replace('/', '_').replace('(', '').replace(')', '')
            img_url = f"/images/{safe_name}.jpg"
            processed_products.append((p[0], p[1], p[2], p[3], img_url, p[5], p[6], p[7], p[8]))
            
        c.executemany('INSERT INTO products (name, category, price, stock, image, source, rating, source_url, description) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', processed_products)
    conn.commit()
    conn.close()

class Handler(http.server.SimpleHTTPRequestHandler):
    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        try:
            if self.path == '/api/products':
                conn = sqlite3.connect(DB_FILE)
                conn.row_factory = sqlite3.Row
                rows = conn.execute('SELECT * FROM products').fetchall()
                conn.close()
                return self.send_json([dict(r) for r in rows])
            elif self.path == '/api/users':
                conn = sqlite3.connect(DB_FILE)
                conn.row_factory = sqlite3.Row
                rows = conn.execute('SELECT * FROM users').fetchall()
                conn.close()
                return self.send_json([dict(r) for r in rows])
            elif self.path == '/api/orders':
                conn = sqlite3.connect(DB_FILE)
                conn.row_factory = sqlite3.Row
                rows = conn.execute('SELECT * FROM orders').fetchall()
                orders = []
                for r in rows:
                    d = dict(r)
                    d['items'] = json.loads(d['items'])
                    orders.append(d)
                conn.close()
                return self.send_json(orders)
            else:
                return super().do_GET()
        except Exception as e:
            pass

    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length) if content_length > 0 else b''
            data = json.loads(post_data.decode('utf-8')) if post_data else {}
            conn = sqlite3.connect(DB_FILE)
            if self.path == '/api/products/delete':
                c = conn.cursor()
                c.execute('DELETE FROM products WHERE id = ?', (data['id'],))
                conn.commit()
                conn.close()
                return self.send_json({"success": True})
            elif self.path == '/api/users':
                c = conn.cursor()
                try:
                    c.execute('INSERT INTO users (email, name, pass, role) VALUES (?,?,?,?)',
                              (data['email'], data['name'], data['pass'], data['role']))
                    conn.commit()
                    conn.close()
                    return self.send_json({"success": True})
                except sqlite3.IntegrityError:
                    conn.close()
                    return self.send_json({"error": "User exists"}, 400)
            elif self.path == '/api/orders':
                c = conn.cursor()
                items_str = json.dumps(data['items'])
                c.execute('INSERT INTO orders (id, items, total, stage, userEmail, address) VALUES (?,?,?,?,?,?)',
                          (data['id'], items_str, data['total'], data['stage'], data['userEmail'], data.get('address', 'No address provided')))
                for item in data['items']:
                    c.execute('UPDATE products SET stock = stock - ? WHERE id = ?', (item['qty'], item['id']))
                conn.commit()
                conn.close()
                return self.send_json({"success": True})
            elif self.path == '/api/orders/advance':
                c = conn.cursor()
                c.execute('UPDATE orders SET stage = stage + 1 WHERE id = ?', (data['id'],))
                conn.commit()
                conn.close()
                return self.send_json({"success": True})
            elif self.path == '/api/products':
                c = conn.cursor()
                
                image_url = data.get('image', '')
                if image_url == '' or 'pollinations.ai' in image_url:
                    try:
                        from duckduckgo_search import DDGS
                        import os
                        safe_name = data['name'].replace(' ', '_').replace('&', 'and').replace('/', '_').replace('(', '').replace(')', '')
                        filepath = f"images/{safe_name}.jpg"
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
                return self.send_json({"success": True, "id": new_id})
            elif self.path == '/api/grok':
                try:
                    # Use completely free pollinations.ai API (no auth needed) - defaults to GPT
                    prompt_encoded = urllib.parse.quote(data['prompt'])
                    req = urllib.request.Request(
                        "https://text.pollinations.ai/prompt/" + prompt_encoded + "?json=true&model=openai",
                        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                    )
                    with urllib.request.urlopen(req) as response:
                        res_body = response.read().decode('utf-8')
                            
                    return self.send_json({"result": res_body})
                except Exception as e:
                    err_msg = str(e)
                    if hasattr(e, 'read'):
                        try:
                            err_msg += " Body: " + e.read().decode('utf-8')
                        except Exception:
                            pass
                    return self.send_json({"error": err_msg}, 500)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return self.send_json({"error": "Internal server error: " + str(e)}, 500)

if __name__ == '__main__':
    init_db()
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("", PORT), Handler) as httpd:
        print(f"Serving at http://localhost:{PORT}")
        httpd.serve_forever()
