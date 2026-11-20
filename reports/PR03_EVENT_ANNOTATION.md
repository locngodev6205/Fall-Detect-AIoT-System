# PR-03 · Annotation sự kiện té ngã

**0/3.140 clip Fall có hai mốc đã xác minh.** Bản Kaggle không kèm bảng thời điểm ngã. Metadata B-MCFD cung cấp phân đoạn trên timeline đã căn chỉnh của bản gốc Montréal. Cần xác minh camera, scenario và điểm cắt của MP4 Kaggle trước khi chuyển mốc. Các nguồn Fall Vision và Figshare đã được truy vết trong [hướng dẫn khôi phục](DATASET_RECOVERY_GUIDE.md) nhưng chưa có bảng ánh xạ đã xác minh tới clip v1. [Metadata và quy ước căn chỉnh B-MCFD](https://github.com/xiaoran007/B-MCFD)

Danh sách rà soát Montréal gồm 176 clip. Có 152 clip ngắn hơn 2,9 giây, là khoảng cách tối thiểu giữa mẫu đầu và cuối của cửa sổ 30 mẫu ở 10 Hz. Còn 24 clip thuộc 3 scenario ứng viên để ưu tiên xem. Danh sách rà soát không chứa nhãn thời gian.

## Đánh dấu và lưu lần chỉnh sửa

1. Mở `scripts/ml/annotate_fall.html` trong trình duyệt máy. Chọn video gốc. Công cụ tính SHA-256 cục bộ để nối đúng clip với manifest.
2. Xem lại clip và đánh dấu lúc bắt đầu mất thăng bằng, lúc chuyển động ngã kết thúc. Nhập tên người xem và ghi nguồn annotation hoặc mô tả bằng chứng. Nếu mốc nằm ngoài phần clip hoặc khó xác định, giữ trạng thái `UNVERIFIED`.
3. Thêm lần ghi và xuất lịch sử JSON. Lần chỉnh sửa sau nhập lại lịch sử trước khi thêm bản ghi. Mỗi lần có checksum video, người xem, dấu thời gian, nguồn, mức tin cậy và hai mốc. Bản ghi cũ vẫn được giữ.
4. Người xác minh đối chiếu checksum và lineage riêng. Chỉ chuyển hai mốc sang `event_start` và `event_end` trong `sources.csv` sau khi cả mốc ngã lẫn nhóm nguồn có căn cứ. Công cụ chỉ ghi lịch sử và không tự quyết định clip nào vào Test.

Không có đề xuất pose tự động trong đợt này. Cần nhãn upstream đã căn chỉnh hoặc bản ghi do người xem xác minh trước khi dùng làm ground truth.
