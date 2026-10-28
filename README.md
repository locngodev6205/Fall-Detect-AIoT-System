# AnNhà — Camera giám sát gia đình

Ứng dụng React/Vite theo giao diện Calm Home từ `AnNha-website.zip`, kết nối với backend FastAPI và SQLite. Dữ liệu tài khoản, quyền, nhà/phòng, camera, vùng, sự kiện, cảm biến, lịch nhắc và lệnh âm thanh được quản lý tại backend; không dùng localStorage để giả lập nghiệp vụ.

## Chạy bằng Docker

```bash
docker compose up --build -d
```

- **Ứng dụng:** http://localhost:8188
- **Hộp thư thử Mailpit:** http://localhost:8125
- Backend, MQTT và SMTP chỉ nằm trong mạng Docker, không publish cổng máy chủ.
- Không sử dụng cổng **5173** hoặc **8080** của dự án khác.

Đăng ký tài khoản → mở thư xác minh trong Mailpit → xác minh → đăng nhập → tạo nhà/phòng. Không có tài khoản hoặc camera mẫu tự động được cấp quyền.

Mailpit chỉ giữ thư trong môi trường cục bộ, không gửi đến email bên ngoài. Khi triển khai thật, thay SMTP bằng máy chủ thư của bạn; bật HTTPS, `COOKIE_SECURE=true`, đặt `APP_ORIGINS`/`PUBLIC_URL` đúng địa chỉ. Đổi cổng qua `.env` dựa trên `.env.example`.

```bash
docker compose ps
docker compose logs -f backend
docker compose down
```

Named volumes giữ SQLite/media, broker và hộp thư qua restart. `docker compose down -v` sẽ xóa dữ liệu; không dùng để cập nhật ứng dụng. Build mới: `docker compose up --build -d`.

## Đăng ký camera thật

Mỗi thiết bị được cấp credential riêng qua lệnh quản trị trong backend:

```bash
docker compose exec backend python -m src.provision --name "Camera phòng khách"
```

Lệnh in ra `device_id`, **`device_token` chỉ cấp một lần** và `pairing_code` có hạn 30 phút. Giữ token ở thiết bị, nhập pairing code tại **Thiết bị → Thêm thiết bị** trên web. Mã không thể dùng lại; gỡ camera vô hiệu credential cũ. Không đưa token vào frontend, Git hoặc log.

Thiết bị sau đó dùng `Authorization: Bearer <device_token>` với `/api/device/*`. Web và thiết bị sử dụng hai cơ chế xác thực riêng. Chi tiết tại [DEVICE_API.md](docs/DEVICE_API.md).

## Các chức năng đã nối backend

- Tài khoản: đăng ký, xác minh email, phiên HttpOnly cookie, CSRF, đăng xuất, khôi phục mật khẩu và thu hồi phiên cũ.
- Nhà/phòng, ghép nối camera, mời thành viên bằng email, vai trò và quyền theo camera; thu hồi quyền API/WebSocket/media.
- Vùng đa giác chuẩn hóa, kiểm tra hình học, cập nhật có phiên bản, phản hồi áp dụng/lỗi từ thiết bị.
- Sự kiện có khử trùng/sequence, lịch sử bền vững, tiếp nhận/ghi chú/xác nhận an toàn/báo giả và audit.
- Telemetry với đơn vị/chất lượng/thời gian đo; luật môi trường cho dữ liệu mới có thời gian duy trì và hysteresis.
- Upload ảnh/clip/audio có giới hạn, truy cập file có quyền, thời hạn lưu bằng chứng; ảnh chụp gần nhất và relay JPEG qua WebSocket.
- Lịch nhắc TTS/audio; tạo file tiếng Việt bằng eSpeak NG trong Docker, phát lệnh có hạn và khử trùng, ghi kết quả thiết bị báo về.
- Ghi âm lời nhắn từ trình duyệt, upload file và relay giọng nói một chiều khi thiết bị có kết nối audio.
- SMTP có hàng đợi/retry; Telegram dùng bot token cấu hình ở máy chủ, có lựa chọn gửi ảnh và nhắc lại tối đa 5 lần khi chưa tiếp nhận.

## Giới hạn tích hợp thiết bị

Backend đã có hợp đồng thật để thiết bị gửi/nhận dữ liệu. Điều này **không tự làm Pi hiện có hỗ trợ toàn bộ hợp đồng**:

- Khi chưa có thiết bị gửi frame, web báo chưa có hình; không thay bằng ảnh minh họa hoặc trạng thái LIVE giả.
- Khi thiết bị chưa xác nhận phiên bản, web giữ trạng thái chờ. Backend không tự coi vùng đã được AI sử dụng.
- Lịch được gửi trong cấu hình để scheduler tại thiết bị chạy, kể cả offline sau khi tải file. Backend chỉ ghi “đã phát” khi nhận execution report; không giả lập việc nghe/uống thuốc.
- Relay hình là JPEG có giới hạn khoảng 5 FPS, chưa phải hệ thống WebRTC/NVR; audio cần bộ nhận/giải mã/phát tại thiết bị. Không có đàm thoại hai chiều.
- Module `fall_detect/` giữ nguyên mô hình, tiền xử lý và luật nhận diện. Chỉ bổ sung token thiết bị và mã sự kiện vào payload MQTT. Luật bất động hiện có chưa tiêu thụ cấu hình vùng; cần tích hợp edge theo đặc tả trước khi coi cảnh báo theo ngữ cảnh là đã chạy đầu-cuối.
- Broker mặc định chỉ cho mạng Compose. Muốn Pi ở LAN kết nối MQTT cần cấu hình listener/auth/ACL/TLS riêng. HTTP device API là đường tích hợp đã có qua web reverse proxy; không mở broker anonymous ra Internet.
- Telegram, camera, loa và cảm biến cần phần cứng/dịch vụ được cấu hình để kiểm thử thực tế. Mailpit và TTS có thể kiểm thử ngay trong Docker.

## Chạy phát triển

Backend dùng **8018**, frontend **5188** và `strictPort` không tự chiếm cổng khác:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
MQTT_ENABLED=false PUBLIC_URL=http://127.0.0.1:5188 SMTP_HOST=127.0.0.1 SMTP_PORT=1025 \
  python -m uvicorn backend.src.main:app --host 127.0.0.1 --port 8018 --no-access-log
```

SMTP trên máy host phải được cấu hình riêng; SMTP nội bộ Docker không publish cổng 1025. Có thể dùng toàn bộ Docker để thử luồng email.

```bash
cd frontend
npm ci
npm run dev
```

Mở http://127.0.0.1:5188. Proxy `/api` và `/ws` sang backend 8018. Không khởi chạy hai stack trên cùng cổng.

## Kiểm tra

```bash
npm --prefix frontend run build
npm --prefix frontend run test:sites
pip install -r backend/requirements-dev.txt
MQTT_ENABLED=false WORKER_ENABLED=false python -m unittest discover -s backend/tests -v
docker compose config --quiet
```

Các test dùng DB/media tạm; không sửa dữ liệu ứng dụng. Test backend kiểm tra auth/CSRF/reset, mời/thu hồi quyền, truy cập chéo camera, cấu hình, sự kiện/WebSocket, file, lệnh, telemetry/hysteresis và relay media. Test Sites chỉ kiểm tra bộ đóng gói tĩnh từ ZIP, không publish website. Mã đóng gói Sites không triển khai được backend nghiệp vụ này thay Docker.

ZIP gốc giữ tại `archives/source-imports/AnNha-website.zip` và đã gitignore. Tài liệu: [Specification](docs/PROJECT_SPECIFICATION.md), [Architecture](docs/ARCHITECTURE.md), [Device API](docs/DEVICE_API.md).
