# ĐẶC TẢ YÊU CẦU & NGHIỆP VỤ HỆ THỐNG

## CAMERA GIÁM SÁT GIA ĐÌNH TÍCH HỢP CẢNH BÁO AN TOÀN VÀ HỖ TRỢ SINH HOẠT

- **Mã dự án:** FALL-DETECT-AIOT-SYSTEM.
- **Phiên bản đặc tả:** 2.3 — ngày 29/10/2026 (tạm bỏ khoanh vùng, định hướng servo tracking).
- **Nguồn hợp nhất:** Bản AnNhà v2.1 là nền nghiệp vụ; nội dung riêng của bản thiết kế AIoT trước đây được đối chiếu tại mục 9. Đây là tài liệu đặc tả chính duy nhất.
- **Quyết định phạm vi 29/10/2026:** Tạm bỏ chức năng khoanh vùng trên web và luật dựa trên vùng. Ưu tiên hướng camera quay bằng servo bám một người; panorama/ánh xạ vùng chỉ xem xét đưa lại khi tracking ổn định (mục 9.5). Giao diện/API chỉnh vùng đã được gỡ; dữ liệu lịch sử được giữ. Tracking servo chưa được triển khai/kiểm chứng.
- **Trạng thái:** Phạm vi nghiệp vụ đã thống nhất để định hướng triển khai. Mức triển khai backend/frontend và giới hạn edge được cập nhật riêng tại [ARCHITECTURE.md](ARCHITECTURE.md); tài liệu yêu cầu không đồng nghĩa tất cả đã được nghiệm thu trên phần cứng.

---

## 1. TỔNG QUAN VÀ PHẠM VI

### 1.1. Mục tiêu

Xây dựng hệ thống camera giám sát gia dụng cho phép người nhà quan sát từ xa, nhận cảnh báo khi có tình huống bất thường và hỗ trợ sinh hoạt qua âm thanh. Hệ thống kết hợp xử lý hình ảnh tại thiết bị, cảm biến môi trường và ứng dụng web.

Các mục tiêu chính:

1. Xem hình ảnh camera trực tiếp và kiểm tra tình hình tại phòng.
2. Phát hiện nghi ngờ té ngã và cảnh báo bất động kéo dài theo ngữ cảnh.
3. Hướng tới camera quay bằng servo bám vị trí một người trong phòng, có xử lý mất dấu và trạng thái camera chuyển động.
4. Theo dõi nhiệt độ, độ ẩm, tín hiệu khí gas và cảnh báo khi vượt ngưỡng cấu hình.
5. Phát lời nhắc theo lịch bằng TTS hoặc âm thanh thu sẵn; hỗ trợ gửi âm thanh và phát giọng nói trực tiếp từ xa.
6. Lưu lịch sử sự kiện, bằng chứng và quá trình xử lý của người nhà.

Hệ thống hỗ trợ phát hiện tình huống cần kiểm tra; không kết luận ngạt thở, đột quỵ, mất ý thức hoặc tình trạng bệnh lý từ tư thế hay mức chuyển động.

### 1.2. Bối cảnh sử dụng

- Sử dụng trong nhà ở, theo từng phòng có camera và thiết bị cảm biến.
- Người sử dụng chính là chủ hộ và người thân được cấp quyền; nghiệp vụ không yêu cầu nhân viên y tế hoặc cơ sở chăm sóc.
- Kịch bản ưu tiên để xây dựng và đánh giá là người cần được quan tâm tại nhà, đặc biệt người cao tuổi. Chưa xác lập chính sách riêng cho trẻ sơ sinh hoặc giám sát hô hấp.
- Mốc nghiệm thu ban đầu: một camera trong một phòng, một người được quan sát rõ; cơ cấu servo quay/nghiêng tại vị trí lắp cố định, không bao gồm robot di chuyển. Đây là giới hạn triển khai ban đầu; giám sát đồng thời nhiều người cần được đánh giá riêng trước khi cam kết hỗ trợ.
- Người được giám sát không cần mang thiết bị hoặc thao tác trên camera đặt cao.

### 1.3. Phân định phạm vi

| Trong phạm vi nghiệp vụ | Ngoài phiên bản đầu / mở rộng sau |
| :--- | :--- |
| Tài khoản, nhà/cụm camera, phân quyền; xem camera, phát hiện té ngã và bất động; định hướng servo bám một người | Khoanh vùng trên ảnh, panorama/ánh xạ vùng; nhận diện danh tính, theo dõi một người xuyên nhiều camera |
| Nhiệt độ, độ ẩm, cảnh báo tín hiệu gas | Suy luận sàn ướt từ độ ẩm; đo mọi loại khí độc |
| Lời nhắc TTS/audio, gửi lời nhắn thoại, phát giọng nói trực tiếp một chiều | Đàm thoại hai chiều, trợ lý hội thoại, nhận dạng giọng nói để xác nhận an toàn |
| Cảnh báo web, âm thanh tại chỗ, thông báo Telegram | SMS, gọi điện tự động, tự động liên hệ cứu hộ |
| Lịch sử sự kiện, ảnh và clip ngắn | Ghi hình liên tục 24/7 như hệ thống NVR |
| Cấu hình, lịch phát và xử lý cảnh báo từ web | SOS vật lý gắn trên camera; nút SOS rời/đeo người |
| Phát hiện mất kết nối và lỗi giám sát | Tự bật đèn dẫn đường, tự động hóa thiết bị điện, cảm biến ánh sáng bổ sung |

Phát giọng nói trực tiếp nằm trong hướng chức năng đã chọn nhưng triển khai sau phát file âm thanh. Phần cứng, giao thức media và chỉ tiêu độ trễ được chốt ở bước thiết kế kỹ thuật.

## 2. VAI TRÒ VÀ TRÁCH NHIỆM

| Vai trò | Trách nhiệm / quyền hạn |
| :--- | :--- |
| Chủ hộ / quản trị | Quản lý thiết bị, phòng, người được truy cập; cấu hình ngưỡng, lịch nhắc, kênh cảnh báo và lưu trữ |
| Người thân được cấp quyền | Xem camera, nhận và xử lý cảnh báo, xem lịch sử; phát âm thanh hoặc sửa cấu hình khi được cấp quyền tương ứng |
| Người xem | Chỉ xem camera, media và dữ liệu được cấp quyền; không mặc định được xử lý cảnh báo, sửa cấu hình hoặc phát loa |
| Người được giám sát | Nhận lời nhắc và âm thanh tại phòng; không bắt buộc có tài khoản hay bấm nút tại thiết bị |
| Thiết bị biên | Xử lý hình ảnh, cảm biến, cảnh báo tại chỗ, lịch và âm thanh đã đồng bộ; lưu tạm khi mất mạng |
| Backend | Quản lý dữ liệu nghiệp vụ, cấu hình, người dùng, sự kiện, thông báo và đồng bộ thiết bị |

### 2.1. Tài khoản và nhà/cụm camera

- Cấu trúc quản lý: **Tài khoản → tư cách thành viên và quyền → Nhà/cụm camera → Phòng → Camera/thiết bị/cảm biến**. Một tài khoản có thể tham gia nhiều nhà.
- Trên web dùng tên “Nhà” cho đơn vị quản lý một cụm camera. Camera không được công khai; đăng ký tài khoản không tự cấp quyền xem camera của người khác.
- Chủ hộ sở hữu nhà và quản lý thành viên. Người thân/người chăm sóc và người xem chỉ có quyền trong phạm vi được cấp; quyền phát loa, sửa chính sách/lịch và quản trị được phân biệt rõ.
- Đây là quyền truy cập thiết bị, không phải nhận diện danh tính người trong video. Mốc đánh giá AI một camera/một người vẫn giữ nguyên dù ứng dụng quản lý được nhiều camera.

## 3. KIẾN TRÚC VÀ PHÂN CHIA XỬ LÝ

```text
Camera ───────────────┐
Cảm biến môi trường ──┼─> Raspberry Pi / thiết bị biên
Loa <────────────────┘   - Phân tích hình ảnh, tư thế và trạng thái tracking
                         - Đọc cảm biến, phát hiện vượt ngưỡng
                         - Cảnh báo tại chỗ, lịch phát âm thanh
                         - Bộ đệm sự kiện và cấu hình cục bộ
                                   │
               MQTT: telemetry, sự kiện, cấu hình, lệnh và phản hồi
               HTTPS / kênh media: ảnh, clip, file âm thanh, live stream
                                   │
                                   ▼
                         Backend + cơ sở dữ liệu
                         + kho ảnh/video/audio
                                   │
                     ┌─────────────┴─────────────┐
                     ▼                           ▼
              Web dashboard                Kênh Telegram
              - Xem camera                 - Thông báo sự cố
              - Cấu hình, lập lịch          - Tham chiếu sự kiện
              - Xử lý và xem lịch sử
```

- **Backend là nguồn quản lý nghiệp vụ chính:** phiên bản cấu hình, lịch nhắc, quyền truy cập, trạng thái xử lý sự kiện và lịch sử thao tác.
- **Thiết bị thực thi bản cấu hình đã áp dụng gần nhất:** không phụ thuộc việc mở web để tiếp tục phân tích hoặc phát lịch nhắc.
- **Web là nơi tương tác:** thay đổi cấu hình qua backend, hiển thị phản hồi áp dụng từ thiết bị.
- Video và âm thanh trực tiếp đi qua kênh media riêng; không đóng gói luồng media vào bản tin telemetry MQTT.
- ThingsBoard, nếu sử dụng, phục vụ telemetry và biểu đồ môi trường. Không duy trì một quy trình xử lý cảnh báo hoặc nguồn cấu hình độc lập gây trùng với backend.
- Định dạng mô hình, số khớp đầu vào, độ dài chuỗi và runtime phải theo artifact mô hình được chọn và kiểm chứng. Đặc tả nghiệp vụ không tự thay đổi hợp đồng tiền xử lý/đầu vào mô hình hiện có.

Kiến trúc thành phần, hiện trạng mã nguồn và các luồng kỹ thuật được mô tả tại [ARCHITECTURE.md](ARCHITECTURE.md). Backend kiểm tra quyền trên API, WebSocket và media; không broadcast dữ liệu của mọi nhà đến mọi trình duyệt.

### 3.1. Pipeline AI và hợp đồng mô hình

Thiết kế hai giai đoạn từ bản AIoT được giữ lại: MediaPipe Pose trích xuất tư thế, sau đó mô hình Transformer phân loại chuỗi thời gian tại thiết bị. Luật xác nhận té ngã và bất động thuộc lớp nghiệp vụ bổ sung, không đồng nhất với điểm mô hình.

| Thành phần | Hợp đồng tham chiếu trong mã nguồn |
| :--- | :--- |
| Trích xuất tư thế | Chọn 17 khớp từ MediaPipe Pose theo `SORTED_YOUR_KEYPOINT_NAMES` trong [skeleton.py](../fall_detect/modules/skeleton.py) |
| Đặc trưng mỗi khớp | `x, y, visibility`; không phải `x, y, z` như bảng thiết kế cũ |
| Chuẩn hóa | Dịch gốc về trung điểm hông, co giãn x/y theo chiều cao thân khi đủ điều kiện; giữ kênh visibility theo mã tiền xử lý |
| Chuỗi đầu vào | 30 khung hình × 51 đặc trưng, dạng `(1, 30, 51)`; thời lượng thực phụ thuộc tốc độ lấy mẫu, không cố định 1–2 giây |
| Artifact / runtime | [fall_detection_transformer.tflite](../fall_detect/models/fall_detection_transformer.tflite), `tflite-runtime`; cấu hình tham chiếu tại [config.py](../fall_detect/config.py) |
| Kết quả | Điểm phân loại té ngã để kết hợp với luật theo dõi; không mặc định là xác suất đã hiệu chuẩn |

Bảng này được đối chiếu nguồn khi hợp nhất, không phải kết quả chạy mô hình trên Pi. Số attention head, kích thước artifact và lựa chọn ONNX/NCNN/NPU không trở thành yêu cầu nghiệp vụ cố định. Khi thay artifact phải xác minh lại đầu vào, đầu ra, thứ tự khớp và chuẩn hóa. Chi tiết giao thức thiết bị theo [DEVICE_API.md](DEVICE_API.md); ví dụ telemetry ThingsBoard cũ không thay thế hợp đồng tích hợp hiện hành.

## 4. ĐẶC TẢ NGHIỆP VỤ

### 4.0. Truy cập hệ thống và đăng ký camera

| Mã | Yêu cầu |
| :--- | :--- |
| ACC-01 | Có landing page giới thiệu tính năng, cách hoạt động và quyền riêng tư, dẫn đến đăng nhập/đăng ký. Không hiển thị dữ liệu camera thật cho người chưa được phép. |
| ACC-02 | Hỗ trợ đăng ký bằng email/mật khẩu, xác minh email, đăng nhập, đăng xuất và khôi phục mật khẩu. Hiển thị lỗi rõ ràng và bảo vệ phiên truy cập. |
| ACC-03 | Sau đăng nhập, hiển thị nhà đã tham gia; nếu có nhiều nhà cho phép chọn/chuyển nhà. Chưa có nhà thì hướng dẫn tạo mới hoặc nhận lời mời. |
| ACC-04 | Chủ hộ tạo nhà, phòng và mời thành viên bằng email với vai trò/phạm vi quyền. Lời mời có hạn và được chấp nhận bởi đúng tài khoản người nhận. |
| ACC-05 | Phân quyền theo nhà/camera cho xem live/media, nhận và xử lý sự kiện, phát âm thanh, sửa chính sách/lịch và quản trị. Kiểm tra tại backend, WebSocket và kênh media. |
| ACC-06 | Người có quyền đăng ký thiết bị bằng mã ghép nối/QR còn hạn, đặt tên và chọn phòng. Mã dùng một lần; không cho nhận quyền thiết bị đang thuộc nhà khác chỉ bằng ID hoặc mã cũ. |
| ACC-07 | Luồng thiết lập hướng dẫn kiểm tra hình ảnh, cảm biến/loa nếu có, kiểm tra khả năng tracking khi được hỗ trợ và theo dõi thiết bị áp dụng cấu hình. Không hiển thị sẵn sàng khi chưa nhận phản hồi cần thiết. |
| ACC-08 | Có thể đổi vai trò hoặc thu hồi thành viên. Khi thu hồi, chặn truy cập mới và kết thúc quyền nhận sự kiện/live media hiện có, thay vì chỉ ẩn mục điều hướng. |
| ACC-09 | Chỉ người có quyền quản lý mới được gỡ thiết bị khỏi nhà. Cần xác nhận, ghi audit và vô hiệu quyền truy cập/lệnh của nhà cũ; chuyển chủ cần xác minh riêng, không tự mở quyền công khai. |


### 4.1. Camera và khả năng quan sát

| Mã | Yêu cầu |
| :--- | :--- |
| CAM-01 | Người có quyền mở hình ảnh trực tiếp của camera theo phòng. Giao diện phân biệt đang kết nối, đang phát và mất hình. |
| CAM-02 | Hiển thị thời điểm dữ liệu gần nhất; không giữ ảnh cũ với trạng thái như đang trực tiếp. |
| CAM-03 | Hiển thị trạng thái camera cố định/đang bám, đang quay hoặc mất dấu khi thiết bị hỗ trợ tracking; không hiển thị trạng thái tracking giả khi chưa có phản hồi thiết bị. |
| CAM-04 | Phân biệt người ra khỏi khung hình, bị che khuất/không đủ độ tin cậy, camera lỗi hoặc luồng hình đứng. Không suy diễn các trường hợp này thành bất động. |
| CAM-05 | Giới hạn quyền xem camera, ảnh và clip theo hộ gia đình/phòng được phân quyền. |

### 4.2. Camera bám một người bằng servo (hướng triển khai)

Tạm bỏ thao tác vẽ vùng, đa giác vùng nghỉ ngơi/vùng bỏ qua và mọi luật phụ thuộc vùng khỏi phạm vi hiện tại. Các mã `ZONE-01`–`ZONE-07` được bảo lưu cho chức năng đã hoãn, không tái sử dụng cho tracking. Điều kiện đưa lại khoanh vùng được mô tả ở mục 9.5.

| Mã | Yêu cầu mục tiêu |
| :--- | :--- |
| TRK-01 | Camera quay/nghiêng bằng servo để bám một người trong phòng trong giới hạn cơ khí và góc nhìn cho phép. Không bao gồm nhận diện danh tính hoặc theo dõi xuyên nhiều camera. |
| TRK-02 | Ưu tiên giữ toàn thân đủ quan sát cho pose/té ngã; điều khiển có vùng chết và giới hạn tốc độ để hạn chế rung, đuổi theo nhiễu hoặc quay liên tục. Góc và tốc độ cụ thể chốt sau đo phần cứng. |
| TRK-03 | Phân biệt camera ổn định, đang quay, đang bám và mất dấu; khi không có dữ liệu thiết bị, hiển thị chưa xác định thay vì tự nhận đã bám thành công. |
| TRK-04 | Khi mất dấu, ghi nhận thiếu quan sát và thực hiện chính sách dừng/tìm lại có giới hạn đã cấu hình; không tự chuyển sang một người khác mà coi là cùng đối tượng. Kịch bản nhiều người chưa thuộc nghiệm thu ban đầu. |
| TRK-05 | Theo dõi ảnh hưởng chuyển động camera tới pose/chuỗi AI và bộ đếm bất động. Đoạn quay hoặc ảnh chưa ổn định không được tự coi là chuyển động/phục hồi của người; không cộng đoạn thiếu quan sát vào thời lượng bất động. |
| TRK-06 | Servo không làm dừng cảnh báo môi trường, cảnh báo tại chỗ hoặc xóa sự kiện đang mở. Đánh giá té ngã trong và sau khi quay trước khi cam kết chất lượng vận hành. |

Phần cứng servo, số trục, phản hồi góc, giao thức trạng thái và luật tìm lại chưa được chốt. Không coi các yêu cầu trên là tính năng đã có trong API/agent hiện hành.

### 4.3. Phát hiện nghi ngờ té ngã

| Mã | Yêu cầu |
| :--- | :--- |
| FALL-01 | Phân tích diễn biến theo thời gian để nhận diện nghi ngờ té ngã; không kết luận ngã từ một ảnh nằm ngang đơn lẻ. |
| FALL-02 | Kết hợp đầu ra mô hình với tư thế sau diễn biến, chất lượng quan sát và trạng thái chuyển động camera để giảm báo giả do cúi người, ngồi hoặc chủ động nằm xuống. |
| FALL-03 | Phân biệt thời điểm nghi ngờ, khoảng theo dõi xác nhận và thời điểm phát cảnh báo. Ngưỡng và khoảng chờ có thể cấu hình, được đánh giá trên thiết bị thực tế. |
| FALL-04 | Khi có nghi ngờ, tạo sự kiện và giữ bằng chứng. Nếu có dấu hiệu phục hồi rõ ràng, ghi nhận diễn biến phục hồi; nếu đã phát cảnh báo, không tự coi sự cố đã được người nhà xử lý. |
| FALL-05 | Có thể gửi thông báo nghi ngờ sớm, sau đó cập nhật cùng sự kiện khi đủ điều kiện cảnh báo. Không tạo liên tiếp nhiều sự kiện cho cùng một diễn biến. |
| FALL-06 | Camera quay hoặc mất dấu không xóa lịch sử nghi ngờ đang theo dõi. Nếu mất quan sát trước khi xác minh, giữ sự kiện với trạng thái thiếu quan sát; không tự coi người đã phục hồi. |

“Đủ điều kiện cảnh báo” là kết quả luật của hệ thống, không phải xác nhận y khoa hay xác nhận của người nhà.

### 4.4. Cảnh báo bất động kéo dài

| Mã | Yêu cầu |
| :--- | :--- |
| IMM-01 | Theo dõi tư thế và mức chuyển động của người quan sát được qua thời gian; có thể cảnh báo dù không ghi nhận thời điểm ngã. |
| IMM-02 | Áp dụng thời gian chờ theo tư thế, lịch và chính sách phòng. Khi chưa có ngữ cảnh vị trí, không khẳng định người ở sàn, ghế hoặc giường; chỉ ít chuyển động chưa đủ để kết luận sự cố khẩn cấp. |
| IMM-03 | Bộ đếm chỉ tích lũy khi đủ chất lượng quan sát. Mất dấu ngắn được ghi nhận gián đoạn và không cộng thời gian chưa quan sát; mất dấu quá giới hạn kết thúc đoạn đo, không ghép vào một người mới. |
| IMM-04 | Chỉ đặt lại bộ đếm khi có chuyển động/phục hồi đủ rõ theo cấu hình; tránh nhiễu nhỏ của khớp làm bộ đếm liên tục bị xóa. |
| IMM-05 | Không dùng thay đổi khớp do camera quay làm bằng chứng người chuyển động/phục hồi. Khi chưa bù chuyển động camera được kiểm chứng, tạm ngừng tích lũy ở đoạn quay/ảnh không ổn định, giữ lịch sử và ghi nhận gián đoạn thay vì xóa nghi ngờ. |
| IMM-06 | Khi vượt điều kiện, tạo hoặc cập nhật cảnh báo kèm tư thế, chất lượng quan sát, trạng thái camera, thời lượng quan sát và lý do kích hoạt. Liên kết với sự kiện té ngã trước đó nếu thuộc cùng diễn biến. |

Khi chỉ có ít chuyển động và chưa đủ bằng chứng bất thường, gửi mức “Cần chú ý” để người nhà kiểm tra; không nâng lên khẩn cấp chỉ do hết thời gian. Nằm nghỉ/ngủ bình thường cần được đưa vào đánh giá báo giả khi chưa có vùng.

Không gán các ngưỡng thời gian thành tiêu chuẩn an toàn y khoa. Giá trị mặc định phải được lựa chọn và kiểm chứng trong giai đoạn hiệu chỉnh.

### 4.5. Theo dõi môi trường

| Mã | Yêu cầu |
| :--- | :--- |
| ENV-01 | Đọc và hiển thị nhiệt độ phòng, độ ẩm, thời điểm đo, tình trạng cảm biến và biểu đồ lịch sử. |
| ENV-02 | Đọc tín hiệu cảm biến khí gas, hiển thị loại tín hiệu/đơn vị thực sự hỗ trợ. Chỉ hiển thị PPM khi có quy trình chuyển đổi và hiệu chuẩn được kiểm chứng. |
| ENV-03 | Cấu hình ngưỡng cao/thấp, khoảng duy trì và điều kiện trở về bình thường theo từng đại lượng. Có hysteresis hoặc cơ chế tương đương để tránh bật/tắt báo động liên tục ở sát ngưỡng. |
| ENV-04 | Cảnh báo gas theo chính sách riêng, không chờ xác nhận tư thế, lời hỏi an toàn hoặc phản hồi của người trong phòng. |
| ENV-05 | Giá trị lỗi, quá hạn hoặc cảm biến đang khởi động/chưa sẵn sàng phải được đánh dấu; không thay bằng số 0 và hiển thị như dữ liệu hợp lệ. |
| ENV-06 | Vẫn thu thập và cảnh báo tại chỗ khi mất kết nối backend; gửi bù dữ liệu theo dung lượng bộ đệm khi kết nối trở lại. |

DHT11 và MQ-2 là phương án phần cứng dự kiến từ thiết kế trước; linh kiện, mạch đọc và vị trí lắp cần xác minh trước tích hợp. Không suy luận sàn ướt từ độ ẩm không khí hoặc bảo đảm phát hiện mọi loại khí độc bằng một cảm biến gas.

### 4.6. Lời nhắc theo lịch và phát âm thanh

| Mã | Yêu cầu |
| :--- | :--- |
| AUD-01 | Tạo, sửa, bật/tắt, xóa lịch nhắc một lần hoặc lặp theo ngày trong tuần; ví dụ ăn sáng, uống thuốc hoặc lịch sinh hoạt. |
| AUD-02 | Mỗi lịch có tên, giờ, múi giờ, thiết bị đích, nguồn âm thanh, âm lượng và chính sách khi trễ lịch. Múi giờ mặc định là Asia/Ho_Chi_Minh. |
| AUD-03 | Hỗ trợ nhập văn bản để tạo TTS hoặc chọn/tải lên audio thu sẵn. Cho phép nghe thử trước khi lưu. |
| AUD-04 | Tạo và tải sẵn file TTS/audio về thiết bị trước giờ phát. Giao diện phân biệt lịch đã lưu, nội dung đang chuẩn bị, thiết bị đã sẵn sàng và đồng bộ lỗi. |
| AUD-05 | Thiết bị chạy lịch đã đồng bộ khi mất Internet nếu đồng hồ hợp lệ và file sẵn có. Sau khởi động lại, không phát dồn các lịch đã lỡ; xử lý theo chính sách bỏ qua hoặc phát trong khoảng trễ cho phép. |
| AUD-06 | Người có quyền gửi file/lời nhắn thoại để thiết bị phát theo yêu cầu; hiển thị đã nhận, đang phát, hoàn thành hoặc lỗi. |
| AUD-07 | Hỗ trợ chế độ nhấn để nói, truyền giọng nói trực tiếp một chiều từ web đến loa. Mất phiên/kết nối phải dừng phát; không tự phát lại lời nói cũ khi nối lại. |
| AUD-08 | Ưu tiên cảnh báo an toàn hơn lời nhắc và lời nhắn thông thường. Chỉ một nguồn được quyền phát tại một thời điểm; các lịch trùng được xử lý bằng hàng đợi và hạn phát. |
| AUD-09 | Ghi kết quả thực thi. “Đã phát lời nhắc uống thuốc” không đồng nghĩa người đó đã nghe hoặc đã uống thuốc. |
| AUD-10 | Lệnh phát theo yêu cầu có mã lệnh và hạn hiệu lực; retry không phát lặp ngoài ý muốn. Lệnh đã hết hạn khi thiết bị offline không được phát bù. |

Có thể phát câu hỏi như “Bạn có ổn không?” khi nghi ngờ sự cố, nhưng việc phát xong không xác minh được an toàn. Phiên bản đầu không yêu cầu nút trả lời tại camera và không nhận dạng câu trả lời bằng giọng nói.

### 4.7. Cảnh báo và xử lý sự kiện

**Kênh cảnh báo:** web theo thời gian thực, âm thanh tại thiết bị, Telegram và email đã cấu hình. Email cảnh báo dùng địa chỉ tài khoản đã xác minh; chọn loại sự cố/mức độ và bật/tắt theo từng kênh. Email xác minh/reset tài khoản độc lập với tuỳ chọn nhận cảnh báo. Âm thanh trên trình duyệt cần được người dùng cho phép; giao diện vẫn phải hiển thị cảnh báo khi trình duyệt chặn phát âm thanh.

| Mức | Ý nghĩa và ví dụ |
| :--- | :--- |
| Thông tin | Thay đổi trạng thái, phát lịch nhắc, diễn biến nghi ngờ đã phục hồi |
| Cần chú ý | Môi trường vượt ngưỡng cảnh báo; nghi ngờ cần kiểm tra; thiết bị/cảm biến mất khả năng giám sát |
| Khẩn cấp | Té ngã hoặc bất động đủ điều kiện luật cảnh báo; tín hiệu gas vượt ngưỡng báo động đã cấu hình |

**Vòng đời xử lý:**

| Trạng thái / thao tác | Ý nghĩa |
| :--- | :--- |
| Đang mở | Sự kiện cần được kiểm tra, chưa có người nhận xử lý |
| Đã tiếp nhận | Một người nhận kiểm tra; ghi tài khoản và thời điểm, dừng nhắc chưa có người tiếp nhận |
| Xác nhận an toàn / Đã xử lý | Người có quyền chủ động kết thúc sau khi kiểm tra; có ghi chú kết quả |
| Báo động giả | Người có quyền kết thúc với lý do báo giả để phục vụ đánh giá |

Các quy tắc bắt buộc:

- Trạng thái xử lý của người nhà tách khỏi trạng thái quan sát: đang bất thường, đã phục hồi hoặc thiếu quan sát.
- “Đã tiếp nhận” không đồng nghĩa “đã an toàn” và không tự đóng sự kiện.
- Tắt âm tạm thời là thao tác riêng có thời hạn; không tắt giám sát. Cảnh báo gas đang còn điều kiện kích hoạt không bị tắt vĩnh viễn chỉ vì có người tiếp nhận.
- Khi chưa được tiếp nhận, nhắc lại theo khoảng cấu hình với giới hạn tần suất. Có thể gửi đến danh sách người nhận đã được chủ hộ thiết lập.
- Sự kiện cập nhật dùng cùng mã; mất mạng hoặc gửi lại không tạo nhiều bản ghi/cảnh báo cho cùng một sự cố.
- Nếu đóng sự kiện khi điều kiện vẫn bất thường, giao diện phải nêu rõ và hệ thống tiếp tục đánh giá/tái cảnh báo theo chính sách, không im lặng vô thời hạn.

### 4.8. Lịch sử và bằng chứng sự kiện

| Mã | Yêu cầu |
| :--- | :--- |
| HIST-01 | Lưu mã sự kiện, loại, mức độ, phòng/camera, thời điểm bắt đầu/cập nhật, lý do và trạng thái xử lý. |
| HIST-02 | Lưu trạng thái tracking/chuyển động camera nếu có, phiên bản cấu hình, thời lượng bất động và điểm mô hình nếu có. Điểm mô hình không hiển thị như xác suất chắc chắn khi chưa được hiệu chuẩn. |
| HIST-03 | Giữ ảnh và clip ngắn trước/sau sự kiện bằng bộ đệm có giới hạn. Độ dài clip được cấu hình theo khả năng thiết bị. |
| HIST-04 | Nếu thiếu clip, tải lên thất bại hoặc bằng chứng đã hết hạn, vẫn giữ sự kiện và hiển thị lý do thiếu; không chặn gửi cảnh báo để chờ upload. |
| HIST-05 | Tìm/lọc theo khoảng thời gian, camera, loại, mức độ và trạng thái; xem diễn biến và bằng chứng trong trang chi tiết. |
| HIST-06 | Ghi người tiếp nhận, thời gian phản hồi, thao tác tắt âm, kết quả, ghi chú và lịch sử thay đổi trạng thái. |
| HIST-07 | Có thời hạn lưu và giới hạn dung lượng cho ảnh/clip/audio/log. Khi hết dung lượng, áp dụng chính sách dọn dữ liệu và báo trạng thái; không làm đầy ổ đĩa khiến giám sát dừng. |

### 4.9. Dashboard và tình trạng thiết bị

- Trang tổng quan hiển thị camera/phòng dạng danh sách hoặc thẻ phòng, cảnh báo đang mở, môi trường và lần cập nhật gần nhất.
- Biểu đồ môi trường cho phép xem 24 giờ gần nhất và chọn khoảng thời gian trong dữ liệu còn được lưu. Chỉ hiển thị đại lượng mà thiết bị thực sự hỗ trợ.
- Người có quyền chỉnh ngưỡng AI, khoảng theo dõi xác nhận, chính sách bất động và kênh Telegram từ web qua backend; thiết bị phải kiểm tra và phản hồi phiên bản đã áp dụng. Không thay đổi hợp đồng tiền xử lý/mô hình qua cấu hình nghiệp vụ.
- Tách trạng thái kết nối, khả năng quan sát và tình trạng cảnh báo; không tô “an toàn” chỉ vì chưa nhận sự kiện.
- Khi mất heartbeat quá hạn, backend hiển thị mất kết nối và cảnh báo theo cấu hình; dữ liệu cũ được đánh dấu quá hạn.
- Cảnh báo camera lỗi, cảm biến không cập nhật, thiếu dung lượng và phát âm thanh lỗi theo chức năng đang được bật.
- Màn hình cấu hình hiển thị phiên bản mong muốn và phiên bản thiết bị đang chạy; cho phép thử lại khi đồng bộ lỗi.

## 5. DỮ LIỆU VÀ ĐỒNG BỘ

### 5.1. Các đối tượng dữ liệu chính

| Đối tượng | Nội dung tối thiểu |
| :--- | :--- |
| Tài khoản / quyền | Người dùng, phiên, nhà, thành viên, vai trò, phạm vi camera và lời mời có hạn |
| Phòng / thiết bị | Định danh, hộ gia đình, camera, tính năng hỗ trợ, heartbeat và trạng thái sức khỏe |
| Cấu hình camera / tracking | Camera, phiên bản, chính sách giám sát; chế độ cố định/bám và giới hạn quay khi tính năng được hỗ trợ; không yêu cầu đa giác vùng |
| Chính sách cảnh báo | Ngưỡng, khoảng duy trì, thời gian theo dõi, mức độ, kênh nhận và điều kiện kết thúc |
| Sự kiện | Mã duy nhất, thời gian tại nguồn, thời gian backend nhận, loại, ngữ cảnh, diễn biến và xử lý |
| Bằng chứng | Sự kiện liên quan, loại file, khoảng thời gian, vị trí lưu, trạng thái tải lên và hạn lưu |
| Lịch / tài nguyên âm thanh | Nội dung hoặc file, thiết bị đích, múi giờ, lịch lặp, phiên bản và trạng thái sẵn sàng |
| Lệnh điều khiển | Mã, người gửi, thiết bị đích, thời hạn, trạng thái thực thi và lý do lỗi |

### 5.2. Quy tắc đồng bộ

1. Cấu hình đi từ web qua backend xuống thiết bị; thiết bị kiểm tra, áp dụng và phản hồi phiên bản thực tế. Lỗi áp dụng giữ nguyên bản hợp lệ trước đó.
2. Telemetry định kỳ, sự kiện và lệnh điều khiển là các loại bản tin riêng. Chốt topic/schema cụ thể ở thiết kế kỹ thuật.
3. Cảnh báo tại chỗ không chờ backend hoặc upload media. Sự kiện offline lưu thời điểm xảy ra và gửi bù; web phân biệt sự kiện cũ vừa đồng bộ với sự cố vừa xảy ra.
4. Bộ đệm có hạn, ưu tiên sự kiện và bằng chứng quan trọng hơn telemetry định kỳ. Phải ghi nhận khi có dữ liệu bị bỏ do giới hạn dung lượng.
5. Sau kết nối lại, khử trùng theo mã sự kiện/mã lệnh và kiểm tra phiên bản cấu hình. Không phát lại lệnh âm thanh trực tiếp đã hết hạn.
6. Đồng bộ giờ và kiểm tra tính hợp lệ của đồng hồ trước khi chạy lịch. Nếu chưa xác định được giờ, báo lịch chưa sẵn sàng thay vì phát sai giờ.

## 6. YÊU CẦU PHI CHỨC NĂNG

### 6.1. Hiệu năng và chất lượng AI

- Đo riêng tốc độ xử lý hình ảnh, thời gian phát hiện nghi ngờ, thời gian xác nhận theo chính sách, độ trễ thông báo và độ trễ media.
- Không cam kết báo động dưới một giây khi chính sách có khoảng chờ xác nhận. Độ trễ phải được báo cáo cùng cấu hình, thiết bị và điều kiện mạng.
- Đánh giá theo sự kiện: recall, precision và số báo giả trên giờ giám sát; bổ sung các tình huống cúi người, ngồi xuống, chủ động nằm và nghỉ lâu.
- Đánh giá riêng camera đứng yên và servo đang quay: rung/nhòe, mất khớp, giữ toàn thân, mất dấu và báo giả. Chuẩn hóa pose hiện có không được coi là đã bù chuyển động camera.
- Tách kết quả video thử nghiệm khỏi chạy camera trên thiết bị thật. Chỉ tiêu FPS, ngưỡng chấp nhận chất lượng và độ trễ cụ thể phải được chốt sau đo nền, trước nghiệm thu hiệu năng.
- Không mặc định hỗ trợ nhiều người hoặc mất che khuất dài nếu chưa có kết quả đánh giá tương ứng.

### 6.2. Độ ổn định

- Dịch vụ tự khởi động theo thiết bị và phục hồi sau lỗi; khôi phục cấu hình/lịch hợp lệ đã lưu.
- Xử lý lỗi từng cảm biến hoặc kênh media độc lập để không làm dừng toàn bộ giám sát.
- Mất Internet vẫn duy trì các chức năng cục bộ đã sẵn sàng; truy cập từ xa và thông báo qua Internet có thể gián đoạn và phải được thể hiện rõ.
- Không suy ra thiết bị còn hoạt động khi mất điện. Nếu không có nguồn dự phòng, backend chỉ có thể nhận biết thiết bị mất liên lạc qua heartbeat.

### 6.3. Bảo mật và quyền riêng tư

- Xác thực người dùng, phân quyền theo hộ gia đình/thiết bị và quyền thao tác.
- Bảo vệ API, truy cập camera, ảnh/clip và lệnh phát loa; URL media không trở thành đường dẫn công khai không kiểm soát.
- Dùng kết nối mã hóa cho truy cập qua Internet; thông tin xác thực thiết bị không hiển thị trên frontend hoặc ghi vào log.
- Ghi nhật ký thay đổi cấu hình và thao tác xử lý sự kiện; có chính sách lưu/xóa dữ liệu rõ ràng.
- Chủ hộ chủ động cấu hình người nhận Telegram và việc gửi ảnh sự kiện ra kênh đó; mặc định không gửi media ra ngoài khi chưa thiết lập.

## 7. KỊCH BẢN NGHIỆM THU NGHIỆP VỤ

| Mã | Tình huống | Kết quả cần đạt |
| :--- | :--- | :--- |
| AC-01 | Bật bám một người và người di chuyển trong phạm vi quay | Camera bám trong giới hạn cơ khí, giữ toàn thân khi có thể; phản hồi trạng thái thực từ thiết bị |
| AC-02 | Sửa chính sách khi thiết bị offline | Web báo chờ đồng bộ; thiết bị dùng cấu hình cũ đến khi nhận bản mới hợp lệ |
| AC-03 | Servo quay khi người đứng yên | Không coi dịch chuyển ảnh là người phục hồi; đoạn chưa ổn định được ghi gián đoạn, không cộng vào bất động |
| AC-04 | Người nằm nghỉ/ngủ bình thường, không có vùng | Không tự nâng lên khẩn cấp chỉ do ít chuyển động; đánh giá báo giả và giới hạn ngữ cảnh |
| AC-05 | Người ít chuyển động vượt thời gian cấu hình, không có đoạn ngã | Tạo sự kiện cần kiểm tra kèm tư thế, thời lượng quan sát; không tự gán vị trí sàn/giường |
| AC-06 | Có nghi ngờ té ngã rồi camera quay hoặc mất dấu | Giữ cùng sự kiện và bằng chứng; không tự xóa nghi ngờ hoặc coi đã an toàn |
| AC-07 | Người bị che, rời khung hình hoặc camera đứng hình | Phân biệt mất quan sát/lỗi camera; không cộng thời gian không quan sát thành bất động |
| AC-08 | Cúi người, ngồi ghế, chủ động nằm | Ghi nhận để đánh giá báo giả; không nghiệm thu chất lượng chỉ bằng video ngã |
| AC-09 | Cảm biến vượt ngưỡng, dao động sát ngưỡng, sau đó lỗi | Áp dụng khoảng duy trì/hysteresis; lỗi được đánh dấu thay vì hiển thị bình thường |
| AC-10 | Phát lời nhắc TTS và audio thu sẵn, sau đó mất mạng | Lịch và file đã sẵn sàng vẫn phát; lịch lỡ không phát dồn khi khởi động lại |
| AC-11 | Gửi lời nhắn, retry và gửi khi thiết bị offline | Có phản hồi thực thi; không phát trùng hoặc phát lệnh đã hết hạn |
| AC-12 | Nhấn để nói rồi mất kết nối | Âm thanh trực tiếp dừng, không phát lại dữ liệu cũ khi kết nối lại |
| AC-13 | Cảnh báo xuất hiện trong lúc phát lịch nhắc | Cảnh báo được ưu tiên; ghi kết quả lịch bị gián đoạn/hoãn |
| AC-14 | Người nhà tiếp nhận rồi xác nhận an toàn/báo giả | Các bước được lưu riêng; tiếp nhận không tự đóng sự kiện |
| AC-15 | Mất mạng trong lúc có sự cố, sau đó nối lại | Có cảnh báo tại chỗ, gửi bù đúng thời gian nguồn, không nhân đôi sự kiện |
| AC-16 | Xem lịch sử khi clip thiếu hoặc hết hạn | Vẫn xem được sự kiện, lý do thiếu và lịch sử xử lý |
| AC-17 | Tài khoản ngoài hộ gia đình truy cập camera/media/lệnh loa | Bị từ chối dù biết định danh hoặc đường dẫn tài nguyên |
| AC-18 | Tạo tài khoản mới chưa tham gia nhà nào | Không thấy camera của người khác; có hướng dẫn tạo nhà hoặc nhận lời mời |
| AC-19 | Tham gia hai nhà với quyền khác nhau | Chuyển nhà hiển thị đúng tài nguyên/quyền, không lẫn sự kiện hoặc media giữa hai nhà |
| AC-20 | Dùng mã ghép nối hết hạn, đã dùng hoặc thiết bị thuộc nhà khác | Từ chối đăng ký, không ghi đè sở hữu |
| AC-21 | Thu hồi quyền khi thành viên đang xem live và nhận WebSocket | Ngừng quyền truy cập hiện có và chặn yêu cầu mới |
| AC-22 | Người xem thử xử lý sự kiện, sửa chính sách hoặc phát loa | Bị từ chối ở backend/kênh tương ứng dù tự tạo yêu cầu |

## 8. LỘ TRÌNH TRIỂN KHAI

### Giai đoạn 1 — Camera, ngữ cảnh và cảnh báo cốt lõi

- Xây dựng đăng nhập/đăng ký, nhà/phòng, ghép nối thiết bị và kiểm tra quyền trước khi mở truy cập nhiều tài khoản.
- Hoàn thiện luồng xem camera, trạng thái quan sát và cấu hình chính sách; thử nghiệm servo bám một người, giới hạn quay và xử lý mất dấu.
- Tích hợp mô hình té ngã đã được chọn; đánh giá ảnh hưởng camera quay đến chuỗi AI và bộ đếm bất động, chưa áp dụng luật theo vùng.
- Xây dựng vòng đời sự kiện, cảnh báo web/âm thanh tại chỗ và lịch sử kèm ảnh.
- Thực hiện mốc một camera, một phòng, một người; đo nền trên phần cứng thực tế.

### Giai đoạn 2 — Môi trường, bằng chứng và hỗ trợ sinh hoạt

- Tích hợp nhiệt độ, độ ẩm, gas và quy tắc cảnh báo cảm biến.
- Bổ sung clip trước/sau sự kiện, kênh Telegram và khôi phục đồng bộ offline.
- Hoàn thiện lập lịch TTS/audio, lưu file cục bộ và gửi lời nhắn thoại.
- Kiểm tra phân quyền, lưu trữ, sức khỏe thiết bị và các tình huống lỗi.

### Giai đoạn 3 — Âm thanh trực tiếp và đánh giá hoàn chỉnh

- Tích hợp nhấn để nói một chiều, điều phối loa và kiểm tra truy cập từ xa.
- Đánh giá dài giờ, báo giả, chuyển động servo/mất dấu, điều kiện ánh sáng và độ trễ.
- Chốt chỉ tiêu hiệu năng theo kết quả đo và tài liệu hóa giới hạn vận hành.

Các chức năng trong phạm vi được chia theo thứ tự triển khai, không được hiểu là đã hoàn thành ở thời điểm viết tài liệu. Đàm thoại hai chiều, nút SOS rời, cảm biến ánh sáng/tự bật đèn và mở rộng nhiều người được xem xét sau khi phạm vi này hoạt động ổn định.


## 9. ĐỐI CHIẾU BẢN CŨ VÀ CÁC HƯỚNG MỞ RỘNG

### 9.1. Nguyên tắc hợp nhất

Bản AnNhà v2.1 là nền cho mục 1–8 theo lựa chọn của chủ dự án. Nội dung tương đồng đã được gộp vào các nhóm nghiệp vụ tương ứng; các ý tưởng riêng của bản AIoT được giữ bên dưới để xem xét sau. Các mục mở rộng và con số tham khảo không tự trở thành phạm vi bắt buộc hay tiêu chí nghiệm thu. Mở rộng được chọn cần cập nhật đồng thời phạm vi, thiết kế kỹ thuật và kịch bản nghiệm thu.

| Nội dung từ bản AIoT | Kết quả hợp nhất |
| :--- | :--- |
| Edge AI, giám sát bất động, môi trường, web, Telegram và loa | Giữ trong phạm vi, làm rõ chất lượng quan sát và điều kiện cảnh báo ở mục 3–4 |
| `FN-AI-01`–`FN-AI-03`: pose, chuẩn hóa, phân loại chuỗi | Giữ ở mục 3.1 và `FALL-01`–`FALL-03`; sửa mô tả đặc trưng thành x/y/visibility theo nguồn |
| `FN-AI-04`: chờ phục hồi để giảm báo giả | Gộp vào `FALL-02`–`FALL-06`; phục hồi không tự đóng sự kiện đã cảnh báo |
| `FN-AI-05`: cảnh báo bất động | Gộp vào `IMM-01`–`IMM-06`; ngưỡng theo tư thế/chất lượng quan sát và trạng thái camera; chính sách vùng tạm hoãn, không dùng ngưỡng tuổi làm cam kết an toàn |
| `FN-REM-01`: lịch thuốc và lời nhắc qua loa | Gộp vào `AUD-01`–`AUD-05`; thông báo lịch đến Telegram được giữ là mở rộng ở mục 9.2 |
| `FN-REM-02`: nhắc vận động/uống nước khi ngồi lâu | Lời nhắc theo giờ dùng lịch hiện có; tự suy ra ngồi lâu bằng camera là mở rộng |
| `FN-REM-03`–`FN-REM-04`: cữ sữa, ăn dặm, ngủ và kiểm tra tã | Có thể nhập nội dung lịch chung; chính sách chăm sóc trẻ chuyên biệt là mở rộng |
| `FN-REM-05`: xác nhận đã xong, nhắc lại và cảnh báo trễ | Giữ ý tưởng ở mục 9.2; trạng thái phát audio hiện tại không chứng minh hoàn thành việc |
| ThingsBoard làm trung tâm lịch, cấu hình và xử lý cảnh báo | Thay bằng backend quản lý nghiệp vụ ở mục 3; ThingsBoard là tích hợp tùy chọn, không có nguồn cấu hình độc lập |
| Tiếp nhận cứu hộ đồng thời ngừng chuông / hủy bằng nút | Thay bằng tiếp nhận, tắt âm có hạn và kết thúc sự kiện tách biệt ở mục 4.7; nút vật lý là mở rộng |
| Thẻ phòng, biểu đồ 24 giờ, nhật ký và cấu hình từ xa | Gộp vào mục 4.8–4.9; không hiển thị an toàn chỉ vì chưa có cảnh báo |
| Khởi động lại dịch vụ, offline buffer, xác thực thiết bị và TLS | Gộp vào mục 5–6; không coi dịch vụ hoạt động trong thời gian mất điện |
| Trẻ sơ sinh/cơ sở chăm sóc, ánh sáng/relay, SMS/cuộc gọi và tối ưu phần cứng | Giữ ở mục 9.2; chưa thuộc nghiệm thu ban đầu |

### 9.2. Danh sách mở rộng được giữ lại

| Mã | Hướng mở rộng | Điều kiện cần chốt trước triển khai |
| :--- | :--- | :--- |
| EXT-01 | Chính sách riêng cho trẻ nhỏ/trẻ sơ sinh: ngã từ giường/nôi và bất động theo ngữ cảnh | Dữ liệu, giới hạn quan sát, đánh giá phù hợp đối tượng và ngưỡng riêng; không suy ra hô hấp hay bệnh lý từ pose |
| EXT-02 | Triển khai tại cơ sở chăm sóc, phân công người trực/nhân viên | Vai trò, phạm vi truy cập, bàn giao và quy trình xử lý; không mặc định đã có trong mô hình hộ gia đình |
| EXT-03 | TSL2561 qua I2C, nhận biết phòng tối và bật đèn dẫn đường bằng relay khi có chuyển động | Linh kiện, dải đo, ngưỡng lux, điều kiện chuyển động, điều khiển điện và chế độ thủ công |
| EXT-04 | Nhắc vận động/uống nước theo thời gian ngồi lâu do camera ghi nhận | Phân biệt ngồi, nghỉ và thiếu quan sát; cấu hình thời gian, giờ yên lặng và tránh nhắc lặp |
| EXT-05 | Mẫu lịch cữ sữa, ăn dặm, ngủ và kiểm tra tã; lịch lặp theo chu kỳ | Quy tắc lặp theo khoảng thời gian, chính sách khi trễ và người nhận; không mặc định lịch mẫu phù hợp mọi trẻ |
| EXT-06 | Gửi nhắc việc qua Telegram; nút “Đã xong”, “Nhắc lại sau” và báo trễ cho người thân | Định danh từng lần nhắc, người được phép xác nhận, trạng thái riêng với kết quả phát loa và chống thao tác lặp |
| EXT-07 | Nút xác nhận tại phòng hoặc nút SOS rời/đeo người | Vị trí dễ thao tác, ánh xạ đúng sự kiện/lần nhắc và quyền hủy; không yêu cầu bấm nút trên camera đặt cao |
| EXT-08 | SMS, gọi điện tự động, chuyển tiếp đến người trực hoặc cứu hộ | Dịch vụ, chi phí, người nhận, quy tắc nhắc/escalation và quyền kích hoạt |
| EXT-09 | Dashboard ThingsBoard, Rule Chain, Shared Attributes/RPC | Backend vẫn quản lý cấu hình/lịch/trạng thái xử lý; ánh xạ phiên bản và mã sự kiện, tránh gửi cảnh báo trùng |
| EXT-10 | Đàm thoại hai chiều hoặc tương tác giọng nói | Phần cứng micro, giao thức, phân quyền và giới hạn xác minh; phát câu hỏi không đồng nghĩa đã nhận câu trả lời |
| EXT-11 | Vỏ hộp AIoT tích hợp camera/cảm biến/loa, tối ưu NCNN hoặc Raspberry Pi AI HAT/NPU | Thiết kế phần cứng, tản nhiệt, tương thích artifact và đo lại chất lượng/hiệu năng |
| EXT-12 | Bản đồ mặt bằng phòng và giám sát nhiều người | Mô hình bố trí, quyền hiển thị, theo dõi từng người và đánh giá riêng; mốc nghiệm thu một người chưa bao phủ tính năng này |

### 9.3. Tham số và chỉ tiêu từ bản cũ cần hiệu chỉnh

Các giá trị sau được lưu để không mất đề xuất thiết kế. Chưa dùng làm mặc định đã phê duyệt, kết quả đo hoặc tiêu chuẩn an toàn; giá trị có trong cấu hình mã nguồn cũng không chứng minh đã được kiểm chứng thực tế.

| Nhóm | Đề xuất ở bản cũ | Cách xử lý trong bản hợp nhất |
| :--- | :--- | :--- |
| Xác nhận té ngã | Chờ 3–5 giây, đồng thời yêu cầu báo động ≤ 1 giây từ khi chạm đất | Tách phát hiện nghi ngờ, xác nhận và thông báo theo mục 6.1; không giữ hai cam kết mâu thuẫn |
| Bất động người cao tuổi | Có chỗ nêu 30 giây ở mức cam, có chỗ nhắc sau 1 phút; khẩn cấp sau 2–3 phút | Chưa chọn một ngưỡng chung; cần hiệu chỉnh theo tư thế, trạng thái camera và chất lượng quan sát |
| Bất động trẻ nhỏ | 30–60 giây | Chỉ tham khảo cho EXT-01, không là ngưỡng bảo đảm an toàn hoặc suy luận ngạt thở |
| Nhắc vận động | Ngồi lâu 90–120 phút | Đầu vào xem xét cho EXT-04 |
| Lịch chăm sóc và phản hồi | Cữ sữa 2–3 giờ; nhắc lại sau 10 phút; báo trễ sau 15 phút | Đầu vào xem xét cho EXT-05–EXT-06; phải cấu hình thay vì áp dụng cứng |
| DHT11 | Đọc mỗi 10–30 giây; cảnh báo dưới 16°C, trên 35°C hoặc độ ẩm trên 85% | Chốt theo cảm biến và điều kiện vận hành; không suy luận sàn ướt hay tình trạng sức khỏe từ số đo phòng |
| TSL2561 | Dải 0,1–40.000 lux, coi tối khi dưới 5 lux | Đề xuất cho EXT-03; xác minh linh kiện và phép đo trước khi sử dụng |
| MQ-2 | Cảnh báo trên 400 PPM; mô tả phát hiện nhiều khí/khói | Chỉ áp dụng đơn vị/ngưỡng sau hiệu chuẩn phù hợp; không bảo đảm nhận diện mọi khí độc |
| Hiệu năng | Camera 640×480; 15–20 FPS; MQTT ≤ 200 ms | Mục tiêu đo nền cần chốt cùng phần cứng, mạng và cách đo; không phải kết quả đã đạt |
| Chất lượng AI | Recall ≥ 92%, false positive rate ≤ 5% | Cần dữ liệu, cách chia tập và định nghĩa mẫu số; bổ sung precision và báo giả/giờ theo mục 6.1 |
| Điểm AI và schema cũ | Ví dụ `fall_confidence: 95.58`, cấu hình ngưỡng 0,85–0,90, gộp sự kiện/cảm biến trong telemetry | Không sao chép thành schema hiện hành; quy định rõ thang điểm, tách loại bản tin và dùng hợp đồng tại DEVICE_API |
| Phần cứng/mô hình | 4 attention head, artifact 313 KB, gói pose 3–5 MB, ARM NEON/XNNPACK | Thông tin thiết kế cũ; cần đối chiếu artifact/runtime và đo thực tế trước khi công bố |

### 9.4. Việc cần chốt trước nghiệm thu

- Chọn linh kiện, mạch đọc và quy trình hiệu chuẩn cảm biến; chốt ngưỡng, khoảng duy trì và điều kiện trở về bình thường.
- Chọn ngưỡng AI, khoảng theo dõi xác nhận và chính sách bất động theo tư thế/chất lượng quan sát trên dữ liệu đánh giá phù hợp, có tình huống camera quay.
- Chốt FPS, độ trễ, recall/precision và giới hạn báo giả theo phép đo trên thiết bị thực tế.
- Chỉ đưa từng mục EXT vào phạm vi khi đã xác định thiết kế, người dùng/quyền liên quan và kịch bản nghiệm thu tương ứng.

### 9.5. Khoanh vùng và panorama — tạm hoãn, có thể đưa lại

Theo quyết định ngày 29/10/2026, khoanh vùng không còn là yêu cầu triển khai hay nghiệm thu hiện tại. Cơ chế cũ gồm vẽ đa giác giường/sofa/ghế/sàn/vùng bỏ qua trên ảnh, chính sách theo vùng/giờ, kiểm tra chồng lấn và đồng bộ phiên bản; các mã `ZONE-01`–`ZONE-07` chỉ được bảo lưu để truy vết.

Có thể xem xét đưa lại sau khi servo tracking và AI chạy ổn định:

- Chọn phương án vùng theo góc camera đã hiệu chỉnh hoặc vùng trên panorama của phòng; panorama là ảnh tham chiếu, không tự cung cấp vị trí người trong phòng.
- Kiểm chứng ánh xạ từ ảnh hiện tại về hệ tham chiếu phòng, sai số góc/độ rơ servo, thị sai, thay đổi bố trí và vị trí lắp camera.
- Phân biệt được nghỉ trên giường/sofa với nằm trên sàn qua tư thế, vị trí và tính liên tục; vùng nghỉ không được tự hủy nghi ngờ té ngã.
- Thiết kế lại quy tắc vùng bỏ qua, chồng lấn, thời gian theo vùng, phiên bản và phản hồi thiết bị; bổ sung kịch bản nghiệm thu trước khi kích hoạt.

UI/API chỉnh vùng đã được gỡ, quyền sửa vùng không còn được cấp. Khi backend khởi động, camera còn vùng được cấp revision mới với `zones: []`, `reference: {}` và chờ thiết bị ACK; cả cấu hình đọc ra lẫn revision mới đều không chứa vùng hoạt động. Lịch sử cấu hình/sự kiện vẫn được giữ; thiết bị offline chỉ xóa vùng đã cache sau khi nhận và áp dụng cấu hình mới.
