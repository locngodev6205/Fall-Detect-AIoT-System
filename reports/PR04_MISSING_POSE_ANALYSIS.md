# PR-04.1 · MediaPipe Pose Lite và Full

Probe development dùng ba recording Validation subject 6, gồm ngã trước, trái và phải. Cùng AVI và timestamp giải mã, model GRU 20 + gap từ PR-04, không huấn luyện lại model cho Full. Đếm mất pose trên lưới 10 Hz trong 1 giây trước onset, trong khoảng Fall và 1 giây sau khoảng Fall. Số cửa sổ dưới đây yêu cầu nhãn thời gian đạt hợp đồng hiện hành.

| Recording | Lite mất trước/trong/sau | Full mất trước/trong/sau | 30 strict Lite → Full | 20 gap Lite → Full | Phát hiện Lite → Full |
|---|---|---|---:|---:|---|
| FallForwardS6 | 10/10 · 16/29 · 0/10 | 10/10 · 11/29 · 0/10 | 0 → 0 | 0 → 0 | Không → Không |
| FallLeftS6 | 0/10 · 16/26 · 0/10 | 0/10 · 15/26 · 10/10 | 0 → 0 | 1 → 1 | Không → Có |
| FallRightS6 | 0/10 · 17/23 · 10/10 | 0/10 · 0/23 · 0/10 | 0 → 8 | 0 → 4 | Không → Có |

Full giảm số mẫu mất trong ngã từ 49/78 xuống 26/78. Lợi ích không đồng đều. Ngã trái mất pose nhiều hơn sau sự kiện với Full và số cửa sổ gán nhãn không tăng. Vì thế không thể quy toàn bộ cải thiện ngã trái cho số cửa sổ. Hết khoảng ngã trước vẫn không có cửa sổ đạt quy tắc gán nhãn 20 mẫu với gap ở cả hai extractor.

Độ trễ `Pose.process` trên máy phát triển, bỏ frame đầu. P50/P95 theo clip của Lite lần lượt là 42,4/64,4 ms, 45,1/65,0 ms và 46,7/70,1 ms. Full lần lượt là 50,9/79,3 ms, 42,1/59,3 ms và 48,2/65,0 ms. Các lượt chạy có tải CPU của ablation cùng lúc, nên số đo mô tả lần chạy này. Chưa xác định được chênh lệch chi phí ổn định hoặc FPS Raspberry Pi. Trích xuất Lite/Full chạy ngoài runtime production.

## Negative control visibility-only

- Seed 42: TP 10, FN 5, FP 40, ADL báo 14/14, F2 0.455.
- Seed 43: TP 12, FN 3, FP 28, ADL báo 12/14, F2 0.600.
- Seed 44: TP 9, FN 6, FP 28, ADL báo 11/14, F2 0.464.

Cả Train và Validation đều che toàn bộ x/y, chỉ giữ visibility và vị trí zero theo thời gian. Phép này đo lượng tín hiệu nhãn có thể học từ detector và chất lượng pose. Nếu tín hiệu mạnh, ưu tiên đánh giá thêm trên subject/nguồn mới và kiểm soát phân bố missingness theo lớp trước khi dùng feature này trong production.
