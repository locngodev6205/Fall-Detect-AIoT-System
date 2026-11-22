# PR-08 · Phát hiện sự kiện ngã và kiểm tra demo AnNhà

**Chọn GRU E4-42 + EventEngine hiện có.** Chưa đạt mục tiêu demo đầy đủ. Cổng kiểm chứng chuyển động làm mất quá nhiều Fall. Một lượt retrain ưu tiên clip nhặt đồ không cải thiện chỉ số.

## Chẩn đoán từ 29 recording Validation

Dùng pose CSV V2.1 đã ghim provenance và nhãn thời gian, 15 Fall và 14 No Fall. So sự kiện từ onset đến min(onset + 3 s, end + 1 s), timestamp tại frame đầu vào mà score đã sẵn sàng. Trên clip Fall, mỗi cảnh báo sớm, muộn hoặc lặp sau lần khớp được tính FP. Test khóa giữ nguyên.

| Ca | Bằng chứng | Kết luận |
| --- | --- | --- |
| Nhặt đồ S9 | Hai cảnh báo tại 3,40 và 7,90 s, peak 0,980. PR-05.3 thấy 37/39 frame ở cửa sổ đỉnh có vai và hông đủ visibility. | GRU chấm cao khi cúi, kể cả với pose quan sát được. |
| Ngã trước S6 | Onset 2,36 s, pose hợp lệ 8/40 trước ngã, 24/56 trong ngã, 40/40 sau ngã. Score đầu ở 6,70 s, sau vùng đối chiếu. | Thiếu cửa sổ hợp lệ đúng lúc. |
| Ngã trái / phải S6 | 19/51 và 11/45 frame pose hợp lệ trong ngã. Peak trong vùng lần lượt 0,166 và 0,020. | Đã có score nhưng dưới ngưỡng. Mất pose đồng thời xuất hiện, chưa đủ để xác định quan hệ nhân quả. |
| Ngã sau S6 | Pose trong ngã hợp lệ 74/74. Peak trong vùng 0,348, cảnh báo tại 6,10 s. | Score chưa đủ đúng lúc dù pose sẵn có. |
| Ngã sau S7 | Pose trong ngã hợp lệ 49/49. Cảnh báo ở 2,80 s trước onset 3,09 s. Peak vùng match 0,994 nhưng engine không phát thêm. | Quy tắc khớp timestamp chấm một FP và một FN. |

Warm-up có khoảng cách tối thiểu 1,9 s giữa mẫu đầu và mẫu thứ 20 ở 10 Hz, còn phụ thuộc độ đầy đủ của pose và stride 3. Khi khởi động lại stream 0,5 s trước từng onset có nhãn, baseline bắt được 11/15 và bỏ sót 4/15. Ba clip không có score hợp lệ trong vùng match, một clip có score nhưng không khớp. Đây là stress test bằng cách cắt lịch sử, chưa xác minh một người thực sự đi vào từ ngoài khung.

## So sánh thực nghiệm

| Phương án | TP / FP / FN | Event Recall | Precision | F2 | Trễ p50 | Cảnh báo lặp trong vùng |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| E4-42 baseline | 10 / 8 / 5 | 66,7% | 55,6% | 0,641 | 1,65 s | 0 |
| E4-42 + xác nhận chuyển động | 5 / 0 / 10 | 33,3% | 100% | 0,385 | 1,58 s | 0 |
| GRU retrain tăng trọng số nhặt đồ | 10 / 8 / 5 | 66,7% | 55,6% | 0,641 | 1,79 s | 0 |

Cổng thử nghiệm dùng hông hạ ít nhất 7% chiều cao ảnh so với tư thế đứng trong 0,85 s vừa qua, thân nghiêng từ 35° và GRU score từ 0,5. Tín hiệu dùng tối đa tới thời điểm frame hiện tại, không yêu cầu nằm bất động. Khóa episode tới khi quan sát tư thế đứng và score thấp đủ 0,4 s. Hai cảnh báo nhặt đồ S9 biến mất, nhưng thêm 5 FN. Loại cổng.

Retrain giữ architecture, schema, gap, seed 42 và cùng recipe E4 với 30 epoch. Tăng trọng số gấp đôi cho 4 recording nhặt đồ đã xác minh trong Train, tổng 584 cửa sổ từ 50 recording. Validation và clip demo nằm ngoài Train theo subject. Nhặt đồ S9 vẫn báo hai lần. Dừng sau một lượt. Không xuất checkpoint.

PR-06 là benchmark clip-level của nhóm, còn PR-07 là benchmark event-level trên 10 clip Pi. Kết quả upstream FallTCN/BiLSTM thuộc tập và pipeline của tác giả. Các con số trong bảng trên là PR-08, dùng streaming replay từ CSV chứ chưa đo camera.

## Kịch bản demo và cách chạy

Chạy với checkpoint E4-42 ghim, Python ARM64 và MediaPipe Lite đã chuẩn bị theo PR-07. Dùng đường dẫn file cục bộ và tên output mới.

```bash
python scripts/ml/pr08_replay.py "$e4_checkpoint" "$output" --video "$fall_avi"
python scripts/ml/pr08_replay.py "$e4_checkpoint" "$experiment_json" --data "$dataset_v21" --retrain
```

1. **Vào khung và đi bộ.** Bắt đầu với camera trống, bước vào và đi ngang. Kiểm tra trạng thái và không có alert.
2. **Đi rồi nhặt đồ.** Nhặt đồ và đứng lên. Kiểm tra cả ca nhặt đồ đã biết gây báo giả.
3. **Đi rồi ngồi.** Ngồi ghế rồi đứng dậy.
4. **Đi rồi ngã.** Replay video Fall có annotation qua MediaPipe Lite trên Pi. Đối chiếu timestamp và yêu cầu một event duy nhất. Không yêu cầu diễn ngã thật.
5. **Mất pose.** Rời khung hoặc dùng che khuất an toàn. Kiểm tra suy luận chờ dữ liệu đủ và không phát alert chỉ vì thiếu pose. Kiểm tra reconnect riêng khi được phép dùng camera.

Các clip ADL replay chỉ thay thế một phần động tác live. Test trực tiếp 640×480, người bước vào camera, occlusion và reconnect vẫn cần phiên camera được bố trí trước.

Khi webcam rảnh và đã bố trí phiên thử, dùng `--camera 0 --seconds 45` thay `--video`. Runner yêu cầu 640×480 và ghi kích thước thực tế, số lần reconnect, độ trễ recovery, FPS, CPU, RAM và nhiệt vào JSON. Không lưu ảnh. Không có callback ra ngoài. Test tự động dùng capture giả để kiểm tra reconnect và yêu cầu lại resolution.

## Bằng chứng replay Raspberry Pi 4

Chạy tuần tự bằng MediaPipe Lite trên năm AVI 720×480, nguồn 20 FPS. Edge vẫn chạy và giữ `/dev/video0`. Replay đạt **7,49 FPS**, CPU tiến trình 105% trên thang một lõi, RSS đỉnh 395 MiB, nhiệt cuối clip cao nhất 82,3 °C. `vcgencmd get_throttled` báo `0x80000` trước và sau replay. FPS dưới cadence nguồn, chưa có bằng chứng chạy camera realtime.

| Recording | Số frame | FPS | Inference p50 | Timestamp E4-42 | Timestamp kèm cổng motion |
| --- | ---: | ---: | ---: | --- | --- |
| WalkS7 | 193 | 7,46 | 63,55 ms | 1,90 s | — |
| PickupobjectS6 | 202 | 7,74 | 57,02 ms | — | — |
| SitDownS7 | 193 | 7,42 | 62,55 ms | 6,70 s | — |
| FallLeftS7 | 212 | 7,32 | 64,29 ms | 3,10 s | 3,10 s |
| PickupobjectS9 | 220 | 7,52 | 68,89 ms | 3,40 s, 8,80 s | — |

FallLeftS7 có onset 2,36 s. Cả hai policy phát đúng một event ở 3,10 s, trễ 0,74 s theo media timestamp. E4-42 có bốn cảnh báo giả trên ba clip No Fall nên không đạt acceptance target demo. Tập năm clip chọn để xác minh kịch bản có chủ đích, không dùng để chọn cổng. Kết quả camera live và unplug/replug thực tế còn thiếu.

## Xác minh đường sự kiện và kiểm thử

Dùng output FallLeftS7 thật từ Pi chạy `python scripts/ml/pr08_demo_web_probe.py "$fall_replay_json"`. Probe gửi một FALL qua endpoint thiết bị thật vào SQLite tạm, worker và MQTT tắt. HTTP 200, WebSocket nhận cùng ID, lịch sử xem được đúng một event, retry giữ nguyên ID. Đây là chứng cứ API/WebSocket, chưa mở trang frontend trong browser và chưa nối research engine vào Edge đang vận hành. Vì các cải tiến đều bị loại và baseline chưa đạt demo acceptance, checkpoint mặc định và đường Edge hiện tại được giữ nguyên.

**39 test đạt** gồm 38 test research/Edge và một test API/WebSocket. Không chạy Test khóa, không gửi email/Telegram, không commit video, checkpoint hay dữ liệu thử.
