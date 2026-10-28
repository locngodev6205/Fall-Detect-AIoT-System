# Hợp đồng tích hợp thiết bị AnNhà

Tài liệu cho firmware/agent tại Pi; đây là giao thức đã có ở backend, không khẳng định mã AI/thiết bị hiện tại đã thực thi tất cả chức năng.

## 1. Cấp và ghép nối

Quản trị chạy `docker compose exec backend python -m src.provision --name "Camera phòng khách"`. Giữ `device_token` tại thiết bị; mã ghép nối dùng một lần, hết hạn sau 30 phút. Chủ nhà đăng nhập web, tạo phòng và nhập mã. Trước khi được claim, credential không truy cập được device API.

Tất cả HTTP device API dùng header `Authorization: Bearer <device_token>`. Base URL mặc định trên máy chạy Docker: `http://localhost:8188`; thiết bị LAN cần cấu hình truy cập an toàn và địa chỉ mạng thực tế, không dùng localhost của Pi để chỉ backend ở máy khác. Không ghi token vào log hoặc commit Git.

## 2. Heartbeat và cấu hình

`POST /api/device/heartbeat` mỗi khoảng 15 giây:

```json
{"observation":"clear","capabilities":{"camera":true,"speaker":true,"sensors":true}}
```

Observation hỗ trợ: `unknown`, `clear`, `no_person`, `occluded`, `camera_error`. Sau 45 giây không có heartbeat, web coi trạng thái kết nối là quá hạn.

`GET /api/device/config` trả phiên bản mới nhất, zones, reference, reminders và environment policy. Thiết bị cần:

1. Tải, kiểm tra và áp dụng nguyên khối; không thay đổi mô hình/tiền xử lý chỉ để phù hợp payload.
2. Tải file audio/TTS từ `GET /api/device/assets/{asset_id}` khi file sẵn sàng; lưu cục bộ cho lịch offline.
3. Lưu cấu hình bền vững. Chỉ phản hồi thành công khi các module liên quan thực sự sử dụng được cấu hình.
4. `POST /api/device/config/ack` với `{"version":2,"success":true}`; lỗi dùng `success:false,error:"..."`. Backend không tự tăng applied version theo thời gian.

Vùng dùng đa giác tọa độ 0–1 theo khung hình, loại `bed/sofa/chair/floor/ignore`, ngưỡng trong/ngoài lịch. Thiết bị phải kiểm tra góc nhìn, tư thế, chất lượng quan sát và tính liên tục; không tự coi vùng nghỉ là miễn phát hiện ngã.

## 3. Sự kiện và bằng chứng

`POST /api/device/events`:

```json
{
  "event_id":"edge-unique-001",
  "sequence":1,
  "kind":"immobility",
  "severity":"critical",
  "observed_at":"2026-10-28T10:00:00+07:00",
  "observation":"abnormal",
  "reason":"Nằm trên sàn vượt ngưỡng cấu hình",
  "duration_s":120,
  "config_version":2,
  "zone_id":"floor-1"
}
```

- `kind`: fall, immobility, environment, device. `severity`: info, warning, critical.
- `observation`: suspected, abnormal, recovered, unknown.
- Mã nguồn ổn định cho cùng diễn biến; tăng sequence khi cập nhật. Retry cùng sequence không tạo sự kiện thứ hai. Backend trả `id` nội bộ, sequence đã lưu và `stored:true` để xác nhận outbox.
- Không gửi home_id: backend suy ra nhà/camera từ credential. Không được ghi sự kiện cho camera khác.
- Phục hồi cập nhật cùng source ID với sequence cao hơn và observation recovered. Trạng thái người nhà xử lý vẫn độc lập. Cập nhật abnormal mới sau khi đã đóng có thể mở lại sự kiện.

Upload bằng chứng bằng `POST /api/device/evidence?event_id=<id nội bộ>`; body là file nhị phân, `Content-Type` tương ứng và tùy chọn `X-File-Name` URL-encoded. Hỗ trợ JPEG/PNG, MP4/WebM. Ảnh không gắn event là snapshot, không được coi là clip sự kiện. Metadata cảnh báo gửi trước, file có thể upload sau.

File tối đa 25 MB; tổng media mỗi nhà mặc định 512 MB. Khi backend từ chối upload, giữ sự kiện và báo trạng thái thiếu bằng chứng; không giữ retry không giới hạn đến khi đầy bộ nhớ.

## 4. Telemetry

`POST /api/device/telemetry`:

```json
{
  "message_id":"sensor-unique-001",
  "observed_at":"2026-10-28T10:00:00+07:00",
  "readings":{
    "temperature":{"value":28,"unit":"C","quality":"valid"},
    "humidity":{"value":65,"unit":"%","quality":"valid"},
    "gas":{"value":320,"unit":"ADC","quality":"valid"}
  }
}
```

`quality`: valid, error, warming_up. Giá trị lỗi có thể null; không thay bằng 0. PPM chỉ dùng khi thực sự đã hiệu chuẩn. Backend lưu dữ liệu gửi bù, nhưng chỉ đánh giá luật môi trường cho số đo trong khoảng 120 giây so với giờ máy chủ; edge chịu trách nhiệm cảnh báo offline và gửi sự kiện tương ứng.

Cùng message_id chỉ được lưu/đánh giá một lần. Backend áp dụng hold/hysteresis theo policy; khi trở về bình thường cập nhật observation của cùng sự kiện, không tự xác nhận người nhà đã xử lý.

## 5. Lịch và lệnh phát

Lịch nằm trong config và gồm múi giờ, giờ, weekdays (0 = thứ Hai, 6 = Chủ nhật), once_date, enabled, asset_id, volume, version và late_seconds.

- Scheduler tại thiết bị phải có đồng hồ hợp lệ, lưu config/file và định danh lần phát qua restart.
- Ưu tiên cảnh báo tại chỗ hơn phát theo yêu cầu/lịch. Không trộn nguồn cùng lúc, không phát dồn lịch lỡ.
- Sau thực thi, `POST /api/device/executions` với `reminder_id`, `occurrence` (ví dụ mã lịch + version + thời điểm dự kiến), `status` played/failed/skipped và detail. Cùng occurrence không ghi lặp.
- Không báo played khi chỉ tải file hoặc nhận lịch; không suy ra người dùng đã uống thuốc.

Lệnh thủ công: `GET /api/device/commands`. Trả những lệnh pending/accepted chưa hết hạn, gồm ID, kind, payload, expires. Xử lý theo ID và lưu chống lặp tại thiết bị.

`POST /api/device/commands/{id}/ack`: status accepted → executing → executed hoặc failed; gửi detail khi lỗi. Không chạy lệnh đã hết hạn trước khi bắt đầu. Lệnh silence từ sự kiện chỉ có thời hạn và không được vô hiệu cảnh báo gas tại chỗ đang còn điều kiện.

## 6. Hình ảnh và audio trực tiếp

WebSocket device dùng header Authorization như HTTP:

- `/ws/device/frames`: gửi frame JPEG nhị phân, tối đa 1 MB/frame, khoảng 5 FPS. Backend chuyển cho người xem đã có quyền. Không lưu luồng liên tục thành NVR; bằng chứng sự kiện upload riêng.
- `/ws/device/audio`: kết nối bộ nhận loa. Backend gửi JSON `{"type":"start","mime":"audio/webm"}` hoặc audio/ogg, sau đó các chunk nhị phân theo thứ tự và `{"type":"stop"}` khi kết thúc.
- Bộ nhận phải giải mã/phát được định dạng, phối hợp ưu tiên với cảnh báo và dừng khi mất socket/nhận stop. Không phát lại chunk cũ khi nối mạng.
- Một thiết bị có tối đa một audio peer và một người truyền; phiên từ trình duyệt tối đa 60 giây. Không có peer hoặc đang bận thì từ chối phiên mới. Không có âm thanh từ phòng gửi ngược về web.
- Khi quyền/session bị thu hồi, backend đóng media. Trình duyệt phân biệt frame mới với ảnh cũ; không nhận frame thì không hiện LIVE.

Đây là relay WebSocket qua cùng reverse proxy, không yêu cầu mở cổng Pi hoặc thiết lập WebRTC/TURN trong bản hiện tại.

## 7. Tương thích MQTT với module AI hiện có

Topic nội bộ `smartfall/alerts` cần `device_token` và thông tin sự kiện. Gateway suy ra camera từ token, không tin device_id/home_id tự khai. Dạng payload legacy FALL_DETECTED/PROLONGED_IMMOBILITY_DETECTED được chuyển thành schema sự kiện; cần event_id ổn định và timestamp có múi giờ.

`fall_detect/config.py` đọc DEVICE_TOKEN từ `.env`; hai hàm publish bổ sung token và UUID. Mô hình, ngưỡng và tiền xử lý không đổi. Không công khai broker anonymous; triển khai LAN/Internet cần xác thực broker, ACL và mã hóa riêng. Tắt nhánh Telegram trực tiếp trong module AI nếu backend đã phân phối Telegram để tránh gửi trùng.
