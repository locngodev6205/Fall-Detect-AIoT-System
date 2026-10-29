# Giao diện khi chưa kết nối Raspberry Pi — 29/10/2026

## Kết quả và dữ liệu demo

Khôi phục ảnh `frontend/public/images/living.png`, `bedroom.png`, `entrance.png` từ thiết kế Calm Home. Không tạo ảnh phòng bằng các hình khối nữa. Ảnh minh hoạ thuộc frontend, không được coi là snapshot hay bằng chứng từ camera.

Đã giữ **2 nhà demo, mỗi nhà 4 phòng/camera mô phỏng**: phòng khách, phòng ngủ, cửa chính, sân sau. Sân sau dùng lại ảnh cửa chính như nguồn ảnh sẵn có của bản thiết kế. Seed UUID ổn định, giữ tài khoản/mật khẩu và dữ liệu khác. Bốn tài khoản vẫn ở `.secrets/demo-credentials.json`; caregiver có bốn camera của nhà A, viewer chỉ có phòng khách, outsider chỉ có nhà B. Không xoá nhà/tài khoản cũ đã import từ SQLite.

Seed hiện có 24 sự kiện mẫu, 384 batch số đo, 8 lịch nhắc/audio mẫu trong hai nhà demo. Không phát heartbeat giả để làm các camera này online. File ảnh hình khối từ lần seed trước còn được giữ trong media lịch sử, nhưng bị loại khỏi endpoint snapshot và không được hiển thị như ảnh thiết bị.

## Các bước đã kiểm tra trực quan

1. **Tổng quan desktop — đã sửa:** ảnh phòng khách lớn và bốn thumbnail, khung hình có tỷ lệ ổn định; chọn phòng đổi preview đúng phòng. Nhãn ảnh minh hoạ, chờ ảnh, ảnh gần nhất và trực tiếp tách biệt. Thời gian sự kiện không còn dính vào tiêu đề. CSS nền được nạp trước CSS nghiệp vụ để không ghi đè spacing/format sau khi build.
2. **Camera/phòng mới/nhà trống — đã sửa:** phòng chưa ghép nối vẫn có ảnh gốc, trạng thái và thao tác ghép nối; tên phòng mới không nhận diện được dùng ảnh phòng khách. Chủ nhà xem được các phòng chưa có camera; người được chia sẻ chỉ thấy camera trong phạm vi của mình.
3. **Môi trường, lịch nhắc, thiết bị và quyền — đã rà soát:** số đo được định dạng gọn, có thời điểm đo/quá hạn; kết quả command ACK dạng JSON được render bằng nội dung `detail`; không gây trang trắng. Luồng nói trực tiếp bị vô hiệu khi thiết bị offline, còn chuẩn bị audio/lịch vẫn dùng được.
4. **Mobile — đã sửa:** thumbnail, tiêu đề/hành động và thẻ sự kiện/lịch nhắc co giãn theo màn hình; bảng số đo cuộn trong khung riêng. Bộ kiểm tra trình duyệt kiểm tra tràn ngang và lỗi JavaScript.
5. **Làm mới/lỗi API — đã sửa:** giữ nội dung đã tải khi refresh nền hoặc lỗi tạm thời, có thông báo/thử lại. Đổi nhà/401/403/404 vẫn xoá dữ liệu không còn được phép xem. Lỗi render có fallback ở cấp trang.

Ảnh chụp thực tế và `checks.json` được sinh vào `artifacts/ui-review/` bởi `npm run test:ui`. Đã lưu bản trước khi sửa, bản sau và các màn hình/phân quyền/trạng thái trống để đối chiếu. Thư mục này bị gitignore và không nằm trong Docker build context. Ảnh viewport/full-page mobile có thanh điều hướng cố định; ảnh full-page có thể thấy thanh này tại vị trí cuối viewport đầu tiên.

## Quy tắc ảnh và trạng thái

| Tình trạng | Hình ảnh | Nhãn |
|---|---|---|
| Phòng chưa ghép nối | Ảnh gốc theo tên phòng, hoặc phòng khách mặc định | Chưa ghép nối camera + Ảnh minh hoạ |
| Camera chưa gửi ảnh | Ảnh gốc | Chưa kết nối / Đang chờ hình + Ảnh minh hoạ |
| Có snapshot thật nhưng chưa nhận frame mới | Snapshot do thiết bị gửi | Ảnh gần nhất + thời điểm nhận |
| Đang nhận frame | Frame qua WebSocket được xác thực | Đang nhận hình trực tiếp |
| Luồng ngừng gửi quá 5 giây | Giữ frame cuối, không giả chuyển động | Bỏ nhãn trực tiếp, hiện Ảnh gần nhất và timestamp |
| Quyền bị thu hồi/đổi camera | Ngừng socket và bỏ ảnh cũ | Fallback hoặc trang không có quyền |

`CameraImage` chỉ mở socket hình khi backend báo camera online. Thumbnails tĩnh không mở thêm socket/database connection. `snapshot_available` giúp tránh liên tục gọi endpoint không có ảnh. Ảnh placeholder không đổi trạng thái `online`, cấu hình đã áp dụng, quan sát AI hay kết quả đã phát.

`is_demo` được backend suy ra từ ID fixture đã seed, không dựa vào việc người dùng đặt tên camera hay source_id sự kiện. Flag này chỉ dùng để trình bày, không cấp quyền. **Cảnh báo thật trong nhà demo vẫn nổi bật**, không bị banner demo che hoặc bỏ qua.

## Rà soát backend

- Không đổi schema, tài khoản runtime, RLS hay cơ chế session/CSRF hiện có. Không dùng owner credential trong runtime.
- API camera có `snapshot_available`/`is_demo`; nhà/sự kiện có `is_demo`. Snapshot loại ảnh seed minh hoạ và ảnh đã hết hạn; vẫn yêu cầu quyền camera và chỉ trả file local đã ánh xạ.
- Ingest kiểm tra camera còn hoạt động sau khi lấy row lock, tránh race giữa xác thực thiết bị và thu hồi camera.
- Telemetry hiển thị theo `observed_at` mới nhất, không nhầm số đo cũ vừa gửi bù thành mới nhất. Frontend kiểm tra quá hạn theo thời điểm đo. Sai đơn vị cảm biến bị từ chối 422 trước khi ghi DB.
- Các kiểm tra PostgreSQL bao gồm quyền theo nhà/camera, revocation, event sequence/idempotency/realtime, cấu hình/ACK, command/file/audio/ACK, snapshot thật so với demo, relay JPEG/audio, môi trường hold/hysteresis và telemetry gửi bù.

## Chạy kiểm tra lại

```bash
npm run build
npm run test:frontend
# Sử dụng Chrome cài trên macOS; máy khác có thể đặt CHROME_EXECUTABLE,
# hoặc cài browser cho Playwright: npx playwright install chromium.
npm run test:ui
python3 -m unittest backend.tests.test_business -q
# Chỉ chạy với credentials của branch thử, không dùng production:
ANNHA_TEST_ENV=.secrets/neon-test-runtime.env python3 -m unittest backend.tests.test_postgres -v
```

Playwright đăng nhập bằng tài khoản demo đã seed và đọc web tại `http://localhost:8188`. Các trường hợp phòng mới, nhà trống, API 503, ACK object, cảnh báo thật trong nhà demo và luồng ngừng gửi dùng fixture **chỉ trong trình duyệt**; không đổi trạng thái thiết bị/database thật. Các API/relay PostgreSQL được kiểm tra riêng trên branch Neon. Script không gửi email ngoài hay xin quyền microphone/camera của máy.

## Giới hạn

Đã kiểm tra bằng browser và API; chưa đo luồng camera/cảm biến/loa/servo từ Pi thật. Không xác nhận tương thích hardware hoặc độ chính xác AI từ dữ liệu mẫu. Cloudinary vẫn hoãn; media thật vẫn dùng volume local. Bộ test không thay cho load test, restore backup hoặc kiểm tra accessibility đầy đủ bằng thiết bị hỗ trợ.

## Kết quả kiểm chứng trong lần sửa này

- `npm run build`: PASS; bản cuối build thành công.
- Browser desktop 1440×1000 và mobile 390×844: 22 tình huống PASS trên bản sửa CSS; không có lỗi JavaScript chưa xử lý. Kiểm tra riêng cuối cùng cho lỗi tải danh sách nhà/thử lại và trạng thái ghép nối/offline được lưu trong `.secrets/ui-final-focus.log`; testcase khởi động cũng đã được thêm vào `test:ui` để chạy lại sau này.
- Ba kiểm tra frontend thuần PASS: ảnh nguồn/phòng mới, phạm vi phòng chưa ghép nối và nhãn offline.
- PostgreSQL branch thử: 7 testcase PASS trong 193,916 giây; thêm testcase telemetry gửi bù/sai đơn vị PASS trong 16,742 giây (8 tình huống tổng cộng).
- Regression SQLite: 8 testcase PASS trong 15,023 giây.
- Backend/frontend/MQTT/Mailpit đều healthy; health HTTP qua web trả `database=postgres`, `database_connected=true`, `mqtt_connected=true`.

Log đầy đủ ở `.secrets/ui-*.log`; ảnh và JSON ở `artifacts/ui-review/`. Các testcase có API override hoặc stream một frame là mô phỏng trong browser; kết quả không được dùng để khẳng định đã có camera Pi thật.

## Cập nhật giao diện sử dụng thông thường

Theo yêu cầu tiếp theo, UI không còn banner/nhãn/tiền tố Demo; tên dữ liệu seed đã chuẩn hoá nhưng tài khoản đăng nhập và cấu trúc 2 nhà/4 phòng mỗi nhà vẫn giữ nguyên. Mọi sự kiện mở dùng cùng luồng xử lý, không lọc theo flag fixture. Ảnh minh hoạ và trạng thái kết nối vẫn được ghi đúng. Trang chọn nhà đã thêm ảnh bìa và metadata phù hợp quyền. Xem [PERFORMANCE_AND_UI_REVIEW.md](PERFORMANCE_AND_UI_REVIEW.md) để biết kết quả mới và tối ưu tốc độ.


## Bổ sung luồng sử dụng 29/10/2026

Phân trang cho danh sách dài, bộ lọc sự kiện theo phòng/camera/thời gian, biểu đồ môi trường, đăng xuất riêng, thiết lập thiết bị sau và lưu trữ nhà đã có. Form lịch nhắc hỗ trợ nghe thử TTS/file âm thanh và ghi âm trực tiếp, không cần camera đang online. Lịch sử hoạt động/thông báo trong cài đặt đóng mặc định và dùng diễn đạt dễ hiểu; mục phòng có padding và khoảng cách trước/sau riêng. Chi tiết kiểm chứng và giới hạn test microphone giả xem `PERFORMANCE_AND_UI_REVIEW.md`.
