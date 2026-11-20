# PR-03 · Dataset V2

Chưa có dataset huấn luyện. Số video và sequence được chấp nhận vào cả Train, Validation và Test hiện là **0**. 6.988 video đang được cách ly khỏi split vì lineage chưa xác minh. Trong số đó, 152 clip ứng viên Montréal có thêm lý do không đủ thời lượng tối thiểu. Hai lý do giao nhau và không cộng thành tổng số video.

Bộ kiểm tra dùng `annha-pose-v2`, 17 khớp × 3 kênh, sampling 10 Hz và cửa sổ 30 mẫu. Cấu hình hiện tại chỉ giữ cửa sổ từ clip Fall nếu giao với khoảng ngã đã xác minh và đủ mẫu pose hợp lệ. Cửa sổ hoàn toàn trước hoặc sau ngã được bỏ qua. Đoạn chuyển tiếp mơ hồ cần được loại khi lập annotation hoặc clip. Nhãn No Fall dành cho video có bằng chứng là hoạt động không ngã. Không chuyển cửa sổ ngoài mốc của video Fall thành No Fall.

Chỉ tạo cửa sổ huấn luyện sau khi chia theo source group. Giữ cùng nhóm cho các góc quay của cùng scenario và các đoạn cắt của cùng video gốc. Augmentation chỉ áp dụng trong Train. Test dùng manifest đã khóa.

## Chạy thử trên 24 clip thật đủ thời lượng trong danh sách Montréal

| Chỉ số | Kết quả |
| --- | ---: |
| Khung đọc được | 2.580 |
| Khung mất toàn bộ pose | 758 (29,38%) |
| Điểm thiếu hoặc visibility dưới 0,3 | 13.591 / 43.860 (30,99%) |
| Giá trị NaN/Inf | 0 |
| Timestamp xuất không tăng nghiêm ngặt | 0 |
| Clip đủ pose để tạo ít nhất một cửa sổ | 4 / 24 |
| Cửa sổ kỹ thuật chưa gán nhãn | 6 |
| Scenario ứng viên có cửa sổ | 2 |

20 clip qua sàng lọc thời lượng vẫn không tạo được cửa sổ có đủ pose hợp lệ. Timestamp được kiểm tra sau extractor, vốn có cơ chế fallback theo FPS. Sáu cửa sổ chỉ dùng đo khả năng tạo đặc trưng trong thư mục tạm. Hai scenario ứng viên chưa đủ cho ba split ngay cả khi sau này xác minh được danh tính và mốc ngã. Chi tiết theo clip nằm trong `mcfd-review-quality.json` cạnh bộ dữ liệu nguồn.
