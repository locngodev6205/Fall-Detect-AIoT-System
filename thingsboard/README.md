# Hướng Dẫn Kết Nối Raspberry Pi Với ThingsBoard (Fall-Detect-AIoT-System)

## 1. Sơ Đồ Kiến Trúc Tích Hợp

```text
Raspberry Pi (detect.py + modules/notifier.py)
  │  MQTT, cổng 1883, xác thực bằng Access Token (smartfall_pi4_token_101)
  │  - Telemetry: v1/devices/me/telemetry (fps, fall_prob, immobile_seconds, ai_state, cpu_temp, event)
  │  - Attributes: v1/devices/me/attributes
  │  - 2-Way RPC:  v1/devices/me/rpc/request/+
  ▼
ThingsBoard (Docker container: smartface_thingsboard - cổng Web 8080, MQTT 1883)
  │  Device Profile: SmartFall_Profile ──► SmartFall Rule Chain (Độc lập với SmartFace)
  │  Rule Node: Check Fall or Immobility Alert ──► REST API Call Webhook
  ▼
FastAPI Backend :8000 (/api/tb-webhook)  ──►  Web Dashboard (WebSocket /ws/alerts)
```

> **Lưu ý quan trọng:** Hệ thống tái sử dụng trực tiếp container `smartface_thingsboard` đang chạy ở cổng `8080` (Web UI) và `1883` (MQTT). Nhờ cơ chế **Device Profile (`SmartFall_Profile`)** gắn riêng vào **`SmartFall Rule Chain`**, dữ liệu và luồng xử lý của thiết bị nhận diện té ngã hoàn toàn tách biệt, không ảnh hưởng tới thiết bị điểm danh `PI4_FRONT_GATE` của dự án SmartFace.

---

## 2. Thông Tin Đã Được Cấu Hình Sẵn Trên ThingsBoard

Script [`setup_thingsboard.py`](file:///mnt/windows/Users/62205/Documents/locngo/school/7th-semester/Công%20nghệ%20IOT/Fall-Detect-AIoT-System/thingsboard/setup_thingsboard.py) đã tự động khởi tạo đầy đủ trên ThingsBoard (`http://127.0.0.1:8080`, tài khoản `tenant@thingsboard.org` / `tenant`):

| Thành phần | Giá trị / Tên trên ThingsBoard | Mô tả |
| :--- | :--- | :--- |
| **Device Name** | `RASPI_ROOM_101` | Thiết bị biên Raspberry Pi phòng giám sát 101 |
| **Access Token** | `smartfall_pi4_token_101` | Token xác thực MQTT cho Pi |
| **Device Profile** | `SmartFall_Profile` | Định tuyến riêng toàn bộ bản tin sang `SmartFall Rule Chain` |
| **Rule Chain** | `SmartFall Rule Chain` | Lưu Telemetry, Attributes, xử lý RPC và gọi Webhook tới Backend `:8000` |
| **Dashboard** | `SmartFall AIoT Monitor` | Giao diện theo dõi FPS, biểu đồ $P(\text{Fall})$, thời gian bất động và công tắc RPC |

Các file cấu hình đã xuất sẵn trong thư mục này:
- [`smartfall_rule_chain.json`](file:///mnt/windows/Users/62205/Documents/locngo/school/7th-semester/Công%20nghệ%20IOT/Fall-Detect-AIoT-System/thingsboard/smartfall_rule_chain.json)
- [`smartfall_dashboard.json`](file:///mnt/windows/Users/62205/Documents/locngo/school/7th-semester/Công%20nghệ%20IOT/Fall-Detect-AIoT-System/thingsboard/smartfall_dashboard.json)

Nếu cần chạy lại tự động cấu hình bất kỳ lúc nào:
```bash
python3 thingsboard/setup_thingsboard.py
```

---

## 3. Cấu Hình Trên Raspberry Pi (`fall_detect/.env`)

Trên Raspberry Pi (cùng mạng Wi-Fi / LAN với máy chạy Docker ThingsBoard), chỉnh file `fall_detect/.env`:

```env
DEVICE_ID=RASPI_ROOM_101
TARGET_AUDIENCE=elderly

FALL_CONFIDENCE_THRESHOLD=0.85
FALL_EVENT_COOLDOWN=10
ENABLE_IMMOBILITY_DETECTION=true
IMMOBILITY_TIMEOUT_SECONDS=120

# Địa chỉ IP LAN của máy Server đang chạy Docker ThingsBoard
ENABLE_MQTT=true
TB_HOST=192.168.1.14
TB_PORT=1883
TB_TOKEN=smartfall_pi4_token_101
TELEMETRY_INTERVAL=2.0
```

Sau đó chạy trên Pi:
```bash
python detect.py --source file --file sample_videos/fall_example_2.mp4 --no-display
# Hoặc chạy với camera thực tế:
python detect.py --source webcam --no-display
```

Khi kết nối thành công, Pi sẽ in ra:
```text
[MQTT] Đã kết nối thành công tới ThingsBoard Broker (192.168.1.14:1883)
[ThingsBoard] Đã đồng bộ cấu hình từ xa: {'target_audience': 'elderly', 'fall_confidence_threshold': 0.85, ...}
```
Và dữ liệu sẽ nhảy trực tiếp theo thời gian thực trên Dashboard **`SmartFall AIoT Monitor`** tại `http://127.0.0.1:8080`.
