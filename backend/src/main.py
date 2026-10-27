import os
import json
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(
    title="Fall-Detect AIoT Backend API",
    description="Backend Server quản lý thiết bị Raspberry Pi và nhận cảnh báo té ngã thời gian thực.",
    version="1.0.0"
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage for active WebSocket clients
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()

# In-memory fall alerts log (can be swapped for SQLite / PostgreSQL)
alerts_history = []

@app.get("/")
def health_check():
    return {"status": "online", "system": "Fall-Detect AIoT Backend"}

@app.get("/api/alerts")
def get_alerts():
    return {"total": len(alerts_history), "alerts": alerts_history[::-1]}

@app.post("/api/alerts/mock")
async def trigger_mock_alert():
    """API giả lập một sự kiện té ngã để test Web Dashboard."""
    event = {
        "device_id": "RASPI_ROOM_101",
        "event": "FALL_DETECTED",
        "confidence": 0.95,
        "confidence_pct": "95.00%",
        "timestamp": "2026-10-27T15:00:00Z",
        "local_time": "2026-10-27 15:00:00"
    }
    alerts_history.append(event)
    await manager.broadcast(event)
    return {"message": "Mock alert broadcasted", "data": event}

@app.websocket("/ws/alerts")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint để Web Dashboard kết nối và nhận cảnh báo khẩn cấp tức thì."""
    await manager.connect(websocket)
    try:
        while True:
            # Keep alive
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# Background MQTT Handler
def start_mqtt_client():
    try:
        import paho.mqtt.client as mqtt
        broker = os.getenv("MQTT_BROKER", "127.0.0.1")
        port = int(os.getenv("MQTT_PORT", 1883))
        topic = os.getenv("MQTT_TOPIC_FALL_ALERT", "smartfall/alerts")

        def on_connect(client, userdata, flags, rc):
            print(f"[*] Backend connected to MQTT Broker ({broker}:{port}) with result code {rc}")
            client.subscribe(topic)

        def on_message(client, userdata, msg):
            try:
                payload = json.loads(msg.payload.decode())
                print(f"[🚨 CẢNH BÁO TỪ RASPBERRY PI] {payload}")
                alerts_history.append(payload)
                # Broadcast via async event loop
                asyncio.run(manager.broadcast(payload))
            except Exception as e:
                print(f"[!] Lỗi phân tích gói tin MQTT: {e}")

        client = mqtt.Client(client_id="SmartFall_Backend_Subscriber")
        client.on_connect = on_connect
        client.on_message = on_message
        client.connect_async(broker, port, keepalive=60)
        client.loop_start()
    except Exception as e:
        print(f"[!] Không thể khởi động MQTT Client: {e}")

@app.on_event("startup")
async def startup_event():
    start_mqtt_client()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
