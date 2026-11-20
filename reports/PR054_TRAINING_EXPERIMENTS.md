# PR-05.4 · Huấn luyện đối chứng

E0 dùng checkpoint gốc E4-42. E1 tái huấn luyện đúng kiến trúc GRU 32 hidden, 20 mẫu, gap 3, stride 3, 10 Hz, threshold 0,5, 30 epoch, AdamW 0,001, batch 32 và BCE cân bằng theo lớp/recording. Ba seed định trước 42/43/44. Mỗi lần có 584 cửa sổ Train. Kết quả và checkpoint ở thư mục hiện vật local `annha-recovery-payutch-v1/pr054`.

| Run | TP / FN / FP | ADL có báo | Recall | Precision | F1 / F2 | Delay p50/p95 s |
|---|---:|---:|---:|---:|---:|---:|
| E0 | 10/5/8 | 3/14 | 66,7% | 55,6% | 0,606/0,641 | 1,65/2,69 |
| E1 seed 42 | 10/5/8 | 3/14 | 66,7% | 55,6% | 0,606/0,641 | 1,65/2,69 |
| E1 seed 43 | 9/6/12 | 4/14 | 60,0% | 42,9% | 0,500/0,556 | 1,42/2,03 |
| E1 seed 44 | 12/3/4 | 1/14 | 80,0% | 75,0% | 0,774/0,789 | 1,66/2,55 |

E2 mở rộng Train bằng hard negatives, E3 cân bằng theo subject và E4 cân bằng missingness đều **BLOCKED_BY_DATA**. Script có đường chạy E2 sau xác minh nhiều subject Train và kiểm split, với tham số cùng E1. Epoch cố định khiến số bước cập nhật tăng khi thêm window. E2 chỉ là đánh giá phát triển trên Validation đã dùng. Đánh giá tiến cứu cần một giao thức riêng gồm cả Fall và ADL từ cohort độc lập. E3/E4 sẽ giữ seed, số bước và policy event như đối chứng khi thiết kế phép đo có đủ dữ liệu. Không chọn seed tốt nhất hoặc tune theo ca live.

```bash
PYTHONPATH=fall_detect python scripts/ml/pr054_audit.py "$data_root" audit.json
PYTHONPATH=fall_detect python scripts/ml/pr05_replay.py "$data_root" "$checkpoint" baseline.json
PYTHONPATH=fall_detect python scripts/ml/pr054_training.py "$data_root" "$new_output"
```
