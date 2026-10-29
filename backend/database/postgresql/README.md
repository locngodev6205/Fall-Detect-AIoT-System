# AnNhà PostgreSQL / Neon target schema

Thiết kế đầy đủ: [DATABASE_DESIGN_NEON.md](../../../docs/DATABASE_DESIGN_NEON.md).

Đây là DDL cho **database mới**, không phải migration đang được backend SQLite tự chạy. Không chứa tài khoản/secret hoặc thao tác gọi Neon/Cloudinary.

- `001_schema.sql`: cấu trúc, constraints, index, trigger, bốn group NOLOGIN.
- `002_security.sql`: GRANT, RLS, policy và helper quyền.
- `003_verify.sql`: fixture SQL tổng hợp, kết thúc ROLLBACK; chỉ dùng database thử.
- `004_inspect.sql`: báo cáo catalog chỉ đọc, không trả dữ liệu người dùng.
- `005_email_notifications.sql`: nâng cấp một lần cho cảnh báo email, trạng thái provider và vòng đời địa chỉ email.
- `006_verify_email.sql`: kiểm tra bổ sung email bằng fixture rollback.

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

Backend hiện tại vẫn dùng SQLite. Phải port adapter và giao dịch, tách login/pool và đặt context theo thiết kế trước khi cấu hình Neon cho ứng dụng. SQL chỉ bảo vệ các bất biến đã thể hiện; không tự triển khai upload, retention worker, đóng socket hoặc state machine nghiệp vụ.

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

`db-init` chỉ dùng lần đầu cho database mới; không tự reset dữ liệu. Neon và Cloudinary cần điền secret trước khi chạy các cloud tools. Hướng dẫn đầy đủ nằm tại mục 12–15 của [DATABASE_DESIGN_NEON.md](../../../docs/DATABASE_DESIGN_NEON.md).

## Ưu tiên Neon; Cloudinary để sau

Làm theo [NEON_SETUP.md](../../../docs/NEON_SETUP.md). Người dùng chỉ cần tạo database trống và lưu direct URI bằng `python3 scripts/cloud/configure_neon.py`; chưa cần tự chạy migration hoặc cung cấp Cloudinary key.

Bootstrap Docker mới tự gộp 001 + 002 + 005 nguyên tử. Lab/database đã có bản 39 bảng cũ chỉ nâng cấp một lần bằng lệnh sau, không init lại:

```bash
docker compose -f compose.database.yaml build db-init
docker compose -f compose.database.yaml run --rm db-inspect upgrade-email
docker compose -f compose.database.yaml run --rm db-check
```

Chỉ chạy upgrade khi chưa áp 005. Hiện có 40 bảng, 73 kiểm tra SQL (46 nền + 27 email); backend ứng dụng vẫn SQLite cho tới đợt tích hợp Neon.
