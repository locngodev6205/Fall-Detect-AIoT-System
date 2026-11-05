# Tài liệu AnNhà

Tài liệu được phân theo mục đích; mã nguồn và SQL migrations là căn cứ cuối cùng về hành vi đang chạy.

| Thư mục | Nội dung |
|---|---|
| `product/` | [Đặc tả sản phẩm và phạm vi](product/PROJECT_SPECIFICATION.md) |
| `architecture/` | [Kiến trúc](architecture/ARCHITECTURE.md), [database Neon và media Cloudinary](architecture/DATABASE_DESIGN_NEON.md) |
| `api/` | [Hợp đồng tích hợp thiết bị](api/DEVICE_API.md) |
| `setup/` | [Thiết lập và vận hành Neon](setup/NEON_SETUP.md) |
| `planning/` | [Trạng thái triển khai](planning/IMPLEMENTATION_STATUS.md), [backlog phần mềm](planning/SOFTWARE_BACKLOG_ANNHA.md) |
| `handoff/` | [Chuẩn bị máy và bàn giao cho teammate](handoff/TEAMMATE_SETUP.md) |
| `reports/` | Báo cáo kiểm thử, nghiệm thu từng Phase, preview và ghi chép cũ; **chỉ lưu cục bộ, được gitignore** |

## Trạng thái hiện hành

P1 web MVP trên PostgreSQL đã hoàn thiện qua Phase 6: tài khoản/OTP, mã mời, phân quyền camera, media ảnh/âm thanh, queue/realtime, Telegram polling, email Brevo, sự kiện, biểu đồ và phân trang. Không coi nghiệm thu web là xác nhận phần cứng/video/servo đã hoạt động. SQLite legacy chưa có toàn bộ API Phase 6.

Xem [trạng thái](planning/IMPLEMENTATION_STATUS.md) và [backlog](planning/SOFTWARE_BACKLOG_ANNHA.md) để biết phạm vi/giới hạn. Báo cáo đầy đủ tại `docs/reports/` cần gửi riêng nếu teammate cần bằng chứng kiểm thử; clone Git không có thư mục này. Link tới báo cáo trong tài liệu được ghi dạng đường dẫn cục bộ để tránh liên kết GitHub bị hỏng.

## Quy ước

- Tài liệu sản phẩm, API, thiết lập và backlog được commit; reports/preview/generated artifacts được giữ ngoài Git.
- Credential, `.env`, `.secrets/`, dữ liệu runtime và gói bàn giao riêng không nằm trong repository.
- Khi di chuyển tài liệu, sửa cả liên kết tương đối và các tham chiếu từ README/script.
- Không chạy reset/seed/migration database đang dùng chỉ để dựng lại máy phát triển; xem hướng dẫn bàn giao trước.
