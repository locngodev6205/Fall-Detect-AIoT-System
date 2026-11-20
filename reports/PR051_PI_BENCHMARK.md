# PR-05.1 · Benchmark trên Raspberry Pi 4

Benchmark dùng ARM64 Debian 13 và PyTorch 2.6.0+cpu, hai threads, MediaPipe 0.10.14, OpenCV 4.11.0. Dùng checkpoint nguyên gốc được ghim SHA-256. Phân loại sự kiện theo PR-04.1, threshold 0,5, cooldown 2 giây. Raw Validation video có annotation và đo Recall riêng. Camera live dùng cho throughput, tài nguyên và ổn định. Không có ground truth Fall trong camera live.

## Cách chạy lại

Chọn một thư mục nghiên cứu riêng, có thể dùng vùng RAM nếu phân vùng gốc ít chỗ. Giữ checkpoint, clip và kết quả ngoài Git. Dùng interpreter ARM64 đã kiểm tra có NumPy/OpenCV/MediaPipe và cài PyTorch vào target riêng. Kiểm tra Edge đang dừng và node camera rảnh trước khi mở live.

```bash
python -m pip install --no-cache-dir --target "$research_deps" torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
export PYTHONPATH="$research_deps:fall_detect"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=2
python -m research.benchmark --video "$clip" --complexity 0 --checkpoint "$checkpoint" --output lite.json
python -m research.benchmark --video "$clip" --complexity 1 --checkpoint "$checkpoint" --output full.json
timeout 330 python -m research.benchmark --camera 0 --seconds 300 --checkpoint "$checkpoint" --output live.json
```

JSON có số frame, scored windows, read/inter-frame/pose/preprocessing/GRU/pipeline latency p50/p95/p99, CPU time, peak RSS, mẫu RSS/nhiệt độ định kỳ và throttling. Timebase live là thời điểm read thành công. Thiếu hardware sequence ID nên dropped frames và timestamp drift theo sensor chưa đo được. Timeout bên ngoài chỉ dùng để bảo vệ trước blocking V4L2 read. Camera capture resolution là resolution thực tế của frame, đọc từ JSON. Cooldown dùng source time chứ không dùng wall time khi replay.

## Kết quả camera

| Chỉ số | Smoke 15 giây | Phiên 5 phút |
|---|---:|---:|
| Kích thước frame | 640×480 | 640×480 |
| Frame / thời lượng (s) | 156 / 15.03 | 3250 / 300.03 |
| FPS toàn pipeline | 10.38 | 10.83 |
| Frame pose hợp lệ / cửa sổ scored | 10 / 0 | 0 / 0 |
| Read p50/p95/p99 ms | 1.79/2.04/2.62 | 1.81/1.97/2.62 |
| Khoảng frame p50/p95/p99 ms | 91.17/95.16/131.12 | 91.13/95.42/123.53 |
| Pose p50/p95/p99 ms | 87.89/91.91/128.03 | 87.88/92.09/119.61 |
| Pipeline p50/p95/p99 ms | 91.16/95.20/131.61 | 91.12/95.39/123.27 |
| CPU trung bình theo một core | 100.2% | 101.0% |
| Peak RSS MiB | 375.7 | 377.1 |
| Nhiệt cao nhất từ mẫu định kỳ | 56.0 °C | 68.7 °C |
| Interruptions / timestamp resets / model errors | 0 / 1 / 0 | 0 / 0 / 0 |
| Throttling cuối phiên | throttled=0x0 | throttled=0x0 |

Khoảng FPS theo từng đoạn khoảng 5 giây sau warmup là 10.47–11.30. RSS sau warmup nằm trong 352.4–377.5 MiB, từ 376.5 MiB ở mẫu đầu đến 352.4 MiB ở mẫu cuối. Mẫu nhiệt đầu/cuối là 62.8/68.7 °C.

Phiên 30 phút và unplug/replug vật lý chưa thực hiện. Kết quả camera được đo khi Edge production dừng. Không có đủ người/hoạt động được kiểm soát để đánh giá Fall, false alarm/hour hay tải tracking duy trì.
