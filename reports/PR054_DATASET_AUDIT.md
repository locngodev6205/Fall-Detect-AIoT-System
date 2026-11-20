# PR-05.4 · Kiểm kê dữ liệu phát triển

V2.1 giữ nguyên. Audit đọc đúng các pose CSV Train/Validation theo manifest SHA-256 ghim, kiểm checksum pose và subject/group/hash overlap bằng loader development. Đếm cửa sổ E4 20/3, gap 3. Missing là mẫu không có pose canonical sau resample, còn visibility là phân vị trung bình từng recording trên frame gốc.

| Split | Hoạt động | Recording | Subject biết | Camera ID theo nguồn | Thời lượng min/p50/max s | Window | Missing / mẫu | Visibility min/p50/max |
|---|---|---:|---:|---:|---|---:|---:|---|
| train | ADL unspecified | 8 | 0 | 1 | 4.96/5.99/9.42 | 102 | 48/520 | 0.67/0.84/0.94 |
| train | Fall | 27 | 4 | 5 | 3.00/7.69/11.65 | 79 | 404/2065 | 0.00/0.79/0.93 |
| train | Hop | 4 | 4 | 1 | 7.15/8.38/9.05 | 83 | 11/332 | 0.83/0.84/0.84 |
| train | Kneel | 4 | 4 | 1 | 6.45/10.98/12.75 | 83 | 58/414 | 0.47/0.79/0.83 |
| train | Pick up object | 4 | 4 | 1 | 5.80/8.57/13.25 | 39 | 131/365 | 0.17/0.73/0.83 |
| train | Sit down | 4 | 4 | 1 | 5.55/9.60/10.55 | 77 | 33/356 | 0.56/0.76/0.83 |
| train | Walk | 4 | 4 | 1 | 10.75/12.00/12.15 | 121 | 30/471 | 0.75/0.79/0.89 |
| val | Fall | 15 | 3 | 1 | 7.35/10.55/12.55 | 39 | 219/1579 | 0.28/0.80/0.91 |
| val | Hop | 3 | 3 | 1 | 8.05/9.85/10.55 | 68 | 21/286 | 0.73/0.84/0.89 |
| val | Kneel | 2 | 2 | 1 | 10.05/10.40/10.75 | 47 | 12/209 | 0.73/0.78/0.82 |
| val | Pick up object | 3 | 3 | 1 | 7.60/10.05/10.95 | 44 | 60/288 | 0.47/0.74/0.77 |
| val | Sit down | 3 | 3 | 1 | 9.40/9.60/11.85 | 62 | 23/311 | 0.68/0.71/0.82 |
| val | Walk | 3 | 3 | 1 | 9.60/11.65/13.25 | 90 | 18/347 | 0.70/0.86/0.86 |

Train phát triển có 27 Fall và 28 ADL, Validation có 15 Fall và 14 ADL. CAUCAFall đóng góp 4 subject Train và 3 subject Validation riêng. MCFD/URFD chỉ ở Train, 16 recording thiếu ID subject đã xác minh. Không suy ra 16 người khác nhau. Các trial nhặt đồ đều từ một camera CAUCAFall. Thiếu nhãn riêng cho cúi nhẹ/sâu, cúi giữ, đứng lên, quay người, nằm chủ động, chuyển tư thế liên tiếp và ra/vào khung. URFD ADL chưa có nhãn con xác minh trong pipeline này. Camera ID là metadata, chưa chứng minh độ đa dạng góc hoặc ánh sáng.

Train Fall thiếu 404/2.065 mẫu sau chuẩn hóa. Train pick-up thiếu 131/365, cao hơn ngay cả Fall aggregate. Sự khác biệt giữa nhóm hành động và tín hiệu mất pose có thể gây lệch khi train, chưa chứng minh quan hệ nhân quả.
