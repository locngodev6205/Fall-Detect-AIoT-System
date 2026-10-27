# SmartFall Frontend Dashboard

Giao diện Web Giám sát tập trung (Client Application) cho người dùng/nhân viên y tế:
* **Công nghệ:** HTML5, CSS3, JavaScript (WebSocket Client), Bootstrap 5.
* **Chức năng:**
  * Kết nối thời gian thực với Backend qua WebSocket (`/ws/alerts`).
  * Giám sát trạng thái an toàn / cảnh báo của từng phòng (Raspberry Pi nodes).
  * Hiển thị Popup cảnh báo khẩn cấp toàn màn hình và chuông báo động khi có người té ngã.
  * Nhật ký sự kiện thời gian thực (Real-time Event Log).

## Cách chạy Dashboard:
Sau khi Backend đã khởi chạy tại `http://localhost:8000`:
* Mở trực tiếp file `src/index.html` bằng trình duyệt (Chrome, Edge, Firefox).
* Hoặc chạy local server bằng: `python -m http.server 3000` bên trong thư mục `src`.
