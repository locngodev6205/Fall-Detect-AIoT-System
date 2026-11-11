# Firmware Arduino AnNhà (`annha_node`)

Mã nguồn nhúng C++ cho **Arduino Nano / Arduino Uno (ATmega328P)** kết nối với **Raspberry Pi 4** qua cáp USB Serial (`115200 baud`).

## 1. Bảng Đấu Nối Chân Cắm (Pinout)

| Linh kiện | Chân linh kiện | Chân trên Arduino Uno/Nano | Ghi chú |
| :--- | :--- | :--- | :--- |
| **Cảm biến DHT11** | `VCC` / `+` | `5V` | Cấp nguồn 5V |
| | `DATA` / `OUT` | **`D2`** | Tín hiệu số 1-Wire (module 3 chân đã có trở kéo lên) |
| | `GND` / `-` | `GND` | Mass chung |
| **Cảm biến Gas MQ-2** | `VCC` | `5V` | Cấp nguồn 5V (cần ~20s làm nóng sợi đốt) |
| | `A0` (Analog Out) | **`A0`** | Đọc thang ADC `0..1023` liên tục |
| | `GND` | `GND` | Mass chung |
| **Servo Pan (Ngang)** | Dây Cam / Vàng (PWM) | **`D9`** | Phạm vi an toàn: `30°..150°` (Giữa `90°`) |
| | Dây Đỏ (`VCC`) | `5V` (khuyên dùng nguồn 5V-2A ngoài) | Chung `GND` với Arduino |
| | Dây Nâu / Đen (`GND`) | `GND` | Mass chung |
| **Servo Tilt (Dọc)** | Dây Cam / Vàng (PWM) | **`D10`** | Phạm vi an toàn: `45°..135°` (Giữa `90°`) |
| | Dây Đỏ (`VCC`) | `5V` (khuyên dùng nguồn 5V-2A ngoài) | Chung `GND` với Arduino |
| | Dây Nâu / Đen (`GND`) | `GND` | Mass chung |

## 2. Cách Nạp Code Nhanh

### Cách A: Nạp trực tiếp từ Raspberry Pi 4 (1 lệnh)
```bash
# Cài đặt công cụ (chỉ chạy 1 lần đầu tiên)
bash scripts/install_arduino_tools.sh

# Nạp cho Arduino Nano (bootloader mới):
arduino-cli compile --fqbn arduino:avr:nano:cpu=atmega328 firmware/arduino/annha_node -u -p /dev/ttyUSB0

# Hoặc nạp cho Arduino Uno:
arduino-cli compile --fqbn arduino:avr:uno firmware/arduino/annha_node -u -p /dev/ttyACM0
```

### Cách B: Nạp bằng Arduino IDE trên Máy tính
1. Mở **Arduino IDE** $\rightarrow$ vào **Library Manager** cài thư viện **`DHT sensor library`** (của Adafruit) và **`Servo`**.
2. Mở file `firmware/arduino/annha_node/annha_node.ino`.
3. Chọn Board (**Arduino Nano** hoặc **Arduino Uno**) + cổng COM tương ứng $\rightarrow$ Bấm **Upload**.

### Cách C: Nạp bằng PlatformIO (VSCode)
```bash
cd firmware/arduino/annha_node
pio run -e nanoatmega328new -t upload
```

## 3. Giao Thức USB Serial (`115200 baud`, kết thúc dòng `\n`)
- **Arduino tự động gửi lên Pi 4 mỗi 2 giây:**
  ```json
  {"temp":28.5,"hum":65.0,"gas":180,"gas_warmup":0,"pan":90,"tilt":90}
  ```
- **Lệnh từ Pi 4 gửi xuống Arduino:**
  - `SERVO:90,90` hoặc `BOTH 90 90` — Đặt góc tuyệt đối Pan & Tilt
  - `MOVE -3 2` — Dịch chuyển tương đối `(deltaPan, deltaTilt)`
  - `PAN 100` / `TILT 80` — Đặt góc từng trục
  - `CENTER` — Đưa cả 2 trục về `(90, 90)`
  - `DETACH` — Ngắt xung giữ PWM (tắt tiếng ồn động cơ khi khóa góc / chế độ ban đêm)
  - `STATUS` / `SENSORS` / `PING`
