import smbus2
import time
from datetime import datetime
from BlynkLib import Blynk
import RPi.GPIO as GPIO
import os
from flask import Flask, send_from_directory, jsonify, render_template_string
import threading

# Blynk configuration
BLYNK_TEMPLATE_ID = "TMPL2HJv4qbjL"
BLYNK_TEMPLATE_NAME = "WCM Project"
BLYNK_AUTH_TOKEN = "rCcypOT9NC9kl_3MTzZXHXkvP2i2G-Bo"
blynk = Blynk(BLYNK_AUTH_TOKEN, server='blynk.cloud', port=80)

# GPIO setup
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
PUMP_PIN = 26
GPIO.setup(PUMP_PIN, GPIO.OUT)
GPIO.output(PUMP_PIN, GPIO.LOW)

# I2C bus and ADC address
ADS7830_ADDRESS = 0x4B
bus = smbus2.SMBus(1)

# Flask configuration
PORT = 8000
app = Flask(__name__)
IMAGE_DIR = "/home/pi/images"

# Global variables
manual_control = False
pump_state = False

# HTML template for the image gallery
GALLERY_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Image Gallery</title>
    <style>
        body { font-family: Arial, sans-serif; }
        .gallery { display: flex; flex-wrap: wrap; gap: 20px; }
        .gallery img { max-width: 200px; height: auto; }
        .gallery div { text-align: center; }
    </style>
</head>
<body>
    <h2>Image Gallery</h2>
    <div class="gallery">
        {% for image in images %}
        <div>
            <img src="{{ image.url }}" alt="{{ image.name }}">
            <p>{{ image.name }}</p>
        </div>
        {% endfor %}
    </div>
</body>
</html>
"""

# Flask routes
@app.route('/')
def gallery():
    images = [{'name': img, 'url': f"/images/{img}"} for img in os.listdir(IMAGE_DIR) if img.endswith(".jpg")]
    return render_template_string(GALLERY_TEMPLATE, images=images)

@app.route('/recent.jpg')
def recent_image():
    return send_from_directory(IMAGE_DIR, 'recent.jpg')

@app.route('/images/<filename>')
def serve_image(filename):
    return send_from_directory(IMAGE_DIR, filename)

@app.route('/list_images')
def list_images():
    images = [img for img in os.listdir(IMAGE_DIR) if img.endswith(".jpg")]
    return jsonify({"images": images})

# Start Flask server in a separate thread
def start_flask_server():
    app.run(host='0.0.0.0', port=PORT)

server_thread = threading.Thread(target=start_flask_server)
server_thread.daemon = True
server_thread.start()

# Ensure the image directory exists
if not os.path.exists(IMAGE_DIR):
    os.makedirs(IMAGE_DIR)

# ADC functions
def read_adc(channel):
    if channel < 0 or channel > 7:
        return -1
    command = 0x84 | (channel << 4)
    bus.write_byte(ADS7830_ADDRESS, command)
    return bus.read_byte(ADS7830_ADDRESS)

def map_to_scale(value, in_min, in_max, out_min, out_max):
    return (((value - in_min) * (out_max - out_min)) / (in_max - in_min)) + out_min

def read_average(channel, num_samples=10):
    total = 0
    for _ in range(num_samples):
        total += read_adc(channel)
        time.sleep(0.05)
    return total // num_samples

# Image capture function
def capture_image(event):
    timestamp = datetime.now().strftime("%d%m%Y%H%M%S")
    recent_image_path = f"{IMAGE_DIR}/recent.jpg"
    timestamped_image_path = f"{IMAGE_DIR}/{timestamp}_{event}.jpg"
    os.system(f"fswebcam -r 640x480 --no-banner {recent_image_path}")
    os.system(f"convert {recent_image_path} -resize 800x600 {recent_image_path}")
    os.system(f"cp {recent_image_path} {timestamped_image_path}")
    print(f"Captured image: {timestamped_image_path}")
    return recent_image_path

# Pump control function
def control_pump(state):
    global pump_state
    GPIO.output(PUMP_PIN, GPIO.LOW if state else GPIO.HIGH)
    if state != pump_state:
        event = "ON" if state else "OFF"
        recent_image_path = capture_image(event)
        image_url = f"http://192.168.137.70:{PORT}/recent.jpg"
        blynk.virtual_write(2, image_url)
    pump_state = state

# Blynk virtual write handler for manual pump control
@blynk.VIRTUAL_WRITE(1)
def manual_pump_control(value):
    global manual_control
    manual_control = int(value[0])
    control_pump(manual_control)
    print("Manual pump control:", "On" if manual_control else "Off")

# Function to read moisture level and update Blynk
def read_and_update():
    if not manual_control:
        moisture_adc_value = read_average(0)
        moisture_level = map_to_scale(moisture_adc_value, 0, 255, 0, 100)
        print(f"Raw Moisture: {moisture_adc_value}")
        print(f"Moisture Level: {moisture_level:.2f} / 100")
        blynk.virtual_write(0, moisture_level)
        if moisture_level < 30:
            control_pump(True)
            print("Pump turned on")
        else:
            control_pump(False)
            print("Pump turned off")

# Main loop
try:
    while True:
        blynk.run()
        read_and_update()
        time.sleep(2)
except KeyboardInterrupt:
    pass
finally:
    GPIO.cleanup()