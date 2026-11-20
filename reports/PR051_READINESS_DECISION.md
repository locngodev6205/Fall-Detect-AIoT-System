# PR-05.1 · Quyết định staging

Cổng staging cần khả năng chạy PyTorch trên board thật, parity quyết định trong sai số công bố, live có người đủ đại diện và giữ cadence đầu vào cho grid 10 Hz. FPS trung bình trên 10 là điều kiện cần cho dữ liệu camera mới ở 10 Hz. Cần kiểm tra phân bố khoảng frame, coverage và độ trễ ở tải thực. Yêu cầu thêm kiểm thử reconnect vật lý, thời gian warmup 20 mẫu, headroom CPU/RAM khi AnNhà chạy cùng và sự ổn định nhiệt đủ lâu. Một phiên camera thiếu người không đo được chi phí tracking liên tục và có thể đánh giá thấp tải.

Chỉ dùng validation đã xác minh cho Recall. Chưa phê duyệt G3, chưa mở Test V2.1, chưa có phiên ADL đủ dài được gán nhãn để kết luận false alarm/hour. Không triển khai production.

## Quyết định sau benchmark

**Pi chạy được checkpoint PyTorch ARM64 và đạt parity trong tolerance. Chưa mở PR-06 tích hợp staging.** Trên 8 clip Validation, Lite đạt 10,49 FPS replay và 3/5 Fall đúng hạn, trong khi Full đạt 7,35 FPS và 2/5 Fall. Lite là cấu hình để đo tiếp. Pose chiếm khoảng 87 ms/frame ở p50, GRU khoảng 5,8 ms mỗi window scored. Chưa có cơ sở chuyển sang ONNX/TFLite khi pose đang là phần chiếm thời gian chính. Runtime PyTorch vẫn cần đưa vào dự toán RAM và dung lượng cùng dịch vụ thực tế.

Camera live 5 phút đạt 10,83 FPS, không reset timestamp, không mất camera, không lỗi model, nhiệt đạt 68,7 °C và cờ throttle cuối phiên 0x0. Không có pose hợp lệ trong phiên này, vì vậy phần GRU có người chỉ được kiểm chứng qua video replay. Cần đo với hoạt động bình thường có người, thử ngắt/cắm lại camera thật và đo tải có các dịch vụ staging đi cùng trước khi kết luận headroom. Regression reconnect giữ latch và cooldown, không phát lặp qua reset giả lập. Chưa xác minh soak 30 phút hoặc unplug/replug trên phần cứng.

Parity ARM64/desktop trên 91 cửa sổ có max sai lệch tensor 2,38e-7 và score 1,19e-7, không đổi quyết định cảnh báo. Có 44 hash tensor khác ở mức làm tròn. Không có score gần 0,5 trong batch, ca sát ngưỡng được kiểm thử riêng bằng fixture.

**85/85 tests đạt.** JSON thiết bị, checkpoint và pose diagnostics ở `annha-recovery-payutch-v1/pr05/pi051` và thư mục hiện vật kề bên, ngoài Git. Sandbox Pi nằm trong tmpfs và không khởi động cùng hệ thống.
