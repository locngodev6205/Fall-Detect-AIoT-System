# PR-05.1 · MediaPipe Lite và Full trên Pi

Dùng cùng tám AVI raw Validation ở 720×480 và 20 fps video, lần lượt chạy Lite và Full. Giữ cùng checkpoint, threshold, stride, feature schema và policy mất pose. Năm clip có Fall và ba clip ADL gồm ngồi, nhặt đồ, đi bộ. Mỗi tiến trình chạy một clip. Tính FPS theo tổng frame chia tổng wall time. Các percentile trong bảng là trung vị các percentile theo clip. Peak RSS là giá trị cao nhất qua các clip. Không trộn FPS decode replay với tốc độ camera USB.

| Chỉ số | Lite | Full |
|---|---:|---:|
| Pose hợp lệ | 1485/1677 | 1478/1677 |
| Scored / candidate windows | 170/233 | 177/233 |
| Coverage Fall | 5/5 | 4/5 |
| TP / FN / FP | 3 / 2 / 4 | 2 / 3 / 5 |
| Recall / Precision / F1 / F2 | 0.600 / 0.429 / 0.500 / 0.556 | 0.400 / 0.286 / 0.333 / 0.370 |
| ADL có cảnh báo | 1/3 | 1/3 |
| Detection delay P50/P95 s | 1.00/2.46 | 1.51/1.97 |
| Replay throughput FPS | 10.49 | 7.35 |
| Decode/read p50/p95/p99 ms | 2.34/2.77/3.52 | 2.33/2.63/3.56 |
| Pose p50/p95/p99 ms | 87.31/90.22/165.15 | 132.27/136.76/174.82 |
| Preprocessing p50/p95/p99 ms | 0.31/0.56/0.60 | 0.32/0.56/0.63 |
| GRU p50/p95/p99 ms | 5.79/9.96/13.50 | 5.83/11.56/13.90 |
| Pipeline p50/p95/p99 ms | 91.27/99.97/169.58 | 136.15/147.90/180.12 |
| Alert capture-to-dispatch p50/p95/p99 ms | 98.11/98.11/98.11 | 141.71/142.04/142.04 |
| CPU core trung bình | 1.04 | 1.03 |
| Peak RSS MiB | 393.7 | 414.8 |
| Nhiệt cuối clip cao nhất | 60.9 °C | 64.3 °C |
| Throttling cuối clip | throttled=0x0 | throttled=0x0 |

Khác với replay pose CSV, MediaPipe chạy lại native trên board. Các kết quả sự kiện theo video phụ thuộc đầu ra pose và không so trực tiếp với parity cùng tensor. Tỷ lệ ADL tính theo trial, không phải báo giả theo giờ.

| Recording | Lite | Full |
|---|---|---|
| FallForwardS6 | FN, 2 FP | FN, 1 FP |
| FallLeftS7 | TP, 0 FP | FN, 1 FP |
| FallRightS9 | TP, 0 FP | TP, 0 FP |
| FallBackwardsS6 | FN, 1 FP | FN, 2 FP |
| FallSittingS7 | TP, 0 FP | TP, 0 FP |
| SitDownS9 | ADL, 0 alert | ADL, 0 alert |
| PickupobjectS6 | ADL, 0 alert | ADL, 0 alert |
| WalkS7 | ADL, 1 alert | ADL, 1 alert |
