# PR-05.3 · Thử nghiệm giảm báo giả

Giữ nguyên checkpoint E4-42, 20 mẫu, stride 3, gap tối đa 3 và threshold 0,5. So bốn chính sách định trước trên raw Validation, không dùng trial live để chọn tham số. Một xác nhận và cooldown 2 giây là baseline. Hai xác nhận là đối chứng PR-05. Hysteresis chỉ mở latch khi score xuống dưới 0,35. Cooldown 4 giây kiểm tra việc kéo dài thời gian khóa. Không retrain.

| Chính sách | TP / FN / FP | ADL trial báo | Recall | Precision | F1 / F2 | Delay p50/p95 (s) |
|---|---:|---:|---:|---:|---:|---:|
| Baseline | 10 / 5 / 8 | 3/14 | 66,7% | 55,6% | 0,606 / 0,641 | 1,65 / 2,69 |
| 2 xác nhận | 9 / 6 / 9 | 3/14 | 60,0% | 50,0% | 0,545 / 0,577 | 1,86 / 2,76 |
| Hysteresis 0,35 | 10 / 5 / 7 | 3/14 | 66,7% | 58,8% | 0,625 / 0,649 | 1,65 / 2,69 |
| Cooldown 4 giây | 10 / 5 / 8 | 3/14 | 66,7% | 55,6% | 0,606 / 0,641 | 1,65 / 2,69 |

**VERIFIED.** Hysteresis loại alert muộn 5,2 giây ở FallSittingS9 và giữ TP 3,1 giây. Không giảm ADL FP. PickupobjectS9 vẫn có hai alert. Cooldown 4 giây không cải thiện tổng đo. Hai xác nhận làm mất 1 TP và tăng trễ trung vị 0,21 giây.

```bash
PYTHONPATH=fall_detect python scripts/ml/pr053_experiments.py "$data_root" "$checkpoint" "$new_private_output"
```
