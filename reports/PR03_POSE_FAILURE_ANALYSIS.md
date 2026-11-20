# PR-03 · Phân tích mất pose theo frame

Lite và Full được chạy lại trên cùng 3.571 frame của 38 clip. Trace ngoài Git lưu số frame từ 0, timestamp OpenCV và timestamp dùng trong pipeline, tình trạng mất pose từng model, số điểm đạt visibility 0,3, visibility trung bình, diện tích hộp quanh các điểm thấy được và luma trung bình toàn ảnh. 30 contact sheet lỗi tập hợp các trạng thái Lite/Full theo clip.

| Nhóm | Frame | Cả hai mất | Chỉ Lite mất | Chỉ Full mất | Cả hai có pose |
| --- | ---: | ---: | ---: | ---: | ---: |
| 24 ứng viên Montréal | 2.580 | 582 | 176 | 236 | 1.586 |
| 7 Fall ngoài nhóm Montréal | 523 | 31 | 5 | 34 | 453 |
| 7 No Fall ngoài nhóm Montréal | 468 | 0 | 1 | 14 | 453 |
| **Tổng** | **3.571** | **613** | **182** | **284** | **2.492** |

Lite mất 795/3.571 frame (22,26%), Full mất 897/3.571 (25,12%). Nhãn theo thư mục được dùng để mô tả nguồn mẫu. Chưa có mốc ngã đã xác minh nên tỷ lệ mất pose trước, trong và sau ngã chưa tính được. Clip No Fall chưa được người xem xác nhận, nên cũng chưa tính tỷ lệ giai đoạn hoạt động bình thường đã xác minh. Trace đánh dấu các frame `UNVERIFIED`. Lệnh `phase --history` ghép lịch sử xác minh với trace theo SHA-256 và tách bốn giai đoạn.

## Giải thích phạm vi bằng chứng

- Trong sheet 03 của S_F1_cam3, frame 0 không thấy rõ người trong vùng ghi hình, Full mất ở frame 39 dù thấy người cạnh nệm, và Lite mất ở frame 71 khi thấy người nằm gần nệm. Sheet 13 của S_F4_cam5 cho thấy Lite mất ở frame 17 dù người vẫn thấy được trên nệm. Các frame minh họa cho thấy nhiều tình huống mất pose, chưa xác định mốc va chạm hoặc nguyên nhân duy nhất.
- Trên nhóm Montréal, luma trung vị khi Lite mất pose là 122,8/255 và khi có pose là 125,0/255. Luma toàn ảnh không đo được ánh sáng chiếu lên người. Khi chỉ một model mất pose, hộp landmark của model còn lại chiếm khoảng 1,8–1,9% diện tích ảnh theo trung vị, so với 3,0–3,1% khi cả hai nhận pose. Đây là chỉ báo liên hệ với vùng người nhỏ, chưa phải đo kích thước độc lập khi cả hai cùng mất.
- Các góc camera cùng nguồn có chênh lệch tỷ lệ mất pose. Các ví dụ có cả người xa, ra vào mép ảnh và tư thế nằm. Chưa có mask che khuất hay điểm đo ánh sáng tại người để quy nguyên nhân định lượng. Không dùng biến thể xoay 180° trong production.

## Khoảng trống 1–3 mẫu

| Model | 1 mẫu | 2 mẫu | 3 mẫu |
| --- | ---: | ---: | ---: |
| Lite | 13 | 11 | 3 |
| Full | 18 | 2 | 5 |

Chỉ đếm khoảng nằm giữa hai mẫu pose hợp lệ tại 10 Hz. Khoảng cách thời gian giữa hai đầu là 0,2/0,3/0,4 giây. Trong các khoảng Lite thiếu một mẫu, dịch chuyển hông giữa hai đầu có trung vị 0,089 và lớn nhất 0,539 theo tọa độ ảnh chuẩn hóa. Giá trị lớn chưa được xác minh là chuyển động thật hay tracking đổi vị trí. Nếu thử nội suy offline, ưu tiên 1 mẫu với hai đầu có visibility tốt và bằng chứng liên tục, giữ mask observed riêng và đánh giá trên clip có nhãn. Hai hoặc ba mẫu vượt giới hạn 0,25 giây hiện tại. Giữ thiếu, không đưa trajectory suy diễn làm mốc ngã, giữ chuỗi gốc để so sánh. Lượt này chỉ lưu khoảng trống và mask, không điền tọa độ.

Pose có thể làm mất đầu vào của detector, nhưng chưa đo được tỷ lệ bỏ sót té ngã do pose vì thiếu annotation và đánh giá theo sự kiện.
