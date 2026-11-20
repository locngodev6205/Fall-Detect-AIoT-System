# PR-05 · Đánh giá cảnh báo theo sự kiện

Raw Validation có 15 Fall và 14 ADL trên ba người. Match một cảnh báo từ onset đến mốc sớm hơn của onset + 3 giây và cuối Fall + 1 giây. Cảnh báo trước onset, sau deadline hoặc thừa trong vùng match được đếm riêng. ADL báo nhầm tính theo trial ngắn. Không quy đổi thành false alarms mỗi giờ.

| Chế độ | TP/FN/FP | Recall | Precision | F1/F2 | ADL báo | Delay p50/p95 s |
|---|---:|---:|---:|---:|---:|---:|
| PR04-compatible một lần xác nhận | 10/5/8 | 66,7% | 55,6% | 0,606/0,641 | 3/14 | 1,650/2,692 |
| Thử hai lần xác nhận | 9/6/9 | 60,0% | 50,0% | 0,545/0,577 | 3/14 | 1,860/2,760 |

Cả hai có coverage 14/15. Một FN do không có window hợp lệ trong vùng match (FallForwardS6). Bốn FN còn lại của chế độ tương thích có score. Chế độ tương thích có một alert sớm, ba alert muộn, bốn alert trên ba ADL và không có alert thừa trong vùng match. Hai xác nhận giảm alert sớm xuống 0 nhưng tăng alert muộn lên 5, giữ ba ADL báo giả và làm mất một TP. Trung vị delay tăng 0,210 giây trên các TP của từng chế độ, với tập TP khác nhau. Giữ chính sách tương thích.

Recall theo subject 6/7/9 là 1/5, 4/5, 5/5. Theo kiểu ngã trước/sau/trái/phải/từ tư thế ngồi là 2/3, 1/3, 2/3, 2/3, 3/3. ADL báo gồm ngồi xuống, cúi nhặt đồ và đi bộ. Không đủ bằng chứng cho nằm xuống có chủ đích, chuyển tư thế đa dạng hoặc camera mất người kéo dài trong dữ liệu thực tế.

Để đo false alarms mỗi giờ, thu video No Fall liên tục từ nhiều phòng, người, điều kiện ánh sáng. Ghi timestamp bắt đầu/kết thúc, khoảng camera gián đoạn và thời lượng quan sát hợp lệ. Xác minh ground truth độc lập và ghi mọi alert cùng thời gian. Đếm alert sau dedup trên tổng giờ camera hợp lệ. Thu recording Fall với onset kiểm chứng để đo delay và báo riêng không đủ đầu vào.
