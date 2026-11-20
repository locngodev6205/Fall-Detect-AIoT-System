# PR-05 · MediaPipe Lite và Full

Đo trên Intel i5-1235U, Python 3.11.18, PyTorch CPU 2.6, OpenCV 4.11 và MediaPipe 0.10.14. Cùng tám AVI raw Validation CAUCAFall 720×480 ở 20 FPS, một recording cho mỗi action, luân phiên ba subject. Chạy Lite rồi Full cùng checkpoint E4-42. Tập nhỏ được chọn trước khi đo, gồm 5 Fall và 3 ADL. Video giải mã nhanh nhất có thể, dùng timestamp clip.

| Chỉ số | Lite | Full |
|---|---:|---:|
| Pose khả dụng | 1464/1677 (87,3%) | 1482/1677 (88,4%) |
| Window đủ điều kiện | 173/233 | 184/233 |
| Coverage trong vùng match | 4/5 | 4/5 |
| TP / FN / FP | 3 / 2 / 3 | 3 / 2 / 4 |
| Event Recall | 60% | 60% |
| Pose p50/p95/p99 ms | 13,65/24,53/32,54 | 21,95/34,96/42,42 |
| Pipeline p50/p95/p99 ms | 14,50/25,47/33,55 | 23,07/35,93/43,28 |
| Replay FPS | 58,13 | 39,66 |
| CPU giây / wall giây | 32,38/28,85 | 46,13/42,28 |
| Peak RSS tích lũy MiB | 755 | 935 |

Percentile là trung vị của percentile từng clip. Peak RSS là high-water của tiến trình dùng chung chạy Lite trước, nên không quy toàn bộ chênh lệch cho Full. FPS là tổng frame chia tổng wall time gồm warmup pose.

Cả hai phát hiện ngã trái, phải và ngã từ tư thế ngồi. Cả hai bỏ sót ngã trước và ngã sau. Đi bộ có cảnh báo giả ở cả hai. Clip ngồi và nhặt đồ được chọn không báo giả. Full thêm một alert ngoài vùng match trên clip ngã sau. Chưa có phân tầng xác minh độc lập cho che khuất hoặc ra khỏi khung. Full cải thiện coverage cửa sổ nhưng chưa tăng coverage sự kiện hay Recall ở batch này. **Ưu tiên Lite cho benchmark Pi**, giữ Full làm đối chứng cho các ca mất pose nặng.
