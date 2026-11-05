# Trạng thái triển khai AnNhà

Cập nhật **05/11/2026 — sau Phase 6, phạm vi web/PBL**. Bản này thay thế các checkpoint cũ; ghi chép trước đó giữ cục bộ trong `docs/reports/legacy/IMPLEMENTATION_STATUS_BEFORE_PHASE6.md`.

| Phần | Trạng thái và phạm vi |
|---|---|
| Tài khoản/quyền (Phase 1) | Backend kiểm tra session/CSRF, vai trò và quyền camera; quyền âm thanh và lịch tách riêng |
| Media (Phase 2) | Cloudinary server-side cho ảnh/âm thanh, private read và consent, retry/delete/retention; còn hỗ trợ file local trong Docker volume |
| Queue/realtime (Phase 3) | TTS enqueue nguyên tử, lease/reclaim/retry, count cảnh báo và reconnect; âm báo trình duyệt tùy chọn |
| Telegram (Phase 4) | COMPLETE web/PBL: long polling, link pairing một lần/10 phút, offset bền vững, single consumer cùng DB; text và ảnh có consent đã được nhận |
| Email/mã mời (Phase 5) | COMPLETE MVP: Brevo STARTTLS, HTML/OTP xác minh và reset; chủ dự án xác nhận reset và safety email qua queue; mời bằng mã một lần/7 ngày |
| Phần mềm web (Phase 6) | COMPLETE P1 PostgreSQL MVP: filter/timeline/evidence, aggregation telemetry toàn range/coverage, inline upload/audio usage/rename, server pagination và notification filters |
| Receipt email | Hoãn deployment HTTPS; accepted không được coi là delivered, không có tracking mở thư |
| SQLite legacy | Không có toàn bộ API Phase 6; runtime nghiệm thu là PostgreSQL |
| Phần cứng/video/P2 | Không nghiệm thu trong các lượt web; teammate tích hợp Pi/camera/servo/loa/cảm biến. SW-14/15/16 bổ sung tiếp tục theo backlog |

## Vận hành hiện tại

- Compose: frontend/nginx + backend/FastAPI + MQTT + Mailpit + Telegram poller. App thường ở `http://localhost:8188`; Mailpit chỉ nhận thư khi cấu hình SMTP trỏ Mailpit.
- PostgreSQL có migration đến `013_invitation_codes.sql`; các migration đã được áp qua runner sau phê duyệt. Phase 6 không thêm migration/schema/grants.
- Theo yêu cầu chủ dự án ngày 05/11, đã bật `EMAIL_ALERTS_ENABLED=true` trên máy hiện tại. Cờ này không tự bật preference email của từng người; chủ nhà chọn người nhận/bộ lọc trên web. File `.env` không nằm trong Git, máy teammate phải tự cấu hình.
- Runtime dùng bốn URL hạn quyền app/auth/device/worker. Cloudinary secret là file mount riêng; không truyền owner URL, SMTP key hoặc bot token vào frontend.
- Bản bàn giao giữ đầy đủ chức năng; máy dùng DB/bot chung cần hiểu lease và single polling consumer; DB clone vẫn có thể tham chiếu media gốc. Xem [hướng dẫn bàn giao](../handoff/TEAMMATE_SETUP.md).

## Bằng chứng nghiệm thu

Phase 6: 5 focused PostgreSQL integration tests PASS tính gộp, browser desktop/mobile PASS sau sửa nested pool read; range 7 ngày đủ 605 mẫu, history vượt 200 bản ghi. Một build frontend cuối PASS (4607 modules), backend/frontend Compose healthy. Không chạy lại các suite/provider cũ để đóng Phase 6.

Báo cáo đầy đủ ở `docs/reports/PHASE_01_IMPLEMENTATION_REPORT.md` đến `docs/reports/PHASE_06_IMPLEMENTATION_REPORT.md`. Thư mục reports được giữ cục bộ và gitignore; gửi riêng khi teammate cần review bằng chứng. Nội dung backlog được commit tại [SOFTWARE_BACKLOG_ANNHA.md](SOFTWARE_BACKLOG_ANNHA.md).

## Giới hạn cần nhớ

Nghiệm thu web không chứng minh inference, điều khiển servo hay phát loa đã chạy trên Pi. Khi thiếu thiết bị, ảnh minh họa luôn được trình bày như placeholder, không giả LIVE. Không reset/seed DB đang dùng để dựng máy khác. Local media/TTS cần file thực ngoài DB; không tự có khi clone repository.
