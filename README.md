# AnNhà — Camera giám sát gia đình

Ứng dụng React/Vite + FastAPI, PostgreSQL/Neon, Cloudinary, Telegram và email Brevo. Backend quản lý tài khoản, quyền theo camera, nhà/phòng, sự kiện, môi trường, media và lời nhắc. **Phase 6 P1 đã hoàn thiện trong phạm vi web MVP trên PostgreSQL**; phần cứng/video/servo do teammate tích hợp. SQLite legacy chưa có toàn bộ API Phase 6.

## Bắt đầu

Cần Git và Docker Desktop/Engine có Compose. Chuẩn bị `.env` từ `.env.example` và file secret Cloudinary theo [hướng dẫn bàn giao](docs/handoff/TEAMMATE_SETUP.md). Có thể tạo template không ghi đè file hiện có bằng:

```sh
python3 scripts/cloud/prepare_secrets.py
```

Nếu nối Neon hiện có, dùng `DATABASE_BACKEND=postgres` với bốn URL runtime đúng role; không dùng migration-owner URL làm runtime. Đừng tự chạy seed/migration/reset database đang dùng để khởi động ứng dụng.

Máy chính đã được cấu hình đầy đủ có thể chạy:

```sh
docker compose up -d --build
```

Bản bàn giao đầy đủ dùng cùng lệnh để bật toàn stack, không thêm cấu hình khóa chức năng. Khi chia sẻ DB/bot, đọc [hướng dẫn bàn giao](docs/handoff/TEAMMATE_SETUP.md): dữ liệu dùng chung và mỗi bot chỉ có một polling consumer; không chạy cùng bot trên hai DB độc lập.

- Ứng dụng: http://localhost:8188
- Mailpit: http://localhost:8125 — chỉ có thư nếu SMTP trỏ Mailpit; cấu hình Brevo gửi ra hộp thư thật.
- Backend/MQTT/SMTP mặc định chỉ ở mạng Docker; cổng host đổi qua `WEB_PORT`/`MAIL_PORT`.

Đăng ký → nhập mã xác minh từ email → đăng nhập → tạo nhà hoặc nhập mã mời. Có thể tra tài khoản seed hiện hữu trong `.secrets/demo-credentials.json` được chia sẻ riêng; file này không nằm trên Git. Ảnh/font/placeholder frontend đã nằm trong repository.

## Menu và cập nhật

- macOS/Linux: `./run.sh` hoặc `bash run.sh`.
- Windows: `run.bat` hoặc `.\run.bat`.

```sh
./run.sh status
./run.sh logs backend
./run.sh stop
```

Launcher giữ `.env` và volumes. Menu `up` chạy toàn stack. Khi dùng chung bot cần thống nhất máy điều phối polling như hướng dẫn bàn giao. `recreate` nạp cấu hình từ image có sẵn; cần build khi mã nguồn thay đổi. Không dùng `docker compose down -v` khi cập nhật vì sẽ xóa volume.

## Các luồng chính

- Xác minh/reset bằng OTP HTML; session HttpOnly, CSRF, thu hồi phiên; mã mời một lần/7 ngày và phân quyền camera.
- Sự kiện: bộ lọc ngày/mức độ/địa điểm, timeline cập nhật, xử lý cảnh báo và trạng thái bằng chứng tách biệt.
- Môi trường: aggregation toàn range, coverage/gaps/units và bảng dữ liệu phân trang.
- Media Cloudinary riêng tư và media local cũ; thư viện có search/filter/usage/rename/xóa an toàn.
- Lịch nhắc TTS/file/ghi âm, inline upload; kết quả phát chỉ có khi thiết bị gửi phản hồi.
- Queue/retry/lease và realtime; Telegram long polling với pairing từ website; email có bộ lọc người nhận/kênh/trạng thái. `accepted` khác `delivered`.
- Khoanh vùng đã bỏ khỏi UI/API nghiệp vụ. Device config chỉ giữ `zones: []`/`reference: {}` để tương thích xóa cấu hình cũ; servo tracking chưa được nghiệm thu ở phần web.

`EMAIL_ALERTS_ENABLED` kiểm soát riêng cảnh báo email; không chặn thư xác minh/reset. Từng người nhận vẫn cần bật kênh và lưu preference. Không đưa secret vào source hoặc frontend.

## Thiết bị và phát triển

Provision thiết bị mới trên backend được quản trị:

```sh
docker compose exec backend python -m src.provision --name "Camera phòng khách"
```

Giữ `device_token` trên Pi và dùng pairing code trên web. Token chỉ hiện một lần; không gửi vào Git/log. Chi tiết ở [Device API](docs/api/DEVICE_API.md). Không mở broker anonymous ra Internet.

Development frontend dùng **5188**, backend **8018**; Vite proxy API/WebSocket. Cấu hình backend đúng DB thử và tắt workers/provider trước khi chạy kiểm thử có fixture. Mã nguồn PostgreSQL chính là `backend.src.pgmain:app`; adapter SQLite là `backend.src.main:app`.

```sh
npm --prefix frontend ci
npm run dev
# Terminal khác, sau khi nạp env kiểm thử riêng:
python3 -m uvicorn backend.src.pgmain:app --host 127.0.0.1 --port 8018 --no-access-log
```

TTS local cần eSpeak NG (đã có trong backend image). PostgreSQL test phải dùng runtime role của DB cô lập, không trỏ fixture tới production. Chọn focused tests phù hợp với thay đổi thay vì chạy lại tất cả provider live.

## Tài liệu

- [Danh mục docs](docs/README.md)
- [Đặc tả](docs/product/PROJECT_SPECIFICATION.md), [kiến trúc](docs/architecture/ARCHITECTURE.md), [database/media](docs/architecture/DATABASE_DESIGN_NEON.md)
- [Neon setup](docs/setup/NEON_SETUP.md), [database tooling/migrations](backend/database/postgresql/README.md)
- [Trạng thái hiện tại](docs/planning/IMPLEMENTATION_STATUS.md), [backlog](docs/planning/SOFTWARE_BACKLOG_ANNHA.md)
- [Teammate cần nhận gì ngoài `.env`](docs/handoff/TEAMMATE_SETUP.md)

`docs/reports/`, `.env`, `.secrets/`, runtime data, build và review screenshots được giữ ngoài Git. Nếu cần báo cáo nghiệm thu hoặc file media local cũ, chia sẻ riêng; pull source không tự khôi phục các dữ liệu này.
