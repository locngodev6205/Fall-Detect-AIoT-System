# PR-03 · Nhóm nguồn video

Đã kiểm kê 6.988 video từ Kaggle v1 theo manifest thu được khi giải nén. Cả 6.988 video đều có CSV keypoint cùng lớp và stem. Tiêu đề cả 6.988 CSV là `Frame,Keypoint,X,Y,Confidence`, không có trường người tham gia, phiên quay hay mốc ngã.

| Kiểm tra | Kết quả |
| --- | ---: |
| Video Fall theo danh mục | 3.140 |
| Video No Fall theo danh mục | 3.848 |
| Nhóm trùng SHA-256 file | 134 |
| Video thuộc các nhóm trùng SHA-256 | 327 |
| Nhóm trùng byte có nhãn thư mục mâu thuẫn | 0 |
| Clip ứng viên Montréal theo tên | 176 |
| Scenario ứng viên | 22 |
| Clip được tính hash track hình giải mã | 176 |
| Trùng track hình trong phạm vi 176 clip | 0 |
| Video đã xác minh lineage phiên quay hoặc subject | 0 |
| Video `UNVERIFIED` | 6.988 |

Giữ mỗi nhóm trùng byte cùng một nhóm bảo thủ. 193 bản sao dư có thể loại khi build sau khi đối chiếu annotation. Không xóa video nào khỏi nguồn. Hash hình đã kiểm tra trong tập ứng viên Montréal. Video cắt hoặc đổi khung hình vẫn có thể thuộc cùng một sự kiện dù hash khác.

Tên `S_Fxx_camN` được ghi vào cột ứng viên. Nó gợi ý scenario nhiều góc quay, chưa đủ bằng chứng định danh phiên quay. Tập Montréal tham chiếu cấu trúc `chuteNN/camN.avi` theo dữ liệu gốc. Các MP4 ứng viên ở Kaggle có thời lượng 1–4 giây. Chưa xác nhận điểm cắt và căn chỉnh timeline giữa hai bản. Không tự điền subject ID hay gửi các clip này vào Test. [Bộ metadata B-MCFD](https://github.com/xiaoran007/B-MCFD)

Manifest `source-groups-mcfd-audit.csv` nằm cạnh bộ dữ liệu, ngoài Git. SHA-256 là `dff04d4fbf73bd08c928199e45fe6972bdecc23c5eb413e3e498c2d72d70c9af`. Danh sách rà soát `mcfd-review-queue.csv` ghi thời lượng và góc quay ứng viên.
