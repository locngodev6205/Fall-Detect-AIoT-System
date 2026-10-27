# Kiến Trúc Hệ Thống Fall-Detect-AIoT-System

## Sơ đồ Khối Tổng Thể (System Architecture)

```
[ Camera / Video Input ] 
       │
       │ (1. Trích xuất 17 khớp xương - MediaPipe BlazePose)
       │ (2. Phân loại chuỗi 30 frames - TFLite Transformer)
       ▼
 [ Module fall_detect ] 
       │
       ├─────────────────────────────────────────┐
       │ (Giao thức MQTT: smartfall/alerts)       │ (Cảnh báo phụ)
       ▼                                         ▼
[ Mosquitto MQTT Broker ]               [ Telegram Bot Alert ]
       │
       ▼
[ Backend Server (FastAPI) ]
       │
       │ (WebSocket Realtime Push: /ws/alerts)
       ▼
[ Frontend Web Dashboard ]
  (Bật còi, Popup khẩn cấp, Ghi log)
```

## Các luồng dữ liệu chính:
1. **Model Inference (`fall_detect`):**
   * Video stream $\rightarrow$ MediaPipe Pose $\rightarrow$ Vector đặc trưng $(1, 30, 51)$ $\rightarrow$ `fall_detection_transformer.tflite`.
   * Khi $P(\text{Fall}) \ge 0.85$ và vượt qua thời gian Cooldown: kích hoạt sự kiện.
2. **Truyền tin IoT (MQTT):**
   * `fall_detect` publish payload lên topic `smartfall/alerts`.
   * Gói tin JSON:
     ```json
     {
       "device_id": "RASPI_ROOM_101",
       "event": "FALL_DETECTED",
       "confidence": 0.9558,
       "confidence_pct": "95.58%",
       "timestamp": "2026-10-27T15:03:50Z",
       "local_time": "2026-10-27 15:03:50"
     }
     ```
3. **Phân phối cảnh báo (Backend & Web):**
   * Backend nhận tin nhắn từ MQTT, lưu vào cơ sở dữ liệu nhật ký sự cố.
   * Đồng thời broadcast ngay lập tức qua WebSocket đến toàn bộ trình duyệt Web đang mở.
