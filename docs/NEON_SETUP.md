# AnNhà: Neon đang chạy, thiết lập và vận hành

Cập nhật 29/10/2026. Ứng dụng tại **http://localhost:8188** đã dùng Neon PostgreSQL; ảnh, video, audio/TTS vẫn ở volume `backend-data`. Mailpit tại **http://localhost:8125** nhận email thử, không chuyển thư ra Internet. Cloudinary chưa được tích hợp vào runtime.

## Trạng thái đã triển khai

- Project `weathered-river-25273807`, organization `org-wild-boat-73403801`, branch `production`, database `neondb`, region Singapore. Đã chạy Neon CLI init/deploy; chỉ bật Postgres, giữ nguyên cơ chế đăng nhập của AnNhà.
- Schema gồm **40 bảng nghiệp vụ/hệ thống và 1 bảng migration ledger**. Migration `001`, `002`, `005` có checksum, chạy trong transaction và advisory lock.
- Psycopg 3 sử dụng bốn pool và bốn LOGIN SQL riêng: app/auth/device/worker. URL runtime dùng pooler; migration dùng direct endpoint. TLS `verify-full`; context RLS và role chỉ có hiệu lực trong transaction. Owner URL không được truyền vào container backend.
- Dữ liệu SQLite cũ đã nhập: tài khoản/hash mật khẩu, nhà/phòng, camera/hash device token, cấu hình, sự kiện, media metadata, lịch nhắc, telemetry, audit. Media vẫn cùng đường dẫn trong volume. Phiên đăng nhập cũ không chuyển sang: đăng nhập lại. Liên kết email cũ cần gửi lại.
- Backup tại `/app/data/annha-before-neon.sqlite3` trong volume và `.secrets/annha-before-neon.sqlite3` trên host; không xoá DB cũ.
- Seed có nhãn `DEMO`: 4 tài khoản đã xác minh, 2 nhà với 4 phòng/camera mô phỏng mỗi nhà, 24 sự kiện, 384 batch cảm biến, 8 lịch nhắc và audio WAV. Frontend dùng các ảnh phòng gốc của thiết kế làm placeholder có nhãn; backend không coi ảnh minh hoạ là snapshot. Camera demo chưa kết nối Pi thật; không giả trạng thái online lâu dài.

## Đăng nhập demo

Mở file riêng **`.secrets/demo-credentials.json`** để lấy email/mật khẩu. File không được commit. Bốn email:

| Email | Phạm vi |
|---|---|
| `owner@demo.annha.test` | Chủ nhà DEMO AnNhà, cả 4 camera |
| `caregiver@demo.annha.test` | Chăm sóc, xử lý sự kiện/âm thanh/lịch của cả 4 camera |
| `viewer@demo.annha.test` | Chỉ xem camera phòng khách, không điều khiển |
| `outsider@demo.annha.test` | Chủ nhà DEMO độc lập, không vào được nhà AnNhà |

Đây là tên miền thử nghiệm. Email gửi vào Mailpit. Password sinh ngẫu nhiên riêng từng tài khoản. Seed giữ password/quyền đã tồn tại, không reset dữ liệu. Lưu file credentials nếu cần chạy seed lại.

```bash
# Seed lại có kiểm soát, giữ dữ liệu ngoài bộ demo:
docker compose exec backend python -m src.seed_demo
# Lấy file credentials từ volume sau lần seed đầu:
docker cp annha-backend-1:/app/data/demo-credentials.json .secrets/demo-credentials.json
chmod 600 .secrets/demo-credentials.json
```

## Chạy lại ứng dụng trên máy hiện tại

Root `.env` đã có đủ cấu hình runtime; giữ file này và `.secrets` ngoài Git.

```bash
npm run build
docker compose up -d --build --wait --wait-timeout 120
curl --fail http://localhost:8188/api/health
```

Health phải có `"database":"postgres","database_connected":true`. Thay env thì **recreate** container; chỉ `restart` không nạp env mới. `DATABASE_BACKEND=sqlite` chọn adapter cũ, `postgres` chọn adapter Neon. Không đổi `DATABASE_PATH` thành URL.

## Thiết lập từ đầu trên một database/branch trống

Giữ đúng project hiện có; không tạo project khác. Cần Node/npm, Python 3.11+ và Docker.

```bash
npm i -g neon@latest
# Nếu global install lỗi quyền, dùng npx --yes neon@latest thay neon.
neon init -y --org-id org-wild-boat-73403801 --project-id weathered-river-25273807 --branch production --services postgres
neon deploy
```

Nếu CLI mở trình duyệt, hoàn tất đăng nhập tại đó. CLI kéo `DATABASE_URL`, `DATABASE_URL_UNPOOLED`, `NEON_BRANCH` vào `.env` hiện hữu. Các URL này là credentials quản trị cho công cụ triển khai; frontend/Pi không dùng chúng. Đừng chạy deploy để trỏ môi trường test sang production nhầm.

Tạo môi trường công cụ Python nếu chưa có:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
# Công cụ dùng direct URL trong file --env:
.venv/bin/python scripts/cloud/deploy_postgres.py --env .env --output .secrets/neon-runtime.env
```

Script áp migration mới, xác minh checksum cũ và tạo login có quyền tối thiểu bằng SQL. Chạy lại với cùng output giữ nguyên password và khoá mã hoá. Nếu schema/role tồn tại nhưng không có ledger/credential tương ứng, script từ chối thay vì ghi đè. **Không chạy bootstrap Docker thủ công trước script này** trên cùng DB. Giữ database owner URL ở secret manager/máy quản trị.

Merge các biến trong `.secrets/neon-runtime.env` vào root `.env` bằng trình soạn thảo hoặc `dotenv.set_key`, giữ nguyên cấu hình khác. Đặt `DATABASE_BACKEND=postgres`; các khoá bắt buộc là `DATABASE_URL_APP/AUTH/DEVICE/WORKER`, `SESSION_CSRF_KEY`, `DATA_ENCRYPTION_KEY`, `DATA_ENCRYPTION_KEY_ID`. Khoá Fernet và CSRF do script sinh. Mất khoá Fernet sẽ không đọc được secret của Telegram/mail/TTS còn trong queue; sao lưu an toàn cùng env.

```bash
docker compose up -d --build --wait
```

Không chia sẻ `.env`, `.secrets`, output `docker compose config` hoặc `docker inspect` chứa environment. `.env.example` chỉ có mẫu, không có credentials thật.

## Chuyển dữ liệu SQLite

Script nhập hiện hỗ trợ snapshot của phiên bản này. Chỉ chạy vào **application tables còn trống**, sau migration và trước seed; không ghi đè dữ liệu hiện có. Kiểm tra trên branch riêng trước.

```bash
python3 scripts/cloud/import_sqlite.py --source .secrets/annha-before-neon.sqlite3 --env .env
```

Import có transaction, checksum snapshot và marker trong migration ledger; cùng snapshot chạy lại là no-op. Dữ liệu nguồn không bị sửa. Nếu gặp bảng executions/commands/deliveries/invitations cũ có dữ liệu, script dừng để bổ sung mapping, không âm thầm bỏ dữ liệu đó. Session/email token được cấp lại; queues mail cũ còn trong SQLite để kiểm tra khi cần. Đây là cutover một lần, không đồng bộ hai DB.

Trước cutover thực tế cần dừng ghi SQLite trong cửa sổ chuyển đổi. Trên máy này đã sao lưu trước khi thay backend. Nếu quay lại SQLite sau khi Neon có ghi mới, cần xử lý phần dữ liệu phát sinh; không chỉ bật SQLite rồi coi hai nơi đồng nhất.

## Email và Telegram

- Verify/reset/invitation: worker lấy job mã hoá trong `annha_private.job_queue`, gửi qua `SMTP_*`, retry có lease. Token lưu SHA-256, dùng một lần, có thời hạn và phiên bản địa chỉ email. Reset password tăng `auth_version` và thu hồi session.
- Cảnh báo: `EMAIL_ALERTS_ENABLED=true` cho phép worker SMTP; chủ nhà bật thêm ở **Cài đặt nhà → Thông báo email**. Recipient phải có email đã xác minh. App đang dùng SMTP Mailpit để thử; muốn gửi thư thật phải thay `SMTP_*` và bật STARTTLS theo nhà cung cấp.
- Telegram: cần `TELEGRAM_BOT_TOKEN` và Chat ID/opt-in của nhà. Không tự gửi thử đến người nhận ngoài hệ thống. Chat ID trong DB mã hoá; quyền/sự kiện/recipient được kiểm tra lại trước gửi.
- SMTP chấp nhận thư chỉ ghi `accepted`, không có nghĩa hộp thư ngoài đã nhận. Chưa có webhook receipt cho delivered/bounce/complaint; schema đã có bảng để mở rộng.
- Worker ngừng nhắc khi sự kiện được xác nhận/đóng hoặc quyền bị thu hồi; retry có giới hạn. Nếu mất tiến trình trong lúc gửi, trạng thái `unknown` cần kiểm tra thay vì gửi lại mù quáng.

## Media và Cloudinary

Hiện ảnh, video, audio/TTS giữ trong `/app/data/media`. PostgreSQL chỉ lưu metadata, quota và quyền truy cập. URL lấy file đi qua FastAPI kiểm tra quyền; không có public Cloudinary URL. Hãy backup **cả Neon lẫn volume media**.

Phần [Cloudinary trong thiết kế database](DATABASE_DESIGN_NEON.md#14-setup-cloudinary) có hướng dẫn tài khoản/key/preset signed + authenticated và Docker checker. Đây là chuẩn bị cho giai đoạn sau. Chỉ điền Cloudinary env hoặc tạo preset không tự chuyển media lên cloud; chưa có upload/delivery webhook runtime.

## Kiểm tra

Các branch `annha-integration-20261029` và `annha-schema-20261029` có hạn đến 30/10/2026, không dùng thay production. Bộ SQL fixture yêu cầu database riêng trống và rollback; không chạy nó lên database demo/production.

```bash
# Regression SQLite, không truy cập cloud:
python3 -m unittest backend.tests.test_business -v
# Native PostgreSQL API tests: chỉ dùng credentials branch thử có thời hạn:
ANNHA_TEST_ENV=.secrets/neon-test-runtime.env python3 -m unittest backend.tests.test_postgres -v
# Qua web/Docker đang chạy, dùng demo credentials và Mailpit local:
python3 scripts/cloud/smoke_neon.py
```

Smoke tạo dữ liệu `SMOKE` có chủ đích: sự kiện/lệnh/lịch sử nhắc và tài khoản verify/reset dùng `example.test`. Không xoá dữ liệu hay gửi email ra Internet. Nó kiểm tra đăng nhập, quyền, config/ACK, command/ACK, file local, event/WebSocket, email alert, TTS và verify/reset/session revocation.

Thông tin kiểm chứng và các giới hạn còn lại được ghi tại [NEON_INTEGRATION_REPORT.md](NEON_INTEGRATION_REPORT.md).

Giao diện khi chưa nối Pi đã được rà soát và khôi phục ảnh gốc: [UI_OFFLINE_READINESS.md](UI_OFFLINE_READINESS.md).


### Cập nhật quản lý nhà và phân trang

Runner migration hiện bao gồm `007_home_archiving.sql` và `008_archived_home_notifications.sql`. Chạy lại lệnh deploy ở trên sẽ chỉ áp dụng migration chưa có trong ledger, không seed/reset dữ liệu. Chức năng Xoá nhà lưu trữ mềm và thu hồi truy cập; không phải DROP/DELETE vật lý lịch sử. Tham khảo `PERFORMANCE_AND_UI_REVIEW.md` cho API phân trang, bộ lọc và kiểm chứng quyền truy cập.
