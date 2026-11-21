# Thu video webcam và trích xuất pose cho Dataset V3

## Cài và kiểm tra

```bash
git clone --branch review/pr05-5 https://github.com/locngodev6205/Fall-Detect-AIoT-System.git
cd Fall-Detect-AIoT-System
python -m venv .venv
# Linux / Raspberry Pi
source .venv/bin/activate
# Windows PowerShell dùng .venv\Scripts\Activate.ps1
python -m pip install "numpy<2" "opencv-contrib-python==4.11.0.86"
# Chỉ máy trích xuất pose cần MediaPipe. Dùng Python 3.11. Lần đầu MediaPipe Lite có thể cần mạng để tải trọng số chính thức.
python -m pip install mediapipe==0.10.14
```

Dùng `--camera 0` cho webcam mặc định. Đóng ứng dụng đang giữ webcam trước khi chạy. Trên Pi dùng interpreter có OpenCV tương thích với hệ điều hành. Nếu mở qua SSH và muốn cửa sổ nằm trên VNC Wayland, đặt các biến sau trong phiên SSH của tài khoản desktop. Pi cần có `ffplay`.

```bash
export XDG_RUNTIME_DIR="/run/user/$(id -u)" WAYLAND_DISPLAY=wayland-0 SDL_VIDEODRIVER=wayland
```

## Ghi và trích xuất

Sau khi người tham gia đồng ý lưu video, chạy lệnh sau. Countdown ba giây cũng dùng preview để kiểm tra góc webcam. Giữ nguyên mã subject cho cùng một người và đổi mã session cho phiên mới. Dùng đường dẫn lưu riêng ngoài repo.

```bash
python scripts/ml/collect_data.py --output ../dataset_v3 --subject u001 --session session_001 --source lab-a --camera-setup desk-a --activity pick-up --duration 30 --camera 0 --save-video --consent-video --video-only --preview
```

CLI in đường dẫn recording mới. Trên laptop có thể bấm Q trong preview để kết thúc sớm. Clip mặc định chỉ ghi ảnh webcam nén, không lưu âm thanh. Nếu phiên không có giao diện, bỏ `--preview`. Khi người tham gia cũng đồng ý xử lý pose, có thể thay `--video-only` bằng `--extract-pose` để chạy sau khi đóng camera, hoặc chạy riêng:

```bash
python scripts/ml/collect_data.py extract --input "<recording-directory>" --consent-pose
python scripts/ml/collect_data.py label --input "<recording-directory>" --verified NO_FALL
python scripts/ml/collect_data.py validate --input ../dataset_v3 --confirmed
```

Chỉ xác nhận NO_FALL sau khi xem lại clip và xác nhận hoạt động. Dùng EXCLUDED nếu phải loại. Lệnh ghi hỏi nhãn khi có terminal tương tác. Có thể bỏ trống để review sau. `validate --confirmed` yêu cầu pose hoàn tất, có cửa sổ dùng được và nhãn đúng. Kiểm tra toàn thư mục tạo `dataset_manifest.json` và chặn trùng hash video, recording và nhóm giữa split. Dùng nguồn, subject, session và setup không giao nhau nếu đánh giá độc lập.

Trên laptop, thứ tự thử encoder là H.264/MP4, MPEG-4 Part 2/MP4 và MJPEG/AVI. Trên ARM, collector ưu tiên MPEG-4 Part 2/MP4 rồi MJPEG/AVI sau khi H.264 trên Pi làm mất frame khi ghi webcam. Manifest ghi codec được chọn và FPS mã hóa. Frame index bắt đầu ở 0. Pose lấy từ đúng frame đã giải mã với timestamp monotonic lúc read trả frame. FPS video phát lại có thể khác cadence nguồn vì container dùng FPS cố định. Read failure và khoảng frame dài có ghi nhận. Webcam không cung cấp sequence ID nên số frame mất ở tầng driver chưa xác định được.

Ví dụ entry có dạng:

```text
dataset_v3/subjects/u001/session_001/pick-up_<id>/
  video.mp4
  frames.jsonl
  pose.jsonl
  manifest.json
  label.json
```

Nếu extraction lỗi, xem thông báo rồi chạy lại `extract`. Video gốc giữ nguyên và validator kiểm hash trước khi xử lý. Chuyển nguyên thư mục qua hình thức người tham gia đã đồng ý. Chạy validator ở máy nhận. Không đưa video, pose hay manifest cá nhân lên Git.
