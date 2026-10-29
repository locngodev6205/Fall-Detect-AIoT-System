# Trạng thái triển khai AnNhà — cập nhật 29/10/2026

## Thay đổi phạm vi ngày 29/10/2026

- Tạm bỏ khoanh vùng khỏi yêu cầu triển khai/nghiệm thu; có thể đưa lại sau khi servo tracking ổn định theo [đặc tả](PROJECT_SPECIFICATION.md).
- Đã gỡ UI và API chỉnh vùng, quyền sửa vùng và nội dung landing liên quan. Backend trả vùng rỗng, thêm revision xóa vùng một lần cho cấu hình cũ khi khởi động, giữ lịch sử và chờ ACK thiết bị.
- Các kiểm tra ngày 28/10 bên dưới là bằng chứng lịch sử cho phiên bản trước khi gỡ vùng. Servo tracking chưa được triển khai/kiểm chứng.

## Bản chạy hiện tại

- Frontend React/Vite dùng thiết kế, font, ảnh landing và CSS Calm Home từ ZIP.
- Backend nghiệp vụ FastAPI/SQLite, dùng session cookie HttpOnly và CSRF; không còn endpoint cảnh báo công khai cho mọi nhà.
- Docker gồm frontend/nginx, backend, MQTT và Mailpit. Web **8188**, hộp thư thử **8125**; cổng phát triển dành riêng **5188/8018**. Không sử dụng 5173.
- ZIP nguyên bản nằm tại `archives/source-imports/AnNha-website.zip`, được gitignore.

## Kiểm tra thay đổi bỏ khoanh vùng — 29/10/2026

- Tám test nghiệp vụ backend đạt, bao gồm API vùng trả 404, từ chối quyền vùng, lọc cấu hình cũ, thêm revision khi khởi động, chống lặp và giữ lịch sử; kiểm tra lại riêng test di trú sau khi bổ sung tình huống khởi động.
- Build production frontend đạt. Chrome headless với profile/database tạm: landing, camera desktop/mobile 390 px, quyền thành viên và đường dẫn vùng cũ; không có JavaScript exception, mobile không tràn ngang. Sửa chiều rộng khung camera khi chưa có ảnh trong quá trình kiểm tra.
- Docker daemon chưa chạy nên chưa rebuild/khởi động stack Compose trong lần sửa này. Chưa kiểm chứng thiết bị thật nhận revision xóa vùng hoặc servo tracking.

## Kiểm tra lịch sử ngày 28/10/2026

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

- Pi phải lấy cấu hình còn trong phạm vi và phản hồi phiên bản thực sự áp dụng. Tích hợp vùng vào AI đã tạm hoãn; thiết bị từng cache vùng phải áp dụng revision rỗng mới để xóa vùng.
- Servo tracking cần tích hợp điều khiển, giới hạn quay, mất dấu và trạng thái camera; phải đánh giá lại AI/bộ đếm bất động khi camera quay, chưa coi luồng này đã chạy đầu-cuối.
- Scheduler trên edge phải tải và giữ audio, xử lý lịch theo múi giờ, phát offline và gửi execution report; backend không tự giả lập “đã phát”.
- Camera phải gửi JPEG/snapshot; bộ nhận audio phải giải mã và phát đúng nguồn, ưu tiên cảnh báo tại chỗ. Backend có relay xác thực; chưa xác nhận chất lượng trên phần cứng Pi/loa thật.
- Cảm biến phải gửi số đo và quality hợp lệ; không gắn PPM nếu chưa hiệu chuẩn.
- Telegram cần cấu hình bot/người nhận và sự đồng ý chia sẻ ảnh. Chưa gửi kiểm thử đến Telegram bên ngoài trong lần triển khai này.
- Chưa đánh giá recall/báo giả, FPS AI, độ trễ video/audio, mất mạng/nguồn hoặc runtime dài giờ trên Pi.

Xem [README](../README.md), [Architecture](ARCHITECTURE.md), [Device API](DEVICE_API.md) và [Specification](PROJECT_SPECIFICATION.md).


## Database/cloud tools và Docker — 29/10/2026

- Thiết kế, SQL và hướng dẫn đầy đủ: [DATABASE_DESIGN_NEON.md](DATABASE_DESIGN_NEON.md); `.env.example` tách cấu hình có hiệu lực hiện tại khỏi cấu hình adapter dự kiến.
- PostgreSQL lab Docker riêng có 39 bảng; 46 kiểm tra SQL/RLS đạt. Hai image db-tools/cloudinary-tools build thành công, 9 kiểm tra công cụ Cloudinary đạt với mock/cấu hình giả.
- Frontend/backend hiện đã rebuild và healthy; giữ volume SQLite/media, MQTT và Mailpit. Ghi nhận Docker daemon chưa chạy ở lần sửa trước không còn là trạng thái hiện tại.
- Chưa tạo Neon project, chưa dùng Cloudinary credential thật, chưa upload media hoặc port adapter backend sang cloud.


## Mở rộng schema email và chuẩn bị Neon — 29/10/2026

- Migration `005_email_notifications.sql` nâng schema lên 40 bảng (25 nghiệp vụ/15 private); không reset bảng cũ. Cảnh báo email dùng tài khoản đã xác minh, phiên bản địa chỉ, bộ lọc sự cố/mức độ và suppression.
- Thêm receipt nhà cung cấp, phân biệt accepted/delivered/bounced/complained/rejected; app không được tạo receipt hoặc tự bỏ suppression.
- 73 kiểm tra SQL đạt trên Docker lab sau nâng cấp; bootstrap nguyên tử từ database mới cũng được kiểm tra. Công cụ cấu hình Neon có 5 unit test, nhập URI qua lời nhắc ẩn và không ghi đè secret đã tuỳ chỉnh.
- Hướng dẫn người dùng chuẩn bị Neon: [NEON_SETUP.md](NEON_SETUP.md). Cloudinary để giai đoạn sau, chưa cần credential. Chưa migrate dữ liệu thật hoặc port adapter SQLite sang PostgreSQL trong lần mở rộng schema này.
