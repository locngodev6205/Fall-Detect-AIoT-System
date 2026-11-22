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
