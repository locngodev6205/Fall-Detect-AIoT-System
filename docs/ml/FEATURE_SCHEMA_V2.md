# PR-02 · Schema đặc trưng annha-pose-v2

Schema gồm 17 khớp MediaPipe theo thứ tự cố định trong `fall_detect/ml/features.py`. Mỗi khớp đóng góp ba giá trị `[x, y, visibility]` dạng `float32`. MediaPipe Pose dùng cấu hình Lite trên cả extractor và Edge. Tọa độ đầu vào theo tỷ lệ chiều rộng và chiều cao ảnh. Khi dữ liệu ở đơn vị pixel, chuyển đổi bằng kích thước ảnh trước khi chuẩn hóa.

Vector lấy tâm hông làm gốc và chia tọa độ cho khoảng cách Euclidean giữa tâm vai và tâm hông. Thiếu cả hai vai hoặc cả hai hông, hoặc chiều dài thân gần 0, tạo mẫu không hợp lệ. Khớp có visibility dưới 0,3 được đánh dấu thiếu. Khung hình thiếu không được dùng để nối hai chuỗi cảnh báo.

Sampler dùng timestamp và lưới 10 Hz. Cửa sổ mặc định gồm 30 mẫu, với 2,9 giây giữa mẫu đầu và cuối. Nội suy chỉ áp dụng giữa hai mẫu cách nhau tối đa 0,25 giây. Dataset bỏ các cửa sổ có mẫu không hợp lệ. Edge xóa bộ đệm ở điểm gián đoạn để khởi động lại cửa sổ.

## Tạo dữ liệu

Chuẩn bị `train`, `val` và `test` theo video gốc trước khi tạo cửa sổ. Mỗi thư mục đầu vào có `Fall/Raw_Video` và `No_Fall/Raw_Video`. Ví dụ chạy từ thư mục repository cho split train.

```bash
python fall_detect/utils/extract_keypoint.py --canonical --dataset /path/to/raw/train
python fall_detect/utils/process_csv_data.py --canonical --dataset /path/to/raw/train --output /path/to/annha-pose-v2/train
```

Lặp lại cho val và test. Dùng `fall_detect/utils/timesteps60/create_seq.py --canonical` khi cần cửa sổ 60 mẫu. Extractor tạo `Keypoints_CSV_v2` có sidecar ghi timestamp, FPS, kích thước ảnh, phiên bản MediaPipe và SHA-256 nguồn. NPY chứa khớp đã lấy mẫu nhưng chưa chuẩn hóa. Mỗi split có `feature_schema.json` mô tả schema và nhóm video theo hash.

Notebook `01_huan_luyen_transformer_fall_detection_aug.ipynb` đọc các split này. Khi chạy trên Kaggle, đặt `ANNHA_REPO_ROOT` thành đường dẫn bản checkout có module dùng chung. Notebook kiểm tra schema và video trùng hash giữa các split, dùng cửa sổ gốc để đánh giá chéo theo nhóm video, và chỉ augment dữ liệu cho lượt huấn luyện cuối. Việc kiểm tra trùng người hoặc video đã mã hóa lại vẫn cần metadata nguồn.

## Tương thích model

TFLite cũ tiếp tục dùng pipeline legacy. Model huấn luyện bằng schema v2 dùng tệp tên mới và sidecar `<tên-model>.manifest.json` chứa `feature_schema_version`, `sample_rate_hz`, `window_size`, `sha256` và `fall_threshold`. Chỉ dùng model v2 sau khi huấn luyện và đánh giá riêng. PR-02 không xuất model mới.
