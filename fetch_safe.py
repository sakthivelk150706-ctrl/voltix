import os
import urllib.request
from duckduckgo_search import DDGS
import time

products = [
    "LDR Light Sensor Module",
    "IR Obstacle Avoidance Sensor",
    "STM32F103C8T6 Blue Pill",
    "Line Follower Robot Kit",
    "4WD Smart Car Chassis",
    "NEMA 17 Stepper Motor",
    "L298N Motor Driver",
    "SG90 Micro Servo Motor",
    "0.96 inch OLED Display",
    "16x2 LCD with I2C",
    "NEO-6M GPS Module",
    "SIM800L GSM Module",
    "RFID RC522 Reader Kit",
    "Smart Home Automation Kit",
    "Weather Station Pro Kit"
]

os.makedirs('images', exist_ok=True)
ddgs = DDGS()

def download_image(query, filename):
    print(f"Searching for: {query}")
    try:
        # Search for a high-quality product photo
        results = list(ddgs.images(f"{query} electronic component top down white background", max_results=5))
        if not results:
            results = list(ddgs.images(query, max_results=3))
            
        if results:
            for res in results:
                url = res['image']
                try:
                    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
                    with urllib.request.urlopen(req, timeout=5) as response, open(filename, 'wb') as out_file:
                        out_file.write(response.read())
                    print(f"Success: {url}")
                    return True
                except Exception as e:
                    print(f"Failed to download {url}: {e}")
                    continue
    except Exception as e:
        print(f"Search failed for {query}: {e}")
    return False

for p in products:
    safe_name = p.replace(' ', '_').replace('&', 'and').replace('/', '_').replace('(', '').replace(')', '')
    filepath = f"images/{safe_name}.jpg"
    print(f"Fetching {p} safely...")
    download_image(p, filepath)
    time.sleep(5) # 5 seconds delay to prevent rate limit!

print("Finished fetching images safely!")
