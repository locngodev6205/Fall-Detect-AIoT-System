# PR-09 · GRU E4-42 trong camera Edge

**Tích hợp PASS. Demo toàn bộ chưa đạt.** Pi phát hiện một Fall đúng thời điểm từ video có nhãn, nhưng vẫn báo nhầm ở clip cúi nhặt đồ. Chưa chạy kịch bản người dùng với webcam. Edge hiện có trên Pi vẫn đang giữ webcam.

## Thay đổi

Edge vẫn mặc định `legacy_tflite`. Khi chọn `gru_e4_42`, adapter dùng kết quả từ một lượt MediaPipe Lite hiện có, 17 keypoint, schema `annha-pose-v2`, grid 10 Hz, cửa sổ 20, stride 3, gap tối đa 3 và EventEngine của GRU. E4-42 được kiểm SHA-256 và warm-up trước khi báo model ready. Lỗi khởi tạo hoặc inference GRU được ghi là `MODEL_UNAVAILABLE`. Web nhận tên model hoặc trạng thái unavailable trên HUD JPEG. GRU dùng callback Fall, evidence và hàng đợi Edge hiện có. Logic theo dõi bất động được dùng lại, không đổi hành vi legacy.

Sửa HTTP 422 ở heartbeat do backend chưa cho phép trường capability `show_landmarks` mà Edge đã gửi. Cùng schema được dùng bởi SQLite và PostgreSQL. Không có migration.

## Kiểm chứng

| Kịch bản | Kết quả | Bằng chứng |
| --- | --- | --- |
| Video Fall `FallLeftS7` qua Edge trên Pi 4 | **PASS** | 1 Fall tại 3,10 s, sau onset 2,36 s là 0,74 s theo timestamp video. Confidence 54,65%, có JPEG tại frame callback. |
| Video No Fall `PickupobjectS9` qua Edge trên Pi 4 | **FAIL** | 2 báo giả ở 3,40 và 8,80 s. Không chỉnh threshold. |
| Fall → backend → WebSocket → lịch sử | **PASS, fixture cục bộ** | Chạy cùng Edge loop và clip trên máy phát triển. 1 Fall tại 3,40 s, HTTP 200, WebSocket nhận đúng ID, 1 bản ghi sau POST retry cùng ID. |
| Camera JPEG và model status | **PASS ở tầng transport** | HUD model do Edge render. JPEG từ Edge được relay nguyên vẹn qua endpoint thiết bị và endpoint xem camera. Heartbeat HTTP 200. Chưa kiểm tra trang bằng trình duyệt. |
| Live bước vào, đi bộ, ngồi/đứng, nhặt đồ, rời/quay lại | **CHƯA CHẠY** | Webcam đang do Edge hiện tại sử dụng. Chưa có phiên camera riêng để đo hoặc đánh giá phát hiện. |

Clip Fall và No Fall trên Pi dùng luồng vision Edge thật và worker hàng đợi, sink nhận cục bộ. Phép thử backend riêng dùng endpoint và WebSocket của AnNhà trên SQLite tạm. Không phát còi, không kết nối ThingsBoard trong runner, không gửi email/Telegram, không ghi video. Cấu hình triển khai hiện tại trên Pi chưa được đổi. Browser UI và full camera live vẫn cần xác minh.

| Pi 4 replay | FallLeftS7 | PickupobjectS9 |
| --- | ---: | ---: |
| Frame / kích thước | 212 / 720×480 | 220 / 720×480 |
| Capture + pose FPS theo wall time, gồm khởi tạo | 5,91 | 6,06 |
| JPEG đưa vào streamer | 201 | 209 |
| Pose p50 | 112,89 ms | 113,07 ms |
| GRU p50 / p95 | 61,34 / 93,33 ms | 62,93 / 85,93 ms |
| Số cửa sổ có score | 28 | 21 |
| CPU tiến trình / RSS đỉnh | 105% / 406 MiB | 104% / 406 MiB |
| Nhiệt đầu / cuối | 74,5 / 79,4 °C | 80,3 / 79,9 °C |
| Model errors / reset timestamp | 0 / 0 | 0 / 0 |

Timestamp file cách 50 ms, 0 gap trên 100 ms. Vì replay dùng timestamp media, con số này không chứng minh camera duy trì được 10 Hz ngoài thực tế. Cần lấy cadence thật ở 640×480. Edge hiện tại vẫn chạy song song khi đo. `vcgencmd get_throttled` ghi `0x80000` trước và sau replay. CPU 100% tương ứng một lõi.

## Chạy trên Pi và rollback

Chuẩn bị checkout PR-09, môi trường Edge có MediaPipe Lite và PyTorch CPU riêng. Giữ checkpoint E4-42 ngoài Git. SHA-256 là `5ef559faee3374f57e240b389ad413c336449f85866b4ef357581abef13bb7ac`. Đặt đường dẫn tuyệt đối và tên output mới.

```bash
# Runner không gửi cảnh báo, không cần thông tin ghép nối.
python scripts/ml/pr09_edge_demo.py "$e4_checkpoint" "$fall_log" --video "$fall_avi"

# Khi webcam rảnh, chạy một lệnh mỗi kịch bản và dùng log riêng.
python scripts/ml/pr09_edge_demo.py "$e4_checkpoint" "$live_log" --camera 0 --seconds 25
```

Đợi `CAMERA READY`. Lần lượt thử bước vào, đi bộ, ngồi rồi đứng, cúi nhặt đồ, rời rồi quay lại. Chờ một lần chạy kết thúc trước khi đổi log. Dùng video có nhãn cho ca Fall. Nếu có FP, giữ log. Runner yêu cầu 640×480, ghi kích thước thực tế, timestamp camera, pose FPS, GRU latency, CPU, RSS, nhiệt, reset và model errors. Môi trường backend test trên desktop có thể thêm `--web-probe` để kiểm tra route AnNhà với SQLite tạm.

Để chủ động bật GRU trong Edge đang dùng cho hệ thống, đặt trong `.env.edge` và restart Edge theo cách đang vận hành. Runtime thông thường sử dụng đường gửi cảnh báo thật. Dùng runner trên cho demo yên lặng.

```dotenv
FALL_MODEL_BACKEND=gru_e4_42
FALL_GRU_CHECKPOINT=/absolute/path/to/full-E4-42.pt
FRAME_WIDTH=640
FRAME_HEIGHT=480
```

Rollback bằng `FALL_MODEL_BACKEND=legacy_tflite` rồi restart. Lỗi GRU sẽ không tự chuyển model. Giữ legacy làm mặc định cho tới khi camera live được xác minh và trường hợp nhặt đồ được chấp nhận.

**Tests:** 30 test liên quan đạt, gồm vòng đời Edge với image backend cục bộ mang tag riêng. Kiểm tra thêm bằng replay đầy đủ của Pi và backend fixture. Không commit checkpoint, video, log nhạy cảm hay file cấu hình thật.
