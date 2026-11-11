# Hướng Dẫn Tích Hợp Phần Cứng Arduino & Giao Thức Serial (Bàn Giao Teammate)

Tài liệu này dành cho thành viên phụ trách lắp ráp mạch **Arduino + Cảm biến + Đế Pan-Tilt Servo** để kết nối đồng bộ 100% với phần mềm trên **Raspberry Pi 4** của hệ thống AnNhà.

---

## 1. Tổng Quan Phân Chia Nhiệm Vụ Phần Cứng

```
[Cảm biến DHT11] ----(D2)----+
[Cảm biến Gas MQ-2] -(A0)----+---> [Arduino Uno / Nano] <=== Cáp USB Serial ===> [Raspberry Pi 4]
[Servo Pan Ngang] ---(D9)----+        (115200 baud)
[Servo Tilt Dọc] ----(D10)---+
```

- **Arduino đảm nhận:**
  1. Đọc nhiệt độ (°C) và độ ẩm (%) từ **DHT11**.
  2. Đọc tín hiệu khí gas/khói liên tục từ chân Analog `A0` của **MQ-2** (giá trị ADC `0..1023`).
  3. Xuất xung PWM mượt mà (1° / 20ms, không dùng `delay()`) để xoay 2 động cơ **Servo Pan/Tilt**.
- **Raspberry Pi 4 đảm nhận:**
  1. Nhận chuỗi dữ liệu cảm biến qua cáp USB (`/dev/ttyUSB0` hoặc `/dev/ttyACM0`).
  2. Chạy AI Pose nhận diện người & té ngã, tính góc lệch và gửi lệnh điều khiển Servo xuống Arduino.
  3. Đẩy dữ liệu lên Web AnNhà, ThingsBoard và điều khiển Loa Bluetooth.

---

## 2. Sơ Đồ Đấu Nối Chân Cắm (Pinout Chuẩn)

> **Lưu ý nguồn điện cho 2 Servo (SG90 / MG90S):**
> Khi 2 servo cùng khởi động, dòng đỉnh có thể lên tới `0.8A - 1.2A`. Nếu cấp nguồn từ chân `5V` của Arduino qua cổng USB Pi 4 bị sụt áp (làm Arduino tự reset), hãy cấp nguồn `5V - 2A` ngoài cho 2 dây Đỏ của Servo và **bắt buộc nối chung dây `GND` của nguồn ngoài với `GND` của Arduino**.

| Thiết bị | Chân trên linh kiện | Đấu vào chân Arduino | Lưu ý kỹ thuật |
| :--- | :--- | :---: | :--- |
| **DHT11** (Module 3 chân) | `VCC` (`+`) | `5V` | Hoạt động ổn định ở 5V |
| | `DATA` (`OUT` / `S`) | **`D2`** | Nếu dùng DHT11 4 chân rời, gắn thêm trở kéo `4.7kΩ - 10kΩ` lên `5V` |
| | `GND` (`-`) | `GND` | Mass chung |
| **MQ-2** (Cảm biến khí Gas) | `VCC` | `5V` | Sợi đốt cần **20 giây đầu** để làm nóng ổn định |
| | `A0` (Analog Out) | **`A0`** | **Dùng chân `A0`**, không dùng chân `D0` để Web vẽ được đồ thị liên tục |
| | `GND` | `GND` | Mass chung |
| **Servo PAN** (Trục ngang) | Dây Cam / Vàng | **`D9`** | Giới hạn an toàn trong code: `30° .. 150°` (Giữa `90°`) |
| | Dây Đỏ | `5V` | Nguồn 5V |
| | Dây Nâu / Đen | `GND` | Mass chung |
| **Servo TILT** (Trục dọc) | Dây Cam / Vàng | **`D10`** | Giới hạn an toàn trong code: `45° .. 135°` (Giữa `90°`) |
| | Dây Đỏ | `5V` | Nguồn 5V |
| | Dây Nâu / Đen | `GND` | Mass chung |

### Quy ước chiều lắp đặt Đế Camera Pan-Tilt (Đã hiệu chuẩn thực tế):
- Khi cả 2 servo ở góc **`90°` (`CENTER`)**, mặt ống kính camera hướng **thẳng chính diện về phía trước**.
- Theo bộ gá hiện tại:
  - Tăng góc `PAN` (`+`) $\rightarrow$ Camera xoay sang **TRÁI**; Giảm góc `PAN` (`-`) $\rightarrow$ Camera xoay sang **PHẢI**.
  - Tăng góc `TILT` (`+`) $\rightarrow$ Camera ngửa **LÊN**; Giảm góc `TILT` (`-`) $\rightarrow$ Camera cúi **XUỐNG**.
  *(Nếu lắp ngược chiều servo, không cần tháo ốc cơ khí — chỉ cần đổi biến `PAN_DIRECTION` / `TILT_DIRECTION` từ `-1` sang `1` trong file `.env` trên Pi 4).*

---

## 3. Giao Thức Truyền Thông Serial (Dành cho trường hợp tự tuỳ biến code)

Mã nguồn chuẩn đã được viết sẵn tại [`firmware/arduino/annha_node/annha_node.ino`](../../firmware/arduino/annha_node/annha_node.ino). Nếu bạn tự điều chỉnh code Arduino, chỉ cần giữ đúng chuẩn sau:

1. **Tốc độ Baud Rate:** `115200` (`Serial.begin(115200);`), kết thúc mỗi dòng bằng `\n`.
2. **Dữ liệu Cảm biến gửi từ Arduino $\rightarrow$ Pi 4 (mỗi 2 giây):**
   - **Chuẩn ưu tiên (JSON 1 dòng):**
     ```json
     {"temp":28.5,"hum":65.0,"gas":180,"gas_warmup":0}
     ```
     *Lưu ý quan trọng:* Nếu cảm biến DHT11 bị tuột dây hoặc đọc lỗi (`isnan`), hãy in `"temp":null,"hum":null` (tuyệt đối **không in số `0`** để tránh hệ thống báo động giả nhiệt độ tụt 0°C).
   - **Chuẩn dự phòng (CSV):** Bộ đọc trên Pi 4 cũng hỗ trợ tự nhận diện dòng CSV `28.5,65.0,180` (`temp,hum,gas`) nếu muốn viết tối giản.
3. **Lệnh điều khiển Servo gửi từ Pi 4 $\rightarrow$ Arduino:**
   - `MOVE <delta_pan> <delta_tilt>\n` $\rightarrow$ Phản hồi: `OK MOVE <delta_pan> <delta_tilt>`
   - `BOTH <pan> <tilt>\n` hoặc `SERVO:<pan>,<tilt>\n` $\rightarrow$ Phản hồi: `OK ...`
   - `CENTER\n` $\rightarrow$ Đưa về `(90, 90)`, phản hồi: `OK CENTER`
   - `DETACH\n` $\rightarrow$ Ngắt xung PWM để servo im lặng hoàn toàn khi khóa góc / chế độ ban đêm, phản hồi: `OK DETACH`
   - `STATUS\n` $\rightarrow$ Phản hồi: `STATUS PAN=90 TILT=90 TARGET_PAN=90 TARGET_TILT=90 ENABLED=1 MOVING=0`
   - `PING\n` $\rightarrow$ Phản hồi: `PONG`
