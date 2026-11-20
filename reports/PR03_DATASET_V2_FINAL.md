# PR-03 · Dataset V2.0

Dataset local nằm tại `../annha-recovery-payutch-v1/verified-expansion-v2/annha-v2.0` tính từ repo. Build ở chế độ official, seed 42, schema `annha-pose-v2`, 17 × 3 features, 10 Hz, 30 mẫu mỗi cửa sổ và stride 3 mẫu. Dataset lưu nguyên các cửa sổ đã kiểm tra. Loader chỉ cho phép augmentation ở Train.

| Tập | Nhóm | Video Fall / No Fall | Cửa sổ Fall / No Fall |
| --- | ---: | ---: | ---: |
| Train | 9 | 6 / 6 | 18 / 51 |
| Validation | 4 | 2 / 2 | 3 / 18 |
| Test | 2 | 1 / 1 | 3 / 5 |
| Tổng | 15 | 9 / 9 | 24 / 74 |

Tỷ lệ thực tế theo video là 66,7% / 22,2% / 11,1% do ràng buộc nhóm. Train chứa 4 video Montréal Fall, 2 URFD Fall và 6 URFD No Fall. Validation và Test đều thuộc URFD. Nguồn Montréal ghi hình RGB 720 × 480 trong môi trường nhiều camera. URFD dùng 640 × 480 RGB camera 0, với các bản ghi ADL được chọn để có hoạt động thường ngày đa dạng trong phạm vi nguồn này. Chưa đo đại diện từng loại hành động hoặc từng môi trường triển khai.

Trong 21 video qua cổng metadata, Montréal mất pose 2.059/6.035 frame (34,12%), URFD mất 354/2.737 frame (12,93%). Ba video bị loại vì không tạo được cửa sổ liên tục. Tính cả bốn khoảng ngã ngắn bị loại trước preflight, tỷ lệ loại của batch là 7/25 (28%). Đây là số đo toàn video của batch, không phải tỷ lệ mất pose tại thời điểm ngã hay kết quả model.

18/18 nhãn có nguồn upstream. Khoảng Fall trên các clip hợp lệ dài 0,308–1,058 giây. Cửa sổ Fall yêu cầu có onset và chồng với khoảng Fall ít nhất 0,3 giây. Overlap nhỏ nhất quan sát được của Train, Validation và Test lần lượt là 0,308, 0,598 và 0,968 giây. Có 2/24 cửa sổ nằm trong khoảng 0,30–0,35 giây, đều ở Train. Đây là kiểm tra quy tắc hiện hành. Chưa đánh giá độ tối ưu của ngưỡng.

- SHA-256 nội dung logic: `70ada1f05bbac20af1d2548fa43d1d4cb6bf3abac926fcc9f146914ae53c8b62`.
- SHA-256 byte của `manifest.json`: `40f8a04b140dea7e8738ba06ec38a9d54c03ada0bfd350621081883ccb81e1fb`.

Các đầu vào và kết quả `preflight-official.json`, `build-preflight.json`, `build-stats.json`, `verify-stats.json` nằm cạnh dataset. Có thể tái tạo bằng `scripts/ml/dataset_v2.py build` với `sources-official.csv`, `--version v2.0 --seed 42 --mode official` và thư mục đích mới. Kiểm chứng bằng `scripts/ml/dataset_v2.py verify <dataset> --verify-sources`.
