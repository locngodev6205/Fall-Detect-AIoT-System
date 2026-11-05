# Bàn giao AnNhà cho teammate

Cập nhật 05/11/2026. Hướng dẫn này dành cho bản web MVP PostgreSQL hiện tại; không tự migrate, reset hoặc seed database đang dùng.

Bản ZIP riêng `AnNha_Teammate_Handoff_2026-11-05.zip` gồm cấu hình đầy đủ, Cloudinary secret, thông tin tài khoản seed, snapshot media local và các reports cục bộ. Gói có credential thật nên chỉ gửi riêng, không upload vào GitHub. `README_BAN_GIAO.md` trong ZIP hướng dẫn copy cấu hình, restore media trước khi khởi động và dùng đầy đủ stack. ZIP không lặp source code; teammate clone/pull `main` đã bàn giao.

## 1. Cần gửi gì ngoài repository và `.env`?

| Thành phần | Có cần gửi riêng? | Ghi chú |
|---|---|---|
| `.secrets/cloudinary.env` | **Có, nếu dùng Cloudinary hiện tại** | Compose mount file này làm secret. Root `.env` không thay thế được file mount. Nếu dùng đường dẫn khác, gửi đúng file được `CLOUDINARY_CONFIG_FILE` trỏ tới; mẫu nằm ở `docker/cloudinary/cloudinary.env.example` |
| Thông tin đăng nhập tài khoản ứng dụng | **Có nếu dùng tài khoản seed hiện có** | Chia sẻ riêng tài khoản phù hợp; file cục bộ `.secrets/demo-credentials.json` có thể dùng để tra cứu. Không đưa mật khẩu vào tài liệu/Git. Hoặc teammate tự đăng ký và chủ nhà cấp mã mời |
| Media còn lưu local | **Có nếu cần giữ đúng nội dung cũ** | PostgreSQL chỉ chứa metadata. File `provider=local` nằm trong `MEDIA_ROOT` thuộc Docker volume `backend-data`; clone Git/Neon không có file này. Cần snapshot media đúng thời điểm hoặc cùng truy cập backend đang giữ volume. Media Cloudinary đã upload không cần copy lại nếu dùng đúng tài khoản/environment và có quyền |
| Các khóa mã hóa hiện hành | **Cần giữ đúng khi dùng chung/copy DB** | `DATA_ENCRYPTION_KEY`, `DATA_ENCRYPTION_KEY_ID`, `SESSION_CSRF_KEY` thường đã nằm trong `.env`; không tự sinh lại nếu cần giải mã queue/destination hiện có. Không gửi thêm một bộ key mới khác DB |
| Credential thiết bị Pi | Chỉ khi teammate tích hợp thiết bị đã đăng ký | Token thiết bị không nằm trong Git, DB chỉ giữ hash. Giữ token tại Pi; không cần gửi cho teammate chỉ sửa web. Thiết bị mới thì provision/pair theo Device API |
| Báo cáo nghiệm thu | Tùy nhu cầu | `docs/reports/` đã ignore. Gửi riêng nếu cần review; không gửi kèm `.secrets` hoặc bản dump không liên quan |
| Database dump/migration-owner URI | **Không cần khi dùng cùng Neon** | App chỉ cần bốn URL runtime app/auth/device/worker trong `.env`. Teammate không cần migration owner để chạy ứng dụng. DB riêng thì chuẩn bị branch/role và migrate theo quy trình riêng được duyệt |

Ảnh minh họa, font và frontend assets cần thiết đã nằm trong `frontend/public/` và source trên Git; không cần gửi một thư mục ảnh riêng cho placeholder.

## 2. Chạy máy teammate lần đầu

Cài Git và Docker Desktop/Engine với Compose. Sau khi clone branch/main đã bàn giao:

1. Lưu `.env` ở project root bằng kênh riêng. Kiểm tra `DATABASE_BACKEND=postgres`, đủ bốn URL runtime đúng database/branch và đúng role.
2. Tạo `.secrets/`, lưu file Cloudinary ở đúng đường dẫn. Nếu chỉ cần tạo template trống, chạy `python3 scripts/cloud/prepare_secrets.py`; script giữ file hiện có. Template trống chưa phải cấu hình Cloudinary hợp lệ.
3. Bản bàn giao đầy đủ giữ các chức năng như máy chính: worker, MQTT ingestion, Telegram polling và email theo cấu hình được cấp. Không thêm override tắt chức năng.
4. Khởi chạy đầy đủ stack:

   ```sh
   docker compose up -d --build
   docker compose ps
   ```

5. Mở `http://localhost:8188`, đăng nhập bằng tài khoản đã cấp hoặc tài khoản riêng đã xác minh. Mailpit local ở `http://localhost:8125`; nếu `.env` trỏ Brevo, thư sẽ đi theo Brevo chứ không xuất hiện trong Mailpit.

Bản bàn giao dùng Brevo hiện có và giữ `EMAIL_ALERTS_ENABLED=true` như máy chính theo yêu cầu chủ dự án. Mỗi người nhận vẫn chọn bật kênh và bộ lọc của mình trên giao diện; không tự đổi preference hoặc gửi tin thử khi khởi động. Worker xử lý job và SMTP thật theo nghiệp vụ đã cấu hình.

Nếu chủ đích dựng môi trường thử khác, có thể chọn Mailpit/bot riêng theo một kế hoạch riêng; đây không phải mặc định hoặc giới hạn của bản bàn giao đầy đủ.

Nếu đổi cổng, cập nhật `WEB_PORT`, `PUBLIC_URL` và `APP_ORIGINS` tương ứng. Không chạy `docker compose down -v`; volume không được phục hồi chỉ bằng cách pull source.

## 3. DB dùng chung và môi trường độc lập

**Dùng cùng Neon là dùng cùng dữ liệu:** chỉnh nhà, thành viên, quyền, lịch hoặc media sẽ ảnh hưởng ngay tới người khác. Nhiều backend/worker cùng DB dùng lease/idempotency đang có; điều đó không làm dữ liệu từng máy độc lập. Không seed/reset để “khớp demo”.

Nếu cần dữ liệu thử độc lập, tạo branch Neon và runtime role riêng. Tuy nhiên clone DB có thể vẫn tham chiếu cùng Cloudinary public IDs: **không chạy cleanup/delete/reconciliation có ghi hoặc bật workers trên clone khi media còn trỏ tài nguyên gốc**. Phải thống nhất kho media riêng/copy media trước các thao tác đó. Không tự tạo thêm hạ tầng backup.

Telegram long polling chỉ có một consumer cho cùng bot. Lock/offset nằm trong database; **hai database/branch khác nhau không phối hợp lock với nhau**. Với cùng database, poller hiện có dùng khóa để chỉ một consumer hoạt động; máy khác có thể chờ khóa. Muốn chuyển máy điều phối thì dừng poller cũ trước. Nếu chuyển sang database/branch khác mà vẫn dùng bot này, phải bàn giao consumer có chủ đích; không chạy consumer trên hai DB cùng lúc. Đây là giới hạn của Telegram, không phải chức năng bị tắt trong bản bàn giao.

## 4. Media local và dữ liệu cần giữ

`backend-data` là Docker named volume, đường dẫn mặc định trong container `/app/data`; tên thực tế phụ thuộc Compose project. Chỉ media nằm tại `MEDIA_ROOT` cần cho file local; không cần gửi nguyên volume chứa SQLite cũ hay dữ liệu không liên quan. Việc export/import nên được thực hiện riêng, chọn đúng phạm vi và snapshot cùng DB; không tự chép đè volume đang dùng.

Metadata hiện có 11 media ready/local và 4 ready/Cloudinary tại thời điểm bàn giao; số lượng có thể thay đổi. File local và bản sao media trong ZIP cần được giữ đúng đường dẫn. TTS/local legacy không được tự có trên máy mới chỉ từ database. Vì vậy **chỉ `.env` + Cloudinary key chưa đảm bảo phát được mọi file cũ**. Nếu không gửi media snapshot, teammate vẫn chạy web và xem placeholder, nhưng file local thiếu sẽ không phát/xem được. Không đánh dấu các file đó đã bị xóa khỏi Cloudinary hoặc tự dọn DB để che lỗi thiếu file.

## 5. Tài liệu tham khảo

- [Danh mục tài liệu](../README.md).
- [Neon và vận hành](../setup/NEON_SETUP.md).
- [Database/media](../architecture/DATABASE_DESIGN_NEON.md).
- [Device API](../api/DEVICE_API.md).
- [Backlog hiện tại](../planning/SOFTWARE_BACKLOG_ANNHA.md).
