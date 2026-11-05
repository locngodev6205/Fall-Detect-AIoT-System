# AnNhà: Neon đang chạy, thiết lập và vận hành

Cập nhật 05/11/2026. Ứng dụng tại **http://localhost:8188** dùng Neon PostgreSQL; runtime chọn Cloudinary khi secret hợp lệ và vẫn đọc được media local cũ từ volume `backend-data`. Mailpit tại **http://localhost:8125** chỉ nhận thư khi SMTP trỏ Mailpit; máy chính hiện dùng Brevo cho email thật. Xem [trạng thái hiện hành](../planning/IMPLEMENTATION_STATUS.md) và [bàn giao teammate](../handoff/TEAMMATE_SETUP.md) trước khi chạy stack dùng chung.

## Trạng thái đã triển khai

- Project `weathered-river-25273807`, organization `org-wild-boat-73403801`, branch `production`, database `neondb`, region Singapore. Đã chạy Neon CLI init/deploy; chỉ bật Postgres, giữ nguyên cơ chế đăng nhập của AnNhà.
- Migration hiện có đến `013_invitation_codes.sql` đã áp qua runner sau phê duyệt; ledger lưu checksum. Phase 6 không thêm migration. Khi dựng máy mới dùng cùng DB, không chạy bootstrap/seed lại.
- Psycopg 3 sử dụng bốn pool và bốn LOGIN SQL riêng: app/auth/device/worker. URL runtime dùng pooler; migration dùng direct endpoint. TLS `verify-full`; context RLS và role chỉ có hiệu lực trong transaction. Owner URL không được truyền vào container backend.
- Dữ liệu SQLite cũ đã nhập: tài khoản/hash mật khẩu, nhà/phòng, camera/hash device token, cấu hình, sự kiện, media metadata, lịch nhắc, telemetry, audit. Media vẫn cùng đường dẫn trong volume. Phiên đăng nhập cũ không chuyển sang: đăng nhập lại. Liên kết email cũ cần gửi lại.
- Backup tại `/app/data/annha-before-neon.sqlite3` trong volume và `.secrets/annha-before-neon.sqlite3` trên host; không xoá DB cũ.
- Bộ seed ban đầu (tên hiển thị đã bỏ tiền tố demo): 4 tài khoản đã xác minh, 2 nhà với 4 phòng/camera mô phỏng mỗi nhà, 24 sự kiện, 384 batch cảm biến, 8 lịch nhắc và audio WAV. Frontend dùng các ảnh phòng gốc của thiết kế làm placeholder có nhãn; backend không coi ảnh minh hoạ là snapshot. Camera demo chưa kết nối Pi thật; không giả trạng thái online lâu dài.

## Tài khoản seed hiện hữu (chia sẻ riêng)

Mở file riêng **`.secrets/demo-credentials.json`** để lấy email/mật khẩu. File không được commit. Bốn email:

| Email | Phạm vi |
|---|---|
| `owner@demo.annha.test` | Chủ nhà AnNhà, cả 4 camera |
| `caregiver@demo.annha.test` | Chăm sóc, xử lý sự kiện/âm thanh/lịch của cả 4 camera |
| `viewer@demo.annha.test` | Chỉ xem camera phòng khách, không điều khiển |
| `outsider@demo.annha.test` | Chủ nhà độc lập, không vào được nhà AnNhà |

Đây là tên miền thử nghiệm, không nhận email Internet. Chỉ dùng Mailpit nếu cần gửi thư cho các tài khoản này trên DB thử riêng. Password sinh ngẫu nhiên riêng từng tài khoản. Seed giữ password/quyền đã tồn tại, không reset dữ liệu. Lưu file credentials nếu cần chạy seed lại.

```bash
# Chỉ chạy trên DB thử riêng sau khi đã thống nhất; không seed DB đang dùng để dựng máy mới:
docker compose exec backend python -m src.seed_demo
# Lấy file credentials từ volume sau lần seed đầu:
docker cp annha-backend-1:/app/data/demo-credentials.json .secrets/demo-credentials.json
chmod 600 .secrets/demo-credentials.json
```

## Chạy lại ứng dụng trên máy chính

Root `.env` và file secret Cloudinary đã có cấu hình runtime; giữ cả hai ngoài Git. Máy teammate dùng DB/bot chung phải theo hướng dẫn service riêng trong [bàn giao](../handoff/TEAMMATE_SETUP.md), không bật worker/poller mặc định như máy chính.

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

Neon lưu metadata/quota/quyền; backend nhận secret từ Docker secret `/run/secrets/cloudinary.env` (compose target `cloudinary.env`). `MEDIA_STORAGE_PROVIDER=auto` chọn Cloudinary khi credential hợp lệ và local nếu không; mỗi asset vẫn được đọc theo `provider` của chính nó. Upload và audio/video/image delivery dùng Cloudinary `authenticated`; file được trả qua FastAPI sau kiểm tra session, home/camera permission và RLS. Signed URL chỉ tồn tại trong backend request; không gửi provider URL hoặc credential xuống frontend. Runtime đã xác minh: environment `development`, folder `Fall Detection`, ID prefix `annha/development/`; secret hợp lệ nhưng không ghi giá trị credential ra log/tài liệu. Đây là cấu hình runtime hiện tại, không phải bằng chứng cho một deployment production khác.

Ngày 04/11/2026, migration tool chuyển 4/4 media local đủ điều kiện lên Cloudinary; verify metadata, kích thước và SHA-256 đạt; các file gốc vẫn trong `/app/data/media`. 11 media có `upload_key` `demo:*` được giữ local. Reconciliation kiểm tra 4 Cloudinary assets và 11 local assets, không thiếu file/checksum lệch; Admin API inventory namespace `annha/development/` không tìm thấy orphan. Neon production không cần DDL mới/reset/seed lại. Tài liệu trước đó ghi một recovery branch tạm; trạng thái và expiry live hiện **chưa xác minh được qua Neon API**, vì vậy không dựa vào branch này làm backup.

Hướng dẫn config, migration/reconcile và rollback nằm trong [Cloudinary/database guide](../architecture/DATABASE_DESIGN_NEON.md#14-setup-cloudinary) và báo cáo hoàn tất Phase 2 (`docs/reports/PHASE_02_COMPLETION_REPORT.md`; báo cáo cục bộ, không nằm trong Git). Diễn tập restore chỉ đọc từ Neon sang PostgreSQL 18 cô lập đã đạt: 41 bảng, 15 local originals (654,167 bytes) khớp SHA-256, 0 mapping Cloudinary thiếu, 0 reminder reference treo, RLS bật và migration 009 khớp. Sau nghiệm thu, dump, media copy, credentials QA và các tài nguyên container/network tạm đã được dọn khỏi môi trường QA; không lưu trong repository.

### Runbook khôi phục sau khi branch tạm hết hạn

Branch dùng thử không phải bản sao lưu lâu dài. Khôi phục mới phải bắt đầu bằng một Neon branch/project trống hoặc branch PITR được tạo theo thời điểm sự cố, cùng quyền migration riêng:

1. Lấy snapshot Neon bằng `pg_dump --format=custom` vào kho backup mã hoá; ghi kèm thời điểm, phiên bản PostgreSQL và SHA-256. Lưu Cloudinary originals hoặc bản local cần thiết riêng, không giả định Neon snapshot có chứa media.
2. Tạo target Neon cô lập mới. Chỉ restore vào database rỗng, ví dụ `pg_restore --no-owner --no-privileges --dbname "$DATABASE_URL_MIGRATION" ./annha.dump`; không dùng `--clean` trên database đang có dữ liệu.
3. Khôi phục local originals từ bản backup bảo vệ; giữ secret Cloudinary ở secret manager. Nếu khôi phục sang environment khác, chỉ định environment/prefix riêng để tránh ghi đè object hiện hành.
4. Chạy kiểm tra chỉ đọc: migration ledger/checksum, số bảng, mapping provider/public ID/resource type, quota/reservation, SHA-256 originals, reminder references, RLS và orphan/missing report. Tạm thời không chạy cleanup hoặc tự xoá orphan trong giai đoạn khôi phục.
5. Nếu object Cloudinary thiếu nhưng có original đã xác minh, upload lại cùng media ID/public ID vào target namespace, xác minh bytes/version rồi mới cập nhật metadata bằng migration/job có idempotency. Không đánh dấu asset `ready` trước khi provider xác nhận.
6. Chỉ chuyển traffic sau khi owner kiểm thử truy cập, quyền chéo nhà/camera bị từ chối, audio Range đọc được, event vẫn tồn tại khi image không sẵn và quota khớp. Giữ source read-only đến khi nghiệm thu.

Runbook này không phụ thuộc tên/expiry của branch tạm. Restore rehearsal Phase 2 đã kiểm thử bước database metadata + local originals; tạo PITR branch mới và khôi phục Cloudinary từ backup lâu dài vẫn cần được diễn tập định kỳ.

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

Thông tin kiểm chứng và các giới hạn còn lại được ghi tại NEON_INTEGRATION_REPORT.md (`docs/reports/legacy/NEON_INTEGRATION_REPORT.md`; báo cáo cục bộ, không nằm trong Git).

Giao diện khi chưa nối Pi đã được rà soát và khôi phục ảnh gốc: UI_OFFLINE_READINESS.md (`docs/reports/legacy/UI_OFFLINE_READINESS.md`; báo cáo cục bộ, không nằm trong Git).


### Cập nhật quản lý nhà và phân trang

Runner migration hiện bao gồm `007_home_archiving.sql`, `008_archived_home_notifications.sql` và `009_schedule_tts_permissions.sql`. Migration 009 **đã áp dụng trên Neon production**; policy chỉ cho quyền `schedules` tạo media `tts`, còn upload audio thường đòi quyền `audio`. Migration không thêm grant, không sửa dữ liệu và không đổi checksum `001`–`008`. Phase 2 không cần DDL. Phase 1 suite PostgreSQL cũ có 12/13 đạt do assertion status; sau khi sửa, ca permission được chạy riêng và đạt 1/1. Browser permission flow vẫn chưa được tự động kiểm tra. Backend `/api/health` hiện báo online và `database_connected=true`; chưa deploy lên hosting từ xa. Chi tiết ở báo cáo Phase 1 (`docs/reports/PHASE_01_IMPLEMENTATION_REPORT.md`; báo cáo cục bộ, không nằm trong Git) và Phase 2 (`docs/reports/PHASE_02_IMPLEMENTATION_REPORT.md`; báo cáo cục bộ, không nằm trong Git).
