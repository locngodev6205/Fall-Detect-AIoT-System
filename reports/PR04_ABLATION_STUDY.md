# PR-04.1 · Controlled ablation

Đã chạy lại inference từ cả bảy checkpoint của PR-04. JSON Validation tái lập giống từng byte. Pipeline kiểm tra SHA-256 checkpoint, ghim manifest V2.1 và xác nhận subject/group/hash video không giao nhau giữa Train và Validation. Các thí nghiệm chỉ tải pose của Train/Validation. Raw Test đã được tiếp xúc qua kiểm toán PR-04 và không tham gia chọn cấu hình ở đây. Đánh giá cuối cùng cần holdout mới hoặc quy trình nghiệm thu độc lập.

## Giao thức

GRU hidden 32, schema `annha-pose-v2`, 10 Hz, stride 3, AdamW 0,001, batch 32, BCE cân bằng theo lớp và recording, 30 epoch, threshold 0,5, seed 42/43/44. Cùng subject split. Xử lý gap cho phép tối đa một đoạn ba mẫu liên tiếp nằm bên trong cửa sổ. Giữ visibility bằng 0 tại mẫu thiếu và không tạo pose giả.

Matched-data dùng cùng recording, số cửa sổ và timestamp kết thúc huấn luyện. Cắt 10 mẫu đầu từ cửa sổ 30 để có cửa sổ 20. Cả hai phải đạt quy tắc nhãn, cửa sổ 30 phải đủ pose. So sánh gap trong matched-data chỉ thay đổi eligibility ở inference vì Train không có gap. Cửa sổ validation dùng stride 3 theo mỗi độ dài nên pha timestamp kết thúc khác nhau. Full-eligibility tạo lại toàn bộ cửa sổ hợp lệ theo từng cấu hình. Giữ số epoch cố định, vì vậy số update tăng khi dữ liệu tăng. Chênh lệch matched/full không cô lập riêng số lượng dữ liệu với phân bố mẫu hoặc số update.

Quét tuần tự và chấm tại timestamp mẫu cuối, không lọc cửa sổ inference bằng annotation. Một alert phát khi vượt ngưỡng và cooldown 2 giây đã hết. Chuỗi điểm liên tục trên ngưỡng được gộp thành một alert. Điểm dưới ngưỡng tái kích hoạt bộ phát. Match tối đa một alert cho mỗi Fall trong khoảng onset đến mốc sớm hơn giữa onset + 3 giây và cuối Fall + 1 giây. Alert trước, sau hoặc thừa trong khoảng match và mọi alert trên ADL đều tính FP. Event không có score trong khoảng match vẫn tính FN. Tỷ lệ ADL báo nhầm tính theo trial, không quy đổi theo giờ.

## matched

| Run | Recording / window Train | Recall | Precision | F1 | F2 | TP / FN / FP | ADL báo / 14 | Coverage Fall / 15 | Trễ P50 / P95 (s) |
|---|---|---|---|---|---|---|---|---|---|
| E1 seed 42 | 43 / 421 | 0.400 | 0.353 | 0.375 | 0.390 | 6 / 9 / 11 | 4 | 8 | 1.920 / 2.320 |
| E1 seed 43 | 43 / 421 | 0.400 | 0.429 | 0.414 | 0.405 | 6 / 9 / 8 | 2 | 8 | 2.010 / 2.380 |
| E1 seed 44 | 43 / 421 | 0.400 | 0.375 | 0.387 | 0.395 | 6 / 9 / 10 | 1 | 8 | 2.140 / 2.465 |
| E2 seed 42 | 43 / 421 | 0.533 | 0.400 | 0.457 | 0.500 | 8 / 7 / 12 | 5 | 10 | 1.855 / 2.280 |
| E2 seed 43 | 43 / 421 | 0.533 | 0.471 | 0.500 | 0.519 | 8 / 7 / 9 | 3 | 10 | 1.935 / 2.364 |
| E2 seed 44 | 43 / 421 | 0.533 | 0.421 | 0.471 | 0.506 | 8 / 7 / 11 | 3 | 10 | 2.010 / 2.459 |
| E3 seed 42 | 43 / 421 | 0.600 | 0.529 | 0.562 | 0.584 | 9 / 6 / 8 | 3 | 11 | 1.420 / 2.592 |
| E3 seed 43 | 43 / 421 | 0.600 | 0.500 | 0.545 | 0.577 | 9 / 6 / 9 | 5 | 11 | 1.420 / 2.656 |
| E3 seed 44 | 43 / 421 | 0.533 | 0.571 | 0.552 | 0.541 | 8 / 7 / 6 | 0 | 11 | 1.845 / 2.784 |
| E4 seed 42 | 43 / 421 | 0.800 | 0.600 | 0.686 | 0.750 | 12 / 3 / 8 | 4 | 14 | 1.450 / 2.181 |
| E4 seed 43 | 43 / 421 | 0.800 | 0.571 | 0.667 | 0.741 | 12 / 3 / 9 | 5 | 14 | 1.500 / 2.292 |
| E4 seed 44 | 43 / 421 | 0.733 | 0.688 | 0.710 | 0.724 | 11 / 4 / 5 | 1 | 14 | 1.580 / 2.570 |

F2 trung bình E1/E2/E3/E4: 0.397 / 0.509 / 0.567 / 0.738.

## full

| Run | Recording / window Train | Recall | Precision | F1 | F2 | TP / FN / FP | ADL báo / 14 | Coverage Fall / 15 | Trễ P50 / P95 (s) |
|---|---|---|---|---|---|---|---|---|---|
| E1 seed 42 | 47 / 458 | 0.400 | 0.375 | 0.387 | 0.395 | 6 / 9 / 10 | 3 | 8 | 2.010 / 2.380 |
| E1 seed 43 | 47 / 458 | 0.400 | 0.375 | 0.387 | 0.395 | 6 / 9 / 10 | 2 | 8 | 2.140 / 2.690 |
| E1 seed 44 | 47 / 458 | 0.333 | 0.312 | 0.323 | 0.329 | 5 / 10 / 11 | 2 | 8 | 2.000 / 2.340 |
| E2 seed 42 | 48 / 493 | 0.600 | 0.474 | 0.529 | 0.570 | 9 / 6 / 10 | 4 | 10 | 1.870 / 2.536 |
| E2 seed 43 | 48 / 493 | 0.600 | 0.529 | 0.562 | 0.584 | 9 / 6 / 8 | 2 | 10 | 1.870 / 2.260 |
| E2 seed 44 | 48 / 493 | 0.600 | 0.529 | 0.562 | 0.584 | 9 / 6 / 8 | 1 | 10 | 1.870 / 2.372 |
| E3 seed 42 | 49 / 553 | 0.600 | 0.429 | 0.500 | 0.556 | 9 / 6 / 12 | 9 | 11 | 1.420 / 2.224 |
| E3 seed 43 | 49 / 553 | 0.600 | 0.474 | 0.529 | 0.570 | 9 / 6 / 10 | 6 | 11 | 1.260 / 2.592 |
| E3 seed 44 | 49 / 553 | 0.533 | 0.333 | 0.410 | 0.476 | 8 / 7 / 16 | 5 | 11 | 1.220 / 2.455 |
| E4 seed 42 | 50 / 584 | 0.667 | 0.556 | 0.606 | 0.641 | 10 / 5 / 8 | 3 | 14 | 1.650 / 2.692 |
| E4 seed 43 | 50 / 584 | 0.600 | 0.429 | 0.500 | 0.556 | 9 / 6 / 12 | 4 | 14 | 1.420 / 2.028 |
| E4 seed 44 | 50 / 584 | 0.800 | 0.750 | 0.774 | 0.789 | 12 / 3 / 4 | 1 | 14 | 1.660 / 2.554 |

F2 trung bình E1/E2/E3/E4: 0.373 / 0.579 / 0.534 / 0.662.

## E4 full theo subject và kiểu ngã

| Seed | Subject 6 | Subject 7 | Subject 9 | Ngã trước | Ngã sau | Ngã trái | Ngã phải | Ngã khi ngồi |
|---|---|---|---|---|---|---|---|---|
| 42 | 1/5 | 4/5 | 5/5 | 2/3 | 1/3 | 2/3 | 2/3 | 3/3 |
| 43 | 3/5 | 3/5 | 3/5 | 0/3 | 2/3 | 3/3 | 2/3 | 2/3 |
| 44 | 2/5 | 5/5 | 5/5 | 2/3 | 3/3 | 2/3 | 2/3 | 3/3 |

Các ô là số Fall phát hiện trên tổng số Fall. Phân tách early, late, duplicate, score, delay và thống kê theo subject/loại cho mọi cấu hình nằm trong JSON local.

Bộ hồi quy Edge và PR-04 đạt **67/67**. Bốn tests mới kiểm tra cổng gap, cooldown và match, đối sánh cửa sổ Train và reset streaming.
