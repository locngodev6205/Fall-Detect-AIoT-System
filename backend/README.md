# AnNhà Business API

Thiết kế chuyển sang Neon/PostgreSQL và Cloudinary: [DATABASE_DESIGN_NEON.md](../docs/DATABASE_DESIGN_NEON.md), [SQL schema](database/postgresql/README.md). Adapter PostgreSQL đã chạy với Neon; hướng dẫn vận hành và demo tại [NEON_SETUP.md](../docs/NEON_SETUP.md).

Backend FastAPI có `src.entrypoint:app` chọn PostgreSQL hoặc SQLite qua `DATABASE_BACKEND`. Các module `pgdb`, `pgsecurity`, `pgapi`, `pgservices`, `pgmedia`, `pgmain` dùng schema chuẩn hoá và RLS; adapter SQLite cũ gồm:

- `db.py`: schema, transaction và lưu trữ; giữ nguyên bảng legacy `alerts` nếu tồn tại, không công khai dữ liệu legacy chưa có sở hữu.
- `security.py`: password PBKDF2, session cookie, CSRF, rate limit, membership, camera permission và device credential.
- `models.py`: validation cho payload, lịch, sensor quality và lệnh.
- `api.py`: API tài khoản, nhà/phòng, camera, thành viên, sự kiện, telemetry, file, lịch và device endpoints.
- `services.py`: đồng bộ phiên bản, event upsert, SMTP/TTS/Telegram worker, cảnh báo môi trường và lưu trữ.
- `media.py`: relay JPEG/audio có xác thực và giới hạn kích thước/thời gian.
- `provision.py`: cấp credential/mã ghép nối từ CLI quản trị, không có API công khai tự nhận thiết bị.

Khoanh vùng đã tạm bỏ: không còn `PUT /api/cameras/{camera_id}/zones` hoặc schema chỉnh vùng trong OpenAPI; quyền `zones` bị từ chối khi cấp mới và được lọc khỏi dữ liệu quyền trả về. Khi khởi động, backend thêm đúng một revision rỗng cho camera còn cấu hình vùng; giữ nguyên các revision lịch sử và chờ thiết bị ACK. Cả API đọc cấu hình và mọi revision mới đều trả `zones: []`, `reference: {}`. Thiết bị cần nhận/áp dụng cấu hình mới để xóa vùng đã cache khi offline.

Swagger: service nội bộ `/docs`; nginx mặc định chỉ proxy `/api/` và `/ws/`. Luồng nghiệp vụ bắt đầu tại `/api/auth/register`; `/api/alerts` và endpoint mock không còn mở công khai. Sự kiện dùng `/api/homes/{home_id}/events` và WebSocket yêu cầu `home_id` + session hợp lệ.

Chạy một Uvicorn worker: kết nối media/WebSocket nằm trong bộ nhớ của worker này. Muốn scale nhiều worker phải bổ sung pub/sub và media routing trước; không chỉ tăng `--workers`.

Xem [README gốc](../README.md) để chạy Docker và [Device API](../docs/DEVICE_API.md) cho hợp đồng thiết bị. SQLite và media cần đặt trên volume riêng; `DATABASE_PATH` và `MEDIA_ROOT` được Compose cấu hình.

Biến môi trường SMTP: `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM`, `SMTP_STARTTLS`, `SMTP_USER`, `SMTP_PASSWORD`. Các biến ứng dụng: `PUBLIC_URL`, `APP_ORIGINS`, `COOKIE_SECURE`, `MQTT_ENABLED`, `MQTT_BROKER`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASSWORD`, `TELEGRAM_BOT_TOKEN`, `MAX_HOME_MEDIA_BYTES` (mặc định 512 MB). `WORKER_ENABLED=false` chỉ dùng khi test; bình thường phải bật để xử lý email/TTS/thông báo và retention.

Hàng đợi email xoá nội dung chứa liên kết bí mật sau gửi thành công. Log/API không trả session hash, password hash, token thiết bị hoặc bot token.

Docker tắt HTTP access log mặc định để đường dẫn chứa mã lời mời không bị ghi nguyên văn; audit nghiệp vụ vẫn được lưu riêng trong DB. Khi chạy phát triển cũng dùng `--no-access-log` hoặc bộ lọc che mã bí mật.
