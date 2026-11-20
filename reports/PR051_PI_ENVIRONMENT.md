# PR-05.1 · Môi trường Raspberry Pi 4

Đã xác minh bằng SSH strict host checking qua IP do chủ dự án xác nhận. Địa chỉ cũ timeout. Hostname mDNS bị chặn do host key không khớp bản ghi hostname. Kết nối IP qua bản ghi host key đã tin cậy và tài khoản được cấp thành công. Không thay known_hosts.

| Thành phần | Kết quả kiểm tra |
|---|---|
| Board | Raspberry Pi 4 Model B Rev 1.4 |
| OS / CPU | Debian 13 trixie / aarch64 |
| RAM / swap lúc đầu | 3,7 GiB RAM, 3,3 GiB available, 2 GiB swap chưa dùng |
| Lưu trữ | 1,1 GiB trống trên phân vùng gốc 29 GiB |
| Nhiệt / throttle ban đầu | 43,3 °C / 0x0 |
| Camera | USB V4L2 Wed Camera, node capture /dev/video0 |
| Python | System 3.13.5, interpreter đã có trong venv Edge là 3.11.17 |
| Vision | NumPy 1.26.4, MediaPipe 0.10.14, OpenCV package 4.11.0.86 |
| Edge | Không thấy process edge.main_edge trước benchmark |

Đặt bản sao mã nghiên cứu, checkpoint E4-42 nguyên gốc, các clip phát triển và dependency PyTorch riêng trong `/dev/shm/annha-pr051` với quyền 0700. Dùng interpreter sẵn có và thêm thư mục package nghiên cứu qua PYTHONPATH. Cài package với `pip --target` trong vùng RAM riêng. Không sửa package, cấu hình hoặc dịch vụ production. Artifact ngoài Git và vùng RAM trên Pi không tồn tại sau reboot.
