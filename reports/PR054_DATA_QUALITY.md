# PR-05.4 · Điều kiện nhận dữ liệu

Gate xác minh phiên bản, contract pose, provenance checkpoint, hash trace/sidecar, metadata thiết bị, mã nguồn và consent. Timestamp phải hữu hạn, tăng dần, có thời lượng trong giới hạn. Pose đúng 17×3 và visibility hợp lệ. Phiên NO_FALL đã xác nhận phải có pose hợp lệ và ít nhất một cửa sổ được chấm. E2 còn từ chối phiên đứt quãng để tránh tạo cửa sổ bắc qua disconnect. Model không gán ground truth.

Regression tests kiểm tra consent, nhãn, checksum, timestamp, subject/session/source/setup overlap và duplicate recording/pose. Audit không thấy overlap trên phần development đã biết ID. Subject chưa biết ở nguồn Train-only giới hạn khả năng chứng minh danh tính. Với V3 chưa có phiên người thật, kết quả test là kiểm chứng hành vi gate. Không kết luận không có duplicate ngoài dữ liệu đã kiểm tra.

97/97 tests đạt trên desktop. Trên Pi, CLI validate và sidecar EXCLUDED chạy trên fixture SitDownS9 từ development, 238 frame và 19 cửa sổ được chấm. Replay checkpoint trên trace development có sẵn khớp 34/34 cửa sổ, max score delta 0. Đã xác minh đường kiểm tra offline trên Pi. Chưa mở camera hoặc xác minh end-to-end với phiên người thật mới có consent.
