# Hướng Dẫn Đấu Nối Phần Cứng (Pinout) & Tổng Kết Triển Khai AnNhà AIoT

Tài liệu này tổng hợp đầy đủ **8 nhóm tính năng đã hoàn thiện**, **sơ đồ cắm chân phần cứng chi tiết (Pinout)** giữa **Raspberry Pi 4 + Arduino Uno/Nano + DHT11 + MQ-2 + 2 Servo Pan-Tilt + Loa Bluetooth**, cùng **hướng dẫn nạp code và vận hành thực tế**.

---

## 1. Tổng Kết Các Tính Năng Đã Hoàn Thiện

| STT | Nhóm tính năng | Mô tả chi tiết đã triển khai | Thành phần chính |
| :-: | :--- | :--- | :--- |
| **1** | **Thêm & Ghép nối thiết bị Pi 4** | Tạo mã ghép nối 1 lần từ CLI (`new_device.sh`), nhập mã trên giao diện Web `#/setup`, quản lý trạng thái kết nối và thu hồi thiết bị tại `#/devices`. | `scripts/new_device.sh`, `HomeScreens.jsx` |
| **2** | **Cầu nối Cảm biến Arduino USB Serial & Dual-Pipeline Telemetry** | Arduino đọc đồng thời nhiệt độ/độ ẩm **DHT11** và khí gas **MQ-2** mỗi `2 giây` (có đánh dấu sấy nóng `gas_warmup` 20s đầu), gửi JSON qua cổng USB `115200 baud` lên Pi 4 để đẩy về Web AnNhà (`POST /api/device/telemetry`) và tùy chọn song song lên **ThingsBoard MQTT**. | `annha_node.ino`, `arduino_bridge.py`, `device_client.py` |
| **3** | **Tự động Xoay 2 Servo Pan-Tilt Bám Theo Người (AI Pose Tracking)** | Trích xuất tâm thân người `(cx, cy)` từ MediaPipe Pose, điều khiển tỷ lệ mượt (có vùng chết chống rung, lọc EMA, tự ngắt xung PWM sau `800ms` đứng yên). | `pan_tilt_tracker.py`, `annha_node.ino` |
| **4** | **Bàn phím Xoay Camera PTZ Thủ công trên Web UI** | Tích hợp cụm phím điều hướng 5 nút (**Lên / Xuống / Trái / Phải / Giữa 90°**) kèm chọn bước xoay (`5° / 10° / 15°`) ngay trong trang Chi tiết Camera (`#/camera/:id`). | `HomeScreens.jsx`, `live.css`, `models.py`, `api.py` |
| **5** | **Công tắc Chế độ AI Thông minh trên Web UI** | Cho phép bật/tắt tức thời **Phát hiện té ngã AI** và **Tự động xoay Servo bám người** từ Web; tự động đồng bộ xuống Pi 4 qua cơ chế `desired_version / applied_version` và ngắt xung PWM khi tắt bám người. | `HomeScreens.jsx`, `services.py`, `api.py`, `pan_tilt_tracker.py` |
| **6** | **Còi Báo động Độc lập Tại chỗ qua Loa Bluetooth Chuyên dụng** | Khi phát hiện **Té ngã** hoặc **Rò rỉ khí Gas (`gas >= gas_high`)**, Pi 4 lập tức hú còi khẩn cấp `100%` âm lượng + đọc cảnh báo tiếng Việt qua **Loa Bluetooth** ngay tại phòng (kể cả khi mất mạng Internet). Tuyệt đối không đẩy âm thanh ra cổng 3.5mm/HDMI nếu loa Bluetooth mất kết nối. Cảnh báo khí gas không bao giờ bị tắt bởi lệnh `silence`. | `bluetooth_manager.py`, `audio_player.py`, `main_edge.py` |
| **7** | **Chế độ Ban đêm Yên tĩnh (`22:00 – 06:00`)** | Tự động khóa và ngắt xung PWM 2 động cơ Servo (`0 tiếng ồn` trong phòng ngủ), đồng thời tạm hoãn các lời nhắc sinh hoạt thường (`status="skipped"`), nhưng vẫn **giữ nguyên 100% còi báo động khẩn cấp** khi té ngã hoặc rò khí gas. | `pan_tilt_tracker.py`, `scheduler.py`, `HomeScreens.jsx` |
| **8** | **Lịch nhắc Sinh hoạt Offline, Live Stream JPEG & Đàm thoại 1 chiều** | Tải trước file âm thanh lịch nhắc về bộ nhớ đệm `edge_cache/` để phát đúng giờ kể cả khi rớt mạng; truyền hình ảnh trực tiếp `/ws/device/frames` và nhận giọng nói trực tiếp từ người thân qua `/ws/device/audio` (Push-to-Talk). | `scheduler.py`, `live_streamer.py`, `LiveAudio.jsx` |

---

## 2. Sơ Đồ Đấu Nối Chân Phần Cứng (Pinout Chi Tiết)

### 2.1. Kiến trúc tổng thể

```text
                       Cáp USB (Serial 115200 baud + Cấp nguồn 5V cho mạch & cảm biến)
┌────────────────────┐ ══════════════════════════════════════════════════════════════► ┌──────────────────────────┐
│  RASPBERRY PI 4    │                                                                 │  ARDUINO UNO / NANO      │
│  (Edge AI & Audio) │                                                                 │  (ATmega328P Node)       │
│                    │                                                                 │                          │
│ • Camera USB / CSI │                                                                 │ • Chân D2  ───► DHT11    │
│ • Bluetooth 5.0 ───┼───(( Sóng Bluetooth A2DP ))───► [ LOA BLUETOOTH PHÒNG ]         │ • Chân A0  ───► MQ-2     │
│ • Wi-Fi / LAN   ───┼───► Backend & Web UI AnNhà (:8188)                              │ • Chân D9  ───► Servo Pan│
└────────────────────┘                                                                 │ • Chân D10 ───► ServoTilt│
                                                                                       └────────────┬─────────────┘
                                                                                                    │ GND chung!
                                                                                       ┌────────────┴─────────────┐
                                                                                       │ NGUỒN NGOÀI 5V (≥ 2A)    │
                                                                                       │ Cấp riêng VCC cho 2 Servo│
                                                                                       └──────────────────────────┘
```

### 2.2. Bảng cắm chân chi tiết trên Arduino Uno / Nano (`ATmega328P`)

> **⚠️ LƯU Ý AN TOÀN NGUỒN ĐIỆN QUAN TRỌNG:**
> - Cảm biến **DHT11** và **MQ-2** có thể lấy nguồn `5V` trực tiếp từ chân `5V` trên Arduino.
> - **2 Động cơ Servo (SG90 / MG90S)** khi khởi động đồng thời có dòng đỉnh `0.8A – 1.5A`. Để tránh sụt áp làm treo cổng USB của Raspberry Pi 4 hoặc làm sai số đọc ADC của cảm biến MQ-2, **khuyến nghị cấp nguồn `5V ≥ 2A` ngoài cho dây Đỏ (`VCC`) của 2 Servo**, và **BẮT BUỘC nối chung dây `GND` của nguồn ngoài với chân `GND` của Arduino** (`Common Ground`).

| Linh kiện | Chân trên linh kiện | Chân cắm trên Arduino Uno / Nano | Ghi chú kỹ thuật |
| :--- | :--- | :---: | :--- |
| **Cảm biến Nhiệt ẩm DHT11** | `VCC` (`+`) | **`5V`** | Nếu dùng module 3 chân có sẵn trở kéo lên thì cắm thẳng; nếu dùng DHT11 4 chân rời thì nối thêm điện trở `4.7kΩ – 10kΩ` giữa `VCC` và `DATA`. |
| **Cảm biến Nhiệt ẩm DHT11** | `DATA` (`OUT` / `S`) | **`D2`** (Digital Pin 2) | Đọc định kỳ không chặn mỗi `2000 ms`. |
| **Cảm biến Nhiệt ẩm DHT11** | `GND` (`-`) | **`GND`** | Mass chung với Arduino. |
| **Cảm biến Khí Gas MQ-2** | `VCC` | **`5V`** | Cần cấp điện liên tục; 20 giây đầu mới bật mạch tự gán nhãn `warming_up`. |
| **Cảm biến Khí Gas MQ-2** | `A0` (`AO` - Analog Out) | **`A0`** (Analog Pin 0) | **Bắt buộc cắm chân `AO` (Analog)** để đọc dải `0 – 1023 ADC` (không dùng chân `DO` Digital). |
| **Cảm biến Khí Gas MQ-2** | `GND` | **`GND`** | Mass chung với Arduino. |
| **Servo 1 — Trục Ngang (PAN)** | Dây Tín hiệu (Cam / Vàng) | **`D9`** (PWM Pin 9) | Xoay trái / phải. Khởi tạo mặc định **`90°`**, giới hạn an toàn **`30° – 150°`**. |
| **Servo 1 — Trục Ngang (PAN)** | Dây Nguồn `+` (Đỏ) | **`+5V Nguồn ngoài`** | Nguồn 5V dòng ≥ 2A (hoặc `5V` Arduino nếu chỉ test không tải nhẹ với SG90). |
| **Servo 1 — Trục Ngang (PAN)** | Dây Mass `-` (Nâu / Đen) | **`GND chung`** | Nối chung `GND` nguồn ngoài và `GND` Arduino. |
| **Servo 2 — Trục Dọc (TILT)** | Dây Tín hiệu (Cam / Vàng) | **`D10`** (PWM Pin 10) | Ngẩng lên / cúi xuống. Khởi tạo mặc định **`90°`**, giới hạn an toàn **`45° – 135°`**. |
| **Servo 2 — Trục Dọc (TILT)** | Dây Nguồn `+` (Đỏ) | **`+5V Nguồn ngoài`** | Dùng chung nguồn ngoài 5V ≥ 2A với Servo Pan. |
| **Servo 2 — Trục Dọc (TILT)** | Dây Mass `-` (Nâu / Đen) | **`GND chung`** | Nối chung `GND` nguồn ngoài và `GND` Arduino. |

### 2.3. Thông số Góc Khởi Tạo & Phạm Vi Quay An Toàn Của 2 Servo

Cấu hình nằm tại `firmware/arduino/annha_node/config.h` và đồng bộ hoàn toàn với `fall_detect/edge/sensors/arduino_bridge.py`:

| Trục Servo | Chân Arduino | Góc mặc định khi khởi động | Phạm vi quay cho phép | Tốc độ bước mượt | Cơ chế chống rung / chống ồn |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **PAN (Quay ngang)** | `D9` | **`90°`** (Chính diện) | **`30° → 150°`** (Biên độ `120°`) | `1° / 15ms` (`~66°/s`) | Lazy-Attach: Chỉ cấp PWM khi có lệnh quay; tự động `detach()` sau **`800 ms`** đứng yên. |
| **TILT (Gật dọc)** | `D10` | **`90°`** (Ngang tầm mắt) | **`45° → 135°`** (Biên độ `90°`) | `1° / 15ms` (`~66°/s`) | Tự khóa & `detach()` hoàn toàn khi tắt công tắc Tracking hoặc trong Chế độ ban đêm (`22:00–06:00`). |

> **Hiệu chỉnh chiều lắp gá (`PAN_DIRECTION` / `TILT_DIRECTION`)**:
> Mặc định `PAN_DIRECTION = -1` và `TILT_DIRECTION = 1` (theo đúng bộ gá thực tế `CameraPanTilt`). Nếu bạn lắp ngược chiều Servo, chỉ cần đổi dấu `-1` / `1` trong file `.env.edge` mà không cần tháo lắp lại phần cứng.

### 2.4. Kết nối Phụ kiện trên Raspberry Pi 4

| Thiết bị ngoại vi | Cổng kết nối trên Raspberry Pi 4 | Ghi chú |
| :--- | :--- | :--- |
| **Arduino Uno / Nano** | Cổng **USB 2.0** bất kỳ (`/dev/ttyUSB0` hoặc `/dev/ttyACM0`) | Tự động nhận diện qua `ARDUINO_SERIAL_PORT=auto`, tự kết nối lại nếu rút/cắm cáp. |
| **Webcam USB / Pi Camera** | Cổng **USB 3.0** (Webcam) hoặc cáp dẹt **CSI** | Mặc định `CAMERA_ID=0` (`640x480`). |
| **Loa Bluetooth** | Kết nối không dây **Bluetooth 5.0 tích hợp trên Pi 4** | **Bắt buộc dùng Loa Bluetooth** (hệ thống chủ động chặn cổng 3.5mm/HDMI để đảm bảo âm thanh phát đúng tại loa đặt trong phòng người cao tuổi). |

---

## 3. Hướng Dẫn Nạp Firmware, Ghép Nối & Khởi Chạy

### Bước 1: Nạp chương trình cho Arduino Uno / Nano
Bạn có thể nạp `firmware/arduino/annha_node/annha_node.ino` theo 1 trong 2 cách:
- **Cách A — Trực tiếp trên Raspberry Pi 4 qua dòng lệnh**:
  ```bash
  cd Fall-Detect-AIoT-System
  ./scripts/install_arduino_tools.sh --compile --upload --port /dev/ttyUSB0 --board nano
  # Hoặc nếu dùng Arduino Uno hoặc Nano bootloader cũ:
  # ./scripts/install_arduino_tools.sh --compile --upload --port /dev/ttyACM0 --board uno
  # ./scripts/install_arduino_tools.sh --compile --upload --port /dev/ttyUSB0 --board nano-old
  ```
- **Cách B — Trên máy tính bằng Arduino IDE / PlatformIO**:
  Mở `firmware/arduino/annha_node/annha_node.ino`, cài thư viện `Servo` và `DHT sensor library` (Adafruit), chọn đúng Board & Port rồi bấm **Upload**.

### Bước 2: Ghép nối Loa Bluetooth trên Raspberry Pi 4
```bash
bluetoothctl
# Trong dấu nhắc bluetoothctl:
power on
scan on
# Đợi hiện địa chỉ MAC của loa (ví dụ AA:BB:CC:11:22:33), sau đó chạy:
pair AA:BB:CC:11:22:33
trust AA:BB:CC:11:22:33
connect AA:BB:CC:11:22:33
exit
```
Điền địa chỉ `BT_SPEAKER_MAC=AA:BB:CC:11:22:33` vào file `fall_detect/.env.edge` để Pi 4 tự động kết nối lại mỗi khi bật loa.

### Bước 3: Khởi chạy Server Web AnNhà & Tạo Mã Ghép Nối Thiết Bị
Trên máy chủ chạy Docker:
```bash
cd Fall-Detect-AIoT-System
docker compose up -d --build

# Cấp phát thiết bị Pi 4 mới (lấy PAIRING_CODE và DEVICE_TOKEN):
./scripts/new_device.sh "Pi 4 Phòng ngủ"
```
1. Mở trình duyệt tại `http://localhost:8188` -> vào mục **Thêm thiết bị (`#/setup`)**.
2. Nhập **Mã ghép nối (`PAIRING_CODE`)**, đặt tên thiết bị và chọn phòng để hoàn tất nhận thiết bị vào nhà.

### Bước 4: Cấu hình `.env.edge` & Chạy Thiết Bị Biên Pi 4
Trên Raspberry Pi 4 (hoặc chạy thử ngay trên máy tính):
```bash
cd Fall-Detect-AIoT-System/fall_detect
cp .env.edge.example .env.edge
# Cập nhật ANNHA_BASE_URL=http://<IP_LAN_SERVER>:8188 và DEVICE_TOKEN=<token_vừa_cấp>

# Cài đặt thư viện Python:
pip install -r requirements.txt

# Khởi chạy toàn bộ hệ thống biên hợp nhất:
python3 -m edge.main_edge --env-file .env.edge

# (Tùy chọn) Chạy thử chế độ giả lập phần cứng trên máy tính:
python3 -m edge.main_edge --env-file .env.edge --mock
```

---

## 4. Danh Sách Các Tệp Đã Tạo Mới & Cập Nhật

### Phần cứng & Firmware Arduino
- `firmware/arduino/annha_node/config.h` — Cấu hình chân cắm (`D2, A0, D9, D10`), góc giới hạn an toàn, chu kỳ đo & sấy nóng MQ-2.
- `firmware/arduino/annha_node/annha_node.ino` — Firmware đa nhiệm không chặn (DHT11 + MQ-2 + 2 Servo Lazy-Attach).
- `firmware/arduino/annha_node/platformio.ini` & `README.md` — Cấu hình biên dịch tự động cho Uno / Nano.
- `scripts/install_arduino_tools.sh` — Script cài `arduino-cli`, thư viện và biên dịch/nạp code trực tiếp từ Pi 4.
- `scripts/new_device.sh` — Script cấp phát nhanh `DEVICE_TOKEN` & `PAIRING_CODE` cho Pi 4 mới.

### Hệ thống Biên Raspberry Pi 4 (`fall_detect/edge/`)
- `fall_detect/edge/sensors/arduino_bridge.py` & `mock_sensors.py` — Cầu nối USB Serial tự động dò cổng, tự chuyển Mock & kết nối lại nóng.
- `fall_detect/edge/client/device_client.py` — Đồng bộ Heartbeat, Config ACK, Dual-Pipeline Telemetry (AnNhà REST + ThingsBoard MQTT), Upload bằng chứng JPEG, hàng đợi Offline Outbox.
- `fall_detect/edge/client/live_streamer.py` — Truyền khung hình trực tiếp `/ws/device/frames` & nhận giọng nói `/ws/device/audio`.
- `fall_detect/edge/tracking/pan_tilt_tracker.py` — Điều khiển Servo bám người theo khớp xương AI, PTZ thủ công & khóa động cơ ban đêm.
- `fall_detect/edge/audio/bluetooth_manager.py` — Quản lý `bluetoothctl` & khóa cứng đầu ra Loa Bluetooth (`wpctl`/`pactl`).
- `fall_detect/edge/audio/audio_player.py` — Tổng hợp còi báo động khẩn cấp `.wav`, đọc cảnh báo tiếng Việt, ưu tiên còi khí gas không thể tắt nhầm.
- `fall_detect/edge/audio/scheduler.py` — Bộ lập lịch nhắc nhở Offline lưu vết chống lặp & tự tạm hoãn trong Chế độ ban đêm.
- `fall_detect/edge/main_edge.py` & `fall_detect/.env.edge.example` — Trình điều phối đa luồng hợp nhất toàn bộ thiết bị biên.

### Backend, Giao diện Web & Bộ Kiểm thử Tự động
- `backend/src/models.py`, `backend/src/services.py`, `backend/src/api.py`, `backend/src/pgservices.py`, `backend/src/pgapi.py` — Bổ sung lệnh điều khiển `ptz_move` / `ptz_center`, cấu hình `SmartModes` đồng bộ phiên bản tự động, và các API tổng hợp môi trường.
- `frontend/src/HomeScreens.jsx` & `frontend/src/live.css` — Bổ sung cụm điều khiển góc quay **PTZ D-Pad**, công tắc **Chế độ AI & Ban đêm**, và đàm thoại trực tiếp trên trang Chi tiết Camera.
- `fall_detect/tests/test_group1_sensors.py` → `test_group5_main_edge.py` — **15 bài kiểm thử đơn vị & tích hợp toàn trình E2E**.
