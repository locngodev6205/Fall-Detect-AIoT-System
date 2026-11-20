# PR-03 · Kiểm tra rò rỉ dữ liệu

**Trạng thái: dữ liệu huấn luyện đầy đủ chưa có để xác minh G3.**

- CSV báo cáo lỗi cũ có 581 tên sequence khác nhau. Có **36 tiền tố video xuất hiện trong cả Validation và Test** khi lấy phần đứng trước `_keypoints_`. Ví dụ gồm `C_D_0032`, `S_F6_cam3` và `20240916195937`. Đây là dấu hiệu khả dĩ của rò rỉ theo video. Chưa có manifest hoặc NPY gốc để xác minh ID video, nội dung và khoảng thời gian của các cửa sổ.
- Không có tên sequence giống hệt giữa hai tập trong CSV báo cáo lỗi. CSV chỉ chứa kết quả dự đoán sai và không có Train.
- Bảy video mẫu có SHA-256 file và SHA-256 luồng hình giải mã khác nhau. Video bị cắt, thay đổi kích thước hoặc mã hóa mất dữ liệu có thể đổi dấu vân tay. Các biến thể đó cần `source_group` từ lineage gốc hoặc rà soát bổ sung.
- Chưa có subject ID để đánh giá khả năng tổng quát hóa sang người mới.

Pipeline mới gộp bản sao theo hash file và hash hình giải mã, cùng `source_group` và subject ID nếu có. Subject ID được hiểu trong phạm vi bộ nguồn. Gặp bản sao video có nhãn hoặc khoảng té ngã mâu thuẫn, chương trình dừng. Mỗi nhóm chỉ có một split và cửa sổ được tạo sau bước chia tập. Validator chặn hash NPY hoặc tensor đã chuẩn hóa trùng giữa các tập. Chỉ loader Train mới được bật augmentation.

Dữ liệu cũ chưa được sửa. Cần đối chiếu 36 trường hợp với bộ gốc.
