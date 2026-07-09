import os
import urllib.request
import json
import time

missing_products = {
    "LDR Light Sensor Module": "Photoresistor",
    "IR Obstacle Avoidance Sensor": "Infrared sensor",
    "STM32F103C8T6 Blue Pill": "STM32",
    "Line Follower Robot Kit": "Mobile robot",
    "4WD Smart Car Chassis": "Robot kinematics",
    "NEMA 17 Stepper Motor": "Stepper motor",
    "L298N Motor Driver": "H-bridge",
    "SG90 Micro Servo Motor": "Servomotor",
    "0.96 inch OLED Display": "OLED",
    "16x2 LCD with I2C": "Liquid-crystal display",
    "NEO-6M GPS Module": "Global Positioning System",
    "SIM800L GSM Module": "GSM",
    "RFID RC522 Reader Kit": "Radio-frequency identification",
    "Smart Home Automation Kit": "Home automation",
    "Weather Station Pro Kit": "Weather station"
}

os.makedirs('images', exist_ok=True)

def fetch_wiki_image(title, filename):
    try:
        url = f"https://en.wikipedia.org/w/api.php?action=query&prop=pageimages&format=json&piprop=original&titles={urllib.parse.quote(title)}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read())
            pages = data.get('query', {}).get('pages', {})
            for page_id, page_info in pages.items():
                if 'original' in page_info:
                    img_url = page_info['original']['source']
                    print(f"Downloading from Wiki: {img_url}")
                    img_req = urllib.request.Request(img_url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(img_req, timeout=5) as img_resp, open(filename, 'wb') as out_file:
                        out_file.write(img_resp.read())
                    return True
    except Exception as e:
        print(f"Failed wiki for {title}: {e}")
    return False

for orig_name, wiki_title in missing_products.items():
    safe_name = orig_name.replace(' ', '_').replace('&', 'and').replace('/', '_').replace('(', '').replace(')', '')
    filepath = f"images/{safe_name}.jpg"
    if not os.path.exists(filepath):
        print(f"Fetching backup for {orig_name}...")
        fetch_wiki_image(wiki_title, filepath)
        time.sleep(1)

print("Finished backup fetch!")
