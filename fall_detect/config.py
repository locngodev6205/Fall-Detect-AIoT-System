import os
from pathlib import Path
from dotenv import load_dotenv

# Base paths
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# --- AI & Model Configuration ---
MODEL_PATH = str(BASE_DIR / "models" / "fall_detection_transformer.tflite")
INPUT_TIMESTEPS = 30
FALL_CONFIDENCE_THRESHOLD = float(os.getenv("FALL_CONFIDENCE_THRESHOLD", 0.85))
FALL_EVENT_COOLDOWN = int(os.getenv("FALL_EVENT_COOLDOWN", 10))  # seconds

# --- Target Audience & Immobility Configuration ---
TARGET_AUDIENCE = os.getenv("TARGET_AUDIENCE", "elderly").lower() # "elderly" hoặc "child"
ENABLE_IMMOBILITY_DETECTION = os.getenv("ENABLE_IMMOBILITY_DETECTION", "true").lower() == "true"
# Ngưỡng bất động: 30s cho trẻ em (tránh ngạt/co giật), 120s cho người già (đột quỵ/bất tỉnh)
IMMOBILITY_TIMEOUT_SECONDS = int(os.getenv("IMMOBILITY_TIMEOUT_SECONDS", 30 if TARGET_AUDIENCE == "child" else 120))

# --- Camera Configuration ---
CAMERA_SOURCE = os.getenv("CAMERA_SOURCE", "0") # 0 for webcam or path to .mp4
FRAME_WIDTH = int(os.getenv("FRAME_WIDTH", 640))
FRAME_HEIGHT = int(os.getenv("FRAME_HEIGHT", 480))
DEVICE_ID = os.getenv("DEVICE_ID", "RASPI_ROOM_101")

# --- MQTT Configuration ---
ENABLE_MQTT = os.getenv("ENABLE_MQTT", "true").lower() == "true"
MQTT_BROKER = os.getenv("MQTT_BROKER", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_TOPIC_FALL_ALERT = os.getenv("MQTT_TOPIC_FALL_ALERT", "smartfall/alerts")
MQTT_TOPIC_STATUS = os.getenv("MQTT_TOPIC_STATUS", "smartfall/status")

# --- Telegram Alert Configuration ---
ENABLE_TELEGRAM = os.getenv("ENABLE_TELEGRAM", "false").lower() == "true"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
