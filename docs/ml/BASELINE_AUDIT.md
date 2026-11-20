# PR-01 · Audit baseline nhận diện té ngã

PR-01 giữ nguyên weights, dữ liệu, preprocessing và ngưỡng cấu hình hiện tại. Nhánh local `fix/fall-detection-reliability` được tạo từ checkout tích hợp tại `567fcd12d9127aad1dcb36a84bac600bf0c41e9e` để giữ các thay đổi Edge/VNC/MQTT đang có. `origin/main` đang được tham chiếu ở `f16e2d672a0b27ec36da281f1d91a85002d3dd00`.

Đã rà cấu trúc backend Python SQLite/PostgreSQL, frontend React, Edge, firmware Arduino, Docker, ThingsBoard, script và tài liệu. Audit sâu tập trung vào đường chạy `detect.py` và `run_edge.sh → edge.main_edge`, detector, notifier, API ingest sự kiện, cấu hình, script tạo dataset và notebook liên quan.

## Model đã đọc bằng TFLite Runtime 2.14.0

| Tệp | Bytes | SHA-256 | Nguồn checkpoint |
| --- | ---: | --- | --- |
| `fall_detect/models/fall_detection_transformer.tflite` | 320.912 | `c66659c3ac6d37c60469bee4d6f88cb2ac4976928bde6d46b19e7f851e8980b0` | UNKNOWN_PROVENANCE |
| `notebooks/results/fall_detection_transformer.tflite` | 469.788 | `3349de9f88dbcf4119c5754e76a228b89cc31d763d013fe145f3bf32e4ea4b9d` | UNKNOWN_PROVENANCE. Khớp hash bản trong ZIP do kế hoạch ghi, chưa xác minh được run export |

Hai model có input float32 `[1,30,51]` và output float32 `[1,1]`. Tập toán tử giống nhau: ADD, BATCH_MATMUL, FULLY_CONNECTED, LOGISTIC, MEAN, MUL, NEG, RESHAPE, RSQRT, SOFTMAX, SQUARED_DIFFERENCE, TRANSPOSE. Hash khác nhau nên không thể chuyển kết quả đánh giá từ tệp này sang tệp kia.

Môi trường kiểm thử local dùng Python 3.11.18, NumPy 1.26.4, MediaPipe 0.10.14 và OpenCV 4.11. Edge production khai báo TFLite 2.14.0 trong `fall_detect/requirements.txt`. Không có bằng chứng về checkpoint, split hash và ngưỡng calibration gắn với cả hai artifact. Số đã cung cấp là sequence-level: Test TP 1092, TN 1181, FP 165, FN 134. Các số này không dùng để chỉnh ngưỡng PR-01.

## Trạng thái

| Hạng mục | Kết quả |
| --- | --- |
| R01 callback | FIXED. Edge và detector dùng hợp đồng hai đối số đang có, tương thích notifier của `detect.py`. Regression trước sửa ghi `Prediction Error: callback regression`; sau sửa giữ kết quả FALL và áp dụng cooldown bằng đồng hồ monotonic |
| Gửi backend khi mất mạng | FIXED khi tiến trình còn chạy. Còi local được xử lý độc lập trước HTTP, hàng đợi giới hạn, retry cùng ID và timestamp. Backend SQLite/PostgreSQL hiện dedup theo camera và event ID |
| Model lỗi | FIXED cho thiếu file, hash sai khi có manifest, dtype/shape sai và lỗi probe. Camera còn hoạt động có thể tiếp tục phát hình và bám người. Mất camera chuyển lỗi và thử mở lại, HUD chỉ dùng khi bật mock rõ ràng |
| R08/R12 ngưỡng và provenance | UNVERIFIED. Nếu có sidecar `<tên-model>.manifest.json`, kiểm tra `sha256` và dùng `fall_threshold` đi kèm. Nếu thiếu, log hash và dùng ngưỡng legacy từ cấu hình (mặc định 0,85), không chứng nhận production |
| R02/R05/R06 | CONFIRMED ở mã legacy bằng fixture tổng hợp. Xem audit dataset. Chưa quy kết cho dữ liệu thực đã tạo model |
| R03/R04 | CONFIRMED rủi ro ở cách split/CV có trong mã. Overlap thực tế chưa xác minh |
| R07/R09/R10/R11 | Hành vi và khác biệt pipeline đã ghi nhận. Tác động định lượng chưa xác minh, để ngoài PR-01 |

Hàng đợi nằm trong RAM. Tắt tiến trình hoặc mất điện có thể mất sự kiện chưa gửi. Hàng đợi đầy có log lỗi. Ảnh bằng chứng được thử tải sau ACK sự kiện, chưa có retry ảnh riêng. Chưa đo latency hoặc phát còi thật trên Pi trong PR-01.
