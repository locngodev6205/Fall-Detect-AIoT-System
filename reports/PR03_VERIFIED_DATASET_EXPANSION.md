# PR-03 · Mở rộng dữ liệu đã xác minh

Batch tập trung vào 9 góc quay Montréal, 10 bản ghi URFD ADL, 5 bản ghi URFD Fall có archive RGB và 1 clip Kaggle Fall từ pilot. Không kiểm kê lại kho 6.988 video.

## Bằng chứng nguồn

- **Montréal:** Khớp 9 clip Kaggle với 9 AVI gốc theo frame matching. Sai số cosine trung bình nằm từ 0,0000481 đến 0,0000596. Sai lệch vị trí frame tốt nhất cục bộ p95 bằng 0 ở cả 9 clip. Mốc mã 2 được chuyển bằng delay của camera trên B-MCFD `ffcb4d60e3ea491973434b248047eb40fa1b51ea`. Các đoạn cắt được đối chiếu với nguồn, còn dataset dùng AVI nguyên bản và clip pilot đã xác minh. Tất cả video Montréal được giữ trong **một nhóm bảo thủ** để không phân tách các lần quay có thể chung người. Scenario và camera vẫn được ghi riêng. [B-MCFD](https://github.com/xiaoran007/B-MCFD) · [Mirror AVI](https://www.kaggle.com/datasets/tuyenldvn/multiple-cameras-fall-dataset)
- **URFD:** Dùng PNG RGB và CSV timestamp chính thức. 15 bản ghi, 2.737 frame kiểm tra khớp timeline nguồn ở độ phân giải 1 ms. Video demo kèm ảnh depth chỉ dùng để kiểm tra cách công bố dữ liệu. Dữ liệu pose đến từ RGB gốc đóng gói lossless. Nhãn Fall dùng khoảng frame liên tục có mã posture 0 theo bảng chính thức. No Fall dùng bản ghi trong bảng ADL. Recording ID và camera 0 có căn cứ từ bảng nguồn. Chưa có ánh xạ subject ID theo recording, nên không suy đoán. URFD công bố điều kiện sử dụng học thuật phi thương mại. [URFD chính thức](https://fenix.ur.edu.pl/mkepski/ds/uf.html)

## Loại và giữ mẫu

Trong 25 video của batch chính, 4 khoảng Fall Montréal bị loại trước khi lập danh sách nguồn vì ngắn hơn 0,3 giây. Preflight nhận 21 video. Ba video bị loại thêm do không có cửa sổ pose liên tục, gồm `chute17-cam3`, `chute21-cam3` và `adl-23`. Còn **18 video đủ điều kiện**, gồm 9 Fall và 9 No Fall. Có 15 nhóm dùng để chia theo recording hoặc nhóm Montréal bảo thủ. Không có bản ghi nào được gắn HUMAN_VERIFIED.

Hai clip No Fall Kaggle pilot vẫn cách ly. Các video được thay bằng bản ghi URFD có ID và nhãn do nguồn công bố. Hai demo URFD Fall ngắn hơn 2,9 giây cũng không được đưa vào batch chính. Không padding, kéo giãn hoặc thay đổi ngưỡng Fall.

Bằng chứng ngoài Git nằm trong `annha-recovery-payutch-v1/verified-expansion-v2`, gồm checksum và URL tải, frame matching, kiểm tra PTS của RGB gốc, danh sách nguồn và quyết định preflight. Chưa đánh giá model.
