# ĐẶC TẢ YÊU CẦU & NGHIỆP VỤ HỆ THỐNG (PROJECT SPECIFICATION)
## DỰ ÁN: HỆ THỐNG GIÁM SÁT TÉ NGÃ VÀ MÔI TRƯỜNG THÔNG MINH (FALL-DETECT-AIOT-SYSTEM)

---

## 1. TỔNG QUAN DỰ ÁN (PROJECT OVERVIEW)

### 1.1. Bối cảnh & Lý do thực hiện
Hệ thống được thiết kế hướng tới **hai nhóm đối tượng dễ bị tổn thương nhất trong gia đình và cơ sở chăm sóc: Người cao tuổi và Trẻ nhỏ (trẻ sơ sinh, trẻ tập đi)**:
* **Đối với người cao tuổi:** Té ngã là nguyên nhân hàng đầu gây chấn thương xương khớp, đột quỵ hoặc xuất huyết não. Nguy hiểm lớn nhất là tình trạng **"nằm bất động trong thời gian dài" (Prolonged Lie-time)** sau khi ngã hoặc đột quỵ do không thể tự đứng dậy hay gọi người trợ giúp, dễ dẫn đến hạ thân nhiệt, hoại tử mô hoặc tử vong.
* **Đối với trẻ nhỏ:** Trẻ em rất hiếu động, dễ bị ngã từ giường, nôi, cầu thang hoặc bàn ghế. Ngoài ra, trẻ có nguy cơ cao bị ngạt thở (do chăn gối úp mặt, dị vật đường thở), sốt cao co giật dẫn đến bất tỉnh, hoặc hội chứng ngưng thở khi ngủ mà cha mẹ không kịp thời phát hiện khi ở phòng khác.

Đồng thời, môi trường sống (nhiệt độ quá lạnh/nóng gây sốc nhiệt, độ ẩm cao gây ẩm ướt trơn trượt sàn nhà, thiếu sáng vào ban đêm, hoặc rò rỉ khí gas độc hại) là những tác nhân trực tiếp làm tăng nguy cơ tai nạn cho cả người già và trẻ nhỏ.

### 1.2. Mục tiêu hệ thống
Xây dựng một hệ sinh thái **AIoT hoàn chỉnh (Edge AI + Multi-sensor IoT + ThingsBoard / Web Platform)** nhằm:
1. **Phát hiện té ngã tức thời tại biên (Edge Computing):** Sử dụng Camera kết hợp mô hình AI Deep Learning (MediaPipe + Transformer) phân tích tư thế và kích hoạt báo động trong thời gian dưới 1 giây.
2. **Giám sát & Cảnh báo bất động kéo dài (Prolonged Immobility Monitoring):** Nhận diện trạng thái bất động bất thường trên sàn nhà hoặc giường/nôi vượt quá thời gian cho phép (dấu hiệu ngất, đột quỵ, chấn thương nặng ở người già hoặc ngạt thở, bất tỉnh ở trẻ nhỏ).
3. **Bảo vệ quyền riêng tư (Privacy-First):** Chỉ phân tích và truyền tọa độ khớp xương (Skeleton), không lưu trữ hoặc truyền tải video nhạy cảm của người dùng.
4. **Giám sát môi trường phòng sống đa tham số:** 
   * Thu thập nhiệt độ & độ ẩm thời gian thực thông qua cảm biến **DHT11**.
   * *Mở rộng cải tiến:* Đo cường độ ánh sáng bằng **TSL2561** để tự động cảnh báo/bật đèn khi tối; phát hiện rò rỉ khí độc/cháy bằng **cảm biến Gas (MQ-2)**.
5. **Hạ tầng truyền thông & Điều phối cảnh báo thông minh:** Sử dụng nền tảng **ThingsBoard** qua giao thức **MQTT**, hỗ trợ Rule Chain cảnh báo đa kênh (Web Dashboard, Popup khẩn cấp, Telegram Bot / SMS).

---

## 2. KIẾN TRÚC TỔNG THỂ HỆ THỐNG (SYSTEM ARCHITECTURE)

```
┌────────────────────────────────────────────────────────────────────────┐
│                   TẦNG THIẾT BỊ BIÊN (EDGE IOT LAYER)                  │
│                                                                        │
│   [ Camera USB / CSI ] ──> MediaPipe Pose (17 Khớp) ──> Transformer   │
│                                                          (TFLite)      │
│   [ Cảm biến DHT11 ]    ──> GPIO (Đọc Nhiệt độ / Độ ẩm)       │        │
│   [ Cảm biến TSL2561 ]  ──> I2C (Cường độ ánh sáng Lux)       │        │
│   [ Cảm biến Khí Gas ]  ──> GPIO/ADC (Nồng độ PPM)            │        │
│                                                               │        │
│   ───> Đóng gói Telemetry JSON & Gửi qua MQTT (Port 1883) ────┘        │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Giao thức MQTT (v1/devices/me/telemetry)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   TẦNG NỀN TẢNG IOT (THINGSBOARD PLATFORM)             │
│                                                                        │
│   • MQTT Broker & Device Manager: Quản lý kết nối & Access Token       │
│   • Telemetry Database: Lưu trữ lịch sử nhiệt độ, độ ẩm, ánh sáng, gas │
│   • Rule Engine: Kích hoạt Alarms khi Fall = True hoặc Khí Gas vượt mức│
│   • RPC Remote Control: Điều khiển bật tắt thiết bị ngoại vi từ xa     │
└───────────────────┬────────────────────────────────┬───────────────────┘
                    │                                │
                    ▼                                ▼
┌──────────────────────────────────────┐  ┌──────────────────────────────┐
│     TẦNG ỨNG DỤNG (WEB DASHBOARD)    │  │    KÊNH CẢNH BÁO KHẨN CẤP    │
│                                      │  │                              │
│ • Giám sát trực quan trạng thái phòng│  │ • Telegram Bot gửi cảnh báo  │
│ • Popup khẩn cấp khi có người té ngã │  │ • Còi buzzer / Đèn LED phòng │
│ • Biểu đồ quan trắc môi trường sống │  │ • SMS / Cuộc gọi khẩn cấp    │
│ • Nhật ký sự kiện & xử lý sự cố      │  │                              │
└──────────────────────────────────────┘  └──────────────────────────────┘
```

---

## 3. ĐẶC TẢ CHI TIẾT CÁC NHÓM NGHIỆP VỤ (FUNCTIONAL SPECIFICATIONS)

### 3.1. Nhóm Nghiệp Vụ Phát Hiện Té Ngã Bằng AI (Core Vision AI)

| Mã NV | Tên nghiệp vụ | Mô tả chi tiết |
| :--- | :--- | :--- |
| **FN-AI-01** | Trích xuất khớp xương thời gian thực | Sử dụng **MediaPipe Pose** đọc luồng video (640x480, $\ge 15$ FPS), trích xuất tọa độ không gian 17 khớp xương chính (Mũi, mắt, tai, vai, khuỷu tay, cổ tay, hông, đầu gối, mắt cá chân). |
| **FN-AI-02** | Chuẩn hóa tọa độ (Normalization) | Chuẩn hóa tọa độ khung xương theo tỷ lệ cơ thể và trọng tâm người để loại bỏ sự sai lệch do khoảng cách xa/gần hoặc góc quay của camera. |
| **FN-AI-03** | Phân loại hành động chuỗi thời gian | Đưa chuỗi trượt 30 khung hình (tương đương 1-2 giây cử động) vào mô hình **Transformer Sequence Classifier (TFLite/ONNX)** để phân loại nhị phân: `Fall` hoặc `No-Fall`. |
| **FN-AI-04** | Cơ chế chống báo động giả (False-alarm filter) | Kết hợp kiểm tra trạng thái: sau khi phát hiện rơi đột ngột, theo dõi thêm $T$ giây (ví dụ: 3 - 5s). Nếu đối tượng tự ngồi/đứng dậy $\rightarrow$ Hủy cảnh báo té ngã. |
| **FN-AI-05** | Giám sát & Cảnh báo Bất Động Kéo Dài (Prolonged Immobility Detection) | **(Tính năng quan trọng)**: Theo dõi chuyển động vi sai (micro-motion) của các khớp xương. Nếu đối tượng ở trạng thái nằm/gục bất động trên sàn nhà hoặc vị trí nguy hiểm vượt quá thời gian $T_{\text{immobile}}$:<br>• **Trẻ nhỏ:** Cảnh báo nhanh sau **30 - 60 giây** bất động (nguy cơ ngạt thở, co giật, chấn thương).<br>• **Người già:** Cảnh báo mức nhắc nhở sau **1 phút**, nâng lên **Báo động Đỏ sau 2 - 3 phút** bất động (nguy cơ đột quỵ, chấn thương gãy xương, mất ý thức). |
| **FN-AI-06** | Bảo vệ quyền riêng tư (Privacy Protection) | Hệ thống không lưu trữ video quay cảnh sinh hoạt của người dùng. Trên màn hình giám sát chỉ vẽ đường que bộ xương (Skeleton Wireframe) trên nền đen hoặc làm mờ hoàn toàn khuôn mặt. |

---

### 3.2. Nhóm Nghiệp Vụ Giám Sát Môi Trường (IoT Environmental Monitoring)

#### A. Đo Nhiệt độ & Độ ẩm (Cảm biến DHT11 - Hiện tại)
* **Thu thập dữ liệu định kỳ:** Đọc giá trị nhiệt độ ($^\circ\text{C}$) và độ ẩm ($\%$) từ chân GPIO của Raspberry Pi mỗi $10 - 30$ giây.
* **Cảnh báo nguy cơ sức khỏe:**
  * *Cảnh báo sốc nhiệt / hạ thân nhiệt:* Nếu nhiệt độ phòng $< 16^\circ\text{C}$ hoặc $> 35^\circ\text{C}$.
  * *Cảnh báo nguy cơ trơn trượt:* Nếu độ ẩm không khí $> 85\%$ kéo dài (sàn gạch dễ đọng nước, nguy cơ trượt ngã tăng vọt).

#### B. Đo Cường độ Ánh sáng (Cảm biến TSL2561 - Mở rộng cải tiến)
* **Giao tiếp I2C:** Thu thập cường độ sáng thực tế theo đơn vị Lux ($0.1 - 40,000\text{ Lux}$).
* **Nghiệp vụ phòng ngừa té ngã:**
  * Nhận biết trạng thái ban đêm / phòng tối ($< 5\text{ Lux}$).
  * Khi phát hiện có người cử động trong phòng tối, hệ thống tự động kích hoạt Relay bật đèn ngủ dẫn đường (Path-light) để chống vấp ngã.

#### C. Phát hiện Khí Gas & Khói Độc (Cảm biến MQ-2 - Mở rộng cải tiến)
* **Giám sát khí dễ cháy & ngạt:** Phát hiện rò rỉ khí gas LPG, Methane, khói thuốc hoặc chập cháy điện.
* **Báo động cấp độ đỏ:** Nếu nồng độ khí gas vượt ngưỡng an toàn ($> 400\text{ PPM}$):
  * Phát chuông báo động sơ tán ngay lập tức tại phòng.
  * Gửi cảnh báo khẩn cấp đến ứng dụng người nhà/nhân viên y tế để can thiệp kịp thời trước khi người già bị ngạt hoặc cháy nổ.

---

### 3.3. Nhóm Nghiệp Vụ Truyền Thông & Cảnh Báo Khẩn Cấp (Alerting & ThingsBoard)

#### A. Đóng gói & Truyền dữ liệu Telemetry (MQTT Gateway)
Dữ liệu từ module AI và các cảm biến được đóng gói thành định dạng JSON chuẩn của ThingsBoard và publish lên topic `v1/devices/me/telemetry`:

```json
{
  "device_id": "RASPI_ROOM_101",
  "target_type": "elderly",         // "elderly" (người già) hoặc "child" (trẻ nhỏ)
  "fall_detected": true,            // Sự kiện té ngã
  "fall_confidence": 95.58,
  "immobility_detected": true,      // Trạng thái bất động kéo dài
  "immobility_duration_s": 120,     // Thời gian đã bất động (giây)
  "temperature": 27.5,
  "humidity": 68.2,
  "light_lux": 150.0,
  "gas_ppm": 45,
  "system_status": "CRITICAL_ALARM"
}
```

#### B. Phân cấp mức độ sự cố (Severity Levels)
1. **Mức 1 - Thông tin / Cảnh báo nhẹ (Warning - Vàng):** Nhiệt độ, độ ẩm hoặc ánh sáng phòng không lý tưởng. Hiển thị nhắc nhở trên giao diện web.
2. **Mức 2 - Nguy cơ tiềm ẩn (Minor Alarm - Cam):** 
   * Phát hiện nồng độ gas tăng nhẹ hoặc sàn nhà quá ẩm ướt kéo dài.
   * Phát hiện đối tượng nằm im trên sàn nhưng chưa vượt ngưỡng nguy kịch (30 giây đối với người già).
3. **Mức 3 - Khẩn cấp / Nguy kịch (Critical Alarm - Đỏ):** 
   * **XÁC NHẬN TÉ NGÃ** hoặc **BẤT ĐỘNG KÉO DÀI** (> 30s-60s với trẻ nhỏ, > 2-3 phút với người già) hoặc **RÒ RỈ GAS NGUY HIỂM**.
   * Hệ thống tự động:
     * Kích hoạt còi báo động tại chỗ.
     * Bật Popup khẩn cấp toàn màn hình trên Web Dashboard, phát âm thanh chuông báo động.
     * Gửi tin nhắn tức thì qua **Telegram Bot** kèm vị trí phòng, thời gian chính xác và ảnh chụp hiện trường.

#### C. Nghiệp vụ Phản hồi & Xử lý sự cố (Incident Response)
* **Xác nhận tiếp nhận (Acknowledge):** Người trực/bác sĩ bấm nút *"Đã tiếp nhận cứu hộ"* trên Web Dashboard $\rightarrow$ Ghi nhận thời gian phản ứng, ngừng phát chuông ầm ĩ.
* **Hủy báo động giả (False-alarm Dismissal):** Bệnh nhân bấm nút hủy trên thiết bị hoặc người trực xác nhận sau khi kiểm tra phòng.

---

### 3.4. Nhóm Nghiệp Vụ Giám Sát & Quản Trị Trên Web Dashboard

* **Bản đồ trực quan các phòng (Floor Map / Room Cards):**
  * Hiển thị danh sách toàn bộ các phòng có lắp đặt thiết bị.
  * Trạng thái trực quan: Màu xanh (An toàn), Màu vàng (Môi trường xấu), Màu đỏ nhấp nháy (Đang té ngã).
* **Đồ thị quan trắc môi trường (Charts & Trends):**
  * Biểu đồ theo thời gian thực hiển thị biến thiên nhiệt độ, độ ẩm, ánh sáng trong 24 giờ qua.
* **Nhật ký sự kiện (Audit Log & Event History):**
  * Lưu trữ toàn bộ lịch sử các vụ té ngã: Thời điểm xảy ra, độ tin cậy của AI, thời lượng nằm bất động, nhân viên đã xử lý.
* **Cấu hình tham số từ xa (Remote Configuration via ThingsBoard Shared Attributes):**
  * Cho phép người quản trị điều chỉnh ngưỡng độ tin cậy AI (ví dụ: từ `0.85` lên `0.90`), thời gian chờ xác nhận ngã ($T$ giây), bật/tắt gửi Telegram mà không cần cắm màn hình vào Raspberry Pi.

---

## 4. YÊU CẦU PHI CHỨC NĂNG (NON-FUNCTIONAL REQUIREMENTS)

1. **Hiệu năng & Độ trễ (Performance & Latency):**
   * Thời gian phát hiện từ lúc người chạm đất đến khi phát tín hiệu báo động: $\le 1.0\text{ giây}$.
   * Tốc độ xử lý mô hình AI trên CPU Raspberry Pi: $\ge 15 - 20\text{ FPS}$.
   * Độ trễ truyền bản tin MQTT từ Pi lên ThingsBoard: $\le 200\text{ ms}$.
2. **Độ chính xác (Accuracy):**
   * Tỷ lệ phát hiện té ngã thực tế (True Positive Rate / Recall): $\ge 92\%$.
   * Tỷ lệ báo động nhầm khi cúi người/nằm xuống giường (False Positive Rate): $\le 5\%$.
3. **Tính ổn định & Phục hồi (Reliability & Resilience):**
   * Tự động khởi động lại dịch vụ (`systemd service`) khi Raspberry Pi bị mất điện đột ngột hoặc crash.
   * Bộ đệm ngoại tuyến (Offline Buffering): Nếu mất kết nối Wi-Fi, dữ liệu telemetry môi trường và log té ngã sẽ được lưu tạm thời vào thẻ nhớ và đẩy bù lên ThingsBoard khi có mạng trở lại.
4. **Bảo mật (Security):**
   * Thiết bị xác thực với ThingsBoard thông qua mã Access Token riêng biệt cho từng phòng.
   * Sử dụng mã hóa TLS/SSL cho kết nối MQTT qua Internet nếu triển khai thực tế.

---

## 5. LỘ TRÌNH TRIỂN KHAI & MỞ RỘNG (ROADMAP)

```
GIAI ĐOẠN 1: NỀN TẢNG CỐT LÕI (HIỆN TẠI)
├── Hoàn thiện mô hình AI phát hiện té ngã (MediaPipe + Transformer TFLite)
├── Tích hợp đọc cảm biến Nhiệt độ - Độ ẩm DHT11 trên Raspberry Pi
├── Xây dựng giao thức đóng gói MQTT đẩy trực tiếp lên ThingsBoard / Backend
└── Xây dựng Web Dashboard cơ bản nhận diện sự cố thời gian thực

GIAI ĐOẠN 2: CẢI TIẾN CẢM BIẾN & TỰ ĐỘNG HÓA (TIẾP THEO)
├── Tích hợp cảm biến ánh sáng I2C TSL2561 (tự động bật đèn chống ngã phòng tối)
├── Tích hợp cảm biến Khí Gas & Khói MQ-2 (cảnh báo nguy cơ cháy nổ / ngạt khí)
├── Cấu hình ThingsBoard Rule Chain nâng cao (Alarms, Gửi SMS/Telegram đa người nhận)
└── Thiết kế vỏ hộp thiết bị 3D tích hợp Camera và các cảm biến thành 1 hộp AIoT Box gọn gàng

GIAI ĐOẠN 3: TỐI ƯU HÓA NÂNG CAO (NẾU CÓ THỜI GIAN)
├── Chuyển đổi mô hình sang NCNN hoặc tăng tốc qua NPU (Raspberry Pi AI HAT)
└── Tích hợp loa thông minh phát giọng nói: "Bạn có sao không? Hãy nhấn nút nếu an toàn"
```
