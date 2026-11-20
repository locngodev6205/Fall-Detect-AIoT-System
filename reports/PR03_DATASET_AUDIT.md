# PR-03 · Audit dữ liệu

Đã rà checkout, gồm cả file bị Git bỏ qua, với môi trường Python, cache phụ thuộc và thư mục Git được loại khỏi phạm vi. Có **7 MP4 mẫu, 1 CSV báo cáo lỗi, 0 CSV keypoint và 0 NPY huấn luyện**. Không tìm thấy manifest Train/Validation/Test hay bảng subject/event. Thư mục dataset chỉ có README trỏ đến nguồn bên ngoài. Chi tiết nằm trong [dataset_audit_report.md](dataset_audit_report.md).

| Tập trong báo cáo lỗi cũ | Dòng nhãn Fall | Dòng nhãn No Fall |
| --- | ---: | ---: |
| Validation | 122 | 160 |
| Test | 134 | 165 |

Các dòng trên chỉ là lỗi dự đoán. Chưa xác minh được tổng số mẫu hoặc tỷ lệ lớp. NPY thử nghiệm PR-02 ở thư mục tạm là đầu ra từ video mẫu và không được dùng cho G3.
