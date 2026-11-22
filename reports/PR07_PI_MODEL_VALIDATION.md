# PR-07 · GRU và BiLSTM trên Raspberry Pi 4

## Phạm vi và cách đo

Replay cùng 10 AVI từ raw Validation CAUCAFall V2.1, gồm 5 Fall và 5 No Fall từ 3 subject. Các clip được chọn theo hành động và bao gồm ca nhặt đồ từng bị GRU báo nhầm ở PR-06. Đây là phép kiểm tra phát triển có chủ đích. Không dùng tập Test khóa để chọn model hoặc ngưỡng.

GRU dùng E4-42, MediaPipe Lite và EventEngine của PR-05. BiLSTM dùng Run 5 fold 0, MediaPipe Full và alarm FSM mặc định của demo upstream, theo đúng route đã dùng ở PR-06. Hai tiến trình chạy lần lượt, hai thread PyTorch và một thread OpenCV. BiLSTM dùng toàn bộ frame với chu kỳ đạo hàm danh nghĩa 15 Hz như demo. File nguồn có cadence khoảng 20 Hz. Output FSM chỉ được ghi ra JSON. Cooldown của BiLSTM giữ đồng hồ monotonic của upstream, nên việc replay chậm hơn thời gian gốc có thể ảnh hưởng các lần báo lặp.

- **Model:** ghi timestamp mỗi lần score thô vượt lên ngưỡng riêng của model, 0,5 cho GRU và 0,75 cho BiLSTM. Đây là lần bắt đầu một dải score cao, không phải đếm từng cửa sổ.
- **Engine:** ghi timestamp alert mô phỏng của GRU hoặc mỗi lần BiLSTM vào trạng thái FALL_CONFIRMED.
- **Event:** TP nếu có ít nhất một lần trong khoảng từ onset tới min(onset + 3 giây, end + 1 giây). Một Fall không có lần khớp là FN, kể cả khi thiếu pose. Bản ghi No Fall có dự báo và các lần sớm, muộn, trùng trong clip Fall được đếm là FP theo từng lần. Độ trễ theo thời gian video, không gồm thời gian đến Telegram/email.
- **Thiết bị:** FPS bằng tổng số frame chia tổng wall time của replay. CPU theo thời gian CPU tiến trình trên wall time, 100% tương ứng một lõi. RAM là high-water RSS tiến trình. Nhiệt lấy ở đầu và cuối mỗi clip.

Không mở camera, không dùng backend, không gửi cảnh báo và không đổi checkpoint mặc định.

## Tái lập

Trên máy giữ V2.1, chạy từ root repo để xuất cohort cùng đường dẫn 10 AVI. Runner trên Pi chỉ cần JSON, các AVI có cùng basename và SHA-256, mã từ nhánh review, và hai checkpoint ghim ở PR-06.

```bash
python scripts/ml/pr07_pi_validation.py export "$dataset_v21" /tmp/cohort.json
```

Chép các đầu vào sang thư mục riêng trên Pi. Trong Python 3.11 ARM64 cần PyTorch CPU 2.6.0, MediaPipe 0.10.14, OpenCV, NumPy, PyYAML và python-json-logger. BiLSTM cần checkout upstream ghim và asset MediaPipe Full theo [hướng dẫn PR-06](PR06_PRETRAINED_BENCHMARK.md). GRU cần asset MediaPipe Lite của legacy Solutions. Chạy từ repo trên Pi sau khi kích hoạt môi trường nghiên cứu. Các file đầu ra phải mới.

```bash
python scripts/ml/pr07_pi_validation.py run gru "$cohort" "$media" "$gru" "$out/gru.json"
python scripts/ml/pr07_pi_validation.py run bilstm "$cohort" "$media" "$bi_checkpoint" \
  "$out/bilstm.json" --upstream "$bi_repo"
```

## Kết quả đo trên Pi 4

PyTorch 2.6.0+cpu, OpenCV 4.11.0, MediaPipe 0.10.14. Edge vẫn hoạt động trong lúc đo. FPS phản ánh tải thực tế của lần chạy.

| Model | FPS replay | CPU bình quân | Peak RSS | Nhiệt đầu–cuối, cao nhất | Inference p50 / p95 theo clip |
| --- | ---: | ---: | ---: | ---: | ---: |
| GRU | 7.99 | 106% | 551 MiB | 70.6–78.4, 78.4 °C | 61.20 / 83.41 ms |
| BiLSTM | 4.95 | 106% | 540 MiB | 79.4–82.3, 82.3 °C | 25.64 / 49.00 ms |

| Model | Output | TP / FP / FN | Event Recall | Trễ trung vị |
| --- | --- | ---: | ---: | ---: |
| GRU | raw | 3 / 10 / 2 | 60% | 1.00 s |
| GRU | engine | 3 / 8 / 2 | 60% | 1.00 s |
| BiLSTM | raw | 5 / 2 / 0 | 100% | 1.96 s |
| BiLSTM | engine | 0 / 5 / 5 | 0% | — |

| Clip | Khoảng Fall (s) | GRU raw → engine (s) | BiLSTM raw → engine (s) |
| --- | --- | --- | --- |
| FallForwardS6.avi | 2.36–5.20 | 5.50, 6.10 → 5.50, 7.60 | 4.60 → 9.05 |
| FallBackwardsS7.avi | 3.09–5.55 | 2.50 → 2.50 | 5.05 → 9.45 |
| FallLeftS7.avi | 2.36–4.38 | 3.10, 5.50 → 3.10 | 4.30 → 8.55 |
| FallRightS9.avi | 1.50–3.56 | 2.50, 5.20 → 2.50 | 2.90 → 7.20 |
| FallSittingS9.avi | 1.54–5.00 | 3.10, 4.30 → 3.10, 5.20 | 3.90 → 8.15 |
| PickupobjectS6.avi | No Fall | — → — | — → — |
| PickupobjectS7.avi | No Fall | — → — | 4.05 → — |
| PickupobjectS9.avi | No Fall | 3.40, 8.80 → 3.40, 8.80 | — → — |
| SitDownS7.avi | No Fall | 6.70 → 6.70 | 1.45 → — |
| WalkS7.avi | No Fall | 1.90 → 1.90 | — → — |

## Kết luận

**Giữ GRU E4-42 và cải tiến xử lý cảnh báo.** Pipeline BiLSTM chỉ đạt 4,95 FPS, thấp hơn 38% so với GRU dù inference mỗi cửa sổ nhanh hơn. BiLSTM chạy sau GRU khi Pi đã nóng. `vcgencmd get_throttled` trả `0x0` trước lượt đo và `0x80000` sau lượt đo. Tốc độ ghi nhận có ảnh hưởng của tải nền, thứ tự chạy và nhiệt. Chênh lệch FPS không thể quy riêng cho kiến trúc hay MediaPipe.

Với BiLSTM, raw score vượt ngưỡng trong vùng match ở cả 5 ca Fall. Alarm FSM xác nhận cả 5 sau vùng match từ 3,27 đến 3,83 giây. Vì vậy event recall của đường xác nhận là 0/5, đồng thời cả 5 lần báo muộn được tính FP. Trên 5 clip No Fall, FSM lọc cả hai lần vượt ngưỡng thô ở nhặt đồ S7 và ngồi S7. Sự cải thiện trên No Fall phụ thuộc cả checkpoint và FSM. Trên nhóm này GRU có 4 lần báo trên 3 clip No Fall, trong đó nhặt đồ S9 báo hai lần. Các con số theo timestamp giải thích vì sao kết luận khác PR-06, vốn chấm một kết quả cho cả clip.

Dừng hướng triển khai BiLSTM mặc định. Dùng kết quả raw so với EventEngine để xem xét cách giảm báo sai của GRU, với tiêu chí giữ event recall và theo dõi độ trễ. Tổng số 5 Fall thuộc một tập phát triển nhỏ nên các tỷ lệ chưa đại diện cho môi trường khác. Không thực hiện thử camera trực tiếp trong PR này.

**Kiểm thử:** 31 bài đạt trên máy phát triển. Hai lần replay ARM64 chạy đủ 10 clip mỗi model và kết thúc thành công. Tập video, checkpoint và JSON đo giữ ngoài Git.
