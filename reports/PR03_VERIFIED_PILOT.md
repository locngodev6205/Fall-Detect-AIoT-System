# PR-03 · Pilot xác minh video

Đã chuẩn bị 24 clip thật, gồm 12 Fall và 12 No Fall theo nhãn thư mục. Đây là 12 ứng viên đầu của mỗi lớp trong hàng đợi 120. Đã đối chiếu SHA-256 của từng clip trước khi tạo 24 contact sheet có số frame và timestamp. File `verified-pilot-review/pilot-review.csv` ở thư mục dữ liệu ngoài Git.

Bốn clip đã có cửa sổ Lite 30 mẫu khi sàng lọc với stride 1, nên ưu tiên xem trước.

| Clip | Nhãn archive | Cửa sổ đủ pose |
| --- | --- | ---: |
| S_F1_cam5.mp4 | Fall | 3 |
| S_F4_cam6.mp4 | Fall | 10 |
| B_D_0195.mp4 | No Fall | 1 |
| B_D_0203.mp4 | No Fall | 11 |

Các cửa sổ trên chưa có nhãn huấn luyện. Số clip được người xem xác minh là 0 Fall và 0 No Fall. Chưa xác minh timestamp bắt đầu, va chạm và kết thúc ngã hoặc tình trạng sau ngã. Contact sheet hỗ trợ tìm đoạn cần xem. Hãy xem video gốc bằng công cụ `scripts/ml/annotate_fall.html`, ghi reviewer, nguồn và mức tin cậy, rồi xuất JSON lịch sử. Mốc chạm đất có thể để trống nếu bị che khuất. Gợi ý chuyển động thu thập trước đó vẫn là ứng viên chưa xác nhận. Công cụ không tự xác minh lineage hay gán split.
