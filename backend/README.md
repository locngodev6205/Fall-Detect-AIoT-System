# SmartFall Backend Service

Backend Server được xây dựng bằng **FastAPI** + **MQTT Subscriber** + **WebSocket**, phục vụ việc:
1. Lắng nghe cảnh báo té ngã từ các Raspberry Pi qua MQTT topic `smartfall/alerts`.
2. Đẩy thông báo thời gian thực đến Web Dashboard qua kết nối `WebSocket` (`/ws/alerts`).
3. Cung cấp RESTful API cho ứng dụng Web (`/api/alerts`).

## Cài đặt & Chạy:
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Chạy server
cd src
python main.py
```
* Swagger API Documentation: `http://localhost:8000/docs`
* Endpoint WebSocket: `ws://localhost:8000/ws/alerts`
