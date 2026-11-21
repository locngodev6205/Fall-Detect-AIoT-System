# PR-05.5 · Kết quả collector video và pose

Đã chạy trên Raspberry Pi 4 ARM64 và webcam USB, OpenCV 4.11.0, MediaPipe Lite 0.10.14. Camera được để trống, đã có đồng ý lưu lượt kiểm tra trong RAM. VNC dùng preview Wayland từ cùng frame capture. Cửa sổ mở trong countdown/ghi hình và đóng trước extraction. Edge được tạm dừng theo xác nhận và trở lại active sau lượt.

| Chỉ số | Lượt camera trống |
|---|---|
| Thời lượng ghi / độ phân giải | 5,08 giây / 640×480 |
| Video | MP4 MPEG-4 Part 2 (mp4v) |
| Frame ghi / giải mã / dòng pose | 54 / 54 / 54 |
| FPS capture / mã hóa / webcam báo | 10,71 / 19,93 / 30,00 |
| Thời lượng video mã hóa | 2,71 giây |
| Pose hợp lệ / usable GRU windows | 0/54 / 0 |
| Lỗi read / khoảng thời gian dài so với cadence mã hóa | 0 / 37 |
| CPU lúc ghi / wall time cả lượt | 1,09 CPU-giây / 16,08 giây |

FPS mã hóa ước lượng trong countdown trước khi ghi. Với preview và encoder cùng hoạt động, cadence thực giảm và video CFR phát nhanh hơn khoảng 2,24 giây so với khoảng từ frame đầu đến cuối. Ghi timestamp gốc trong frames.jsonl và dùng chính timestamp đó cho pose, không dùng FPS MP4 để đồng bộ nghiên cứu. Chưa đo peak RAM hoặc frame mất ở driver. H.264 qua được encoder probe nhưng mất frame khi ghi webcam Pi. Giữ các clip lỗi trong sandbox, collector ARM ưu tiên mp4v và kiểm tra lại số frame sau ghi.

Hiện vật hợp lệ nằm trong vùng RAM riêng trên Pi tại `/dev/shm/annha-pr055/smoke-empty/subjects/fixture/session_20261121/standing_c30711f9b550`. Video, timestamps và pose đều có SHA-256. Lượt trống giữ UNVERIFIED, zero subject dùng cho training. Chưa quay phiên có người theo chế độ video V3, chưa đo trực tiếp capture trên Windows hoặc webcam laptop. Không huấn luyện lại.

16 tests liên quan đạt trên desktop, bao gồm OpenCV ghi/đọc file fixture, ID duy nhất, đồng bộ timestamp, tái trích xuất với extractor fixture, lỗi hash, video rỗng, nhãn và regression collector cũ. MediaPipe thật được chạy trong lượt Pi. Dữ liệu ghi hình và hiện vật kiểm tra không đưa vào Git.
