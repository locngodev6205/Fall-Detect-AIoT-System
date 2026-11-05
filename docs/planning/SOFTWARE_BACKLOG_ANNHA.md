# AnNhà — danh sách hoàn thiện phần mềm

Ngày rà soát: **05/11/2026**. Source nền lúc bắt đầu: **`314b6aa67d29ccd167e5a1f5b698b066f3182a4a`**; các thay đổi hiện hành chưa commit. **SW-03/SW-04 đã hoàn tất Phase 3; SW-07 COMPLETE trong phạm vi web/PBL.** Migration 011/012 đã áp và xác minh trên Neon sau phê duyệt. Polling/pairing thật và đúng một text/một ảnh tổng hợp có consent đã đạt; chủ dự án xác nhận nhận cả hai. UI modal mới và audit history được kiểm tra live. Giới hạn queue/event live và SW-06 giữ riêng trong báo cáo cuối Phase 4 (`docs/reports/PHASE_04_COMPLETION_REPORT.md`; báo cáo cục bộ, không nằm trong Git). **Phase 5 COMPLETE — MVP/demo: chủ dự án xác nhận reset thành công và nhận đúng email cảnh báo tổng hợp qua queue/Brevo; history giữ accepted. Verification và Invitation Code đã COMPLETE. Receipt/tracking nâng cao hoãn deployment; **Phase 6 P1 COMPLETE trên PostgreSQL MVP**: SW-09/10/11/13 và SW-06 history đã triển khai, 5 focused integration tests PASS tính gộp, browser smoke đạt; một frontend build cuối và Compose healthy. SQLite legacy/P2 không thuộc nghiệm thu. Chi tiết tại báo cáo Phase 6 (`docs/reports/PHASE_06_IMPLEMENTATION_REPORT.md`; báo cáo cục bộ, không nằm trong Git).**


## Phạm vi và cách đọc

Chỉ gồm frontend, backend nghiệp vụ, database, media cloud, email/Telegram và kiểm thử phần mềm. Không giao việc điều khiển servo, bám người, inference/pose, thuật toán nhận diện trên edge, driver camera/cảm biến/loa, phát offline hoặc thử nghiệm Raspberry Pi. Có thể dùng dữ liệu HTTP/WebSocket giả lập để nghiệm thu phần web/backend mà không chờ Pi.

- **P0:** sửa tính đúng đắn/phân quyền trước khi mở rộng sử dụng.
- **P1:** hoàn thiện các luồng phần mềm đã có trong yêu cầu.
- **P2:** mở rộng tiện ích sau khi phần chính ổn định, cần chốt phạm vi khi bắt đầu.
- Một phần chỉ thiếu cấu hình dịch vụ thật được ghi rõ; không coi toàn bộ luồng là chưa implement.
- Các đường dẫn nguồn dưới đây là bằng chứng tại commit đang rà soát; số dòng có thể đổi sau khi sửa.

## Bảng theo dõi chung

Trạng thái dùng thống nhất: **Chưa làm → Đang làm → PARTIAL → Chờ PostgreSQL cô lập → Hoàn thành**. Phần phụ thuộc bên ngoài ghi rõ dịch vụ/cấu hình đang chờ. Mục có nhiều phần chỉ hoàn thành khi tất cả tiêu chí tương ứng được nghiệm thu; đánh dấu checkbox bên dưới khi làm xong từng phần.

| ID | Ưu tiên | Đầu việc | Trạng thái hiện tại | Phụ thuộc / phần để sau |
|---|---|---|---|---|
| SW-01 | P0 | Xoá hoàn toàn khoanh vùng | **Hoàn thành** | SQLite và PostgreSQL cục bộ đã kiểm tra; migration 001–008 không sửa |
| SW-02 | P0 | Nhất quán phân quyền camera/âm thanh/lịch | **Hoàn thành; browser role smoke đạt** | Migration 009 trên Neon; camera-level API/RLS test chạy lại trong focused regression |
| SW-03 | P0 | TTS, quota và tính bền vững của queue | **Hoàn thành phạm vi nghiệm thu Phase 3** | 010 đã lên Neon; atomic TTS, lease reclaim/restart, provider timeout/DB rollback, retry và quota được kiểm tra cô lập |
| SW-04 | P0 | Tổng cảnh báo chính xác, cảnh báo chung trên web | **Hoàn thành phạm vi nghiệm thu Phase 3** | Count/RLS/revocation và 6 realtime checks đạt; âm báo mặc định tắt đã hoàn tất với 3/3 browser sound checks |
| SW-05 | P1 | Media dùng chung và chuyển dữ liệu cũ | **Hoàn thành trong phạm vi ảnh/audio Phase 2** | Snapshot, ảnh sự kiện, WAV/MP3/TTS đã kiểm thử; video/clip và Pi do teammate phụ trách |
| SW-06 | P1 | Người nhận, bộ lọc và chính sách nhắc cảnh báo | **COMPLETE — MVP; history bổ sung Phase 6 đạt** | Recipient/channel/status filters, paging, accepted khác delivered; receipt tự động hoãn deployment |
| SW-07 | P1 | Telegram polling, pairing và gửi cảnh báo | **COMPLETE — web/PBL** | Polling/pairing/text/photo consent live đạt và người nhận xác nhận; queue/filter/reminder có fixture, chưa tạo event live mới |
| SW-08 | P1 | Mẫu email, hoàn thiện gửi xác minh/reset/cảnh báo và receipt | **COMPLETE — MVP/demo; receipt hoãn deployment** | Người dùng nhận HTML, nhập mã thành công; một job done/1 attempt/ciphertext cleared trên `phase5_test`; không phụ thuộc Cloudinary |
| SW-09 | P1 | Tìm kiếm, diễn biến và bằng chứng sự kiện | **COMPLETE — Phase 6 PostgreSQL MVP** | Ngày/mức, timeline server paging, evidence states API/UI đạt; giữ policy đóng cũ, không video |
| SW-10 | P1 | Biểu đồ bao phủ toàn khoảng thời gian | **COMPLETE — Phase 6 PostgreSQL MVP** | Aggregation đủ 605 mẫu/7 ngày, tách đơn vị, coverage/gaps, raw server paging |
| SW-11 | P1 | Thư viện âm thanh và lịch lỗi | **COMPLETE — Phase 6 PostgreSQL MVP** | Inline local upload/search/filters/usage/rename/delete guard và khóa edit camera đạt; không test lại cloud |
| SW-12 | P1 | Dung lượng và chính sách lưu dữ liệu | **Hoàn thành cơ chế ảnh/audio; một phần khôi phục vận hành** | Quota/UI, retention an toàn, cleanup, retry, reconciliation và restore cô lập đã kiểm tra; trạng thái/expiry branch Neon chưa xác minh |
| SW-13 | P1 | Phân trang backend và tải theo nhu cầu | **COMPLETE — Phase 6 PostgreSQL MVP** | Audio, executions, audit, notification server paging; 205+ rows, lazy tabs/panels, shared data theo màn |
| SW-14 | P2 | Quản lý phòng và metadata camera | Chưa làm | Không chờ Cloudinary |
| SW-15 | P2 | Tài khoản và quản lý phiên | Chưa làm | Xác minh qua app queue và nhập mã live đã đạt; reset đã được chủ dự án xác nhận thành công |
| SW-16 | P2 | Mã mời thành viên và tự rời nhà | **Mã mời MVP COMPLETE; tự rời nhà để sau** | Migration 013 Neon; SQLite/PostgreSQL và browser flow đạt; không cần email invitation/domain |
| SW-17 | P1 | Regression và CI phần mềm | **Focused regression Phase 3 hoàn thành; Phase 4 một phần** | Chỉ chạy các ca Phase 4 liên quan; xem báo cáo để biết ca đạt/chưa xác minh, không chạy suite toàn dự án |
| SW-18 | P1 | Health worker, backup/restore và tài liệu | **Runbook hiện có giữ nguyên; backup dài hạn để backlog production** | Neon/Cloudinary built-in recovery và runbook restore đã kiểm chứng trên môi trường cô lập; không thêm scheduler/S3 |

### Trạng thái Cloudinary và recovery

- [x] **CL-01 · SW-05:** runtime Cloudinary development hợp lệ; adapter/proxy authenticated upload/read/delete ảnh/audio/TTS đã live-smoke. Video adapter được giữ tương thích nhưng chưa nghiệm thu.
- [x] **CL-02 · SW-05:** 4 asset đủ điều kiện đã chuyển theo 2 batch (1 rồi 3); checksum/metadata xác nhận; bản local giữ nguyên.
- [x] **CL-03 · SW-07:** consent/expiry/fallback fixture đạt; sau duyệt riêng đã upload/read/checksum Cloudinary authenticated, gửi một ảnh tổng hợp Telegram và dọn asset thử. Người nhận xác nhận ảnh/caption; không dùng media riêng tư.
- [x] **CL-04 · SW-09/SW-11:** snapshot/ảnh sự kiện, WAV/MP3/TTS, Range, quyền truy cập và fallback đã kiểm tra; clip video để teammate tích hợp.
- [x] **CL-05 · SW-12:** quota/retry/delete, retention ảnh an toàn, giữ audio đang dùng, cleanup staging thất bại và reconciliation đã kiểm tra; UI quota/retention đã có.
- [x] **CL-06 · SW-17/SW-18 trong phạm vi đồ án:** restore cô lập và browser smoke đạt; 010 đã lên Neon. Xác minh retention/expiry backup dài hạn để backlog production, không chặn Phase 3.

Các mục CL là phần việc phụ thuộc của các SW hiện có, **không cộng thêm thành sáu chức năng mới**. Trong thời gian chờ, giữ media local và ảnh minh hoạ đã có; các phần có thể kiểm thử bằng mock/local vẫn triển khai theo thứ tự ưu tiên.

**Cấu hình Cloudinary hiện hành đã xác minh qua runtime container:**

- [x] Secret file backend hợp lệ; environment `development`, folder `Fall Detection`, public ID prefix `annha/development/` và delivery `authenticated`.
- [x] Server-side signed upload, proxy kiểm quyền và secret không xuất hiện trong log/báo cáo.
- [ ] Teammate tích hợp clip video/Pi. Branch Neon cần quyền API để xác minh expiry trực tiếp.

Không đặt API secret trong file Markdown hoặc commit Git. Cấu hình được đọc từ secret file ngoài Git. Runtime đã xác nhận provider Cloudinary hoạt động; credential chỉ được kiểm tra nội bộ và không hiển thị.

## Những chức năng đã có, không làm lại từ đầu

- Đăng ký/xác minh email/đăng nhập/đăng xuất/quên và đặt lại mật khẩu; session, CSRF, RLS theo nhà/camera.
- Tạo/chọn/sửa nhà, lưu trữ mềm khi xoá nhà, thiết lập thiết bị sau; tạo/đổi tên phòng.
- Mời/chấp nhận/từ chối/thu hồi thành viên, chọn camera được chia sẻ.
- Danh sách/chi tiết/xử lý sự kiện, ghi chú, lịch sử thao tác; sự kiện có phân trang backend và bộ lọc phòng/camera/loại/trạng thái/khoảng thời gian dựng sẵn.
- Lịch nhắc một lần/lặp, TTS, nghe thử, ghi âm trong form, thư viện âm thanh, lịch sử phát/lệnh; bộ ghi âm mới đã có giới hạn thời gian và xử lý từ chối microphone.
- Biểu đồ môi trường, nhận biết dữ liệu cũ/lỗi, ảnh placeholder gốc, cảnh báo loading/error và một số danh sách phân trang phía giao diện.
- Queue email/TTS, gửi Telegram dạng chữ, gửi email qua SMTP, kiểm tra quyền trước dispatch, retry có giới hạn và xử lý delivery `sending` quá hạn thành `unknown` đã có.

## P0 — ưu tiên sửa trước

### SW-01 — Xoá hoàn toàn chức năng khoanh vùng khỏi phạm vi hiện hành

- [x] **Backend/model:** `EventInput.zone_id` đã bỏ; cấu hình nghiệp vụ mới và API dành cho người dùng loại `zones`/`reference` ở cả SQLite/PostgreSQL. Device API giữ tombstone rỗng để firmware cũ dọn cache.
- [x] **Frontend/API:** không có route/UI/quyền chỉnh vùng; CSS vùng cũ đã gỡ; URL cũ không có route hoạt động.
- [x] **Dữ liệu/tài liệu:** đặc tả, kiến trúc, device API và database docs phân biệt hợp đồng hiện hành với tín hiệu tương thích. Migration `001`–`008` được giữ nguyên; có migration mới 009 chỉ cho phân quyền TTS.
- [x] **Kiểm chứng SQLite/OpenAPI:** test phủ định `zone_id`, zone API, payload mới, dữ liệu legacy, revision idempotency, ACK/history đã chạy trong `test_zones_disabled_and_legacy_config_retired_once`.
- [x] **Kiểm chứng PostgreSQL:** `test_zone_fields_are_not_part_of_current_config_or_event_contract` đạt trên PostgreSQL 16 cô lập cục bộ; kiểm tra config legacy, event `zone_id`, tombstone, ACK và revision cleanup.

**Bằng chứng:** [models.py](../../backend/src/models.py), [pgservices.py](../../backend/src/pgservices.py), [services.py](../../backend/src/services.py), [test_business.py](../../backend/tests/test_business.py), [test_postgres.py](../../backend/tests/test_postgres.py), [DEVICE_API.md](../api/DEVICE_API.md). SQLite regression và PostgreSQL zone contract test đạt. `zoneinfo`/`timezone` dùng cho múi giờ và được giữ.

### SW-02 — Nhất quán quyền của từng camera và thao tác âm thanh/lịch

- [x] API trả quyền hiệu lực theo camera; UI action lấy quyền từ camera đang chọn, không dùng aggregate của cả nhà.
- [x] Người chăm sóc `schedules=true`, `audio=false` có thể tạo lịch/TTS và nghe preview/tài sản audio được chọn cho lịch; không được upload audio hay điều khiển loa thủ công. Migration 009 giới hạn thay đổi RLS cho `kind='tts'`.
- [x] Xoá asset vẫn chỉ dành cho chủ nhà (`manage`); UI ẩn nút xoá với caregiver.
- [x] SQLite regression phủ owner/viewer/caregiver chỉ lịch/chỉ audio/cả hai, nhiều camera, cross-camera/cross-home, 403, revocation và đóng WebSocket.
- [ ] **Xác nhận lượt PostgreSQL sau sửa assertion:** một lượt test cục bộ PostgreSQL 16 đã chạy 13 test; 12 đạt, còn test ma trận dừng vì test kỳ vọng 422 trong khi endpoint trả 404 khi truy vấn file ngoài camera không khớp. Source trả 404 qua `fail_if_missing` để không tiết lộ tài nguyên; assertion được sửa thành 404 sau lượt chạy và chưa chạy lại theo yêu cầu.

**Bằng chứng:** [cameraPermissions.js](../../frontend/src/cameraPermissions.js), [App.jsx](../../frontend/src/App.jsx), [AdminScreens.jsx](../../frontend/src/AdminScreens.jsx), [pgsecurity.py](../../backend/src/pgsecurity.py), [pgapi.py](../../backend/src/pgapi.py), [Reminders.jsx](../../frontend/src/Reminders.jsx), [009_schedule_tts_permissions.sql](../../backend/database/postgresql/009_schedule_tts_permissions.sql). Lượt PostgreSQL đã quan sát lịch dùng audio/TTS với quyền schedule-only thành công, từ chối loa/upload khi thiếu quyền audio, từ chối viewer và chặn truy cập chéo nhà/camera. Neon production catalog xác nhận ledger 009, policy RLS mới và FORCE RLS. Phần cuối ma trận (cả hai quyền/thu hồi từng quyền) chưa được chạy tới vì test dừng ở assertion sai.

### SW-03 — Làm bền luồng tạo TTS và queue nghiệp vụ

**Trạng thái: Hoàn thành trong phạm vi nghiệm thu Phase 3.** Migration 010 đã áp trên Neon, checksum/function/ACL kiểm tra live; các ca ghi dữ liệu thử chỉ chạy PostgreSQL 16 cô lập. Không chạy lại Cloudinary bulk migration hoặc thay queue hiện có.

- [x] Reminder, revision, asset và job TTS được ghi nguyên tử trong request transaction qua `annha_private.enqueue_tts`; lỗi mã hoá kiểm thử xác nhận rollback cả lịch lẫn asset.
- [x] Quota TTS local/Cloudinary: nếu vượt quota thì asset/job báo lỗi có thể retry, reservation vẫn bằng 0; nhánh Cloudinary không gửi file lên provider khi reservation bị từ chối.
- [x] Retry giữ idempotency key `tts:<asset_id>`; asset đang xử lý hoặc đang upload có kiểm tra trạng thái/hash; asset đã sẵn sàng không upload trùng.
- [x] TTS chậm không chặn job/email/thông báo/maintenance: các worker loop riêng chạy qua `asyncio.to_thread`.
- [x] Nếu asset bị xoá trong lúc tổng hợp, TTS job bị huỷ, file tổng hợp tạm được dọn, job xoá tiếp tục và media không bị tạo lại.
- [x] Test worker restart đóng/mở lại pools, giữ lease còn hạn và reclaim lease hết hạn; TTS hoàn tất một lần, quota không cộng trùng.
- [x] Provider fixture ghi object rồi timeout; transaction metadata rollback sau provider success; retry cùng public ID giữ một object và một lần quota. Lỗi commit khi chốt job sau asset ready cũng được retry mà không synthesis/upload lại.
- [ ] Ngoài nghiệm thu fixture: chưa SIGKILL OS process/partition mạng thật hoặc chạy lại TTS live Cloudinary; không giả nhận các ca này đã kiểm chứng.

**Bằng chứng:** [pgapi.py](../../backend/src/pgapi.py), [010_atomic_tts_enqueue.sql](../../backend/database/postgresql/010_atomic_tts_enqueue.sql), [pgservices.py](../../backend/src/pgservices.py), [test_postgres.py](../../backend/tests/test_postgres.py), [test_phase3_workers.py](../../backend/tests/test_phase3_workers.py). Migration 010 đã lên Neon; checksum `743b02dc2a8f6e542e1f37f43f1d4974ea24d61c61b32c43dce79e73cf5c4fb7`. Chi tiết kiểm tra và giới hạn ở completion report (`docs/reports/PHASE_03_COMPLETION_REPORT.md`; báo cáo cục bộ, không nằm trong Git).

### SW-04 — Cảnh báo đang mở phải đầy đủ và nổi bật trên toàn web

- [x] API `active-events` đếm độc lập danh sách gần đây, lọc `OPEN` + `ACKNOWLEDGED` theo RLS và trả trang active có thứ tự ổn định; test 105 sự kiện cho kết quả 103 active, trang 20, outsider 404.
- [x] ACK được hiển thị là “đã tiếp nhận” nhưng vẫn là active; RESOLVED/FALSE_ALARM bị loại khỏi count.
- [x] Header có badge/popover trên các trang đã đăng nhập; chọn dòng mở đúng event. WebSocket thông báo toast tiếng Việt; browser test phát lặp cùng event chỉ có một toast.
- [x] Baseline ban đầu im lặng; reconnect/poll nhận event mới sau baseline thì hiện toast, historical replay chỉ cập nhật count. Set event ID giữ suốt phiên nhà; session generation/request order chặn response cũ, kể cả A→B→A.
- [x] Full home data refresh giảm còn 30 giây và bỏ qua màn sự kiện/chi tiết; các event view có refresh riêng theo alert tick, không tải lại toàn bộ home data cho từng alert.
- [x] 6/6 browser fault-injection checks: reconnect có event mới, duplicate/update, historical replay/refresh, revoke camera với request chưa xong, A→B/A→B→A và response sai thứ tự; popover mở đúng event. Backend test xác nhận count chỉ camera được chia sẻ và về 0 sau revoke, socket đóng.
- [x] Chủ dự án xác nhận âm báo mặc định tắt. Switch trong menu chuông bật theo tab qua user gesture; duplicate/historical replay không phát lặp. Browser bị chặn/suspended hiển thị hướng dẫn bật lại, visual alert vẫn hoạt động. 3/3 sound checks và build mới đạt.

**Bằng chứng:** [pgapi.py](../../backend/src/pgapi.py) có `active_events`; [002_security.sql](../../backend/database/postgresql/002_security.sql) áp `can_camera` cho event rows; [pgmain.py](../../backend/src/pgmain.py) xác thực WebSocket; [pgservices.py](../../backend/src/pgservices.py) kiểm quyền camera khi broadcast; [App.jsx](../../frontend/src/App.jsx) quản lý badge, baseline, toast, reconnect, polling và đổi nhà; [EventScreens.jsx](../../frontend/src/EventScreens.jsx) tải lại danh sách sự kiện theo alert tick. Kết quả focused PostgreSQL/UI nằm trong báo cáo Phase 3 (`docs/reports/PHASE_03_IMPLEMENTATION_REPORT.md`; báo cáo cục bộ, không nằm trong Git).

## P1 — hoàn thiện các luồng phần mềm chính

### SW-05 — Tích hợp lưu trữ media dùng chung (Cloudinary)

**Trạng thái: Hoàn thành cho snapshot, ảnh sự kiện, WAV/MP3 và TTS; clip/video thuộc giai đoạn tích hợp teammate.**

- [x] Adapter local/Cloudinary, resource type phù hợp, authenticated delivery và backend proxy sau khi kiểm quyền; Range được chuyển tiếp.
- [x] Reservation/uploading/ready/failed/deleting, retry bền bằng job queue, quota, ID idempotent, delete retry, TTS/audio, event evidence và local fallback.
- [x] Migration dry-run/batch/resume/checksum/metadata verification/reconciliation; giữ local originals. Regression provider giả được ghi trong báo cáo Phase 2.
- [x] Nghiệm thu: runtime chọn Cloudinary khi secret hợp lệ; đọc qua backend proxy sau khi kiểm quyền, không cần copy volume media; ảnh minh hoạ tĩnh tiếp tục hoạt động.
- [x] Diễn tập khôi phục Neon media metadata và local originals trên PostgreSQL 18 cô lập; mapping Cloudinary, quota và checksums được xác minh mà không ghi production.
- [ ] Smoke clip/video và thiết bị thật do teammate phụ trách; không phải điều kiện nghiệm thu Phase 2 này.

**Bằng chứng:** [media_storage.py](../../backend/src/media_storage.py), [media_migration.py](../../backend/src/media_migration.py), [pgservices.py](../../backend/src/pgservices.py), [pgapi.py](../../backend/src/pgapi.py), [test_media_storage.py](../../backend/tests/test_media_storage.py). Live JPEG/PNG/WAV/MP3/TTS smoke đạt; 4/4 media đủ điều kiện đã chuyển và checksum đối chiếu. Xem báo cáo hoàn tất Phase 2 (`docs/reports/PHASE_02_COMPLETION_REPORT.md`; báo cáo cục bộ, không nằm trong Git).

### SW-06 — Quản lý người nhận, bộ lọc và chính sách nhắc cảnh báo

**Trạng thái hiện tại: COMPLETE — MVP.** Policy/reminder giữ bằng chứng nghiệm thu Phase 4–5, không chạy lại. Phase 6 hoàn thiện UI/API history server pagination, filter recipient/channel/status và accepted khác delivered. PostgreSQL 205 deliveries kiểm tra trang 21 và filter accepted=102/delivered=0; browser desktop/mobile đạt. Receipt tự động thuộc deployment.

- [x] Cấu hình chủ nhà/người chăm sóc, camera/loại sự kiện/mức tối thiểu và bật/tắt riêng từng kênh; backend kiểm tra email xác minh và quyền camera khi gửi.
- [x] Chính sách mặc định 15 phút/tối đa 3 lần; trạng thái nhắc tách khỏi retry provider. ACK hoặc đóng sự kiện dừng reminder; bất thường môi trường sau ACK dừng tới episode mới.
- [x] UI phân biệt dịch vụ tiếp nhận với trạng thái người nhận đã đọc; lịch sử hiển thị kênh, số lần thử và kết quả ảnh.
- [x] Unit assertion cho các nhãn pending/sending/accepted/delivered/bounced/complained/rejected/failed/unknown; accepted không bị gọi là delivered.
- [x] Telegram và email cấu hình độc lập; event được enqueue theo bộ lọc riêng của kênh.
- [x] Migration 011 đã áp dụng lên Neon production (`weathered-river-25273807/production/neondb`); ledger/checksum khớp, worker-only function grants và RLS/FORCE RLS đã xác minh trực tiếp.

**Bằng chứng:** [NotificationSettings.jsx](../../frontend/src/NotificationSettings.jsx), `save_notification_recipient`, `save_notification_policy`, `ingest_event`, `can_dispatch_notification` và `can_schedule_notification_reminder`. PostgreSQL fixture Phase 4 bao phủ camera scope, email chưa xác minh, thu hồi người nhận, bộ lọc và lịch nhắc. Phase 5: ba test PostgreSQL mục tiêu PASS; test safety email xác nhận owner-only history, lọc người nhận và trạng thái `accepted` (không phải `delivered`). [pagination.test.mjs](../../frontend/tests/pagination.test.mjs) 3/3 PASS ở checkpoint trước. Browser history Phase 6 đã đạt; receipt provider hoãn deployment. Xem báo cáo Phase 6 (`docs/reports/PHASE_06_IMPLEMENTATION_REPORT.md`; báo cáo cục bộ, không nằm trong Git). Chi tiết nền Phase 4: báo cáo Phase 4 (`docs/reports/PHASE_04_IMPLEMENTATION_REPORT.md`; báo cáo cục bộ, không nằm trong Git).

### SW-07 — Hoàn thiện Telegram: polling, ghép nối và gửi cảnh báo

**Phạm vi nghiệm thu:** COMPLETE trong web/PBL. Owner tự pairing, duyệt và nhận được đúng một tin chữ/một ảnh tổng hợp có consent. Polling, private Cloudinary read/checksum/cleanup và audit/UI đều có bằng chứng live. Không khẳng định đã tạo event camera mới và chạy pipeline queue live; filter/reminder/retry có kiểm thử cô lập.

- [x] Mẫu tiếng Việt có AnNhà/nhà/phòng/camera, loại/mức độ, thời điểm, giải thích và link sự kiện; có giới hạn độ dài Telegram.
- [x] Worker kiểm quyền ngay trước dispatch; lịch sử phân biệt accepted/failed/unknown, không diễn giải provider acceptance thành đã đọc. Timeout không rõ kết quả không bị retry mù.
- [x] Chỉ đọc/gửi ảnh khi consent bật; kiểm MIME/kích thước/expiry, tải Cloudinary qua backend private provider và fallback text khi ảnh thiếu/hết hạn/lỗi hoặc Telegram từ chối ảnh.
- [x] UI hướng dẫn liên kết Telegram bằng liên kết riêng dùng một lần; không yêu cầu người dùng tìm mã tài khoản hay chạy lệnh. Gửi thử vẫn yêu cầu xác nhận đích/nội dung; API giới hạn tần suất.
- [x] Ngắt Telegram gọi API ngay sau xác nhận, không cần Lưu thay đổi; lỗi giữ trạng thái cũ để thử lại. Tạo liên kết hiện rõ sẵn sàng/Mở/Sao chép/Tạo lại; smoke Playwright mock bao phủ hủy/lỗi/thành công, không gửi Telegram thật.
- [x] Sửa request lưu/ngắt chỉ gửi các trường policy được phép, loại metadata read-only gây 422 Extra inputs. Smoke UI hiện xác thực payload bằng model Pydantic backend thật và đã PASS; frontend cập nhật riêng, không đổi migration/quyền backend.
- [x] Thay browser confirm/prompt bằng modal chung cho gửi thử/ngắt/consent/sao chép link, xoá lịch/âm thanh và thu hồi quyền. Có preview, focus Hủy, Tab/Escape, mobile padding; mock smoke và live modal Hủy không gửi đạt. Toast và nhãn audit Telegram đã chỉnh.
- [x] Polling worker chạy riêng bằng Compose; `getUpdates` long-poll 30 giây, retry/backoff, shutdown theo SIGTERM/SIGINT, kiểm tra webhook hiện có trước khi poll và không tự thay đổi cấu hình bot.
- [x] Chỉ một consumer gọi polling cùng lúc qua transaction advisory lock; cập nhật pairing và offset nằm trong một transaction, offset chỉ tiến sau khi xử lý hoặc bỏ qua an toàn.
- [x] Rà soát timeout Neon trực tiếp: idle transaction 300 giây, transaction timeout tắt; giữ transaction lock cho phạm vi PBL. PostgreSQL 18 cô lập chờ 30 giây với SQL timeout 100 ms vẫn commit, consumer thứ hai bị chặn và API tạo link không bị khoá. Compose poller có grace period 60 giây.
- [x] API tạo link/status chạy với login runtime không superuser/BYPASSRLS/owner membership; quyền app/auth/device trên bảng pairing/poll-state bị từ chối. Lượt rà soát mới đạt 6 unit/mock + 2 PostgreSQL integration, không gọi Telegram gửi/nhận thật.
- [x] `012_telegram_pairing.sql` additive; có RLS/FORCE RLS cho pairing và polling state, chỉ worker truy cập. Đã kiểm thử PostgreSQL cô lập và áp lên Neon qua runner sau phê duyệt; không reset/seed/media changes.
- [x] Neon ledger/checksum/schema/RLS/ACL đã hậu kiểm trực tiếp; checksum 012 `8fa9f5a314e5e323add0ffcd28ac7f29cc8c3c6fc1d72459c74b3170a3525d48` khớp, runtime credentials/session/encryption key giữ nguyên.
- [x] Build/recreate Compose; backend/frontend healthy, poller running 0 restart. Bỏ HTTP healthcheck kế thừa từ API riêng cho worker; readiness dựa polling state. Hai mốc `last_poll_at` live tiến triển sau recreate, offset tồn tại; UI/API `pairing_ready=true`.
- [x] Chủ dự án tự ghép nối từ UI và xác nhận nhận text/ảnh/chú thích. Đích/nội dung/ảnh đã duyệt riêng, consent được kiểm tra trước gửi. Không chuyển Phase 5.
- [x] Payload/provider errors, endpoint accepted/429, worker Retry-After, retry trước hạn và duplicate event đã có kiểm thử mock/fixture focused.
- [x] Đọc `getWebhookInfo` thật ở chế độ chỉ đọc: hiện không có webhook URL. Poller vẫn kiểm tra trước mỗi lần poll và dừng nếu phát hiện webhook; không tự xoá/thay đổi.
- [x] `/start` thật hoàn tất pairing trên Neon và UI hiện đã kết nối; hết hạn/reuse/replay có fixture bổ sung.
- [x] Text endpoint trả 200/accepted và audit có; ảnh Cloudinary riêng tư gửi qua provider trả accepted, audit có và asset thử dọn thành công. Người nhận xác nhận cả text và ảnh/caption.

**Bằng chứng:** unit/PostgreSQL cô lập, migration 012 live, polling state tiến triển; owner pairing và xác nhận nhận text/ảnh. Playwright live thấy connected/consent, modal Hủy không send, hai nhãn audit text/photo và API delivery history 200. Gửi thử có audit riêng, không tạo delivery event giả; queue/event/filter live mới chưa được thực hiện. Xem mục 6–8 trong completion report (`docs/reports/PHASE_04_COMPLETION_REPORT.md`; báo cáo cục bộ, không nằm trong Git).

### SW-08 — Thiết kế mẫu email, hoàn thiện gửi thư và nhận kết quả phát thư

**Trạng thái Phase 5: COMPLETE — MVP/demo.** Reset OTP được chủ dự án tự kiểm tra thành công. Một safety email tổng hợp qua queue/worker/Brevo được chấp nhận và người nhận xác nhận đúng nội dung; attempt_count=1, history accepted. Không gửi lại email hoặc chạy lại suite cũ. Receipt/tracking nâng cao hoãn deployment; UI/phân trang lịch sử bổ sung thuộc Phase 6.

#### EM-01 — Bộ mẫu email thống nhất AnNhà

- [x] Thiết kế layout HTML responsive, bản text thuần, tiêu đề/preheader, CTA và liên kết dự phòng; chủ dự án đã duyệt preview desktop/mobile.
- [x] **Email xác minh tài khoản:** mã 8 chữ số nổi bật trong email HTML và có trong bản text; nhập mã trên website trong 24 giờ, có hướng dẫn gửi lại khi hết hạn; không phụ thuộc link/domain công khai.
- [x] **Email reset mật khẩu:** OTP 8 chữ số nổi bật, hạn 15 phút, không link; không gửi mật khẩu; token cũ vẫn được backend nhận.
- [x] **Email mời legacy (ngoài MVP):** renderer/API cũ giữ tương thích; giao diện MVP sử dụng mã mời, không enqueue email invitation.
- [x] **Email thông báo sự kiện:** mức/loại, nhà/phòng/camera, thời điểm và liên kết sự kiện; không khẳng định người thân an toàn, không kèm ảnh/video.
- [x] Escape dữ liệu động, kiểm tra URL HTTP(S) và preview bốn mẫu với dữ liệu tổng hợp ngắn/dài/tiếng Việt.
- [x] Renderer được tách khỏi nghiệp vụ; queue giữ token/HTML trong payload mã hóa và vẫn hỗ trợ job text cũ.

#### EM-02 — Reset mật khẩu bằng OTP (FAST-TRACK)

- [x] UI email → OTP → mật khẩu mới/xác nhận, resend/lỗi/tiếp tục mã đã nhận; không cần domain.
- [x] OTP HMAC theo email/purpose riêng, 15 phút, một lần; resend vô hiệu mã cũ; rate limit; response không lộ tài khoản; transaction reset + consume + revoke session, legacy token tương thích.
- [x] HTML/text reset có mã lớn; email queue encrypted. Unit/SQLite 4/4 và PostgreSQL 2/2 cho nhóm mới PASS; browser reset/old session/old password/new UI login PASS; không chạy lại suite cũ.
- [x] **CASE 1 live:** chủ dự án tự kiểm tra email/đổi mật khẩu thành công trên ứng dụng chính và xác nhận; agent không gửi lại. Chứng cứ atomic/session/old-new login được kiểm tra cô lập; không quy kết một job đã cleared ciphertext cho người nhận.

#### EM-03 — Invitation Code thay email invitation trong MVP

**COMPLETE MVP/demo.** Không yêu cầu gửi email invitation thật để nghiệm thu Phase 5.

- [x] Owner tạo mã ngẫu nhiên 16 ký tự (80 bit), chỉ hiển thị lần tạo; hash trong DB, hạn 7 ngày, một lần, thu hồi mã chưa dùng.
- [x] User đã đăng nhập và xác minh email nhập mã tại trang Nhà; membership member, quyền xem camera hiện có, không điều khiển/quản trị; cập nhật danh sách nhà ngay.
- [x] Reject mã sai/hết hạn/used/revoked và already-member; atomic transaction, race hai tài khoản chỉ một thành công; rate limit database, không log raw code.
- [x] UI tạo/sao chép/danh sách/trạng thái/thu hồi và form mobile; layout cùng hệ thống component, phân trang.
- [x] SQLite/PostgreSQL focused tests và browser flow PASS; migration 013 đã áp Neon qua runner sau phê duyệt, checksum/ACL/RLS và dữ liệu cũ giữ nguyên.
- [x] Legacy API email invitation giữ tương thích; không ảnh hưởng email xác minh/reset/cảnh báo qua Brevo.

#### EM-04 — Hoàn thiện email xác minh và gửi lại

- [x] Nối mẫu HTML/text cho xác minh lần đầu/gửi lại; mã 8 chữ số có hạn 24 giờ, lưu dạng HMAC digest và giới hạn 5 lần thử mỗi IP trong 15 phút. Link token cũ vẫn được API chấp nhận để tương thích.
- [x] Unit/SQLite kiểm tra renderer, HMAC, nhập mã và luồng gửi lại; giao diện đăng ký chuyển tới màn nhập mã, không cần domain công khai.
- [x] PostgreSQL verify/resend/replay trên `phase5_test` PASS; sửa hai request test còn dùng trường `token` cũ thay vì `code`, chạy lại đúng ca lỗi đạt 1/1.
- [x] Chủ dự án duyệt một email HTML xác minh qua API → queue → worker → Brevo; SMTP accepted, job done/1 attempt, ciphertext cleared. Người dùng nhập mã thành công; database xác nhận account verified và code consumed. Browser màn nhập mã desktop/mobile 2/2 PASS.
- [ ] Deployment/test bổ sung: assertion expiry và resend live của verification; không chặn MVP, không chạy lại trong FAST-TRACK.

#### EM-05 — Hoàn thiện thông báo sự kiện qua email

- [x] Nối mẫu cảnh báo vào nhánh email của worker; nhánh hiện có vẫn áp recipient/filter/reminder, email xác minh và quyền dispatch.
- [x] Queue xác minh/reset độc lập EMAIL_ALERTS_ENABLED theo source; tắt cảnh báo không chặn email tài khoản. Invitation email ngoài luồng MVP.
- [x] PostgreSQL test xác nhận filter/policy, nội dung cảnh báo, history lọc theo người nhận và trạng thái `accepted` không bị coi là `delivered`; gửi SMTP trong test là mock.
- [x] Focused PostgreSQL SMTP mock: lỗi 451 → pending/retry/history failed → accepted/history accepted, sent_count=1, target dispatch lại không gửi trùng.
- [x] **CASE 2 live:** một cảnh báo tổng hợp trên phase5_test, một owner đủ điều kiện; đúng 1 SMTP call/attempt/sent_count, history accepted; chủ dự án xác nhận đã nhận đúng nội dung. Tắt kênh thử sau gửi, không thay đổi production.
- [ ] Deployment: receipt/delivered và tracking nâng cao; không chặn MVP.
- [ ] Bản cảnh báo chữ/HTML và đường dẫn tới web làm trước. Ảnh/bằng chứng Cloudinary nếu có yêu cầu gửi trong email chỉ nghiệm thu sau SW-05 và quy tắc chia sẻ được chốt.

#### EM-06 — Cấu hình gửi thật và kết quả phát thư

- [x] **Cấu hình cơ bản:** Brevo được cấu hình trong `.env` cục bộ; STARTTLS/SMTP AUTH đạt sau khi IP được cho phép. Secret không vào source/report. AUTH thành công chưa chứng minh gửi thư hoặc sender đã được xác minh.
- [x] **SMTP live smoke:** gửi đúng một email text tới người nhận do chủ dự án chỉ định; SMTP chấp nhận và chủ dự án xác nhận đã nhận. Đây là gọi trực tiếp adapter, không tạo lịch sử trong database; `EMAIL_ALERTS_ENABLED` vẫn tắt.
- [x] **Nghiệm thu qua app:** một email HTML xác minh đã được duyệt, gửi qua queue → worker → Brevo và người dùng nhập mã thành công. Lịch sử giao dịch ở `annha_private.job_queue`: done, attempts=1, không lỗi, ciphertext cleared; không tạo row giả trong lịch sử cảnh báo theo sự kiện.
- [ ] **Deployment, không chặn MVP:** adapter/webhook nhận receipt có xác minh chữ ký, chống xử lý trùng và đối chiếu đúng message/channel/email version.
- [ ] **Deployment, không chặn MVP:** cập nhật delivered/bounced/complained/rejected và suppression theo receipt hợp lệ; UI cho biết kết quả gửi có thể xác nhận được, không tự suy ra đã đọc.

**Bằng chứng:** báo cáo Phase 5 mục 9 (`docs/reports/PHASE_05_IMPLEMENTATION_REPORT.md`; báo cáo cục bộ, không nằm trong Git), [InvitationCodes.jsx](../../frontend/src/InvitationCodes.jsx), [013_invitation_codes.sql](../../backend/database/postgresql/013_invitation_codes.sql), [invitation_code_cases.py](../../backend/tests/invitation_code_cases.py). Invitation code: SQLite 1/1 PASS, PostgreSQL local 1/1 PASS, browser flow PASS, Neon migration/postflight PASS, một frontend build cuối PASS. Checkpoint email trước: template 13/13, OTP PostgreSQL 1/1 và verification live qua queue đã đạt; không chạy lại các suite email/Telegram. Receipt tự động hoãn tới deployment public HTTPS.

### SW-09 — Tìm kiếm và diễn biến sự kiện đầy đủ

**COMPLETE — Phase 6 PostgreSQL MVP.**

- [x] Filter start/end timezone [start,end), mức info/warning/critical, kết hợp phòng/camera/loại/trạng thái; giữ pagination sự kiện hiện có.
- [x] Timeline observation riêng, sequence/observed/received/reason/severity, server paging. 13 updates và trang 2 đạt API/browser.
- [x] Evidence chưa gửi/failed/expired/deleted/deleting/processing và ảnh tải lỗi được phân biệt; không mất event khi ảnh không có.
- [x] Giữ nguyên nghiệp vụ đóng/báo giả; bất thường vẫn cần confirm/ghi chú. Không áp thêm thay đổi policy trong Phase 6.
- [ ] Đề xuất sau MVP: yêu cầu lý do báo giả ngay cả khi đã recovered (khác policy hiện tại, không chặn phạm vi Phase 6 được giao).

**Bằng chứng:** `pgapi.events`, `event_updates`, `event_scope`; [EventScreens.jsx](../../frontend/src/EventScreens.jsx), [focused tests](../../backend/tests/test_phase6_web.py) và báo cáo Phase 6 (`docs/reports/PHASE_06_IMPLEMENTATION_REPORT.md`; báo cáo cục bộ, không nằm trong Git).

### SW-10 — Biểu đồ môi trường bao phủ đúng khoảng thời gian

**COMPLETE — Phase 6 PostgreSQL MVP.**

- [x] SQL aggregation toàn range không cắt 500 raw rows; buckets giới hạn, mean/min/max/count, latest raw.
- [x] Custom start/end, coverage theo bucket có mẫu, số batches, khoảng thiếu, quality valid và đơn vị gas tách riêng; bảng raw server paging.
- [x] Fixture 605 mẫu: test range 24h đủ count/mean/min/gaps, browser custom range và 7 ngày đủ 605 mẫu; raw trang 61 có 5 mẫu.

**Bằng chứng:** `pgapi.telemetry_summary`, `telemetry`, [web_queries.py](../../backend/src/web_queries.py), [EnvironmentChart.jsx](../../frontend/src/EnvironmentChart.jsx), [HomeScreens.jsx](../../frontend/src/HomeScreens.jsx). Coverage không được diễn giải thành uptime; gap hiển thị ở độ rộng bucket.

### SW-11 — Hoàn thiện trải nghiệm thư viện âm thanh và lịch nhắc lỗi

**COMPLETE — Phase 6 PostgreSQL MVP.** Media service/preview/TTS/ghi âm giữ nguyên từ các Phase trước, không test lại provider.

- [x] Inline upload trong form lịch, cùng search/server-paged picker; đọc metadata sẵn sàng trước lưu.
- [x] Library filter camera/tên/status, usage theo revision hiện hành, rename owner/manage, delete guard UI/API; disabled schedule vẫn bảo vệ file.
- [x] Giữ lỗi/retry TTS hiện có, không nhầm file ready với ACK/kết quả phát.
- [x] Khóa camera khi edit lịch; backend vẫn từ chối chuyển camera như trước.
- [x] Browser upload WAV local → chọn file → lưu lịch; search/rename/in-use disabled và desktop/mobile đạt. Cloudinary/ghi âm/provider live không chạy lại.

**Bằng chứng:** [AudioPicker.jsx](../../frontend/src/AudioPicker.jsx), [Reminders.jsx](../../frontend/src/Reminders.jsx), `pgapi.asset_metadata`, `rename_asset`, `assets`, `save_reminder` và báo cáo Phase 6 (`docs/reports/PHASE_06_IMPLEMENTATION_REPORT.md`; báo cáo cục bộ, không nằm trong Git).

### SW-12 — Quản lý dung lượng và chính sách lưu dữ liệu trên web

**Trạng thái Phase 2:** quota API/UI, cảnh báo gần đầy, reserved capacity, retention ảnh, bảo vệ audio đang được reminder dùng, cleanup và daily reconciliation đã có. Restore cô lập đạt; live verification branch Neon còn chờ quyền API.

- [x] API/UI hiển thị dung lượng dùng/giữ chỗ/quota theo nhà, trạng thái cảnh báo và retention.
- [x] Daily reconciliation báo media thiếu/orphan; tự động dọn chỉ loại có TTL hoặc failed staging quá 7 ngày.
- [x] Không xoá audio đang được lịch hiện hành dùng; event record vẫn còn khi ảnh hết hạn.
- [x] Test quota/provider retry/idempotency/delete và restore database/media metadata trên clone cô lập, không ghi production.

**Bằng chứng:** [pgapi.py](../../backend/src/pgapi.py), [pgservices.py](../../backend/src/pgservices.py), [AdminScreens.jsx](../../frontend/src/AdminScreens.jsx), [test_postgres.py](../../backend/tests/test_postgres.py). Browser đã render thanh quota trước khi smoke dừng ở assertion nhãn viết hoa/thường; vì vậy xác nhận UI browser còn PARTIAL. Retention mới không áp hồi tố lên media cũ.

### SW-13 — Phân trang backend và tải dữ liệu theo nhu cầu

**COMPLETE — Phase 6 PostgreSQL MVP.**

- [x] Assets/executions/audit/delivery trả envelope khi có page, COUNT trước LIMIT dưới RLS; stable order; audio permissions lọc SQL trước count.
- [x] 205 executions/deliveries, trên 205 audit và 23 audio: trang 21/3 vẫn có dữ liệu, không cắt ở 200; filter và outsider/viewer đạt.
- [x] Lazy tab library/history và panel audit/delivery, shared App chỉ tải events/reminders cho màn dùng tới; picker theo camera/search/page. Không xây tầng cache mới.
- [x] Giữ abort/stale-response guard của useResource và guard home/session của App; page reset khi filter/home đổi và clamp khi total giảm. Source inspection cho guard, không chạy lại các test Phase 1–5.
- [x] Sửa nested pool reads trong event_scope/asset_scope; 9 request concurrent PASS, không bỏ can_camera/RLS.
- [ ] Sau MVP: benchmark dữ liệu hàng triệu rows/cursor pagination nếu cần; offset hiện có thể dịch trang khi mới chèn.

**Bằng chứng:** [web_queries.py](../../backend/src/web_queries.py), [serverPaging.jsx](../../frontend/src/serverPaging.jsx), [App.jsx](../../frontend/src/App.jsx), [test_phase6_web.py](../../backend/tests/test_phase6_web.py). Không viết lại pagination sự kiện cũ; không triển khai parity SQLite mới.

## P2 — tiện ích thuần phần mềm nên chốt ở vòng sau

### SW-14 — Hoàn thiện quản lý phòng và metadata camera

- [ ] Xoá/lưu trữ phòng rỗng, xử lý phòng còn camera/lịch bằng thông báo và ràng buộc rõ.
- [ ] Đổi tên camera, chuyển camera sang phòng khác trong cùng nhà với kiểm tra quyền và audit. Đây là metadata nghiệp vụ, không phải chuyển động servo hay cấu hình driver.
- [ ] Không tự đổi chủ hoặc chuyển thiết bị sang nhà khác qua thao tác chuyển phòng.

**Bằng chứng:** [pgapi.py:165](../../backend/src/pgapi.py#L165) có GET/POST/PATCH phòng, chưa có DELETE; camera có claim/delete nhưng chưa có PATCH metadata; [AdminScreens.jsx:43](../../frontend/src/AdminScreens.jsx#L43) chỉ thêm/đổi tên phòng.

### SW-15 — Tài khoản và quản lý phiên tự phục vụ

- [ ] Danh sách phiên đăng nhập, đăng xuất các phiên khác.
- [ ] Đổi email kèm xác minh địa chỉ mới, vô hiệu liên kết cũ và cập nhật kênh cảnh báo liên quan.
- [ ] Có thể bổ sung đổi mật khẩu bằng mật khẩu hiện tại + xác thực lại. Luồng đổi qua liên kết email hiện đã có, không gọi là “chưa có đổi mật khẩu”.

**Bằng chứng:** [AdminScreens.jsx:50](../../frontend/src/AdminScreens.jsx#L50), [pgapi.py:73](../../backend/src/pgapi.py#L73), [pgapi.py:90](../../backend/src/pgapi.py#L90), [pgapi.py:102](../../backend/src/pgapi.py#L102). Chưa có API danh sách/thu hồi phiên tùy chọn hoặc đổi email.

### SW-16 — Mã mời thành viên và tự rời nhà

**Mã mời MVP COMPLETE.** Email invitation/inbox/resend email không thuộc tiêu chí MVP hiện tại.

- [x] Chủ nhà tạo/sao chép/thu hồi, danh sách trạng thái; user nhập mã ở trang Nhà; cập nhật home selection và truy cập camera ngay.
- [x] Role member, quyền view-only có camera grants; owner chỉnh role/camera bằng cơ chế hiện có. Mã không buộc email cụ thể và chỉ một tài khoản verified dùng được.
- [x] Migration 013 Neon đã áp sau phê duyệt; hash/expiry/atomic/rate-limit/ACL và browser flow được kiểm tra cô lập; main app health/API-list/UI smoke đạt, không tạo fixture production.
- [ ] Cho thành viên tự rời nhà và thu hồi quyền ngay; chủ nhà duy nhất phải có quy tắc riêng trước khi rời (ngoài thay đổi mã mời).

**Bằng chứng:** [pgapi.py](../../backend/src/pgapi.py), [InvitationCodes.jsx](../../frontend/src/InvitationCodes.jsx), báo cáo Phase 5 (`docs/reports/PHASE_05_IMPLEMENTATION_REPORT.md`; báo cáo cục bộ, không nằm trong Git).

## FAST-TRACK Phase 5 → Phase 6

Phase 5 đã nghiệm thu, không làm/test lại. **Phase 6 P1 đã triển khai và đạt MVP trên PostgreSQL**: SW-09/10/11/13 và SW-06 history. Xem báo cáo kết quả thực tế (`docs/reports/PHASE_06_IMPLEMENTATION_REPORT.md`; báo cáo cục bộ, không nằm trong Git). Một frontend build cuối PASS, Compose backend/frontend healthy. Không migration, không fixture production và không provider live; P2 và SQLite parity giữ ngoài lượt này.

## Công việc nền để nghiệm thu phần mềm

### SW-17 — Bổ sung regression/CI cho các khoảng trống vừa phát hiện — P1

**Trạng thái Phase 3:** focused regression và các smoke browser còn thiếu của Phase 2 đã đạt trên môi trường cục bộ cô lập. Một fixture ban đầu bị rỗng sau bước kiểm tra nhà trống và fixture lịch sử thông báo không có dữ liệu; đã sửa QA fixture, không phải luồng sản phẩm. Không chạy lại migration Cloudinary hoặc các bulk test Phase 2.

- [x] Regression SQLite cho zone legacy/restart, ACK, permissions theo camera, cross-home/cross-camera, revocation; frontend unit test cho quyền camera và quyền bị thu hồi.
- [x] Frontend production build và toàn bộ frontend unit tests đã chạy.
- [x] Lượt hoàn tất PostgreSQL Phase 3 chạy 9 test, gồm atomic enqueue/rollback, quota, delete race, restart/lease reclaim, provider timeout, DB commit rollback/finalization failure, active >100, camera-level count/revocation và worker isolation.
- [x] `scripts/qa/frontend.mjs`: 40 UI checks PASS; gồm desktop/mobile, active badge/toast/dedup, event image, WAV/MP3 playback, TTS preview, offline/empty state và camera role views.
- [x] `scripts/qa/recording-settings.mjs`: 6 checks PASS; ghi âm WebM bằng microphone giả, upload fixture, dùng trong lịch, từ chối quyền microphone, lịch sử thông báo và layout settings.
- [x] Browser realtime fault injection mới đạt 6/6; script riêng `scripts/qa/phase3-realtime.mjs` không phụ thuộc dữ liệu/credential production.
- [x] Sound-only browser pass đạt 3/3 sau khi chủ dự án xác nhận; không chạy lại backend/realtime suite đã đạt.
- [ ] CI workflow và notification policy/provider extensions ngoài Phase 3 còn mở.

**Bằng chứng:** [backend/tests/test_postgres.py](../../backend/tests/test_postgres.py), [scripts/qa](../../scripts/qa), [frontend/tests](../../frontend/tests). Repo hiện chưa có `.github/workflows`; các bộ test hiện hữu có giá trị, không thay bằng viết lại toàn bộ.

### SW-18 — Trạng thái dịch vụ, backup/restore và tài liệu vận hành — P1

**Điều chỉnh phạm vi do chủ dự án yêu cầu:** giai đoạn đồ án dùng recovery có sẵn của Neon và Cloudinary; giữ nguyên runbook restore đã diễn tập. Backup dài hạn không phải điều kiện hoàn thành Phase 3. Không bổ sung scheduler, S3 hay dịch vụ lưu trữ mới.

- [ ] Theo dõi worker còn chạy, job tồn/lỗi và tình trạng storage/email; health DB đang có không đồng nghĩa queue/email đều hoạt động.
- [x] Giữ nguyên runbook Neon metadata + Cloudinary mapping + local originals; dump chỉ đọc và restore rehearsal cùng đối chiếu SHA-256 đã đạt trên PostgreSQL 18 cô lập.
- [x] Không tạo job backup định kỳ, S3 hoặc storage service mới; không xoá dữ liệu Neon/media gốc.
- [ ] Kiểm tra branch/PITR/retention bằng Neon API khi cần; không chặn Phase 3 và không triển khai cấu hình backup dài hạn trong giai đoạn đồ án.
- [ ] Chốt hỗ trợ PostgreSQL/SQLite: nếu giữ cả hai cần test parity tính năng; nếu chỉ hỗ trợ PostgreSQL thì công bố/deprecate SQLite có lộ trình.

**Bằng chứng:** [entrypoint.py](../../backend/src/entrypoint.py) còn chọn hai backend; [pgmain.py:144](../../backend/src/pgmain.py#L144) health kiểm tra DB; [docs/planning/IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) chứa nhiều lớp lịch sử; [compose.yaml](../../compose.yaml) gộp worker vào backend và media ở volume local.

### Backlog production sau này — nâng cao recovery (không chặn Phase 3)

- Đánh giá và ghi rõ retention/PITR sẵn có của Neon, quyền khôi phục branch và thời gian phục hồi mục tiêu khi chuẩn bị production.
- Kiểm tra chính sách khôi phục asset/xoá mềm và lưu phiên bản Cloudinary; thực hiện diễn tập restore mapping cùng object khi cần.
- Chỉ cân nhắc lịch backup ngoài dịch vụ hoặc kho độc lập nếu yêu cầu RPO/RTO, quy định lưu giữ hoặc khả năng khôi phục của Neon/Cloudinary thực sự đòi hỏi.
- Chưa chọn hoặc triển khai scheduler, S3 hay nhà cung cấp lưu trữ mới.

## Thứ tự triển khai đề xuất

1. **Vòng 1 — đã nghiệm thu phần mềm:** SW-01, SW-02, SW-03, SW-04 và focused regression SW-17; các giới hạn fixture/live service ghi trong completion report.
2. **Vòng 2 — SW-06/SW-07/SW-08:** SW-07 COMPLETE web/PBL; SW-08 COMPLETE MVP; SW-06 history Phase 6 đã COMPLETE MVP, receipt hoãn deployment. Verification email qua queue/Brevo đã được người dùng nhập mã thành công. Invitation Code MVP COMPLETE, migration 013 Neon đã áp, không cần domain hay email invitation. Các tiện ích khác tiếp tục theo SW-09–SW-16.
3. **Vòng 3 — tích hợp teammate:** clip video, Raspberry Pi, camera/loa/cảm biến/servo; giữ nguyên các API media tương thích đã có.
4. **Vòng 4 — tiện ích bổ sung:** chốt SW-14, SW-15, SW-16 theo nhu cầu; có thể làm trong thời gian chờ Cloudinary nếu phù hợp nguồn lực.

Không yêu cầu teammate Pi hoàn thành servo hay gửi dữ liệu thật trước khi bắt đầu các vòng này. Chỉ cần dùng hợp đồng API và fixture phần mềm; khi tích hợp sau, đối chiếu hợp đồng đã thống nhất.

## Nhật ký cập nhật tiến độ

Khi bắt đầu/kết thúc một nhiệm vụ, cập nhật trạng thái trong bảng chung, checkbox phần việc, rồi thêm một dòng bằng chứng ở đây. Chỉ ghi **Hoàn thành** khi tiêu chí nghiệm thu của phần được giao đã đạt.

| Ngày | Mục | Thay đổi | Bằng chứng / ghi chú |
|---|---|---|---|
| 04/11/2026 | Phase 3 completion | SW-03/SW-04 hoàn thành core; 010 lên Neon, đóng các gap realtime/reliability | 7/7 migration checksums, ACL/no-write TTS smoke; 9/9 PostgreSQL, 6/6 realtime browser, build PASS. Âm báo đã được xác nhận và hoàn tất, sound-only 3/3 cùng build mới PASS. Xem completion report (`docs/reports/PHASE_03_COMPLETION_REPORT.md`; báo cáo cục bộ, không nằm trong Git) |
| 04/11/2026 | Backlog | Tổng hợp 18 đầu việc phần mềm, chưa triển khai | Audit source/OpenAPI và kiểm thử offline ở cuối file |
| 04/11/2026 | Cloudinary / Phase 2 | Adapter, API proxy, lifecycle, quota, migration tool, inventory và docs; media live migration | Upload/read/delete ảnh và WAV đạt; local-to-cloud 4/4, reconcile 4 cloud + 11 local, thiếu/checksum mismatch/orphan đều 0; originals giữ nguyên. Xem PHASE_02_IMPLEMENTATION_REPORT.md (`docs/reports/PHASE_02_IMPLEMENTATION_REPORT.md`; báo cáo cục bộ, không nằm trong Git) |
| 04/11/2026 | Backlog SW-06/SW-07/SW-08 | Ghi nhận phạm vi mẫu email, luồng tài khoản/cảnh báo và Telegram chữ cần hoàn thiện | Đây là hạng mục backlog, không phải bằng chứng các template email EM-01–EM-06 đã được triển khai; trạng thái hiện tại của email được cập nhật tại checkpoint Phase 5 bên dưới |
| 04/11/2026 | Phase 4 — SW-06/SW-07 | Thêm migration additive 011, cấu hình recipient/filter/reminder, Telegram text/photo consent, private media read, UI và test fixtures | Migration 011 đã áp; ledger/checksum, worker-only function ACL và RLS/FORCE RLS PASS. Live Telegram/Cloudinary vẫn chờ credential và phê duyệt gửi; xem báo cáo Phase 4 (`docs/reports/PHASE_04_IMPLEMENTATION_REPORT.md`; báo cáo cục bộ, không nằm trong Git) |
| 04/11/2026 | SW-07 long polling / pairing | Thêm worker polling riêng, durable offset, single-consumer lock, webhook guard và pairing một lần | 8 unit + 3 PostgreSQL focused tests, frontend build và Compose build PASS; migration 012 chỉ áp trên PostgreSQL cô lập, Neon đang chờ duyệt; chưa gửi live. Xem PHASE_04_COMPLETION_REPORT.md (`docs/reports/PHASE_04_COMPLETION_REPORT.md`; báo cáo cục bộ, không nằm trong Git) |
| 05/11/2026 | SW-07 triển khai sau phê duyệt | Áp 012 qua runner, xác minh ledger/checksum/RLS/grants; start Compose polling | 44 bảng; key/credential giữ nguyên. Poller running, state tiến triển qua recreate; API/UI pairing ready. Chờ owner pairing và duyệt gửi text/ảnh thật; SW-07 PARTIAL |
| 05/11/2026 | SW-07 nghiệm thu web/PBL | Owner tự pairing; text và ảnh tổng hợp đã duyệt/consent được nhận; hoàn thiện popup và báo cáo | SW-07 COMPLETE; Cloudinary private read/checksum/cleanup, audit, UI live và build đạt. SW-06/queue live giữ giới hạn riêng; không chuyển Phase 5 |
| 05/11/2026 | Phase 5 checkpoint — EM-01/SW-06 | Tạo renderer email draft HTML/text, escape dữ liệu, validate URL, preview 4 mẫu với biến thể ngắn/dài và khung desktop/mobile; bổ sung MIME multipart và assertion lịch sử | 5/5 Python unit, 3/3 frontend unit, py_compile PASS. Preview cần duyệt; chưa nối vào queue gửi, chưa có SMTP provider hoặc gửi live. Docker socket không khả dụng nên Mailpit/PG integration chưa chạy. Xem PHASE_05_IMPLEMENTATION_REPORT.md (`docs/reports/PHASE_05_IMPLEMENTATION_REPORT.md`; báo cáo cục bộ, không nằm trong Git) |
| 05/11/2026 | Phase 5 sau duyệt — EM-01/02/03/04/05 | Chủ dự án duyệt nội dung; nối verify/reset/invitation/safety alert vào renderer và MIME HTML/text; mở rộng unit test | 8/8 Python unit PASS; preview sinh lại 8 biến thể. Chưa có PostgreSQL integration mới, SMTP provider, live send hoặc migration. Docker socket vẫn chặn Mailpit/PG isolated. Xem PHASE_05_IMPLEMENTATION_REPORT.md (`docs/reports/PHASE_05_IMPLEMENTATION_REPORT.md`; báo cáo cục bộ, không nằm trong Git) |
| 05/11/2026 | Phase 5 — Brevo/SMTP và integration tests | Cấu hình Brevo STARTTLS; sau khi IP được cho phép, auth-only probe đạt; bổ sung test PostgreSQL cho verify/reset/invitation/safety email, sửa loader env và giảm log pool | `backend.tests.test_email_templates` 9/9 PASS; SMTP AUTH thành công, không gửi thư. APP runtime test đạt probe; URL AUTH/DEVICE/WORKER hiện không cùng endpoint và TLS verify-full chưa xác minh được. PostgreSQL tests chưa chạy lại sau cập nhật URL; không có fixture write. Chưa nghiệm thu app queue/history/receipt. Xem báo cáo Phase 5 (`docs/reports/PHASE_05_IMPLEMENTATION_REPORT.md`; báo cáo cục bộ, không nằm trong Git) |
| 05/11/2026 | Phase 5 — kiểm tra role PostgreSQL | Cập nhật URL về endpoint test; role probe xác nhận APP/AUTH/DEVICE đúng, xác nhận login worker tồn tại nhưng URL worker đang dùng login device | Test invocation dừng trước test methods do selector verify/reset sai và worker pool thiếu quyền `SET ROLE`; không ghi fixture. Cần sửa đúng một biến `DATABASE_URL_WORKER`; tên method verify/reset đúng đã được ghi trong báo cáo. Xem PHASE_05_IMPLEMENTATION_REPORT.md (`docs/reports/PHASE_05_IMPLEMENTATION_REPORT.md`; báo cáo cục bộ, không nằm trong Git) |
| 05/11/2026 | Phase 5 — email thử live | Gửi một email text duy nhất qua Brevo adapter tới người nhận đã chỉ định | SMTP accepted; chủ dự án xác nhận đã nhận. Gửi ngoài app queue nên không tạo delivery-history row. Không gửi email nào khác. Xem báo cáo Phase 5 (`docs/reports/PHASE_05_IMPLEMENTATION_REPORT.md`; báo cáo cục bộ, không nằm trong Git) |
| 05/11/2026 | Phase 5 — kiểm thử PostgreSQL sau khi sửa URL | Sửa fixture timestamp hết hạn và assertion UUID/JSON trong test; chạy lại hai test lỗi | Runtime role APP/AUTH/DEVICE/WORKER đều đạt trên `phase5_test`; verify/resend/reset/session, invitation và safety email/history: 3 ca mục tiêu PASS tổng cộng. Provider SMTP trong test được mock; không gửi thư thật, không truy cập production. Xem báo cáo Phase 5 (`docs/reports/PHASE_05_IMPLEMENTATION_REPORT.md`; báo cáo cục bộ, không nằm trong Git) |
| 05/11/2026 | Phase 5 — chờ duyệt app queue | Chuẩn bị một email xác minh duy nhất qua app queue → worker → Brevo | Chưa tạo job mới hoặc gửi thư. Đã trình bày người nhận, tiêu đề, nội dung và hành động trong báo cáo Phase 5 (`docs/reports/PHASE_05_IMPLEMENTATION_REPORT.md`; báo cáo cục bộ, không nằm trong Git); chờ chủ dự án phê duyệt trước khi thực hiện. |
| 05/11/2026 | Phase 5 — xác minh bằng mã, không cần domain | Đổi email xác minh từ link sang mã 8 chữ số có HMAC, thêm giao diện nhập/gửi lại, HTML rõ ràng và plain text fallback | Template 13/13 PASS; SQLite business 10/10 tính gộp; build/preview PASS. PostgreSQL OTP bị DNS chặn; chưa gửi queue email thật. Cập nhật đề xuất người nhận/tiêu đề/nội dung trong báo cáo Phase 5 (`docs/reports/PHASE_05_IMPLEMENTATION_REPORT.md`; báo cáo cục bộ, không nằm trong Git), chờ duyệt trước gửi. |
| 05/11/2026 | Phase 5 — live app queue và nhập mã | Sau phê duyệt, tạo một tài khoản qua API trên phase5_test, xử lý đúng một email job qua worker/Brevo, đọc lại trạng thái sau khi người dùng nhập mã | PostgreSQL mục tiêu 1/1 PASS sau sửa payload test; API 201, SMTP accepted, queue done/1 attempt/ciphertext cleared; user xác nhận hoàn thành và DB verified/code consumed. Browser verify desktop/mobile 2/2 PASS. Các email thật khác và receipt còn mở. |
| 05/11/2026 | Phase 5 — cập nhật Compose chính | Build và recreate riêng backend/frontend để đưa HTML/OTP vào localhost:8188, giữ volume và database | Build PASS (4603 modules); backend/frontend healthy; renderer checksum khớp source, SMTP cấu hình đủ qua boolean, health PostgreSQL connected và bundle OTP mới có mặt. Hai tiến trình test tạm 8018/5188 đã dừng sau khi người dùng xác minh thành công. |
| 05/11/2026 | Phase 5 — Invitation Code MVP | Thay luồng mời UI bằng mã ngẫu nhiên một lần/7 ngày, member/view-only; giữ email invitation legacy backend | SQLite 1/1 + PostgreSQL local 1/1 PASS; browser owner tạo/copy→member mobile join→camera→owner sửa quyền PASS. Migration 013 Neon sau duyệt: checksum/RLS/ACL/counts PASS; một frontend Docker build PASS, Compose cập nhật và main API/UI smoke PASS. Không gửi email, không reset/seed production. |
| 05/11/2026 | FAST-TRACK chuẩn bị đóng Phase 5 | Reset OTP + target safety email worker; 4 unit/SQLite + 2 PostgreSQL mock mới và 1 browser reset flow PASS; một final Docker build | Chưa gửi email thật mới. Chờ một phê duyệt chung cho đúng 2 email (OTP reset + safety tổng hợp) tới địa chỉ đã trình trong report. Receipt/tracking nâng cao chuyển deployment. Phase 6 chưa triển khai trước khi hai CASE đạt. |
| 04/11/2026 | SW-01/SW-02/SW-17 | Bỏ zone, quyền camera-level, migration 009; hồi quy cuối | Camera permission test riêng PASS 1/1 sau khi assertion được sửa; frontend build/unit đạt trước; browser smoke thiếu dữ liệu environment history cho nhà đang chọn. Xem PHASE_01_IMPLEMENTATION_REPORT.md (`docs/reports/PHASE_01_IMPLEMENTATION_REPORT.md`; báo cáo cục bộ, không nằm trong Git) |

## Kiểm chứng Phase 1

- `npm run build`: PASS; Vite build hoàn tất và gói Sites được tạo.
- `npm run test:frontend`: 11/11 PASS.
- `python3 -m unittest backend.tests.test_business -v`: 10/10 PASS trên SQLite test tạm.
- `python3 -m py_compile backend/src/*.py backend/tests/test_business.py backend/tests/test_postgres.py`: PASS.
- `ANNHA_TEST_ENV=<isolated-runtime.env> python3 -m unittest backend.tests.test_postgres -v`: PostgreSQL 16 cục bộ cô lập, lượt đầu 12 PASS/1 FAIL do assertion 422/404. Sau khi sửa, chạy lại riêng `test_camera_permissions_are_isolated_and_schedule_tts_obeys_rls`: PASS 1/1; không chạy lại cả suite.
- `docker compose exec -T backend python -m src.media_migration --apply --limit 1 --batch-size 1 --backup-reference br-sparkling-rice-a1s9o211`: PASS, chuyển và xác minh 1 asset; batch tiếp theo PASS, chuyển thêm 3; mọi file local được giữ.
- `docker compose exec -T backend python -m src.media_migration --reconcile`: PASS, 4 Cloudinary asset không thiếu/checksum lệch; 11 local không thiếu/checksum lệch; không có file local không ánh xạ hoặc staged. Admin inventory namespace app: 4 resources, 0 orphan.
- Migration `009_schedule_tts_permissions.sql` đã được runner áp dụng lên branch Neon `production`; đọc lại ledger/checksum và catalog policy/RLS bằng truy vấn chỉ đọc. Không chạy bộ API test trên production.
- Người dùng xác nhận bằng mắt trang tài khoản đã có khoảng cách sau khi recreate Compose. Playwright automation chưa xác minh: frontend/backend healthy, CSS mới có trong image; Chromium Playwright chưa có, Chrome hệ thống thoát `SIGABRT` trong sandbox. Shell cũng không truy cập cổng local.
- Đã rebuild/restart frontend và backend local Compose; backend `/api/health` trả online, database PostgreSQL connected. Chưa deploy lên hosting từ xa. Migration 001–008 được giữ nguyên; 009 chỉ thay policy `audio_upload`, không thêm grant hay sửa dữ liệu.


| 05/11/2026 | Phase 5 nghiệm thu cuối | Chủ dự án xác nhận reset thành công và nhận đúng safety email tổng hợp đã duyệt | Phase 5/SW-08 COMPLETE — MVP/demo; CASE 2 queue/worker/Brevo 1 attempt accepted và inbox confirmed. Không lặp SMTP/test cũ; receipt deployment, SW-06 UI và Phase 6 còn riêng. |

| 05/11/2026 | Phase 6 P1 PostgreSQL MVP | Triển khai filter/timeline/evidence, telemetry aggregation, inline audio/library UX và server pagination/history | 5 focused integration tests PASS tính gộp; browser desktop/mobile PASS sau sửa nested pool reads; 605 mẫu/7 ngày, 205+ history rows. Một frontend build 4607 modules PASS, Compose healthy. Không migration/provider live/P2; SQLite parity ngoài phạm vi. |
