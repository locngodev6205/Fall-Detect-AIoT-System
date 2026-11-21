# PR-06 · Benchmark pretrained cho AnNhà

**Kết quả.** Cả hai checkpoint chạy được trên 29 clip Validation. BiLSTM giảm FP từ 3 xuống 0 và tăng nhẹ F1, nhưng bỏ sót thêm 2 clip Fall. FallTCN bỏ sót thêm 9 clip Fall. Giữ GRU E4-42 cho bước kế tiếp.

## Dữ liệu và cách đo

Nguồn video là CAUCAFall v5, nhãn được đối chiếu với OmniFall theo quy trình PR-03. Runner dùng cùng danh sách raw Validation đã ghim theo manifest V2.1, gồm cả clip không tạo được cửa sổ train 30 mẫu. Mỗi video được đối chiếu SHA-256 trước inference. Test V2.1 giữ khóa. GRU đã từng được chọn bằng Validation này, nên kết quả là phép đối chiếu phát triển. Các ứng viên dùng checkpoint huấn luyện trên URFD theo tài liệu upstream. CAUCAFall là nguồn khác và hồ sơ công bố không chỉ ra giao nhau. Đối chiếu 29 clip Validation với 12 clip URFD hiện diện ở Train của AnNhà cho 0 hash video và 0 hash frame giải mã trùng. Đây là phạm vi kiểm tra cục bộ. Danh mục huấn luyện đầy đủ và đối chiếu danh tính xuyên dataset chưa đủ để chứng nhận độc lập tuyệt đối.

Mỗi clip có một nhãn và một dự đoán. TP là clip Fall có quyết định Fall ở bất kỳ thời điểm nào trong clip. FP là clip No Fall có quyết định Fall. Recall, Precision, F1 và F2 ở cấp clip. Phép đo này không kiểm tra alert có đến đúng khoảng ngã và không ước lượng false alarms/giờ. Đối chiếu [PR-05.3](PR053_FALSE_POSITIVE_EXPERIMENTS.md) để xem kết quả event-level có đối chiếu timestamp. Một clip Fall bị báo sai thời điểm vẫn có thể tính TP trong bảng clip. Clip không có score được báo riêng. Số clip cùng một subject có tương quan. Các nhãn hiện có bao gồm cúi nhặt đồ và quỳ. Thiếu nhãn riêng cho độ sâu của cúi, đứng lên và nằm xuống chủ động. Kết luận cho các tình huống đó và cho hiệu quả ngoài CAUCAFall là `NOT_ENOUGH_EVALUATION_DATA`.

## Checkpoint và pipeline upstream

- **FallTCN** dùng checkpoint Git gốc tại commit `cecf81483091883bca1272f956d68c0aa6676d42`, huấn luyện trên 70 sự kiện URFD cam0 theo upstream. Pipeline gốc dùng MediaPipe Lite IMAGE, 15 feature pose + 4 feature motion, 48 mẫu tại 15 Hz, thống kê chuẩn hóa từ checkpoint và ngưỡng 0,5. Foreground dùng median background của toàn clip, giả định camera tĩnh. Không tìm thấy giấy phép code/checkpoint trong snapshot đã kiểm tra. Config ghi URFD là CC-BY-NC-SA-4.0. [Repo gốc](https://github.com/youssef-malak1/fall-detection/tree/cecf81483091883bca1272f956d68c0aa6676d42)
- **BiLSTM** dùng Run 5 fold 0, lựa chọn mặc định của demo khi truyền thư mục LOSO, từ asset release `run5_stride2_aug.zip`. Asset SHA-256 `1f6e654683896d1bfde3a9411e2f74de49508301790a7fa48e3e8333febf5281` khớp downloader. Adapter giữ luồng demo MediaPipe Full VIDEO, feature extractor 15 chiều, cửa sổ 30 quan sát pose, chu kỳ danh nghĩa 15 FPS cho đạo hàm, và alarm FSM mặc định. Demo đọc mỗi frame của video đầu vào và không áp dụng các file normalization theo fold, trong khi script đánh giá LOSO áp dụng chúng. Kết quả ở đây đo đường demo, khác phép tái lập LOSO. README gắn huy hiệu MIT nhưng snapshot thiếu văn bản giấy phép và asset chưa có điều khoản riêng được xác minh. [Repo gốc](https://github.com/egi03/ai-fall-detection-system/tree/2f305fa7d2183181aa1cc87413e46a5e09c79a8a)
- **GRU E4-42** chạy research Stream từ PR-05 với MediaPipe Lite, 20 mẫu ở 10 Hz, stride 3, gap tối đa 3, schema `annha-pose-v2`, một xác nhận và threshold 0,5. SHA-256 checkpoint `5ef559faee3374f57e240b389ad413c336449f85866b4ef357581abef13bb7ac`.

## Tái lập

Dùng Python 3.11, PyTorch 2.6.0 CPU, MediaPipe 0.10.14, OpenCV 4.11, pandas 2.x, PyYAML và python-json-logger 4.2. Chuẩn bị bản local Dataset V2.1 theo báo cáo PR-03. Các đường dẫn trong manifest nguồn phải trỏ tới video/CSV có SHA đúng. Dùng thư mục ngoài Git cho clone upstream, checkpoint và JSON đầu ra.

```bash
python -m pip install 'torch==2.6.0' --index-url https://download.pytorch.org/whl/cpu
python -m pip install 'numpy<2' 'mediapipe==0.10.14' 'opencv-contrib-python==4.11.0.86' \
  'pandas>=2,<3' PyYAML 'python-json-logger>=3'
git clone https://github.com/youssef-malak1/fall-detection.git "$tcn"
git -C "$tcn" checkout --detach cecf81483091883bca1272f956d68c0aa6676d42
git clone https://github.com/egi03/ai-fall-detection-system.git "$bi"
git -C "$bi" checkout --detach 2f305fa7d2183181aa1cc87413e46a5e09c79a8a
curl -fL https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task \
  -o "$tcn/models/pose_landmarker_lite.task"
(cd "$bi" && python scripts/download_models.py --model run5)

python scripts/ml/pr06_benchmark.py gru "$data" "$e4_checkpoint" "$out/gru.json"
python scripts/ml/pr06_benchmark.py falltcn "$data" "$tcn/models/fall_tcn.pt" \
  "$out/falltcn.json" --upstream "$tcn"
python scripts/ml/pr06_benchmark.py bilstm "$data" "$bi/models/run5_stride2_aug/fold_0/best_model.pth" \
  "$out/bilstm.json" --upstream "$bi"
```

Đặt biến `tcn`, `bi`, `data`, `e4_checkpoint`, `out` thành đường dẫn tuyệt đối và tạo thư mục `out` trước khi chạy. JSON ghi từng clip, score cực đại, quyết định, số cửa sổ, pose coverage và thời gian. Score giữa các model có calibration khác nhau. Với BiLSTM, score cực đại có thể vượt ngưỡng mà alarm FSM vẫn chưa xác nhận. Mỗi file đầu ra phải chưa tồn tại. MediaPipe legacy của GRU cần asset Lite `pose_landmark_lite.tflite` trong môi trường local. Để đo hiệu năng chính xác hơn, chạy từng model tuần tự trên cùng máy để tránh tranh CPU. Lượt đo trong báo cáo dùng Intel i5-1235U x86_64, hai thread PyTorch, một thread OpenCV, và có giai đoạn ba tiến trình chạy đồng thời. FallTCN và BiLSTM được ghim lên hai dải CPU riêng. Wall time là số tham khảo gồm decode và pose. Forward FallTCN đo cả batch cửa sổ trong clip, còn GRU và BiLSTM đo từng cửa sổ. Các số này không tương đương độ trễ từ lúc ngã tới cảnh báo.
## Kết quả trên Validation

Có **29 recording**, 15 Fall và 14 No Fall từ 3 subject. Cả ba model có score cho đủ 29 clip.

| Model | Precision | Recall | F1 | F2 | TP / FP / FN / TN | Wall ms/clip p50 | Khả thi trên Pi 4 |
| --- | ---: | ---: | ---: | ---: | --- | ---: | --- |
| GRU E4-42 | 0.812 | 0.867 | 0.839 | 0.855 | 13 / 3 / 2 / 11 | 9327 | Đã benchmark trước ở PR-05.1 |
| FallTCN | 1.000 | 0.267 | 0.421 | 0.312 | 4 / 0 / 11 / 14 | 9360 | Chưa đo, cần pipeline motion causal |
| BiLSTM | 1.000 | 0.733 | 0.846 | 0.775 | 11 / 0 / 4 / 14 | 15693 | Chưa đo, Full pose và FSM cần benchmark |

| Model | Scored / tổng | Thiếu Fall / No Fall | Lỗi video / model | Pose coverage trung vị | Replay FPS p50 | Forward p50 theo clip |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| GRU E4-42 | 29/29 | 0 / 0 | 0 / 0 | 94.7% | 22.5 | 1.46 ms |
| FallTCN | 29/29 | 0 / 0 | 0 / 0 | 77.8% | 31.3 | 3.24 ms |
| BiLSTM | 29/29 | 0 / 0 | 0 / 0 | 97.2% | 13.7 | 3.95 ms |

Phân bố hành động theo số clip gồm Fall backwards (3), Fall forward (3), Fall left (3), Fall right (3), Fall sitting (3), Hop (3), Kneel (2), Pick up object (3), Sit down (3), Walk (3).
Pick up object có 3 clip. Số clip dự đoán Fall lần lượt là 1, 0, 0 theo thứ tự GRU, FallTCN, BiLSTM.
Fall forward có 3 clip. Số clip dự đoán Fall lần lượt là 3, 0, 2 theo thứ tự GRU, FallTCN, BiLSTM.

### Dự đoán từng recording

Ô model ghi quyết định và score cực đại làm tròn. F là Fall, N là No Fall, — là thiếu score.

| Recording CAUCAFall | Nhãn | GRU | FallTCN | BiLSTM |
| --- | --- | --- | --- | --- |
| FallBackwardsS6 | F | F 0.989 | F 0.992 | N 0.909 |
| FallBackwardsS7 | F | F 0.994 | F 0.820 | F 0.949 |
| FallBackwardsS9 | F | F 0.991 | N 0.010 | F 0.975 |
| FallForwardS6 | F | F 0.596 | N 0.118 | F 0.998 |
| FallForwardS7 | F | F 0.881 | N 0.085 | F 1.000 |
| FallForwardS9 | F | F 0.663 | N 0.013 | N 1.000 |
| FallLeftS6 | F | N 0.166 | F 0.964 | N 0.167 |
| FallLeftS7 | F | F 0.988 | N 0.092 | F 1.000 |
| FallLeftS9 | F | F 0.982 | N 0.009 | N 1.000 |
| FallRightS6 | F | N 0.023 | N 0.228 | F 0.997 |
| FallRightS7 | F | F 0.991 | N 0.027 | F 0.963 |
| FallRightS9 | F | F 0.930 | N 0.024 | F 0.982 |
| FallSittingS6 | F | F 0.972 | F 0.999 | F 1.000 |
| FallSittingS7 | F | F 0.992 | N 0.010 | F 0.975 |
| FallSittingS9 | F | F 0.949 | N 0.014 | F 1.000 |
| HopS6 | N | N 0.030 | N 0.010 | N 0.276 |
| HopS7 | N | N 0.051 | N 0.009 | N 0.955 |
| HopS9 | N | N 0.028 | N 0.007 | N 0.963 |
| KneelS7 | N | N 0.110 | N 0.014 | N 0.929 |
| KneelS9 | N | N 0.037 | N 0.007 | N 0.256 |
| PickupobjectS6 | N | N 0.036 | N 0.066 | N 0.655 |
| PickupobjectS7 | N | N 0.118 | N 0.006 | N 0.999 |
| PickupobjectS9 | N | F 0.980 | N 0.007 | N 0.730 |
| SitDownS6 | N | N 0.076 | N 0.007 | N 0.676 |
| SitDownS7 | N | F 0.969 | N 0.012 | N 0.428 |
| SitDownS9 | N | N 0.062 | N 0.083 | N 0.987 |
| WalkS6 | N | N 0.049 | N 0.010 | N 0.939 |
| WalkS7 | N | F 0.919 | N 0.006 | N 0.302 |
| WalkS9 | N | N 0.368 | N 0.005 | N 0.934 |

## Quyết định

**Giữ GRU E4-42 cho bước kế tiếp.** FallTCN tránh báo giả trong ba clip nhặt đồ nhưng bỏ sót 11/15 clip Fall, gồm 3/3 ca ngã về trước. Một số clip bị bỏ sót vẫn có pose coverage trên 90%. Kết quả này chưa đủ để quy toàn bộ lỗi cho mất pose. Median background cần dữ liệu cả clip và phụ thuộc camera tĩnh, nên muốn dùng với PTZ phải xây pipeline causal rồi đánh giá lại.

BiLSTM xác nhận đúng 2/3 clip ngã về trước và không xác nhận Fall trên cả ba clip nhặt đồ. Ở clip nhặt đồ S7, score cực đại vẫn đạt 0,999. FSM loại được quyết định Fall cho clip này, nên kết quả chưa chứng minh checkpoint tự phân biệt tốt động tác cúi. Cùng FSM cũng bỏ sót các clip Fall có score cao. MediaPipe Full và cơ chế persistence/stillness cần được đo riêng trên Pi trước khi cân nhắc dùng. PR-06 không chạy thử camera hay đo nhiệt trên Pi. Đối chứng gần nhất cho GRU Lite là PR-05.1, đo replay khoảng 10,49 FPS trên Pi 4. [Ảnh hưởng của pose Lite/Full trên Pi](PR051_LITE_VS_FULL.md)

Chưa cần fine-tune hai checkpoint ngoài dựa trên ba ca nhặt đồ từ một nguồn. Thử tiếp hướng giảm báo giả với GRU trên hard-negative development và xét đồng thời event recall, trễ cảnh báo và số cảnh báo giả. PR-05.3 đã ghi nhận tăng số lần xác nhận không giải quyết ca nhặt đồ S9. Cần giữ ca ngã thật trong đánh giá để tránh đổi lấy Recall thấp hơn.

## Kiểm thử và phạm vi

29 bài test liên quan đạt, gồm kiểm tra score không hữu hạn, xử lý abstention, thống kê thiếu lớp, PR-04 và streaming PR-05. Cả hai checkpoint upstream tải và đọc được bằng PyTorch CPU. Không thêm checkpoint, video, dataset hoặc cấu hình nhạy cảm vào branch. Không chạy Test khóa, không retrain và không thay đổi Edge hay đường gửi cảnh báo.
