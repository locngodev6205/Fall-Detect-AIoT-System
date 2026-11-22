# AnNhà · Accuracy-first Fall Detection

## Kết luận thực nghiệm

CTR-GCN nhỏ là ứng viên nghiên cứu vì tăng Recall trên Validation. Giữ E4-42 làm đối chứng và giữ nguyên Edge/Pi. CTR-GCN pilot tăng FP, vẫn bỏ sót ngã về trước và chưa có bằng chứng ngoài CAUCAFall hay ca live người vừa bước vào.

## Audit upstream

Snapshot `dada2669566897ac0432d681c0898bb6208938a2` có kiến trúc CTR-GCN COCO-17, mã ERM/SWAD, CLI train/predict và fold split theo miền. Detector RTMDet-m và RTMPose-m xuất tọa độ và confidence. Window 64 mẫu ở 15 Hz (~4,27 s), stride 32. MIL tổng hợp hai logit cao nhất toàn video. Muốn dùng online cần phát từng score khi cửa sổ kết thúc, chấm theo thời điểm arrival, dùng nhãn temporal hoặc quy trình hiệu chỉnh source-only. Dùng max của toàn clip để quyết định ở đầu clip sẽ đưa thông tin tương lai vào phép đo. [Thiết kế và protocol upstream](https://github.com/Datyth/cross-dataset-fall-detection/blob/dada2669566897ac0432d681c0898bb6208938a2/docs/EVALUATION.md)

Git và Releases công khai không có classifier checkpoint. Pose checkpoint là artifact riêng. Verifier upstream chạy đạt, xác minh hash, split, 12 lượt ERM và 1.560 dự đoán. Macro F1 0,839 ± 0,014 và AP 0,924 ± 0,011 được tính lại từ predictions do tác giả lưu. Không tái suy luận checkpoint gốc. Benchmark 520 recording cần CAUCAFall và Le2i từ mirror đã xử lý, URFD cam0 và GMDCSA-24 v2.1. Các recording gốc AnNhà không mặc nhiên tương đương toàn bộ mirror. Upstream ghi môi trường Python 3.11.18, Torch 2.9.1, CUDA 12.8, RTX PRO 4000 Blackwell và MMCV ops tương thích. Máy hiện tại chạy Torch CPU, không có CUDA GPU. Không tái train cấu hình 4 miền × 3 seed tối đa 150 epoch trong pilot. [Kết quả và artifact upstream](https://github.com/Datyth/cross-dataset-fall-detection/tree/dada2669566897ac0432d681c0898bb6208938a2/benchmarks/erm)

CTR-GCN kế thừa CC BY-NC 4.0, SWAD có MIT riêng, không có license MIT áp dụng chung. Hai script AnNhà import upstream từ checkout ngoài Git. RTMLib dùng Apache-2.0. [Thông báo upstream](https://github.com/Datyth/cross-dataset-fall-detection/blob/dada2669566897ac0432d681c0898bb6208938a2/THIRD_PARTY_NOTICES.md) · [RTMLib](https://github.com/Tau-J/rtmlib)

## Pilot CTR-GCN trên dữ liệu thật

Kế thừa PR-03 V2.1, audit group/subject/hash và annotation temporal. Dùng đúng 584 cửa sổ từ 50 recording Train. Validation raw gồm 29 recording CAUCAFall thuộc ba subject giữ riêng. Tập khóa giữ nguyên. Dùng cùng pose CSV, chuẩn hóa annha-pose-v2 và Stream 20/3/gap-3 của E4-42. Candidate dùng graph upstream thu nhỏ width 8, 33.691 tham số, BCE theo nhãn cửa sổ có căn cứ temporal, cân trọng số theo lớp và recording, 12 epoch, seed 42, threshold cố định 0,5. Train khoảng 83 s trên CPU. Đây là pilot khác cấu hình 64/32 và video MIL của tác giả. Không đưa RTMPose vào baseline hoặc pilot này.

| Model | TP / FP / FN | Event Recall | Event Precision | F2 | Trễ p50 | Wall replay 29 clip pose CSV |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| GRU E4-42 | 10 / 8 / 5 | 66,7% | 55,6% | 0,641 | 1,65 s | 2,81 s |
| CTR-GCN pilot | 12 / 12 / 3 | 80,0% | 50,0% | 0,714 | 1,10 s | 16,05 s |

Protocol PR-08 khớp lần báo đầu tiên trong vùng onset đến min(onset+3 s, end+1 s). Tính FP cả lần sớm, muộn, trùng và báo trên No Fall. Hai model không có duplicate trong vùng match. Candidate cứu được FallBackwardsS6, FallBackwardsS7, FallLeftS6, nhưng bỏ sót thêm FallForwardS9 và vẫn bỏ sót FallForwardS6, FallRightS6. PickupobjectS9 giảm từ hai lần báo xuống một. Không suy ra false alarms/hour ngoài thực địa từ clip hoạt động ngắn. Chưa đo cross-dataset vì Validation chỉ CAUCAFall và baseline từng train trên URFD. Cần miền và subject chưa dùng, cùng ADL liên tục đủ dài, để đánh giá ngoài mẫu. Trễ là video timestamp ở các TP, không phải độ trễ mạng hoặc camera.

PR-04/05 cho baseline và kiểm tra missing pose, streaming và ca cúi. PR-06/07 đánh giá pretrained FallTCN và BiLSTM với policy khác nhau. PR-08 loại motion gate do mất Recall và retrain pick-up do không thay đổi kết quả. Không chạy lại các thí nghiệm đó.

## Tái lập

Giữ data, output, upstream và trọng số ngoài Git. Dùng Python 3.11, Torch CPU 2.6.0, MediaPipe 0.10.14, OpenCV 4.11, RTMLib 0.0.16, ONNX Runtime 1.32.0 và tqdm. Legacy MediaPipe cần pose landmark Lite asset. Tải hai artifact ONNX của preset balanced, giải nén rồi truyền đường dẫn vào CLI. ONNX SHA-256 detector `3dea6513388889f0fff4b77bf7a26013600321b9eb9ceb0e9a400a82572f5f23`, pose `5c0a4bf67953e6d2ac43ce15e77dc9d5d354ae18430a47d2c5963a7bc5683e3c`. [URL trọng số trong RTMLib](https://github.com/Tau-J/rtmlib/blob/main/rtmlib/tools/solution/body.py)

```bash
git clone https://github.com/Datyth/cross-dataset-fall-detection.git "$upstream"
git -C "$upstream" checkout --detach dada2669566897ac0432d681c0898bb6208938a2
python scripts/ml/accuracy_pose.py lite "$dataset_v21" "$out/lite.json"
python scripts/ml/accuracy_pose.py rtmpose "$dataset_v21" "$out/rtm.json" \
  --detector "$yolox_onnx" --pose "$rtmpose_onnx"
python scripts/ml/accuracy_ctr_gcn.py "$upstream" "$dataset_v21" "$e4_checkpoint" "$out/ctr.json"
```

## Pose benchmark hoàn tất · DEVELOPMENT

Dùng đủ 1.578 frame của đúng bảy AVI CAUCAFall đã ghim SHA-256. FFprobe xác nhận 720×480, cùng thứ tự frame, 20 FPS và số frame trùng từng file. Hai extractor dùng cùng đường decode, không bỏ frame hay đổi kích thước video đầu vào. RTMPose sử dụng resize nội bộ của YOLOX-m và crop người lớn nhất cho RTMPose-m qua ONNX CPU. Cấu hình này khác detector RTMDet-m và tracking của Datyth. Cả hai lượt hoàn tất hết frame, không có exception inference. Không kiểm tra tọa độ từng khớp bằng ground truth.

Pose dùng được nếu qua cùng cổng hình học annha-pose-v2. Missing joints đếm điểm có score <0,3, kể cả frame không có người. Bình quân toàn clip **1.215/1.578 → 1.530/1.578** (77,0% → 97,0%). Trong Fall **213/315 → 283/315** (67,6% → 89,8%), thiếu 102 → 32 frame. Sau Fall hai giây **200/240 → 236/240**. Ba ca S6 có mất pose được cải thiện, mạnh nhất ở ngã phải S6, với 40/40 frame pose hợp lệ sau ngã so với 0/40 trước đó. Góc thân chiếu 2D ngang có đủ bốn điểm vai/hông ở 80 → 160 frame sau Fall, gồm 0 → 40 ở ngã phải S6. Đây là proxy cho thân ngang và tracking còn hoạt động, không xác minh tư thế hoặc danh tính bằng nhãn thủ công. Ngã trái S7 bị giảm coverage, còn ngã sau S6/S7 có pose đầy đủ từ Lite, nên cải thiện extractor không giải thích hoặc khắc phục mọi FN.

MediaPipe xuất visibility, RTMPose xuất score SimCC. Cùng cutoff giúp đối chiếu dưới cổng cố định, hai giá trị chưa được calibrate như xác suất tương đương. Ví dụ median toàn clip FallRightS6 là 0,000 Lite và 0,710 RTMPose, trong khi FallBackwardsS7 là 0,998 và 0,689 dù cả hai có 252/252 pose dùng được. Đọc kết quả cùng số frame chứ không xếp hạng trực tiếp bằng median score. FPS desktop RTMPose 0,99–1,47, Lite 20,81–25,30. Các lúc đo chạy tách tiến trình, một phần có tải training nền. RSS là peak tích lũy theo tiến trình, không phải spike riêng từng recording. Chưa đo Pi. Không đưa RTMPose vào checkpoint GRU hoặc CTR-GCN đã huấn luyện.

## Phân tích lỗi và một thí nghiệm có mục tiêu · DEVELOPMENT

- Pilot và GRU cùng phát hiện đúng 9 Fall. Pilot cứu được ngã sau S6 ở 3,40 s, ngã trái S6 ở 1,90 s và ngã sau S7 ở 3,70 s. GRU phát hiện ngã trước S9 còn pilot bỏ sót, nên chênh lệch ròng là +2 TP. Cùng bỏ sót ngã trước S6 (không có score đúng vùng), ngã phải S6 (pose đứt và score thấp).
- FP ròng +4 gồm **+3 trên ADL** và **+1 ngoài vùng Fall**. ADL tăng 4 alert ở ngồi xuống (0→2 S6, 1→1 S7 đổi timestamp, 0→2 S9) và 1 ở quỳ S7. Giảm một ở đi bộ S7 và một ở nhặt đồ S9. Trên clip Fall, cảnh báo muộn tăng từ 3 lên 5 và sớm giảm từ 1 xuống 0. Thời điểm chi tiết ở bảng bên dưới.
- Giả thuyết thử một lần: tăng đóng góp của ngồi xuống và quỳ để phân biệt chuyển động hạ thấp người với Fall. Gấp đôi trọng số tương đối của 8 recording ADL đã xác minh thuộc bốn subject Train, giữ nguyên tổng trọng số mỗi lớp. Không đưa Validation vào Train, không chọn threshold hoặc epoch theo Validation. Công thức cố định 2× và 12 epoch. Validation đã được dùng để hình thành giả thuyết nên các số sau chỉ dùng chẩn đoán phát triển. Không thử tiếp nhiều cấu hình trên tập này.

| Model | TP/FP/FN | Recall | Precision | F2 | Trễ p50 |
| --- | ---: | ---: | ---: | ---: | ---: |
| E4-42 | 10/8/5 | 66,7% | 55,6% | 0,641 | 1,65 s |
| CTR-GCN pilot | 12/12/3 | 80,0% | 50,0% | 0,714 | 1,10 s |
| CTR-GCN hard negatives | 10/5/5 | 66,7% | 66,7% | 0,667 | 1,03 s |

Hard-negative giảm 7 FP so với CTR-GCN pilot nhưng mất lợi thế Recall. Vẫn nhận ra ba ca mà GRU bỏ sót, đồng thời mất thêm ngã trước S7 và ngã từ tư thế ngồi S9. Còn bốn báo giả ở ngồi xuống và một cảnh báo ngã muộn. Không chọn variant này. Chỉ chạy một seed 42 mỗi cấu hình. Không có exposure ADL liên tục hoặc cohort mới độc lập để báo false alarms/hour, biến thiên seed hay kết quả ngoài mẫu đáng tin cậy. Test khóa chưa mở.

## Quyết định

**Chưa đưa CTR-GCN vào đánh giá cuối hay benchmark Pi 4.** Trước tiên cần trích RTMPose nhất quán cho Train và cohort phát triển độc lập, huấn luyện lại với đúng joint coordinates và confidence của nó, rồi xác minh trên subject hoặc nguồn chưa dùng để chỉnh cấu hình, gồm ngã sớm và ADL liên tục. Chỉ khi giữ được lợi thế Recall và mức báo giả chấp nhận được mới đo một pipeline causal có detector nhẹ hơn trên Pi, cùng FPS capture/pose, tỷ lệ gián đoạn, RAM, nhiệt và trễ camera tới event. Giữ E4-42 đang chạy.

Thêm `--hard-negatives` vào lệnh train ở trên để tái lập variant. Các score theo từng timestamp và alert có trong JSON runner. Dùng `accuracy_compare.py` để tái tạo bảng, trong đó score có dạng peak@giây, tiếp theo là các đoạn vượt 0,5. Khoảng trống score cắt một đoạn. Pose ADL tính trên cả clip, Fall dùng hai giây trước/sau và khoảng đã gán nhãn.

### CTR-GCN pilot và GRU

| Recording | Hành động | Fall interval (s) | Pose trước / trong / sau hoặc cả clip ADL | Match GRU → CTR | Alert GRU → CTR (s) | Score GRU | Score CTR |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PickupobjectS6 | Pick up object | — | 107/202 | 0/0/0 → 0/0/0 | — → — | 0.036@9.70; — | 0.022@1.90; — |
| SitDownS6 | Sit down | — | 162/189 | 0/0/0 → 0/2/0 | — → 6.10; 8.80 | 0.076@9.40; — | 0.988@8.80; 6.10–6.10, 8.80–9.40 |
| KneelS7 | Kneel | — | 182/202 | 0/0/0 → 0/1/0 | — → 9.70 | 0.110@2.80; — | 0.936@10.00; 9.70–10.00 |
| PickupobjectS7 | Pick up object | — | 142/153 | 0/0/0 → 0/0/0 | — → — | 0.118@2.80; — | 0.360@2.80; — |
| SitDownS7 | Sit down | — | 192/193 | 0/1/0 → 0/1/0 | 6.70 → 4.00 | 0.969@7.00; 6.70–8.50 | 0.662@4.00; 4.00–4.00 |
| KneelS9 | Kneel | — | 214/216 | 0/0/0 → 0/0/0 | — → — | 0.037@10.00; — | 0.021@3.10; — |
| PickupobjectS9 | Pick up object | — | 203/220 | 0/2/0 → 0/1/0 | 3.40; 7.90 → 7.60 | 0.980@8.50; 3.40–4.00, 7.90–9.40 | 0.990@7.60; 7.60–9.10 |
| SitDownS9 | Sit down | — | 216/238 | 0/0/0 → 0/2/0 | — → 6.70; 11.80 | 0.062@11.80; — | 0.985@6.70; 6.70–7.00, 11.80–11.80 |
| FallBackwardsS6 | Fall backwards | 2.22–5.92 | 40/40 / 74/74 / 40/40 | 0/1/1 → 1/1/0 | 6.10 → 3.40; 10.30 | 0.989@7.90; 6.10–11.50 | 0.997@4.60; 3.40–5.50, 10.30–11.50 |
| FallForwardS6 | Fall forward | 2.36–5.20 | 8/40 / 24/56 / 40/40 | 0/1/1 → 0/0/1 | 6.70 → — | 0.596@7.90; 6.70–10.00 | 0.025@6.70; — |
| FallLeftS6 | Fall left | 1.08–3.64 | 22/22 / 19/51 / 40/40 | 0/0/1 → 1/0/0 | — → 1.90 | 0.166@1.90; — | 0.985@1.90; 1.90–1.90 |
| FallRightS6 | Fall right | 2.90–5.12 | 40/40 / 11/45 / 0/40 | 0/0/1 → 0/0/1 | — → — | 0.023@2.20; — | 0.294@3.40; — |
| FallSittingS6 | Fall sitting | 2.98–6.02 | 38/40 / 60/61 / 40/40 | 1/0/0 → 1/1/0 | 5.20 → 4.00; 7.00 | 0.972@10.00; 5.20–12.10 | 0.999@4.30; 4.00–4.60, 7.00–7.00 |
| HopS6 | Hop | — | 135/162 | 0/0/0 → 0/0/0 | — → — | 0.030@7.90; — | 0.032@7.90; — |
| WalkS6 | Walk | — | 265/266 | 0/0/0 → 0/0/0 | — → — | 0.049@10.60; — | 0.468@6.40; — |
| FallBackwardsS7 | Fall backwards | 3.09–5.55 | 40/40 / 49/49 / 40/40 | 0/1/1 → 1/0/0 | 2.80 → 3.70 | 0.994@4.90; 2.80–12.40 | 0.998@4.60; 3.70–5.50 |
| FallForwardS7 | Fall forward | 0.78–2.64 | 10/16 / 32/37 / 39/40 | 1/0/0 → 1/0/0 | 2.50 → 2.50 | 0.881@6.70; 2.50–3.10, 4.00–4.90, 5.50–7.90 | 0.693@2.80; 2.50–2.80 |
| FallLeftS7 | Fall left | 2.36–4.38 | 40/40 / 36/40 / 40/40 | 1/0/0 → 1/0/0 | 3.40 → 3.70 | 0.988@8.80; 3.40–4.60, 5.20–10.30 | 0.805@3.70; 3.70–3.70 |
| FallRightS7 | Fall right | 1.03–3.09 | 21/21 / 40/41 / 40/40 | 1/0/0 → 1/0/0 | 2.50 → 1.90 | 0.991@3.10; 2.50–8.20 | 0.999@2.50; 1.90–3.70 |
| FallSittingS7 | Fall sitting | 1.08–4.16 | 14/22 / 62/62 / 40/40 | 1/0/0 → 1/2/0 | 3.70 → 2.50; 6.70; 10.30 | 0.992@8.50; 3.70–10.30 | 0.999@2.50; 2.50–4.60, 6.70–8.80, 10.30–10.30 |
| HopS7 | Hop | — | 187/198 | 0/0/0 → 0/0/0 | — → — | 0.051@9.40; — | 0.077@8.80; — |
| WalkS7 | Walk | — | 193/193 | 0/1/0 → 0/0/0 | 1.90 → — | 0.919@2.50; 1.90–3.10 | 0.138@9.40; — |
| FallBackwardsS9 | Fall backwards | 1.66–5.08 | 34/34 / 60/68 / 40/40 | 1/0/0 → 1/1/0 | 3.70 → 2.50; 6.70 | 0.991@11.20; 3.70–3.70, 6.10–12.40 | 0.974@7.60; 2.50–3.70, 6.70–8.80 |
| FallForwardS9 | Fall forward | 1.25–3.45 | 1/25 / 39/44 / 40/40 | 1/0/0 → 0/0/1 | 4.00 → — | 0.663@6.40; 4.00–7.30 | 0.059@4.30; — |
| FallLeftS9 | Fall left | 0.92–4.32 | 13/19 / 63/68 / 40/40 | 1/0/0 → 1/0/0 | 2.50 → 2.50 | 0.982@2.80; 2.50–2.80, 3.70–10.30 | 0.966@2.50; 2.50–2.80, 3.70–3.70 |
| FallRightS9 | Fall right | 1.50–3.56 | 21/30 / 42/42 / 39/40 | 1/0/0 → 1/0/0 | 2.50 → 2.50 | 0.930@3.10; 2.50–9.40 | 0.947@2.50; 2.50–3.70 |
| FallSittingS9 | Fall sitting | 1.54–5.00 | 31/31 / 69/69 / 40/40 | 1/1/0 → 1/0/0 | 3.10; 5.20 → 2.80 | 0.949@7.30; 3.10–4.30, 4.90–10.60 | 0.772@3.40; 2.80–2.80, 3.40–3.40 |
| HopS9 | Hop | — | 210/212 | 0/0/0 → 0/0/0 | — → — | 0.028@7.00; — | 0.032@7.00; — |
| WalkS9 | Walk | — | 200/234 | 0/0/0 → 0/0/0 | — → — | 0.368@11.20; — | 0.089@10.90; — |

| Hành động / Subject | GRU TP/FP/FN | CTR TP/FP/FN |
| --- | --- | --- |
| Fall backwards | 1/2/2 | 3/2/0 |
| Fall forward | 2/1/1 | 1/0/2 |
| Fall left | 2/0/1 | 3/0/0 |
| Fall right | 2/0/1 | 2/0/1 |
| Fall sitting | 3/1/0 | 3/3/0 |
| Hop | 0/0/0 | 0/0/0 |
| Kneel | 0/0/0 | 0/1/0 |
| Pick up object | 0/2/0 | 0/1/0 |
| Sit down | 0/1/0 | 0/5/0 |
| Subject 6 | 1/2/4 | 3/4/2 |
| Subject 7 | 4/3/1 | 5/4/0 |
| Subject 9 | 5/3/0 | 4/4/1 |
| Walk | 0/1/0 | 0/0/0 |

### CTR-GCN hard-negative và GRU

| Recording | Hành động | Fall interval (s) | Pose trước / trong / sau hoặc cả clip ADL | Match GRU → CTR | Alert GRU → CTR (s) | Score GRU | Score CTR |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PickupobjectS6 | Pick up object | — | 107/202 | 0/0/0 → 0/0/0 | — → — | 0.036@9.70; — | 0.023@10.00; — |
| SitDownS6 | Sit down | — | 162/189 | 0/0/0 → 0/2/0 | — → 6.10; 9.10 | 0.076@9.40; — | 0.880@6.10; 6.10–6.10, 9.10–9.40 |
| KneelS7 | Kneel | — | 182/202 | 0/0/0 → 0/0/0 | — → — | 0.110@2.80; — | 0.295@10.00; — |
| PickupobjectS7 | Pick up object | — | 142/153 | 0/0/0 → 0/0/0 | — → — | 0.118@2.80; — | 0.085@2.80; — |
| SitDownS7 | Sit down | — | 192/193 | 0/1/0 → 0/1/0 | 6.70 → 3.70 | 0.969@7.00; 6.70–8.50 | 0.892@4.00; 3.70–4.30 |
| KneelS9 | Kneel | — | 214/216 | 0/0/0 → 0/0/0 | — → — | 0.037@10.00; — | 0.015@9.70; — |
| PickupobjectS9 | Pick up object | — | 203/220 | 0/2/0 → 0/0/0 | 3.40; 7.90 → — | 0.980@8.50; 3.40–4.00, 7.90–9.40 | 0.179@6.70; — |
| SitDownS9 | Sit down | — | 216/238 | 0/0/0 → 0/1/0 | — → 6.70 | 0.062@11.80; — | 0.723@6.70; 6.70–6.70 |
| FallBackwardsS6 | Fall backwards | 2.22–5.92 | 40/40 / 74/74 / 40/40 | 0/1/1 → 1/1/0 | 6.10 → 4.60; 10.60 | 0.989@7.90; 6.10–11.50 | 0.867@4.90; 4.60–5.20, 10.60–10.90 |
| FallForwardS6 | Fall forward | 2.36–5.20 | 8/40 / 24/56 / 40/40 | 0/1/1 → 0/0/1 | 6.70 → — | 0.596@7.90; 6.70–10.00 | 0.017@9.10; — |
| FallLeftS6 | Fall left | 1.08–3.64 | 22/22 / 19/51 / 40/40 | 0/0/1 → 1/0/0 | — → 1.90 | 0.166@1.90; — | 0.990@1.90; 1.90–1.90 |
| FallRightS6 | Fall right | 2.90–5.12 | 40/40 / 11/45 / 0/40 | 0/0/1 → 0/0/1 | — → — | 0.023@2.20; — | 0.039@3.40; — |
| FallSittingS6 | Fall sitting | 2.98–6.02 | 38/40 / 60/61 / 40/40 | 1/0/0 → 1/0/0 | 5.20 → 4.00 | 0.972@10.00; 5.20–12.10 | 0.996@4.30; 4.00–4.90 |
| HopS6 | Hop | — | 135/162 | 0/0/0 → 0/0/0 | — → — | 0.030@7.90; — | 0.061@7.90; — |
| WalkS6 | Walk | — | 265/266 | 0/0/0 → 0/0/0 | — → — | 0.049@10.60; — | 0.431@6.40; — |
| FallBackwardsS7 | Fall backwards | 3.09–5.55 | 40/40 / 49/49 / 40/40 | 0/1/1 → 1/0/0 | 2.80 → 3.70 | 0.994@4.90; 2.80–12.40 | 0.996@4.60; 3.70–5.20 |
| FallForwardS7 | Fall forward | 0.78–2.64 | 10/16 / 32/37 / 39/40 | 1/0/0 → 0/0/1 | 2.50 → — | 0.881@6.70; 2.50–3.10, 4.00–4.90, 5.50–7.90 | 0.079@2.80; — |
| FallLeftS7 | Fall left | 2.36–4.38 | 40/40 / 36/40 / 40/40 | 1/0/0 → 1/0/0 | 3.40 → 3.40 | 0.988@8.80; 3.40–4.60, 5.20–10.30 | 0.915@3.40; 3.40–3.70 |
| FallRightS7 | Fall right | 1.03–3.09 | 21/21 / 40/41 / 40/40 | 1/0/0 → 1/0/0 | 2.50 → 2.20 | 0.991@3.10; 2.50–8.20 | 0.997@2.50; 2.20–3.40 |
| FallSittingS7 | Fall sitting | 1.08–4.16 | 14/22 / 62/62 / 40/40 | 1/0/0 → 1/0/0 | 3.70 → 2.50 | 0.992@8.50; 3.70–10.30 | 0.959@2.50; 2.50–3.10 |
| HopS7 | Hop | — | 187/198 | 0/0/0 → 0/0/0 | — → — | 0.051@9.40; — | 0.250@3.70; — |
| WalkS7 | Walk | — | 193/193 | 0/1/0 → 0/0/0 | 1.90 → — | 0.919@2.50; 1.90–3.10 | 0.477@1.90; — |
| FallBackwardsS9 | Fall backwards | 1.66–5.08 | 34/34 / 60/68 / 40/40 | 1/0/0 → 1/0/0 | 3.70 → 2.20 | 0.991@11.20; 3.70–3.70, 6.10–12.40 | 0.867@2.50; 2.20–2.80, 3.70–3.70 |
| FallForwardS9 | Fall forward | 1.25–3.45 | 1/25 / 39/44 / 40/40 | 1/0/0 → 0/0/1 | 4.00 → — | 0.663@6.40; 4.00–7.30 | 0.063@3.70; — |
| FallLeftS9 | Fall left | 0.92–4.32 | 13/19 / 63/68 / 40/40 | 1/0/0 → 1/0/0 | 2.50 → 2.50 | 0.982@2.80; 2.50–2.80, 3.70–10.30 | 0.982@2.80; 2.50–2.80 |
| FallRightS9 | Fall right | 1.50–3.56 | 21/30 / 42/42 / 39/40 | 1/0/0 → 1/0/0 | 2.50 → 2.50 | 0.930@3.10; 2.50–9.40 | 0.950@2.50; 2.50–4.00 |
| FallSittingS9 | Fall sitting | 1.54–5.00 | 31/31 / 69/69 / 40/40 | 1/1/0 → 0/0/1 | 3.10; 5.20 → — | 0.949@7.30; 3.10–4.30, 4.90–10.60 | 0.301@3.10; — |
| HopS9 | Hop | — | 210/212 | 0/0/0 → 0/0/0 | — → — | 0.028@7.00; — | 0.094@6.40; — |
| WalkS9 | Walk | — | 200/234 | 0/0/0 → 0/0/0 | — → — | 0.368@11.20; — | 0.387@8.80; — |

| Hành động / Subject | GRU TP/FP/FN | CTR TP/FP/FN |
| --- | --- | --- |
| Fall backwards | 1/2/2 | 3/1/0 |
| Fall forward | 2/1/1 | 0/0/3 |
| Fall left | 2/0/1 | 3/0/0 |
| Fall right | 2/0/1 | 2/0/1 |
| Fall sitting | 3/1/0 | 2/0/1 |
| Hop | 0/0/0 | 0/0/0 |
| Kneel | 0/0/0 | 0/0/0 |
| Pick up object | 0/2/0 | 0/0/0 |
| Sit down | 0/1/0 | 0/4/0 |
| Subject 6 | 1/2/4 | 3/3/2 |
| Subject 7 | 4/3/1 | 4/1/1 |
| Subject 9 | 5/3/0 | 3/1/2 |
| Walk | 0/1/0 | 0/0/0 |

### Pose Lite → RTMPose

| Recording | Pose toàn clip | Pose trong Fall | Pose sau Fall | Missing joints toàn clip | Dropout dài nhất trong Fall | FPS | p50 ms | Peak RSS MiB |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FallForwardS6 | 130/202 → 201/202 | 24/56 → 55/56 | 40/40 → 40/40 | 1233 → 27 | 18 → 1 | 25.30 → 0.99 | 32.62 → 930.03 | 300.74 → 512.70 |
| FallLeftS6 | 120/229 → 222/229 | 19/51 → 44/51 | 40/40 → 40/40 | 1907 → 145 | 32 → 4 | 21.54 → 1.17 | 42.50 → 836.58 | 362.52 → 513.95 |
| FallRightS6 | 69/229 → 227/229 | 11/45 → 45/45 | 0/40 → 40/40 | 2735 → 35 | 33 → 0 | 21.27 → 1.29 | 43.39 → 730.74 | 415.13 → 514.07 |
| FallBackwardsS6 | 234/234 → 234/234 | 74/74 → 74/74 | 40/40 → 40/40 | 311 → 95 | 0 → 0 | 20.81 → 1.47 | 44.77 → 677.24 | 493.50 → 514.20 |
| FallBackwardsS7 | 252/252 → 252/252 | 49/49 → 49/49 | 40/40 → 40/40 | 119 → 34 | 0 → 0 | 24.08 → 1.42 | 37.68 → 677.06 | 515.50 → 514.32 |
| FallLeftS7 | 207/212 → 174/212 | 36/40 → 16/40 | 40/40 → 36/40 | 186 → 652 | 3 → 16 | 23.96 → 1.33 | 41.07 → 704.40 | 565.50 → 514.32 |
| PickupobjectS9 | 203/220 → 220/220 | — | — | 516 → 24 | — | 22.81 → 1.12 | 40.46 → 867.77 | 565.50 → 514.32 |
