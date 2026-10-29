# Chuẩn bị Neon để migrate và tích hợp AnNhà

Cập nhật 29/10/2026. Phạm vi hiện tại: **Neon + email xác nhận/reset + cảnh báo email/Telegram**. Cloudinary để giai đoạn sau; ảnh, video và audio vẫn lưu cục bộ. Không cần tạo Cloudinary account/key cho bước này.

Schema đích hiện có 40 bảng, hỗ trợ hai kênh cảnh báo độc lập, email tài khoản đã xác minh, bộ lọc sự cố/mức độ, theo dõi phản hồi gửi và vô hiệu địa chỉ/token cũ khi đổi email. Xem [thiết kế đầy đủ](DATABASE_DESIGN_NEON.md).

## 1. Bạn chỉ cần chuẩn bị những gì?

- Một project Neon dành cho AnNhà và một database **mới, trống** để tôi đưa schema lên.
- Direct connection URI của migration owner, lưu tại máy bạn bằng bước 3 bên dưới; không gửi mật khẩu trong chat.
- Chưa chạy file SQL thủ công, chưa tạo bốn runtime login, chưa sửa cấu hình backend đang chạy. Tôi sẽ thực hiện migration, tạo quyền tối thiểu và tích hợp sau khi kết nối sẵn sàng.

## 2. Tạo project trong Neon Console

1. Đăng nhập [Neon Console](https://console.neon.tech/), tạo project mới, ví dụ `annha`.
2. Chọn PostgreSQL 16 trở lên; schema đã được thử trên 16.14. Chọn region gần nơi sẽ chạy backend; không cần bật dịch vụ Auth khác để thay luồng email/mật khẩu hiện tại.
3. Chuẩn bị database mới tên `annha` hoặc dùng database mặc định nếu còn trống. Ghi nhớ đúng tên project, branch và database.
4. Mở **Connect**, chọn đúng branch/database và role owner mà Neon tạo cho project, thường dạng `neondb_owner`.
5. **Tắt Connection pooling** ở hộp Connect và copy URI PostgreSQL. Host migration phải là direct host, không có `-pooler`. Runtime sẽ dùng pooled connection sau khi tôi tạo các login riêng.

Tên/menu có thể khác theo phiên bản Console; thông tin cần đối chiếu là project, branch, database, role và direct connection. [Neon Console](https://neon.com/docs/get-started/signing-up), [pooling](https://neon.com/docs/connect/connection-pooling).

Nếu bạn đã có project/database chứa dữ liệu, giữ nguyên và báo tên database/branch cùng việc có dữ liệu hay chưa; không xoá bảng hoặc chạy bootstrap vào đó. Không cần gửi connection URI qua chat.

## 3. Lưu kết nối tại máy, không lộ mật khẩu

Mở Terminal tại thư mục repository:

```bash
cd /Users/coding/CN_IOT
python3 scripts/cloud/prepare_secrets.py
python3 scripts/cloud/configure_neon.py
```

Windows dùng đường dẫn clone trên máy bạn và có thể dùng `py -3` thay `python3`.

Script thứ hai hỏi `Paste DIRECT Neon connection URI (hidden):`. Dán URI từ Neon rồi Enter; màn hình không hiển thị URI. Công cụ:

- Chỉ nhận direct host Neon, không nhận pooler hoặc host ngoài Neon.
- Tạo `.secrets/pg_service.conf` và `.secrets/pgpass`, bật TLS `verify-full`.
- Giải mã password từ URL rồi escape đúng định dạng pgpass.
- Chỉ thay file mẫu/placeholder; từ chối ghi đè nếu file đã được bạn chỉnh trước đó.
- Không kết nối cloud và không chạy migration.

Thành công sẽ báo đã lưu hai file. `.secrets/` đã gitignore và không vào Docker image. Không chụp/gửi nội dung secret hoặc commit các file này.

Nếu bạn đã tự điền file secret, bỏ qua configure script. Kiểm tra cấu trúc thủ công:

`.secrets/pg_service.conf`:

```ini
[annha_neon_migration]
host=YOUR_DIRECT_HOST.neon.tech
port=5432
dbname=annha
user=YOUR_MIGRATION_OWNER
sslmode=verify-full
sslrootcert=/etc/ssl/certs/ca-certificates.crt
connect_timeout=10
```

`.secrets/pgpass`:

```text
YOUR_DIRECT_HOST.neon.tech:5432:annha:YOUR_MIGRATION_OWNER:YOUR_PASSWORD
```

Thay các giá trị YOUR_ bằng thông tin thật; trong pgpass, ký tự `:` và `\` của password cần escape bằng `\`. Không URL-encode password trong pgpass. Nếu dùng đường dẫn secret khác, cập nhật `NEON_SERVICE_FILE`/`NEON_PGPASS_FILE` trong `.env`.

## 4. Báo lại để tôi migrate

Sau khi lưu xong, nhắn: **“Đã tạo Neon và lưu cấu hình”**, kèm các thông tin không bí mật:

- Tên database/branch, và database có trống hay không.
- Bạn muốn giữ dữ liệu SQLite hiện có hay chỉ dùng database mới cho thử nghiệm. Mặc định tôi sẽ chuẩn bị phương án giữ dữ liệu, không xoá SQLite/media gốc.

Bạn chưa cần chạy các lệnh dưới; đây là quy trình tôi sẽ làm sau khi cấu hình sẵn sàng:

1. Kiểm tra kết nối/TLS và catalog, xác nhận đúng database/owner và trạng thái dữ liệu.
2. Backup SQLite theo cách nhất quán và lập bảng ánh xạ dữ liệu.
3. Áp `001_schema.sql` + `002_security.sql` + `005_email_notifications.sql` trong một transaction nếu database mới.
4. Tạo bốn login runtime tách quyền bằng SQL và lưu credential vào secret, không dùng owner làm runtime. Role tạo qua Console có thể nhận quyền quản trị, vì vậy không tạo bốn runtime login bằng Console. [Neon roles](https://neon.com/docs/manage/roles).
5. Port adapter/giao dịch FastAPI sang PostgreSQL; áp RLS bằng context user/home/camera trong từng transaction.
6. Import dữ liệu cần giữ, kiểm tra số lượng/quan hệ, token/phiên/lệnh hết hạn và quyền truy cập.
7. Tích hợp SMTP email xác nhận/reset và cảnh báo email/Telegram; kiểm thử bằng Mailpit trước khi gửi thư bên ngoài.
8. Giữ media local; không yêu cầu Cloudinary ở giai đoạn này. Rebuild Docker, kiểm tra và chỉ đổi sang DB mới sau khi đường chạy đã được xác minh.

Nếu kết nối có sẵn schema phiên bản cũ, dùng migration nâng cấp một lần, không bootstrap lại và không DROP schema. Các thay đổi quyền/adapter/data sẽ được kiểm tra trước khi đổi hệ thống đang dùng.

## 5. Email cần chuẩn bị ở thời điểm nào?

Neon không phải dịch vụ gửi mail. Để kiểm tra cục bộ, Mailpit hiện có là đủ; nó nhận thư thử nhưng không gửi ra hộp thư Internet.

Khi cần gửi mail thật, chuẩn bị dịch vụ SMTP và điền `SMTP_HOST`, `SMTP_PORT`, `SMTP_STARTTLS`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` trong `.env`/secret theo nhà cung cấp. Chưa cần chọn nhà cung cấp ngay để migrate database. Không gửi SMTP password trong chat.

Cảnh báo email mặc định dùng email tài khoản đã xác minh, không cho nhập một địa chỉ ngoài bất kỳ. Xác nhận/reset/lời mời không bị tắt theo tuỳ chọn nhận cảnh báo. SMTP chấp nhận thư không có nghĩa thư đã vào inbox; chỉ có phản hồi nhà cung cấp đã xác minh mới ghi delivered/bounced/complained. Với SMTP thuần không có webhook, hệ thống giữ trạng thái accepted/unknown phù hợp, không bịa kết quả giao thư.
