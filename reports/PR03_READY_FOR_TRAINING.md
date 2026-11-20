# PR-03 · Trạng thái sẵn sàng cho PR-04

**BLOCKED_DATA_LINEAGE.** Cần đầy đủ video hai lớp, nhãn, ID nguồn, khoảng thời gian té ngã đã xác minh và CSV khớp schema `annha-pose-v2`. Để đối chiếu rò rỉ trong bộ cũ, cần manifest split cũ hoặc bảng gắn NPY với video gốc. Subject ID chỉ điền khi có metadata đáng tin cậy.

Chuẩn bị CSV UTF-8 với các cột sau. Đường dẫn tương đối tính từ thư mục chứa CSV. Dùng chung `source_group` cho clip cắt hoặc biến thể của cùng video. Mỗi bản ghi Fall có một khoảng sự kiện tính theo giây trên trục thời gian CSV. Với nhiều sự kiện, tạo các clip có annotation riêng và giữ chung group.

```csv
video_id,source_file,keypoint_csv,label,source_dataset,subject_id,source_group,event_start,event_end,scene_id,camera_id,annotation_version
```

Nhãn là `fall` hoặc `no_fall`. No Fall để trống hai cột sự kiện. CSV keypoint và sidecar phải đến từ extractor PR-02 và chứa SHA-256 video nguồn. Pipeline chia nhóm trước khi tạo cửa sổ. Chỉ giữ cửa sổ Fall giao với khoảng sự kiện và đủ mẫu pose hợp lệ.

```bash
python scripts/ml/dataset_v2.py audit .
python scripts/ml/dataset_v2.py build /data/sources.csv /data/annha-v2 --version v2.0 --seed 42
python scripts/ml/dataset_v2.py verify /data/annha-v2 --verify-sources
```

Build yêu cầu FFmpeg và một đường dẫn đích mới. Manifest lưu nguồn, checksum, nhóm, split, seed, cấu hình preprocessing, timestamp cửa sổ và khóa nhóm Test.

```python
from ml.training_data import DataLoader

train = DataLoader(root, 'train', batch_size=32, shuffle=True, augment=True, expected_sha256=locked_hash)
val = DataLoader(root, 'val', expected_sha256=locked_hash)
test = DataLoader(root, 'test', purpose='final_evaluation', expected_sha256=locked_hash)
```

Thêm `fall_detect` vào `PYTHONPATH`. Các bộ nạp trả tensor NumPy `float32` dạng `(batch, 30, 51)` và nhãn nguyên nhị phân dùng chung cho Transformer, TCN và GRU. Khi chạy cross-validation, chia cửa sổ gốc của Train theo nhóm trước khi augment phần huấn luyện của mỗi fold. Chọn threshold trên Validation. Chỉ mở Test sau khi đã khóa model candidate và threshold.

Chưa có dataset được nghiệm thu để bắt đầu huấn luyện PR-04.
