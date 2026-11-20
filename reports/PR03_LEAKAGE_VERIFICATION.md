# PR-03 · Kiểm chứng data leakage

`verify --verify-sources` chạy thành công trên Dataset V2.0, digest logic `70ada1f05bbac20af1d2548fa43d1d4cb6bf3abac926fcc9f146914ae53c8b62`. Bộ kiểm tra kiểm lại nguồn, các hash, quan hệ giữa nhóm và split, lịch chia theo seed 42, danh sách khóa Test, tính hợp lệ của timestamp, nhãn, shape và checksum của cửa sổ. Không phát hiện trùng video hoặc cửa sổ xuyên split trong phạm vi nhóm nguồn, SHA-256 tệp, SHA-256 frame giải mã và hash feature đã kiểm tra.

Tất cả video Montréal được giữ trong một nhóm ở Train. Việc ghép clip Kaggle với AVI gốc cung cấp thêm bằng chứng lineage cho phần Montréal. URFD chia theo recording, chỉ dùng RGB camera 0. Chưa có ánh xạ subject ID trên các recording URFD nên chưa thể chứng minh tính độc lập theo người. So sánh hash chính xác không bao phủ mọi biến thể cắt, crop hoặc mã hóa lại giữa các nguồn.

Test khóa hai nhóm URFD, mỗi lớp một nhóm. Nhiều cửa sổ từ một nhóm tương quan với nhau nên số cửa sổ không phải số quan sát độc lập. Chưa có bộ cross-source holdout đủ hai lớp. Montréal trong batch chỉ cung cấp Fall. Chưa dùng Test để chọn ngưỡng hoặc thông số.
