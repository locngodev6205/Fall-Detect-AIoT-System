# PR-03 · Tóm tắt chia tập

Chưa phát hành dataset V2. Số video và sequence của bộ huấn luyện chưa xác minh được.

| Tập | Tỷ lệ mục tiêu | Video Fall | Video No Fall | Sequence Fall | Sequence No Fall |
| --- | ---: | --- | --- | --- | --- |
| Train | 70% | Chưa xác định | Chưa xác định | Chưa xác định | Chưa xác định |
| Validation | 15% | Chưa xác định | Chưa xác định | Chưa xác định | Chưa xác định |
| Test | 15% | Chưa xác định | Chưa xác định | Chưa xác định | Chưa xác định |

Bảy video mẫu gồm hai clip trong thư mục Fall, một clip trong No Fall và bốn clip demo tên `fall_example_*` chưa có manifest nhãn. Chúng không được đưa vào split huấn luyện.

Thuật toán xét các cách gán nhóm với seed cố định và ưu tiên phương án gần tỷ lệ mục tiêu theo **số video duy nhất mỗi lớp**. Tỷ lệ thực tế có thể lệch vì ranh giới nhóm và số cửa sổ hợp lệ mỗi video. CLI trả số lượng theo lớp và tập, cùng SHA-256 manifest. Dùng cùng dữ liệu nguồn, metadata, seed và code để tái lập kết quả.
