# PR-05.3 · Đánh giá và giới hạn

Raw Validation gồm 15 Fall và 14 ADL từ ba người. Đếm alert bằng cùng hợp đồng PR-04.1. Match tối đa một alert từ onset đến mốc sớm hơn giữa onset + 3 giây và cuối Fall + 1 giây. Giữ mọi Fall thiếu cửa sổ trong mẫu số. Cả bốn cấu hình có coverage 14/15. Hysteresis giữ nguyên toàn bộ đầu vào và TP theo subject. Baseline TP/FN/FP của subject 6, 7 và 9 lần lượt là 1/4/2, 4/1/3 và 5/0/3. Hysteresis giảm FP subject 9 xuống 2.

Baseline phát hiện ngã trước/sau/trái/phải/từ tư thế ngồi lần lượt 2/3, 1/3, 2/3, 2/3, 3/3. Báo giả ADL ở ngồi xuống, cúi nhặt đồ và đi bộ. Kết quả chi tiết gồm eligibility, timestamp, score theo recording và subject nằm trong JSON local do script tạo. Validation là tập đã dùng nhiều lần. Không sử dụng Test V2.1 hoặc phiên live để chọn ứng viên.

Case live có một recording từ một người, 30,04 giây và 5 FP. Chưa có video ADL liên tục đủ để ước lượng false alarms/hour có thể tổng quát hóa.
