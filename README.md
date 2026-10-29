# AnNhà — Camera giám sát gia đình

Ứng dụng React/Vite theo giao diện Calm Home từ `AnNha-website.zip`, kết nối với backend FastAPI và Neon PostgreSQL. Adapter SQLite được giữ cho môi trường local/rollback. Dữ liệu tài khoản, quyền, nhà/phòng, camera, sự kiện, cảm biến, lịch nhắc và lệnh âm thanh được quản lý tại backend; không dùng localStorage để giả lập nghiệp vụ.

## Chạy nhanh bằng menu

Cần Docker Desktop/Engine đang chạy. Script tự xác định thư mục dự án, tạo `.env` từ mẫu nếu chưa có và giữ nguyên `.env` hiện tại.

- **macOS/Linux:** chạy `./run.sh` hoặc `bash run.sh`.
- **Windows:** mở `run.bat` hoặc chạy trong Command Prompt/PowerShell (`.\run.bat`).

Menu có build/chạy, chạy nhanh, dừng, tạo lại container, xem trạng thái/log và mở web/hộp thư. Có thể dùng lệnh trực tiếp:

```bash
./run.sh up             # Build và chạy, chờ dịch vụ sẵn sàng
./run.sh status
./run.sh logs backend   # Ctrl+C thoát log; container vẫn chạy
./run.sh stop           # Giữ nguyên dữ liệu
```

Trên Windows dùng `run.bat up`, `run.bat status`, `run.bat logs backend`, `run.bat stop`. Lệnh `recreate` nạp lại cấu hình `.env` từ image hiện có; dùng `up` khi cần build mã mới. URL được lấy từ cổng container thực tế, kể cả khi bạn đổi `WEB_PORT`/`MAIL_PORT` trong `.env`. Các script không tự khởi chạy dịch vụ phát triển hoặc AI trên host.

## Chạy bằng Docker

```bash
docker compose up --build -d
```

- **Ứng dụng:** http://localhost:8188
- **Hộp thư thử Mailpit:** http://localhost:8125
- Backend, MQTT và SMTP chỉ nằm trong mạng Docker, không publish cổng máy chủ.
- Không sử dụng cổng **5173** hoặc **8080** của dự án khác.

Đăng ký tài khoản → mở thư xác minh trong Mailpit → xác minh → đăng nhập → tạo nhà/phòng. Bộ dữ liệu DEMO đã được seed trên Neon theo yêu cầu; xem `.secrets/demo-credentials.json` để đăng nhập và [hướng dẫn Neon](docs/NEON_SETUP.md).

Mailpit chỉ giữ thư trong môi trường cục bộ, không gửi đến email bên ngoài. Khi triển khai thật, thay SMTP bằng máy chủ thư của bạn; bật HTTPS, `COOKIE_SECURE=true`, đặt `APP_ORIGINS`/`PUBLIC_URL` đúng địa chỉ. Đổi cổng qua `.env` dựa trên `.env.example`.

```bash
docker compose ps
docker compose logs -f backend
docker compose down
```

Named volumes giữ backup SQLite/media, broker và hộp thư qua restart. `docker compose down -v` sẽ xóa dữ liệu; không dùng để cập nhật ứng dụng. Build mới: `docker compose up --build -d`.

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
- Khoanh vùng đã được gỡ khỏi giao diện, quyền thành viên và API chỉnh vùng. Cấu hình gửi xuống thiết bị dùng `zones: []`/`reference: {}` để xóa vùng đang áp dụng; lịch sử cấu hình được giữ lại. Panorama/ánh xạ vùng chỉ xem xét đưa lại sau khi servo tracking ổn định.
- Sự kiện có khử trùng/sequence, lịch sử bền vững, tiếp nhận/ghi chú/xác nhận an toàn/báo giả và audit.
- Telemetry với đơn vị/chất lượng/thời gian đo; luật môi trường cho dữ liệu mới có thời gian duy trì và hysteresis.
- Upload ảnh/clip/audio có giới hạn, truy cập file có quyền, thời hạn lưu bằng chứng; ảnh chụp gần nhất và relay JPEG qua WebSocket.
- Lịch nhắc TTS/audio; tạo file tiếng Việt bằng eSpeak NG trong Docker, phát lệnh có hạn và khử trùng, ghi kết quả thiết bị báo về.
- Ghi âm lời nhắn từ trình duyệt, upload file và relay giọng nói một chiều khi thiết bị có kết nối audio.
- SMTP có hàng đợi/retry; Telegram dùng bot token cấu hình ở máy chủ, có lựa chọn gửi ảnh và nhắc lại tối đa 5 lần khi chưa tiếp nhận.

## Giới hạn tích hợp thiết bị

Backend đã có hợp đồng thật để thiết bị gửi/nhận dữ liệu. Điều này **không tự làm Pi hiện có hỗ trợ toàn bộ hợp đồng**:

- Khi chưa có thiết bị gửi frame, web báo chưa có hình; không thay bằng ảnh minh họa hoặc trạng thái LIVE giả.
- Khi thiết bị chưa xác nhận phiên bản, web giữ trạng thái chờ. Backend không tự coi cấu hình đã được AI sử dụng; cấu hình vùng cũ không được mặc định áp dụng khi camera quay.
- Lịch được gửi trong cấu hình để scheduler tại thiết bị chạy, kể cả offline sau khi tải file. Backend chỉ ghi “đã phát” khi nhận execution report; không giả lập việc nghe/uống thuốc.
- Relay hình là JPEG có giới hạn khoảng 5 FPS, chưa phải hệ thống WebRTC/NVR; audio cần bộ nhận/giải mã/phát tại thiết bị. Không có đàm thoại hai chiều.
- Module `fall_detect/` giữ nguyên mô hình, tiền xử lý và luật nhận diện. Chỉ bổ sung token thiết bị và mã sự kiện vào payload MQTT. Luật bất động hiện có chưa tiêu thụ cấu hình vùng; việc tích hợp vùng đã tạm hoãn. Servo tracking và việc đánh giá/bù ảnh hưởng camera quay chưa được triển khai hoặc kiểm chứng trong lần sửa tài liệu này.
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

Thiết kế database đích: [Neon/PostgreSQL và Cloudinary](docs/DATABASE_DESIGN_NEON.md); backend đã tích hợp Neon; media vẫn lưu local.

Bộ Docker database/cloud tools: [compose.database.yaml](compose.database.yaml). Hướng dẫn tạo Neon, cấp role, setup Cloudinary và phân biệt các biến có hiệu lực trong [DATABASE_DESIGN_NEON.md](docs/DATABASE_DESIGN_NEON.md). Chạy `python3 scripts/cloud/prepare_secrets.py` để tạo mẫu cấu hình một lần; file hiện hữu được giữ nguyên. Backend chọn PostgreSQL bằng `DATABASE_BACKEND=postgres`; `.env` hiện tại đã cấu hình Neon.

Neon đã được tích hợp; email xác nhận/reset và cảnh báo qua Mailpit đã kiểm thử. Cloudinary để sau: làm theo [NEON_SETUP.md](docs/NEON_SETUP.md). Có thể lưu direct URI qua lời nhắc ẩn bằng `python3 scripts/cloud/configure_neon.py`; không gửi mật khẩu trong chat.

## Giao diện trước khi kết nối Pi

Hai nhà demo hiện có bốn phòng/camera mỗi nhà. Ảnh gốc Calm Home được dùng làm placeholder có nhãn; phòng mới chưa ghép nối cũng có preview, không giả online. Ảnh/luồng thật tự thay placeholder khi được thiết bị gửi lên. Chi tiết sửa UI, kiểm tra backend và cách chạy `npm run test:ui`: [UI_OFFLINE_READINESS.md](docs/UI_OFFLINE_READINESS.md).

Cập nhật tiếp theo: đã gỡ nhãn/tiền tố Demo khỏi tên hiển thị, hoàn thiện ảnh bìa trang chọn nhà và tối ưu truy vấn/tải dữ liệu. Email/mật khẩu giữ nguyên. Số đo trước/sau và kiểm chứng: [PERFORMANCE_AND_UI_REVIEW.md](docs/PERFORMANCE_AND_UI_REVIEW.md).
