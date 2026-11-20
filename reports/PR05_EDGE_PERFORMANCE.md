# PR-05 · Hiệu năng máy phát triển và quy trình Raspberry Pi 4

**Pi 4 NOT_MEASURED.** Kiểm tra SSH chỉ đọc tới địa chỉ Pi đã biết bị timeout. Chưa xác nhận được kiến trúc hệ điều hành, PyTorch CPU, camera hoặc độ ổn định nhiệt trên Pi. Chưa có cơ sở chuyển runtime hoặc chọn ONNX/TFLite. Nếu cần chuyển đổi, kiểm tra numerical parity input và score trước khi so cảnh báo.

Chạy riêng từ repo trong sandbox nghiên cứu có Python 3.11, NumPy, OpenCV, MediaPipe có `solutions.pose` và PyTorch CPU tương thích kiến trúc. Kiểm tra import và kiến trúc OS trước. Không chạy đồng thời camera production.

```bash
uname -m
python -c 'import torch, cv2, mediapipe; print(torch.__version__, cv2.__version__, mediapipe.__version__)'
export PYTHONPATH=fall_detect
python -m research.benchmark --checkpoint "$checkpoint" --video "$clip" --complexity 0 --output /tmp/pr05-replay-lite.json
python -m research.benchmark --checkpoint "$checkpoint" --camera 0 --seconds 1800 --complexity 0 --output /tmp/pr05-live-lite.json
python -m research.benchmark --checkpoint "$checkpoint" --camera 0 --seconds 1800 --complexity 1 --output /tmp/pr05-live-full.json
```

Dùng checkpoint full-E4-42.pt đúng hash ghim trong adapter. Cấu hình mẫu là Lite, hai thread PyTorch, một xác nhận, threshold 0,5 và cooldown 2 giây. Tệp JSON đầu ra phải mới. Mô phỏng unplug/replug camera trong phiên nghiên cứu rồi kiểm tra interruptions, reset và thời gian warmup trước khi có score mới. Camera benchmark đo thời gian gọi read và cadence của frame sau khi read thành công. Không có sensor sequence ID hoặc timestamp driver thì dropped frames ghi null và jitter chỉ phản ánh cadence quan sát. Live loop tuần tự có thể bị ảnh hưởng bởi blocking read phía driver. Nên quan sát dài hạn thêm việc phục hồi, RAM, nhiệt độ, throttling và thời gian ổn định trước khi quyết định tích hợp.

Replay từ file cho throughput, độ trễ pose, preprocessing và inference độc lập với tốc độ phát video thật. CPU seconds và peak RSS thuộc tiến trình. Nhiệt độ và throttling là snapshot cuối phiên nếu đọc được. Latency simulated alert là từ sau capture đến khi append trong bộ nhớ. Detection delay dựa trên onset annotation, đo riêng trong báo cáo sự kiện. Model checkpoint khoảng 35 KiB, không đại diện footprint của runtime PyTorch và MediaPipe.

Smoke test CLI trên FallForwardS6 đọc 202 frame, thiếu landmark 72 frame. Preprocessing p50/p95/p99 0,053/0,182/0,230 ms. GRU inference 0,930/1,055/1,069 ms.
