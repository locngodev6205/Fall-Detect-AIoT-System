# AnNhà PostgreSQL / Neon target schema

Thiết kế đầy đủ: [DATABASE_DESIGN_NEON.md](../../../docs/architecture/DATABASE_DESIGN_NEON.md).

Đây là DDL cho **database mới**, không phải migration đang được backend SQLite tự chạy. Không chứa tài khoản/secret hoặc thao tác gọi Neon/Cloudinary.

- `001_schema.sql`: cấu trúc, constraints, index, trigger, bốn group NOLOGIN.
- `002_security.sql`: GRANT, RLS, policy và helper quyền.
- `003_verify.sql`: fixture SQL tổng hợp, kết thúc ROLLBACK; chỉ dùng database thử.
- `004_inspect.sql`: báo cáo catalog chỉ đọc, không trả dữ liệu người dùng.
- `005_email_notifications.sql`: nâng cấp một lần cho cảnh báo email, trạng thái provider và vòng đời địa chỉ email.
- `006_verify_email.sql`: kiểm tra bổ sung email bằng fixture rollback.
- `007_home_archiving.sql` và `008_archived_home_notifications.sql`: lưu trữ mềm nhà và dừng thông báo khi nhà được lưu trữ.
- `009_schedule_tts_permissions.sql`: cho phép quyền `schedules` tạo media TTS phục vụ lịch; upload audio thông thường vẫn cần quyền `audio`.
- `010_atomic_tts_enqueue.sql`: hàm bảo mật `enqueue_tts` kiểm tra quyền/lịch hiện hành và ghi TTS job trong cùng transaction với reminder/revision; additive, không sửa hoặc xoá dữ liệu/media.
- `011_notification_policies.sql`: thêm phạm vi camera cho từng kênh nhận, bộ lọc/giới hạn nhắc lại và hàm worker kiểm tra quyền trước khi gửi; additive, không xoá dữ liệu/media.
- `012_telegram_pairing.sql`: thêm liên kết Telegram một lần và offset polling bền vững; bật RLS/FORCE RLS cho hai bảng riêng, chỉ `annha_worker` được truy cập; additive, không xoá dữ liệu hoặc media.
- `013_invitation_codes.sql`: mã mời một lần/7 ngày lưu hash, RLS/FORCE chỉ auth control plane; mở rộng CHECK role để có member/view-only. Đã áp Neon production sau phê duyệt ngày 05/11/2026; dữ liệu và checksum migration cũ giữ nguyên.

Từ thư mục gốc repository, dùng service config của libpq đã cấu hình connection/secret bên ngoài Git:

```bash
psql 'service=annha_migration' -X -v ON_ERROR_STOP=1 -f backend/database/postgresql/001_schema.sql
psql 'service=annha_migration' -X -v ON_ERROR_STOP=1 -f backend/database/postgresql/002_security.sql
psql 'service=annha_migration' -X -v ON_ERROR_STOP=1 -f backend/database/postgresql/005_email_notifications.sql
```

Trong một database thử, sau ba bước trên:

```bash
psql 'service=annha_test_owner' -X -v ON_ERROR_STOP=1 -f backend/database/postgresql/003_verify.sql
psql 'service=annha_test_owner' -X -v ON_ERROR_STOP=1 -f backend/database/postgresql/006_verify_email.sql
```

Service kiểm thử phải dùng đúng owner đã tạo schema và có khả năng SET ROLE bốn group; không dùng database production. Script cố ý không `IF NOT EXISTS`: không che giấu role/schema đã tồn tại hoặc cấu trúc triển khai sai. Quản lý các lần thay đổi tiếp theo bằng migration mới, không chạy lại từ đầu trên dữ liệu thật.

Ứng dụng hiện có adapter Neon/PostgreSQL và SQLite cũ để local/rollback. `scripts/cloud/deploy_postgres.py` áp migration mới theo thứ tự, xác minh checksum các migration đã ghi trong ledger và không sửa migration cũ. Migration 009, 010 và 011 đã áp dụng lên Neon `production`. Lượt xác minh ngày 04/11/2026 xác nhận ledger 011 và SHA-256 khớp file local; hai hàm policy tồn tại và chỉ `annha_worker` có quyền `EXECUTE`; bảng `notification_channel_cameras` bật RLS và FORCE RLS. Probe worker cho delivery không tồn tại trả `false,false`. Hàm `enqueue_tts` từ migration 010 còn tồn tại và `annha_app` có quyền `EXECUTE`; không enqueue TTS vào production trong lượt này. Các kiểm thử hành vi TTS/reliability chạy trên PostgreSQL 16 cô lập; xem báo cáo Phase 3. Migration 011 chỉ bổ sung camera scope/policy/reminder metadata, không xoá lịch sử hoặc media. Runner bỏ qua migration đã ghi đúng checksum và chỉ thêm migration còn thiếu. SQL chỉ bảo vệ các bất biến đã thể hiện; không tự triển khai upload, retention worker, đóng socket hoặc state machine nghiệp vụ.

`012_telegram_pairing.sql` đã được thêm vào runner và được kiểm tra trên PostgreSQL 16 cô lập. Neon production chưa được thay đổi; cần phê duyệt tường minh trước khi chạy migration. Telegram dùng `TELEGRAM_UPDATE_MODE=polling` cho local/Docker/PBL, không cần `PUBLIC_URL` hay HTTPS để nhận `/start`. Compose chạy `telegram-poller` riêng; worker kiểm tra `getWebhookInfo` trước mỗi lượt, dừng polling nếu webhook đang tồn tại và không tự gọi `deleteWebhook`/`drop_pending_updates`. Offset và cập nhật ghép nối được commit cùng transaction dưới advisory lock transaction-scoped, nên chỉ một consumer gọi `getUpdates` tại một thời điểm và cập nhật được phát lại sau lỗi.

Sau này, để chuyển sang webhook: triển khai API ở HTTPS công khai, đổi `TELEGRAM_UPDATE_MODE=webhook`, recreate cả backend và `telegram-poller` (poller sẽ ở trạng thái idle), rồi để backend cấu hình webhook theo URL đã duyệt. Nếu bot đang có webhook khác, backend không thay thế mặc định; chỉ đặt `TELEGRAM_WEBHOOK_REPLACE_EXISTING=true` sau khi chủ dự án xác nhận. Không chạy đồng thời hai chế độ.

## Docker đã chuẩn bị

Từ root repository:

```bash
python3 scripts/cloud/prepare_secrets.py
docker compose -f compose.database.yaml build db-init cloudinary-check
docker compose -f compose.database.yaml up -d --wait postgres
docker compose -f compose.database.yaml run --rm db-init
docker compose -f compose.database.yaml run --rm db-check
docker compose -f compose.database.yaml run --rm db-inspect
```

`db-init` chỉ dùng lần đầu cho database mới; không tự reset dữ liệu. Neon và Cloudinary cần điền secret trước khi chạy các cloud tools. Hướng dẫn đầy đủ nằm tại mục 12–15 của [DATABASE_DESIGN_NEON.md](../../../docs/architecture/DATABASE_DESIGN_NEON.md).

## Ưu tiên Neon; Cloudinary để sau

Làm theo [NEON_SETUP.md](../../../docs/setup/NEON_SETUP.md). Người dùng chỉ cần tạo database trống và lưu direct URI bằng `python3 scripts/cloud/configure_neon.py`; chưa cần tự chạy migration hoặc cung cấp Cloudinary key.

Bootstrap Docker mới tự gộp 001 + 002 + 005 nguyên tử. Lab/database đã có bản 39 bảng cũ chỉ nâng cấp một lần bằng lệnh sau, không init lại:

```bash
docker compose -f compose.database.yaml build db-init
docker compose -f compose.database.yaml run --rm db-inspect upgrade-email
docker compose -f compose.database.yaml run --rm db-check
```

Chỉ chạy upgrade khi chưa áp 005. Hiện có 40 bảng, 73 kiểm tra SQL (46 nền + 27 email); backend ứng dụng vẫn SQLite cho tới đợt tích hợp Neon.

## Migration mã mời MVP đã áp dụng

Dùng runner với direct owner URL đã cấu hình riêng trong `.env`, không đưa URI/secret vào lệnh:

```bash
python3 scripts/cloud/deploy_postgres.py --env .env --migrations-only
```

Cờ này chỉ áp migration chưa có trong ledger và xác minh checksum, không provision/ghi lại runtime credentials. 013 đã được kiểm tra trên PostgreSQL 16 cô lập trước khi áp lên Neon; ledger/checksum/RLS/grants hậu migration đạt. Không chạy lại SQL bootstrap hoặc reset database. Xem mục 9 của báo cáo Phase 5 (`docs/reports/PHASE_05_IMPLEMENTATION_REPORT.md`; báo cáo cục bộ, không nằm trong Git).
