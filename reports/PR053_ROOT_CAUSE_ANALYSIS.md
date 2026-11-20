# PR-05.3 · Phân tích nguyên nhân

## Ca live đã xác nhận

**VERIFIED.** Không reset timestamp, mất camera hoặc lỗi model. Mỗi alert có một chuỗi candidate → confirmed → simulated alert. Engine cần score vượt 0,5 khi latch đã mở lại và cooldown đã hết. Vì vậy các alert phụ thuộc score của model và chính sách rearm. Giữa hai alert, latch có thể mở bởi score xuống dưới ngưỡng hoặc một khoảng mất pose liên tục đủ dài. JSON cũ không cho biết cơ chế cụ thể ở từng mốc. Một số chuyển trạng thái pose ở gần alert, nhưng dữ liệu thiếu cửa sổ không đủ để quy nguyên nhân cho missing pose.

## Bằng chứng trên clip phát triển

**VERIFIED.** PickupobjectS9 trên raw Validation báo ở 3,4 và 7,9 giây. Score giữ cao qua nhiều cửa sổ từ 7,9 đến 9,4 giây, đạt 0,980 ở 8,5 giây. Contact sheet PR-04.1 quanh đỉnh cho thấy người cúi đưa tay về phía sàn. Đây là bằng chứng mô hình báo nhầm động tác cúi ở clip này. Không suy ra pha cụ thể của trial trên Pi. Ở cửa sổ kết thúc 8,5 giây, 37/39 frame gốc có cả vai và hông đạt visibility 0,3, visibility trung bình 0,745, hai frame không có landmark. Mất pose hoàn toàn không phải điều kiện cần để model chấm cao.

Đo vector giữa trung điểm hông và vai trong tọa độ ảnh trên frame đạt visibility. Độ nghiêng trung vị so với trục đứng ảnh tăng từ 7,2° ở cửa sổ kết thúc 7,9 giây lên 26,3° ở cửa sổ kết thúc 8,5 giây. Trung điểm hông nằm khoảng 0,641–0,657 chiều cao ảnh trong cả hai cửa sổ. Đây là hình chiếu 2D. Canonical features dịch gốc về hông và chia theo độ dài thân, nên vị trí tuyệt đối trong ảnh không được giữ. **HYPOTHESIS.** Chuyển động của thân khi cúi và thiếu ngữ cảnh phân biệt với ngã có thể góp phần. Chưa cô lập ảnh hưởng góc camera hoặc độ dài cửa sổ ở case live.

## Dữ liệu và khả năng học theo chất lượng pose

Raw development có 4 recording nhặt đồ Train từ 4 subject, tất cả CAUCAFall, và 3 recording Validation từ 3 subject khác. Pose thiếu toàn bộ ở Train theo recording là 24/117, 17/166, 2/179, 215/266 frame. Cả 3 trial Validation có cửa sổ được chấm, chỉ PickupobjectS9 báo nhầm. Split dùng subject group và kiểm tra group/hash xuyên Train/Validation. Chưa có góc nhìn hoặc nguồn nhặt đồ thứ hai đủ để đo đa dạng. Số trial thuần bending có thể học được còn ít và chất lượng pose thay đổi mạnh.

Trên raw Train, thiếu toàn bộ landmark là 1.617/7.007 frame Fall (23,1%) và 651/5.420 frame ADL (12,0%). Phép thử visibility-only PR-04.1 từng phát hiện 9–12/15 Fall nhưng báo ở 11–14/14 trial ADL. Đây là dấu hiệu tương quan chất lượng pose với nhãn và khả năng học shortcut. Chưa có phép can thiệp đủ để kết luận GRU đầy đủ dựa vào shortcut hoặc quy lỗi riêng cho MediaPipe.
