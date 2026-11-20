# PR-03 · Xác minh G3

**G3 chưa đạt.** Đã xác minh tải đủ nguồn, lập manifest lineage và kiểm tra trùng byte toàn bộ video. Kiểm tra hash hình giải mã hoàn tất cho 176 clip ứng viên Montréal, chưa bao phủ 6.812 clip còn lại. Người tham gia, điểm cắt, nhóm phiên quay và annotation thời điểm ngã chưa được xác minh đủ để tạo một subset Train/Validation/Test độc lập.

19 bài kiểm thử PR-03, schema và audit đạt. JavaScript công cụ đánh dấu qua kiểm tra cú pháp. Kiểm thử phần mềm xác nhận các quy tắc validator trên fixture, còn xác minh rò rỉ giữa các split thật chưa thể chạy khi chưa có dataset. Chưa có SHA-256 manifest của Dataset V2.

Cần xác minh đủ nhóm Fall và No Fall độc lập để cả ba tập có cả hai lớp, cùng hai mốc thời gian đáng tin cậy cho các clip Fall được chọn. Sau đó chạy builder và `verify --verify-sources` theo [hướng dẫn khôi phục](DATASET_RECOVERY_GUIDE.md). PR-04 chưa được mở.
