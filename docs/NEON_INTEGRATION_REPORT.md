# Báo cáo tích hợp Neon AnNhà — 29/10/2026

## Kết quả

Ứng dụng tại **http://localhost:8188** đang chạy Docker FastAPI/React với Neon production. Backend dùng schema PostgreSQL chuẩn hoá, không dùng SQLite làm nguồn ghi khi `DATABASE_BACKEND=postgres`. Bản SQLite cũ và media volume được giữ nguyên để kiểm tra/rollback có kiểm soát. Cloudinary được hoãn theo yêu cầu.

Project: `weathered-river-25273807`; organization: `org-wild-boat-73403801`; branch: `production` (`br-bitter-star-a1bm2t66`); database: `neondb`; PostgreSQL 18.6. Thông tin này đã được kiểm tra trực tiếp, không dựa vào seed/config mẫu.

## Thay đổi

- Root `neon.ts`, package/lock và script `npm run build` trỏ đến build frontend hiện có. Chỉ sử dụng dịch vụ Postgres của Neon.
- Native PostgreSQL backend trong `backend/src/pg*.py`, selector `src.entrypoint:app`, provision thiết bị theo adapter. Giữ nguyên REST/WebSocket frontend đang dùng, không có khoanh vùng.
- Bốn tài khoản runtime SQL riêng, NOINHERIT, không superuser/BYPASSRLS/CREATE ROLE/CREATE DB, không sở hữu bảng; chỉ là thành viên nhóm đúng chức năng. Mỗi transaction SET LOCAL ROLE/context RLS, kết thúc thì reset. Psycopg 3 dùng pooled endpoint, TLS verify-full, pool/timeouts giới hạn. Backend container không nhận owner URL.
- Auth email/password/session hiện có được nối vào PostgreSQL: hash password/token, email verification/version, CSRF HMAC, expiry/revocation, reset thu hồi phiên.
- Sự kiện/sequence/idempotency/action, cấu hình/version/ACK, telemetry/hysteresis, lịch/revision/TTS, command/ACK, audit, quota/media local, SMTP queue và notification delivery được nối vào schema.
- Queue mail/TTS và đích Telegram lưu ciphertext Fernet; khoá ở env riêng. Không lưu raw token hoặc nội dung secret vào log/audit.
- Migration có checksum/advisory lock/transaction trong `scripts/cloud/deploy_postgres.py`; thêm ledger owner-only ngoài 40 bảng ứng dụng. `import_sqlite.py` nhập snapshot một lần, giữ nguồn read-only.
- Đã nhập dữ liệu cũ: 2 tài khoản, 2 nhà/phòng/camera, 10 cấu hình, 1 sự kiện, 2 asset âm thanh, 2 lịch nhắc cùng telemetry/audit. Giữ hash password và device token; session/email link cũ cần cấp lại. Không dựng thêm lịch sử update vốn không có trong SQLite.
- Đã seed DEMO có nhãn: 4 tài khoản, 2 nhà độc lập, 3 camera mô phỏng, 9 sự kiện, 144 batch telemetry, 3 lịch nhắc/execution, 3 PNG minh hoạ phòng và 3 WAV chuông thử. Seed chạy lại thành công, không reset dữ liệu khác.
- Cập nhật `.env.example`, Compose, tài liệu database/setup và báo cáo này. Credentials thực nằm trong file ignored, không trong Git/image.

## Chứng cứ CLI

`npm i -g neon@latest` gặp lỗi quyền hệ điều hành `EACCES` tại `/usr/local/lib/node_modules/neon`. Đã dùng đúng fallback `npx --yes neon@latest`.

```text
init: linked org/project/production and installed Neon skills
Auth complete (profile DEFAULT)
Applying to branch production (br-bitter-star-a1bm2t66)
No changes — branch production already matches the policy.
Utilized services: Postgres
Pulled 3 Neon variables into .env: DATABASE_URL, DATABASE_URL_UNPOOLED, NEON_BRANCH
```

Connection string và mã OAuth không được sao chép vào báo cáo. Đã hoàn tất browser sign-in trong phiên làm việc.

## Chứng cứ kiểm tra

### Build và khởi động

```text
$ npm run build
> npm --prefix frontend run build
✓ 4589 modules transformed.
✓ built in 1.51s
Prepared Sites build: dist/server/index.js and dist/.openai/hosting.json
```

`docker compose up -d --build --wait --wait-timeout 120` hoàn tất với backend/frontend/MQTT/Mailpit healthy. Health từ URL web, đi qua reverse proxy:

```json
{"status":"online","mode":"business-api","database":"postgres","database_connected":true,"mqtt_connected":true,"authentication":"server-session"}
```

JSON trên trích các trường liên quan của response thực tế.

### Schema và regression

- Branch Neon riêng, còn trống trước fixture: `003_verify.sql` **PASS**, `006_verify_email.sql` **PASS** — tổng 73 kiểm tra SQL/RLS/constraint/email; fixture rollback.
- Regression SQLite: `python3 -m unittest backend.tests.test_business -q` → `Ran 8 tests ... OK`.
- Branch API riêng: `ANNHA_TEST_ENV=.secrets/neon-test-runtime.env python3 -m unittest backend.tests.test_postgres -v`:

```text
test_config_version_event_realtime_and_persistence ... ok
test_device_cannot_read_other_camera_assets_or_invent_config_ack ... ok
test_environment_hysteresis_duplicate_and_removed_history ... ok
test_media_requires_scope_and_relays_frames_and_audio ... ok
test_reminder_commands_assets_and_telemetry ... ok
test_scoped_invitation_revocation_and_device_claim ... ok
Ran 6 tests in 170.378s
OK
```

Kiểm tra role production: bốn login chỉ thuộc `annha_app`, `annha_auth`, `annha_device`, `annha_worker` tương ứng; mọi cờ quyền cao bằng false; số bảng runtime sở hữu bằng 0. Ledger bị thu hồi SELECT/INSERT/UPDATE/DELETE khỏi cả bốn runtime group.

### Qua ứng dụng Docker đang chạy

`python3 scripts/cloud/smoke_neon.py` dùng credentials demo riêng, HTTP tại cổng 8188, WebSocket thật và SMTP vào Mailpit:

```text
PASS Docker HTTP health -> Neon PostgreSQL
PASS owner/caregiver/viewer/independent-home accounts and access restrictions
PASS local PNG snapshot and WAV media, metadata read from Neon
PASS authenticated device config/ACK and audio command/ACK
PASS device event -> Neon -> browser WebSocket
PASS email alert -> durable Neon delivery -> SMTP -> Mailpit
PASS encrypted TTS queue -> espeak -> local WAV -> Neon config revision
PASS registration -> Mailpit verification -> login -> CSRF rejection -> reset -> session revocation
ALL LIVE SMOKE CHECKS PASSED
```

`docker compose exec -T backend python - < scripts/cloud/smoke_mqtt.py`:

```text
PASS MQTT -> registered device -> Neon event feed; invalid device token rejected
```

Smoke tạo dữ liệu có nhãn SMOKE và địa chỉ `example.test`; không reset DB. Email test chỉ đi vào Mailpit. Đã thử relay JPEG và push-to-talk bằng dữ liệu tổng hợp trong bộ API; không suy ra camera/microphone thật đã hoạt động.

Các log cục bộ giữ trong `.secrets/neon-*-*.log`/`.secrets/neon-smoke*.log`, không commit vì log vận hành có thể chứa metadata nội bộ.

## Lỗi đã gặp và xử lý

- Global CLI install EACCES: chuyển sang npx, init/deploy thành công.
- Neon owner không tự có quyền SET ROLE vào nhóm vừa tạo: deployment cấp membership cụ thể cho migration owner để chạy bộ kiểm tra; runtime vẫn chỉ thuộc nhóm của mình.
- SQL fixture giả định DB trống; chạy chung với API test có dữ liệu làm fixture xung đột: chuyển bộ SQL sang branch riêng trống, cả hai bộ PASS. Không chạy fixture đó trên production.
- Import audit SQLite có actor `system` thay vì UUID: mapping sang actor_type system, user_id NULL; transaction thử bị rollback, sau sửa import test/production thành công.
- Telemetry device role không có SELECT table để dùng RETURNING/dedupe: endpoint dùng worker transaction với home/camera đã xác thực từ device token; kiểm thử telemetry/hysteresis qua. Không mở rộng quyền DB cho thiết bị.
- Invitation dành cho email khác trả 404 thay cho mã 400 cũ; test được cập nhật theo hành vi tránh tiết lộ tài nguyên, quyền vẫn bị chặn.

Không còn lỗi chặn build/start/smoke tại thời điểm báo cáo.

## Dùng thử và giới hạn

Lấy mật khẩu riêng của 4 tài khoản tại **`.secrets/demo-credentials.json`**; xem [NEON_SETUP.md](NEON_SETUP.md) để biết phạm vi từng tài khoản và cách chạy lại. File cùng tên còn trong volume `/app/data`; không nằm trong media root/API file.

Cloudinary chưa nối/upload; ảnh và âm thanh vẫn local. Backup PostgreSQL không chứa nội dung media: cần backup cả volume. Telegram có đường gửi nhưng chưa gửi thử ra người nhận thật. Email đã thử qua Mailpit; SMTP ngoài, DNS SPF/DKIM/DMARC và provider delivery/bounce/complaint webhook còn cần thiết lập sau. Schema hỗ trợ receipts nhưng worker receipt chưa triển khai.

Pi/camera/cảm biến/servo thật, tải lớn, quota đồng thời quy mô cao, phục hồi từ backup và đo hiệu năng chưa được kiểm chứng. Backend hiện chạy một uvicorn worker; nhiều instance cần pub/sub chung cho relay/WebSocket. Tự động purge event/audit, đầy đủ security_events/live_sessions analytics và key rotation nhiều khoá còn là phần mở rộng. Queue worker chạy định kỳ sẽ truy cập Neon khi app còn bật.

Hai branch kiểm thử `annha-integration-20261029` và `annha-schema-20261029` tự hết hạn 30/10/2026 16:00 UTC; không chứa dữ liệu production mới. SQLite backup và Neon có thể lệch sau các lần ghi mới: rollback cần xử lý delta, không ghi đè dữ liệu.
