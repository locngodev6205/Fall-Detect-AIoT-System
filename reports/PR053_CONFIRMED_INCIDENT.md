# PR-05.3 · Sự cố đã xác minh

**VERIFIED.** Chủ dự án xác nhận trial pick-up chỉ có cúi nhặt đồ bình thường, không có ngã. Ground truth áp cho toàn bộ 30,04 giây, không có timestamp từng động tác. Năm FP tại 3,82 / 14,92 / 19,42 / 23,32 / 26,02 giây là năm lần phát cảnh báo trong **một trial**. Không quy đổi thành false alarms/hour.

Đọc lại JSON gốc trên Pi và đối chiếu các mốc alert cùng max score 0,960074. Phiên dùng USB 640×480, Lite, GRU E4-42, xử lý 9,52 FPS, pose hợp lệ 273/286 frame, chấm 74/93 cửa sổ. JSON lưu mốc cửa sổ được chấm, cảnh báo và transitions, pose-validity transitions, thống kê timestamp/camera/tài nguyên, và một điểm cực đại toàn phiên. JSON không có score từng cửa sổ, pose hay RGB. Không tìm thấy artifact bổ sung để replay. Giữ nguyên JSON và bổ sung ground truth ở cuối báo cáo PR-05.2.

**NOT_MEASURED.** Không thể đặt đỉnh score 0,9601 vào một timestamp cụ thể, phân pha động tác hay đo visibility/torso của năm cửa sổ gốc.
