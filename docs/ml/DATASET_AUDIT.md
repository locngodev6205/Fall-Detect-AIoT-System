# PR-01 · Audit dữ liệu và hợp đồng đặc trưng

| Đầu vào | Nguồn và mức xác minh |
| --- | --- |
| Video | Có clip mẫu trong `fall_detect/sample_videos/`. Chưa có bằng chứng clip thuộc bộ train, val hoặc test |
| Extractor | Script legacy `fall_detect/utils/extract_keypoint.py`. Runtime dùng `fall_detect/modules/skeleton.py` |
| Sequence và nhãn | `process_csv_data.py` tạo cửa sổ từ CSV. Notebook đọc `/kaggle/input/fall-dataset6/{train,val,test}`. CSV lỗi ghi đường dẫn `/kaggle/input/datasets/locngodev/fall-dataset/…`. Chưa có manifest nối hai nguồn |
| FPS, timestamp, video/subject ID | CSV extractor lưu số thứ tự frame. Chưa có metadata đã xác minh về nhịp lấy mẫu, người tham gia hoặc mốc sự kiện cho toàn dataset |
| Tệp kết quả | CSV chỉ liệt kê lỗi. Đếm được Validation 160 FP / 122 FN và Test 165 FP / 134 FN. Không dùng mẫu lỗi để suy ra overlap toàn tập |

Fixture audit dùng các landmark có tọa độ phân biệt. Năm điểm mặt đầu trong extractor legacy lấy index `[0,1,2,3,4]`, còn runtime lấy `[0,2,5,7,8]`. Fixture round-trip qua extractor → CSV → sequence cho vector 51 chiều khác runtime trên cùng pose. Extractor lưu pixel, bước pivot nhóm theo cột, còn live lấy tọa độ chuẩn hóa và tổ chức theo từng khớp. Đây là bằng chứng lệch giữa hai đường mã đang có, chưa chứng minh file .npy dùng cho checkpoint được tạo bằng chính đường legacy đó.

`split_dataset.py` chia danh sách sequence, chưa áp ràng buộc theo video hay subject. Notebook có bước augment trước CV theo các cell được lưu. Điều này tạo khả năng chồng lấn nhưng chưa xác nhận overlap thực tế. Không suy ra video ID từ tên cửa sổ để công bố kết quả.

Chạy khi có manifest xác thực từ raw video hoặc metadata nguồn:

```bash
python scripts/ml/audit_dataset.py --manifest /path/to/verified-manifest.csv --fail-on-overlap
```

CSV bắt buộc có `split,label,video_id`. Có thể thêm `subject_id,parent_id,sha256,feature_path,total_frames,missing_pose_frames`. `feature_path` tính tương đối theo manifest. Tool kiểm tra trùng video, chủ thể, bản gốc của mẫu augment và SHA-256, báo số nhãn, số video và mức thiếu pose từ metadata. Giá trị overlap bằng 0 chỉ áp dụng cho các ID có dữ liệu. Bộ test dùng fixture tổng hợp để xác nhận phát hiện overlap.

**BLOCKED_DATA_LINEAGE:** cần manifest đầy đủ kèm source video và mapping video/subject, hash tập và checkpoint/export log. Chưa thay đổi extractor, notebook, dữ liệu hay model.
