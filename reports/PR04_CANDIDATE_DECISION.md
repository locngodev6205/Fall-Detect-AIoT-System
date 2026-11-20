# PR-04.1 · Quyết định ứng viên nghiên cứu

**Giữ GRU 20 + một đoạn mất pose tối đa 3 mẫu (E4)** để benchmark. E4 dẫn đầu F2 trung bình cả matched-data (0,738) và full-eligibility (0,662). Full E4 đạt F2 0,641 / 0,556 / 0,789. Giữ seed 42 để so sánh trực tiếp với PR-04 và benchmark nguyên mẫu. Không chọn seed tốt nhất trên cùng Validation. Ngưỡng vẫn 0,5. Seed 42 đạt 10 TP, 5 FN, 8 FP theo giao thức mới, gồm 3/14 trial ADL có báo giả. PR-04 dùng cách đếm khác, trong đó alert ngoài sự kiện Fall không được cộng vào FP.

Matched-data cho thấy lợi ích của E4 vẫn xuất hiện với cùng recording, timestamp kết thúc và 421 cửa sổ Train cho mỗi cấu hình. Gap policy tăng coverage chấm Fall từ 8/15 lên 10/15 ở 30 mẫu và từ 11/15 lên 14/15 ở 20 mẫu. Cắt ngắn và cổng gap đều đóng góp, còn việc có nhiều mẫu Train không giải thích hết cải thiện. Chênh lệch pha stride và phân bố đầu vào giữa matched/full vẫn giới hạn diễn giải.

Visibility-only phát hiện 9–12/15 Fall nhưng báo trên 11–14/14 ADL. Tín hiệu chất lượng pose có thể mang thông tin nhãn hoặc trạng thái vận động, nhưng phép này chưa chứng minh GRU đầy đủ dựa chủ yếu vào shortcut. Cần cân bằng phổ missingness giữa Fall/ADL và kiểm tra trên camera hoặc subject mới.

## Nguyên mẫu và quyết định PR-05

Nguyên mẫu độc lập resample theo timestamp, giữ rolling buffer 20 mẫu, stride 3, giữ zero ở mẫu thiếu, reset sampler/buffer/cảnh báo khi gián đoạn thời gian vượt 0,25 giây, và phát sự kiện in-memory theo cooldown 2 giây. Thời điểm phát là lúc sample gốc đến. Bảng ablation dùng timestamp lưới offline. Hai thời điểm có thể lệch trong phạm vi nhịp camera, và chưa đánh giá khả năng chạy cả pipeline qua camera thật.

Replay 6.031 pose updates trên Intel i5-1235U dùng PyTorch CPU, hai threads. Có 649 scores. Latency p50/p95 là 0,111/1,634 ms cho mọi update và 1,619/3,110 ms ở update có inference. Số đo gồm sampling, normalization, buffer và inference. Camera, MediaPipe, I/O và alert thật nằm ngoài benchmark này.

Có đủ cơ sở bắt đầu **benchmark nghiên cứu PR-05** trên Pi 4 ở chế độ tách biệt. Chưa đủ bằng chứng nghiệm thu hoặc deploy. Full E4 có 1–4 trial ADL báo giả trên 14 trial giữa các seed, phát hiện ngã trước dao động 0–2/3. Cần thêm subject và phòng phát triển, hard negatives liên tục để đo báo giả/giờ, đối chiếu Lite/Full trên Pi, và đánh giá cuối cùng độc lập. Test V2.1 không chạy inference, chưa phê duyệt G3-SUBSET. Production và runtime cảnh báo giữ nguyên.

## Tái lập

Checkpoint `full-E4-42.pt`, seed, hash, metrics và `candidate.json` nằm ngoài Git tại `annha-recovery-payutch-v1/pr04.1/controlled`. Các lệnh sau chạy từ repo với Python 3.11, PyTorch CPU 2.6, MediaPipe, OpenCV và Matplotlib. Dùng output mới hoặc tạo thư mục riêng trước khi chạy.

```bash
python scripts/ml/pr041_ablation.py "$data_root" "$run"
python scripts/ml/pr041_pose_probe.py "$data_root" "$prior/short20_mask/gru.pt" "$pose_report"
python scripts/ml/pr041_review.py "$data_root" "$prior" "$run"
```
