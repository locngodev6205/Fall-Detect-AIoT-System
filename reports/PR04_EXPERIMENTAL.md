# PR-04 Experimental · Fall detection trên Dataset V2.1

## Dữ liệu và thiết kế

Manifest V2.1 được ghim theo SHA-256 byte `3c2b4f2930ad678a7fb6cf8621d67916f3a416300d07c590b8d8c7ba92b28dd3`. Baseline dùng đúng 458 cửa sổ Train từ 47 recording và 251 cửa sổ Validation từ 20 recording. Các nhãn Fall/ADL đối chiếu provenance upstream, thời gian Fall và checksum pose trước khi training. Các subject CAUCAFall dùng cho Train và Validation không giao nhau (4 và 3 người). URFD và Montréal chỉ xuất hiện trong Train, với giới hạn subject như báo cáo PR-03. Test không được đọc qua loader hoặc chấm điểm model.

Baseline Train có 4 ngã sau, 2 ngã trái, 3 ngã phải và 4 ngã từ tư thế ngồi của CAUCAFall. Tám Fall còn lại thuộc URFD/Montréal. Baseline Validation có 3 ngã sau, 1 ngã phải và 3 ngã từ tư thế ngồi. Không có ngã trước ở cả hai tập baseline. Tập raw phát triển lấy thêm recording có annotation upstream đã xác minh nhưng từng trượt preflight, bằng subject đã chỉ định cho Train hoặc Validation. Raw Validation có **15 Fall và 14 ADL trên 3 người**, trong đó 3 Fall về phía trước. Raw Train có 3 clip Fall về phía trước có annotation hợp lệ đưa vào kiểm tra coverage.

Ba baseline dùng cùng `annha-pose-v2`, 30 mẫu tại 10 Hz, seed 42, AdamW lr 0,001, batch 32 và 30 epoch cố định trên CPU, PyTorch 2.6.0+cpu. BCE có trọng số để cân bằng hai lớp và hạn chế recording dài chi phối. Không augment, không chọn epoch theo Validation, threshold cố định 0,5. Transformer nhỏ có positional encoding học được và 2 encoder layers. TCN dùng 3 lớp convolution dilation 1/2/4. GRU dùng hidden size 32. Đây là baseline mới huấn luyện cùng protocol. Chưa đo mô hình legacy trên V2.1.

| Baseline | Tham số | Train loss epoch 1 → 30 | F2 theo cửa sổ Validation |
| --- | ---: | ---: | ---: |
| Transformer 30 | 19.745 | 0,671 → 0,008 | 0,782 |
| TCN 30 | 11.169 | 0,693 → 0,086 | 0,810 |
| GRU 30 | 8.193 | 0,681 → 0,200 | 0,559 |

Các biến thể GRU dùng cùng protocol huấn luyện. Tổng hợp Train từ `results.json`:

| Biến thể | Recording Train | Cửa sổ Train | Train loss epoch 1 → 30 | F2 theo cửa sổ Validation |
| --- | ---: | ---: | ---: | ---: |
| GRU 30, gián đoạn ngắn | 48 | 493 | 0,662 → 0,121 | 0,726 |
| GRU 20 | 49 | 553 | 0,691 → 0,114 | 0,486 |
| GRU 10 | 51 | 625 | 0,700 → 0,351 | 0,260 |
| GRU 20, gián đoạn ngắn | 50 | 584 | 0,675 → 0,116 | 0,485 |

Đã đối chiếu SHA-256 của cả bảy checkpoint với log huấn luyện và xác nhận hai lượt quét Validation cho kết quả giống nhau. Train loss là BCE có trọng số trong quá trình tối ưu. Lần chạy này báo các chỉ số phân loại trên Validation.

## Validation theo recording và subject

Mỗi model quét theo thời gian các cửa sổ đủ điều kiện chất lượng trên raw Validation ở stride 3, với timestamp dự đoán tại mẫu cuối. Annotation thời gian chỉ dùng sau khi có dự đoán để khớp. Một recording Fall được phát hiện khi có ít nhất một điểm vượt ngưỡng từ onset tới một giây sau cuối khoảng ngã. Recording ADL có ít nhất một điểm vượt ngưỡng tính là một FP. Recording Fall thiếu cửa sổ phù hợp vẫn nằm trong mẫu số. FP trên các khoảng trước onset của clip Fall được theo dõi riêng. Đây là thước đo theo trial ngắn. Chưa đo được số báo giả trên giờ quan sát liên tục.

| Model | TP | FN | FP | Recall | Precision | F1 | F2 | Ngã trước |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Transformer 30 | 6 | 9 | 3 | 40,0% | 66,7% | 50,0% | 43,5% | 0/3 |
| TCN 30 | 7 | 8 | 4 | 46,7% | 63,6% | 53,8% | 49,3% | 0/3 |
| GRU 30 | 6 | 9 | 5 | 40,0% | 54,5% | 46,2% | 42,3% | 0/3 |
| GRU 30, gián đoạn ngắn | 11 | 4 | 4 | 73,3% | 73,3% | 73,3% | 73,3% | 1/3 |
| GRU 20 | 10 | 5 | 9 | 66,7% | 52,6% | 58,8% | 63,3% | 0/3 |
| GRU 10 | 11 | 4 | 6 | 73,3% | 64,7% | 68,8% | 71,4% | 0/3 |
| GRU 20, gián đoạn ngắn | 12 | 3 | 3 | 80,0% | 80,0% | 80,0% | 80,0% | 2/3 |

| Model | Subject 6 | Subject 7 | Subject 9 |
| --- | --- | --- | --- |
| Transformer 30 | 2/5, 0/4 | 2/5, 2/5 | 2/5, 1/5 |
| TCN 30 | 2/5, 0/4 | 2/5, 2/5 | 3/5, 2/5 |
| GRU 30 | 2/5, 1/4 | 2/5, 2/5 | 2/5, 2/5 |
| GRU 30, gián đoạn ngắn | 2/5, 1/4 | 4/5, 1/5 | 5/5, 2/5 |
| GRU 20 | 3/5, 1/4 | 4/5, 5/5 | 3/5, 3/5 |
| GRU 10 | 3/5, 2/4 | 4/5, 3/5 | 4/5, 1/5 |
| GRU 20, gián đoạn ngắn | 2/5, 0/4 | 5/5, 2/5 | 5/5, 1/5 |

Hai tỷ số mỗi ô lần lượt là phát hiện trên số Fall và báo giả trên số ADL. Số cửa sổ chồng lấn không dùng làm số sự kiện độc lập.

TCN phát hiện 7/7 recording Fall nếu chỉ xét các recording Fall qua cổng V2.1. Recall giảm còn 7/15 khi đưa lại các recording đã loại vào mẫu số. GRU 20 gián đoạn ngắn cho phép một đoạn mất liên tục tối đa 3 mẫu ở bên trong cửa sổ, với hai đầu hợp lệ. Mẫu mất giữ toàn số 0 và visibility 0. Không nội suy chuyển động. Các biến thể GRU được huấn luyện lại trên 493, 553, 625 và 584 cửa sổ Train tương ứng với 30+gián đoạn, 20, 10 và 20+gián đoạn. Thay đổi độ che phủ cũng thay đổi dữ liệu train, nên kết quả mô tả cả pipeline chứ chưa tách riêng ảnh hưởng độ dài với lượng dữ liệu.

GRU 20 gián đoạn ngắn bỏ sót ngã trước, trái và phải ở subject 6. Báo giả xuất hiện ở ngồi xuống, cúi nhặt đồ và đi bộ. Có thêm một clip Fall phát cảnh báo trước onset. Theo điều kiện tạo cửa sổ gán nhãn, biến thể này chỉ khôi phục được cửa sổ cho 1/3 clip ngã trước của Validation. Lượt quét theo thời gian phát hiện 2/3 nhờ đo ở mức sự kiện sau khi quét toàn bộ clip. Kết quả ở ba người có độ bất định cao và chưa chứng minh khả năng khái quát tại phòng khác.

## Raw Test · kiểm toán nguyên nhân 9/15 Fall trượt preflight

Chỉ tái hiện quy tắc 30 mẫu hiện hành trên chín recording bị loại. Không chạy inference, không thử cửa sổ ngắn hoặc cấu hình pose trên Test. Danh mục raw được ghim bằng SHA-256 `4a33a4bf6d42e6df891fcaeafb5d7231807b5b64b1ce3f4a5d8972970c0d7fd2`.

- **9/9** có cửa sổ phù hợp annotation nếu chỉ xét timeline. **0/9** còn cửa sổ vừa phủ sự kiện vừa đủ pose. Vì vậy mã `INSUFFICIENT_EVENT_OVERLAP` của 8 recording diễn giải là *các cửa sổ đủ pose nằm ngoài vùng đủ điều kiện nhãn*. Chúng có 1–21 cửa sổ đủ pose ở vị trí khác. Clip còn lại không có cửa sổ pose đủ ở bất kỳ vị trí nào.
- Trong 209 mẫu 10 Hz nằm trong các khoảng ngã, **68 mẫu (32,5%)** thiếu pose khả dụng, so với **192/971 (19,8%)** trên toàn bộ chín clip. Cả 68 mẫu thiếu landmark có confidence dương ở lưới 10 Hz. Không thấy trường hợp mất riêng do thiếu điểm neo vai/hông sau khi lưới vẫn còn landmark hoặc do suy biến ở bước chuẩn hóa. CSV gốc cũng có **141/418 frame trong khoảng ngã** với toàn bộ confidence bằng 0. Không thấy gap timestamp gốc lớn hơn 0,25 giây.
- Cửa sổ phù hợp annotation ít thiếu nhất theo từng clip vẫn thiếu **1–16 mẫu**. Chín ca gồm 3 ngã trước, 2 ngã trái, 2 ngã phải, 1 ngã sau và 1 ngã từ tư thế ngồi. Pose CSV xác định được tầng mất tín hiệu. Chưa xác minh được nguyên nhân thị giác như che khuất, góc camera hoặc kích thước người từ CSV.

## Quyết định nghiên cứu

GRU 20 cho phép gián đoạn ngắn là ứng viên phát triển dựa trên F2 theo raw Validation ở threshold cố định. Chưa có cơ sở chọn để release. Bước tiếp theo là bổ sung dữ liệu ngã trước từ subject/môi trường phát triển mới, giảm báo giả trên ADL khó, và đối chiếu MediaPipe Lite với Full trên các frame phát triển có mất landmark. Cần khóa quy tắc phát hiện và chạy một đánh giá độc lập có nhiều subject trước khi kết luận hiệu năng. Không phê duyệt G3, không xuất TFLite và không cập nhật Raspberry Pi.

## Tái lập và hiện vật local

Dùng Python 3.11 và PyTorch CPU 2.6.0. Các checkpoint nghiên cứu và JSON theo recording ở thư mục `../annha-recovery-payutch-v1/pr04-experimental-v2.1-seed42` tính từ repo. `results.json` chứa loss theo epoch, hash checkpoint và kết quả theo cửa sổ; `validation-scan.json` chứa kết quả theo recording và subject; `raw-test-exclusion-diagnostics.json` chỉ chứa kiểm toán loại mẫu. Chạy với thư mục đích mới:

```bash
python scripts/ml/pr04_experiment.py train "$data_root" "$new_output"
python scripts/ml/pr04_experiment.py scan-validation "$data_root" "$new_output"
python scripts/ml/pr04_experiment.py audit-test-exclusions "$data_root" "$new_output/raw-test-exclusion-diagnostics.json"
```

Bộ tests đạt **63/63**, gồm tám ca hồi quy PR-04 về cổng thời gian, đoạn mất pose, thống kê sự kiện và checksum đầu vào. Lượt quét Validation chạy lại từ các checkpoint đã lưu cho cùng toàn bộ kết quả. Sau thí nghiệm, checksum manifest V2.1 và danh mục raw Test khớp với trước khi chạy.
