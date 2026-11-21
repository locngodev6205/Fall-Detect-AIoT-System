# Trình diễn cập nhật Raspberry Pi từ AnNhà

## Khởi động

1. Trên máy chạy web thử nghiệm, cấu hình kho release và public key theo [hướng dẫn OTA](DEVICE_UPDATES.md). Dùng database thử nghiệm rồi chạy `docker compose up -d --build`. Mở web qua cổng `8188`.
2. Trên Pi đã bootstrap và ghép đôi với backend thử nghiệm, chạy `sudo systemctl start annha-edge.service annha-updater.service`.
3. Đăng nhập với quyền chủ nhà, chọn camera và mở **Cập nhật ứng dụng Raspberry Pi 4** trên trang chi tiết. Kiểm tra preview, heartbeat và hai phiên bản trước khi cài.

## Demo cập nhật và quay về

1. Bắt đầu ở `0.1.0`. Khi có bản `0.1.1` đã ký, tương thích với Pi, chọn phiên bản và nhấn **Cập nhật ngay**. Nếu chỉ có hai release `0.0.2` và `0.1.0`, dùng cặp đó trên Pi demo.
2. Quan sát timeline. Gói đã tải và xác minh khi job báo chờ cài đặt. Khi Edge khởi động lại, UI tiếp tục theo dõi job. Kết quả thành công xuất hiện khi job hoàn tất và phiên bản trên heartbeat khớp. Kiểm tra lại camera.
3. Nhấn **Quay về bản trước**, xác nhận và quan sát phiên bản đã khôi phục. Lịch sử hiển thị năm lệnh gần nhất.
4. Với rollback tự động, dùng bản thử lỗi đã ký trên backend/Pi thử nghiệm. Nếu cần tạo bản thử mới, dùng commit và tag riêng để ứng dụng khởi động nhưng cố ý không đạt health check. Ký bằng workflow hiện có và kiểm tra đủ manifest, chữ ký và tarball trước khi dùng. Giữ bản trước đã chạy ổn làm đích khôi phục.
5. Updater cũ vẫn chạy OTA. Để thấy **Health check** và **Đang khôi phục** ngay khi từng bước diễn ra, cài updater từ nhánh này theo quy trình bảo trì trong [hướng dẫn OTA](DEVICE_UPDATES.md). Web hiển thị trạng thái đang chờ nếu mất kết nối API hoặc chưa có heartbeat xác nhận. Lệnh cũ thiếu phiên bản gốc có thể không xác nhận được rollback trên web.

Nếu cần đối chiếu trực tiếp trên Pi:

```bash
systemctl is-active annha-edge.service annha-updater.service
readlink /opt/annha/current
journalctl -u annha-updater.service -n 30 --no-pager
```
