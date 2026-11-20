# PR-03 · Quyết định khôi phục dataset

**Quyết định.** Giữ 30 mẫu ở 10 Hz làm chuẩn của subset có giám sát đầu tiên. Ưu tiên clip đủ thời lượng, có pose liên tục và có thể truy được về bản gốc có annotation. Dùng hàng đợi 120 clip để ưu tiên công việc xác minh. G3 toàn bộ và G3 subset đều chưa đạt. Chưa mở PR-04 để huấn luyện hay đánh giá model.

## 1. Thời lượng và FPS của kho Kaggle v1

`ffprobe` đọc thành công cả 6.988 file. Số liệu theo thời lượng track hình. Nhãn đến từ thư mục archive, đang ở mức kiểm kê.

| Thời lượng track | Fall | No Fall | Tổng |
| --- | ---: | ---: | ---: |
| Dưới 1 giây | 1 | 1 | 2 |
| 1 đến dưới 2 giây | 1.006 | 1.235 | 2.241 |
| 2 đến dưới 3 giây | 823 | 332 | 1.155 |
| 3 đến dưới 5 giây | 1.197 | 1.591 | 2.788 |
| 5 đến dưới 10 giây | 113 | 686 | 799 |
| 10 đến dưới 30 giây | 0 | 3 | 3 |
| **Tổng** | **3.140** | **3.848** | **6.988** |

| Cửa sổ ở 10 Hz | Từ mẫu đầu đến cuối | Fall có thể đủ thời gian | No Fall có thể đủ thời gian | Tổng |
| --- | ---: | ---: | ---: | ---: |
| 10 mẫu | 0,9 giây | 3.139 | 3.847 | 6.986 |
| 20 mẫu | 1,9 giây | 2.133 | 2.613 | 4.746 |
| 30 mẫu | 2,9 giây | 1.310 | 2.280 | 3.590 |

Sàng lọc dùng `(nb_frames - 1) / avg_frame_rate` làm ước lượng. Số đạt ở bảng trên chưa tính gián đoạn timestamp, pose và annotation. Điều này cho phép giữ clip dưới 3 giây nếu thực sự có đủ 30 mốc. FPS phổ biến nhất là 30 (4.655 file) và 24 (739 file). Độ phân giải phổ biến nhất là 1920×1080 (3.877 file) và 1100×1080 (2.384 file). Có 981 track có start time khác 0 và 60 track có FPS danh nghĩa khác FPS trung bình. Chênh lệch metadata chưa chứng minh video lỗi. Trong 38 clip giải mã thử, không phát hiện bước timestamp OpenCV không tăng. Chưa giải mã PTS của toàn bộ kho.

## 2. Đo pose trên cùng video

Mẫu gồm 24 clip ứng viên Montréal ở 720×480, 30 FPS và 14 clip ngoài nhóm tên này (7 Fall, 7 No Fall). Chọn nhóm ngoài theo lớp và dải thời lượng với seed 42. Chưa xác minh upstream từng clip trong nhóm ngoài, nên không gán kết quả của nhóm này cho Fall Vision hoặc Figshare. MediaPipe Pose Lite và Full chạy trên cùng khung hình, cùng ngưỡng và tracking. Nhóm Montréal có thêm một lượt thử Lite xoay 180° để kiểm tra độ nhạy đối với hướng ảnh.

| Nhóm | Cấu hình | Khung mất pose | Mẫu 10 Hz có pose chuẩn hóa hợp lệ | Clip có cửa sổ 10 / 20 / 30 |
| --- | --- | ---: | ---: | ---: |
| Montréal ứng viên (24) | Lite | 758 / 2.580 (29,38%) | 602 / 860 (70,00%) | 18 / 10 / 5 |
| Montréal ứng viên (24) | Full | 818 / 2.580 (31,71%) | 585 / 860 (68,02%) | 19 / 12 / 4 |
| Montréal ứng viên (24) | Lite xoay 180° | 647 / 2.580 (25,08%) | 635 / 860 (73,84%) | 19 / 7 / 2 |
| Ngoài nhóm Montréal, Fall (7) | Lite | 36 / 523 (6,88%) | 132 / 145 (91,03%) | 6 / 2 / 1 |
| Ngoài nhóm Montréal, Fall (7) | Full | 65 / 523 (12,43%) | 122 / 145 (84,14%) | 6 / 1 / 0 |
| Ngoài nhóm Montréal, No Fall (7) | Lite | 1 / 468 (0,21%) | 156 / 156 (100%) | 6 / 4 / 2 |
| Ngoài nhóm Montréal, No Fall (7) | Full | 14 / 468 (2,99%) | 151 / 156 (96,79%) | 6 / 4 / 2 |

Bảng dò khả năng tạo ít nhất một cửa sổ với stride 1, không gán nhãn. Báo cáo trước dùng stride 3 và tìm 4 clip Montréal có cửa sổ 30 mẫu. Hai lần đo dùng tiêu chí dò cửa sổ khác nhau. Cửa sổ thử nghiệm không đi vào Dataset V2.

Trong nhóm Montréal, Lite mất pose từ **26/300 (8,67%) ở cam7** đến **166/330 (50,30%) ở cam3**. Các clip này cùng FPS và kích thước ảnh, nên khác biệt đó không được giải thích chỉ bằng FPS hay độ phân giải. Thử xoay cho thấy pose nhạy với hướng ảnh, nhưng số clip đủ cửa sổ 30 giảm từ 5 xuống 2. Chưa có annotation mốc ngã để kiểm tra mất theo dõi xảy ra trước, trong hay sau ngã. Chưa đo ảnh hưởng riêng của che khuất, camera, mức méo hình hoặc cách dựng clip. Giữ cấu hình Lite hiện tại cho vòng xác minh.

## 3. Ba phương án cho clip ngắn

| Phương án | Phạm vi khả dụng | Nhãn, chuyển động và độ trễ |
| --- | --- | --- |
| 30 mẫu, 10 Hz | 3.590 video qua sàng lọc thời lượng. Lite có ít nhất một cửa sổ trong 8/38 clip thử | Giữ schema hiện tại và nhiều ngữ cảnh hơn. Cần 2,9 giây từ mẫu đầu đến cuối khi làm đầy bộ đệm. Đây là thời gian lấy mẫu, chưa phải độ trễ cảnh báo thực tế |
| Nhánh riêng 20 hoặc 10 mẫu | 4.746 hoặc 6.986 video qua sàng lọc thời lượng. Lite có cửa sổ trong 16/38 hoặc 30/38 clip thử | Bộ đệm cần 1,9 hoặc 0,9 giây. Cửa sổ ngắn có ít diễn tiến trước/sau ngã hơn. Mốc ngã vẫn cần xác minh. Chỉ đánh giá lợi ích và cảnh báo nhầm khi có split độc lập và thử nghiệm riêng |
| Phục hồi đoạn dài từ upstream | Chưa định lượng số clip có thể khớp bản gốc | Giữ chuyển động thật. Cần định danh lần ghi, góc camera, offset và căn timeline trước khi dùng annotation. Bộ Montréal có timeline chuẩn và độ trễ camera để đối chiếu. Figshare mô tả cả Fall và hoạt động hằng ngày, nhưng lần đọc ZIP theo byte range trả HTTP 202 nên chưa xác minh metadata theo clip. [B-MCFD](https://github.com/xiaoran007/B-MCFD) · [Figshare v2](https://figshare.com/articles/dataset/Sensor-Based_Fall_Detection_Dataset_with_2017_Activities_from_29_Subjects/28596332/2) |

Ưu tiên kết hợp phương án 30 mẫu và tìm lại ngữ cảnh gốc. Giữ clip ngắn trên danh sách rà soát cho phương án 10–20 mẫu hoặc đối chiếu upstream. Không padding, kéo giãn hay đổi model.

## 4. Hàng đợi xác minh và mức tin cậy

Đã tạo `recovery-review-queue.csv` gồm 120 ứng viên, 60 Fall và 60 No Fall theo thư mục. Có 4 ứng viên đã đo được cửa sổ Lite 30 mẫu. Các ứng viên khác được lấy theo dải thời lượng và tỷ lệ khung hình. Hàng đợi bỏ bản trùng byte, không chọn các stem mơ hồ, và lấy tối đa một góc từ mỗi scenario Montréal ứng viên. Các cột upstream và loại hành động đã xác minh để trống. Chưa thể phân tầng chính thức theo chúng.

| Mức tin cậy | Video xác nhận | Phạm vi sử dụng |
| --- | ---: | --- |
| VERIFIED_TEMPORAL | 0 | Có nhóm nguồn đã xác minh. Với clip Fall, cần annotation thời gian đã xác minh. Các negative cần bằng chứng đã xác nhận không có Fall |
| VERIFIED_CLIP | 0 | Có nhóm nguồn và nhãn clip đã xác minh. Chỉ dành cho phương pháp dùng nhãn clip |
| UNVERIFIED | 6.988 | Chờ xác minh. Cách ly khỏi tập đánh giá |

File `recovery-motion-proposals.json` có 31 gợi ý dựa trên đoạn vận tốc hông lớn nhất khi hông đủ visibility. Mở công cụ đánh dấu, chọn video và nhập file gợi ý. Nút **Gợi ý khoảng cần xem** tìm theo SHA-256 và luôn để trạng thái `UNVERIFIED`. Chuyển sang xác minh chỉ sau khi người xem đối chiếu video và ghi nhận bằng chứng. Gợi ý có thể bắt bước đi, đổi góc hoặc nhiễu pose.

Để duyệt subset, tra metadata theo nguồn gốc trước. Với Montréal, đối chiếu bản quay và ánh xạ mốc timeline đã căn chỉnh. Với nguồn khác, tra clip, người tham gia, loại hành động và lần ghi từ hồ sơ nhà cung cấp khi có. Lấy mẫu cân bằng các hành động và góc quay đã xác minh, bổ sung các hard negative như ngồi nhanh hoặc nằm xuống nếu nhãn cho phép. Đưa tất cả góc quay, đoạn cắt, bản nén lại và bản trùng đã xác nhận của cùng lần ghi vào một nhóm. Ưu tiên phân tách theo người tham gia nếu có ID. Dùng manifest để khóa Test trước khi thử cấu hình hoặc huấn luyện.

## 5. Kiểm tra rò rỉ và quyết định PR-04

Kiểm tra nguồn trước đó tìm thấy 134 nhóm trùng byte (327 video), không phát hiện trùng decoded hash trong 176 clip Montréal đã kiểm tra. Chưa có một nhóm độc lập đã xác minh cho subset. Train, Validation và Test thực tế có 0 video đủ điều kiện. Chưa kiểm tra được rò rỉ trên split thật và chưa có hash manifest Dataset V2.

Có thể mở PR-04 thử nghiệm khi subset có đủ nhóm Fall và No Fall độc lập để chia cả ba tập, có mốc Fall được xác minh và có phòng, hành động hoặc điều kiện hình đủ để mô tả phạm vi đánh giá. Khoảng 100–200 video là mục tiêu rà soát, không bảo đảm đủ độ tin cậy thống kê. Chỉ cân nhắc G3 toàn bộ khi đã kiểm tra phạm vi dữ liệu đầy đủ.

Dữ liệu đo ở ngoài Git gồm `recovery-video-metadata.json`, `recovery-paired-pose.json`, `recovery-review-queue.csv` và `recovery-motion-proposals.json`. Script phân tích chạy qua ba chế độ `probe`, `pose` và `review`. Không thay đổi backend, hệ thống cảnh báo hoặc model production.
