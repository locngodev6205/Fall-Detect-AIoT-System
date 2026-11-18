# Cập nhật ứng dụng Pi của AnNhà

## Phạm vi

Cập nhật mã ứng dụng Edge, giữ model, virtualenv, cấu hình và dữ liệu dùng chung. Chỉ chủ nhà được tạo/hủy lịch hoặc yêu cầu rollback. Bản đầu dành cho Pi Linux ARM64, không nạp firmware Arduino.

Gói tải trước, tới lịch mới cài. Còn cảnh báo OPEN/ACKNOWLEDGED, nguy hiểm local hoặc âm thanh đang phát thì chờ tối đa 30 phút sau lịch. Không xác định được trạng thái an toàn thì giữ chờ. Cài lỗi tự quay về bản trước. Health check tối đa 120 giây gồm khung hình camera thật, model chạy được inference và backend nhận phiên bản mới.

## Cấu hình GitHub

1. Trong repo `locngodev6205/Fall-Detect-AIoT-System`, bật Actions.
2. Mở Settings → Environments → New environment, đặt tên `annha-pi-release`.
3. Trong environment đó, thêm secret `DEVICE_RELEASE_SIGNING_KEY`.
4. Dán nguyên private key PEM từ `.secrets/annha-release.key` của máy phát triển, gồm các dòng BEGIN/END và xuống dòng thật.
5. Nếu bật deployment tag restrictions, cho phép `annha-pi-v*`. Nếu đặt required reviewers, duyệt job khi Actions chờ.

Đọc khóa để dán trong terminal local.

```bash
cat .secrets/annha-release.key
```

Khóa riêng nằm trong `.secrets` đã được gitignore. Public key nằm ở `.secrets/annha-release.pub` và đã cấu hình tại `.env`. Không commit private key hoặc `.env`.

Workflow `.github/workflows/annha-pi-release.yml` đóng gói từ commit của tag, ký manifest và tạo GitHub Release có ba asset `manifest.json`, `manifest.sig`, `annha-pi.tar.gz`. Bản Release giữ draft tới khi tải đủ asset. Chạy lại job thất bại hỗ trợ draft còn dở, bản đã xuất bản được giữ nguyên.

## Backend

Các biến ở `.env` gốc được Compose truyền vào backend.

```dotenv
DEVICE_RELEASE_REPO=locngodev6205/Fall-Detect-AIoT-System
DEVICE_RELEASE_GITHUB_TOKEN=
DEVICE_RELEASE_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\nPUBLIC_KEY\n-----END PUBLIC KEY-----"
DEVICE_RELEASE_CACHE_DIR=data/device-releases
```

Tạo fine-grained personal access token từ GitHub Settings → Developer settings → Personal access tokens, cấp quyền Contents read cho repo. Điền token vào `DEVICE_RELEASE_GITHUB_TOKEN` để backend gọi GitHub có xác thực. Token thuộc tài khoản, khả năng truy cập phụ thuộc quyền token và repo.

SQLite tự tạo bảng OTA khi backend khởi động. PostgreSQL cần migration `016_device_updates.sql` qua công cụ migration của dự án trước khi chạy bản backend mới. Migration dùng tài khoản owner, runtime vẫn dùng các role hiện có. Trường hợp máy dùng libpq service trong `.secrets`, có thể chạy công cụ migration với URI owner được cấp theo hướng dẫn database hiện có. Không thay runtime bằng tài khoản owner.

Sau khi cập nhật cấu hình và migration, build/recreate ứng dụng.

```bash
./run.sh up
```

Trang cập nhật nằm tại chi tiết camera và chỉ hiện với chủ nhà. Backend đồng bộ GitHub mỗi 120 giây. Release sai chữ ký, thiếu asset hoặc sai checksum bị từ chối, lỗi hiển thị trên trang. Chưa có updater trực tuyến vẫn xem được danh sách release.

## Phát hành thử

Commit các thay đổi đã kiểm tra, push nhánh, rồi tạo tag trên chính commit chứa workflow và mã OTA.

```bash
git tag -a annha-pi-v0.0.1 -m "AnNha Pi OTA smoke release"
git push origin annha-pi-v0.0.1
```

Trong Actions, chờ job Publish AnNha Pi thành công. Trong Releases, kiểm tra đủ ba asset. Mở trang chi tiết camera, chờ tối đa hai phút rồi chọn phiên bản `0.0.1`. Khi chưa cài updater trên Pi, trạng thái ngoại tuyến và nút cài bị khóa là đúng.

Script đóng gói chỉ lấy `edge/`, `modules/`, `update/`, `config.py`, `requirements.txt`, `run_edge.sh`. Model không nằm trong tarball, nhưng hash của model và requirements được ghi vào manifest. Mã mới phải tương thích model và requirements này.

## Chuẩn bị Pi một lần

Chỉ cần chép thư mục `fall_detect` lên Pi như cách vận hành hiện tại. Wrapper cài đặt chọn `../venv` trước, rồi `venv` trong `fall_detect`, giống `run_edge.sh`. Từ thư mục `fall_detect` chạy `bash update/install.sh --public-key /path/to/annha-release.pub`. Khi cần dùng Python cụ thể, dùng lệnh trực tiếp bên dưới.

Dùng virtualenv đang chạy Edge, bảo đảm `pip check` thành công và dependency khớp `fall_detect/requirements.txt`. Cài `openssl` và `sudo` nếu chưa có. Chép public key `annha-release.pub` sang Pi, lấy mã đã có OTA, rồi chạy bootstrap bằng tài khoản đang vận hành Edge.

```bash
/path/to/current-venv/bin/python fall_detect/update/install.py \
  --source /path/to/repo/fall_detect \
  --env /path/to/repo/fall_detect/.env.edge \
  --public-key /path/to/annha-release.pub
```

Bootstrap tạo `/opt/annha`, bản nền `0.0.0`, hai service và quyền sudo giới hạn cho updater start/stop service Edge. Script kiểm tra dependency, giữ nguyên pairing, copy model/cache sang vùng dùng chung. Virtualenv tiếp tục nằm ở đường dẫn đã truyền. Giữ virtualenv đó khi dọn checkout cũ.

Dừng tiến trình/service Edge đang chạy trước để giải phóng camera và serial, rồi chạy.

```bash
sudo systemctl enable --now annha-edge.service annha-updater.service
journalctl -u annha-updater.service -f
```

Cấu trúc cài đặt.

```text
/opt/annha/
  current -> releases/0.0.0/
  releases/
  shared/
    app.env
    updater.json
    release.pub
    models/
    edge_cache/
    update.sock
  updater/updater.py
  staging/
```

`app.env` và `updater.json` chứa cùng credential của thiết bị. Khi đổi backend hoặc ghép đôi lại, cập nhật cả cấu hình updater rồi restart hai service. Updater chạy độc lập với ứng dụng. File socket chỉ cho cùng tài khoản truy cập. Bản thân updater cần cập nhật bằng thao tác bảo trì khi thay giao thức updater.

## Kiểm tra

```bash
python -m unittest backend.tests.test_device_updates -v
npm --prefix frontend run build
```

Nghiệm thu trên Pi thật gồm cập nhật ngay, tải trước/hẹn giờ, cảnh báo giữ chờ, hủy lúc tải, hết hạn, sai hash/chữ ký, mất mạng lúc báo kết quả, mất điện lúc chuyển bản và health check lỗi dẫn đến rollback. Kiểm tra camera, model và âm thanh vẫn hoạt động sau cập nhật. Giữ hai bản gồm bản hiện tại và bản rollback.
