# Trạng thái triển khai AnNhà — 28/10/2026

## Bản chạy hiện tại

- Frontend React/Vite dùng thiết kế, font, ảnh landing và CSS Calm Home từ ZIP.
- Backend nghiệp vụ FastAPI/SQLite, dùng session cookie HttpOnly và CSRF; không còn endpoint cảnh báo công khai cho mọi nhà.
- Docker gồm frontend/nginx, backend, MQTT và Mailpit. Web **8188**, hộp thư thử **8125**; cổng phát triển dành riêng **5188/8018**. Không sử dụng 5173.
- ZIP nguyên bản nằm tại `archives/source-imports/AnNha-website.zip`, được gitignore.

## Kiểm tra đã thực hiện

- Build frontend bằng Vite và build hai image Docker.
- Khởi chạy stack Compose với volume bền vững, health check frontend/backend.
- Bảy test nghiệp vụ tích hợp: auth/CSRF/reset, mời/thu hồi thành viên, ghép nối, phiên bản vùng, event upsert/xử lý/WebSocket, media/file/lệnh/lịch, quyền thiết bị, luật môi trường và lưu lịch sử sau gỡ camera.
- Bốn test đóng gói tĩnh được giữ từ ZIP.
- Chrome headless với profile tạm: landing → đăng ký → nhận email thật trong Mailpit cục bộ → xác minh → đăng nhập → tạo nhà/phòng → ghép nối → vẽ/lưu vùng → giữ trạng thái chờ thiết bị → tạo TTS thật và tải file WAV → tổng quan desktop/mobile.
- Kiểm tra màn hình mobile 390 px không có tràn ngang, không ghi nhận JavaScript exception trong hành trình trên.
- Broker MQTT trong Docker: nhận sự kiện có token đúng, ràng buộc camera theo credential, khử trùng khi gửi lại và từ chối token sai.
- Test media chỉ kiểm tra giao thức và quyền bằng dữ liệu thử; không dùng camera hoặc microphone cá nhân.

Các tài khoản/nhà/camera tên “kiểm thử” trong volume cục bộ là dữ liệu QA của lần kiểm tra, không phải thiết bị gia đình đã được kết nối. Không tự cấp một tài khoản mặc định cho người dùng.

## Phần đã có hợp đồng nhưng cần tích hợp/kiểm thử thiết bị

- Pi phải lấy cấu hình, áp dụng vùng vào AI và phản hồi đúng phiên bản. Luật bất động cũ trong `fall_detect` chưa tiêu thụ vùng; không xác nhận đã hoàn thành giám sát theo ngữ cảnh đầu-cuối.
- Scheduler trên edge phải tải và giữ audio, xử lý lịch theo múi giờ, phát offline và gửi execution report; backend không tự giả lập “đã phát”.
- Camera phải gửi JPEG/snapshot; bộ nhận audio phải giải mã và phát đúng nguồn, ưu tiên cảnh báo tại chỗ. Backend có relay xác thực; chưa xác nhận chất lượng trên phần cứng Pi/loa thật.
- Cảm biến phải gửi số đo và quality hợp lệ; không gắn PPM nếu chưa hiệu chuẩn.
- Telegram cần cấu hình bot/người nhận và sự đồng ý chia sẻ ảnh. Chưa gửi kiểm thử đến Telegram bên ngoài trong lần triển khai này.
- Chưa đánh giá recall/báo giả, FPS AI, độ trễ video/audio, mất mạng/nguồn hoặc runtime dài giờ trên Pi.

Xem [README](../README.md), [Architecture](ARCHITECTURE.md), [Device API](DEVICE_API.md) và [Specification](PROJECT_SPECIFICATION_ANNHA.md).
