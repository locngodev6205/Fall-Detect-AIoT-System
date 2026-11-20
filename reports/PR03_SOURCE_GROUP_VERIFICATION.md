# PR-03 · Xác minh nhóm nguồn của pilot

Video trong pilot có đường dẫn archive Kaggle v1 và SHA-256 đã kiểm tra. Dataset tổng hợp, recording/session, subject, camera và event group là các trường riêng. 24/24 clip có định danh file. 0/24 clip có recording và nhóm độc lập được xác minh. Chưa có subject ID đáng tin cậy ở pilot.

Các tên S_F1_cam5 và S_F4_cam6 gợi ý hai scenario và hai góc quay. B-MCFD mô tả phân đoạn trên timeline đã căn chỉnh và độ trễ theo camera. Để chuyển annotation cần đối chiếu ghi hình gốc, camera, khung hình bắt đầu của clip và timeline. Cùng stem hoặc cùng nhà phát hành không chứng minh cùng session. Nếu xác nhận nhiều góc hoặc nhiều đoạn cắt thuộc cùng lần quay, gán cùng source group trước khi split. [Quy ước timeline B-MCFD](https://github.com/xiaoran007/B-MCFD/blob/main/docs/metadata-semantics.md)

Các clip B_D và C_M vẫn thuộc nhóm chưa xác minh upstream theo từng clip. Không suy subject hoặc session từ tiền tố. Giữ kết quả 134 nhóm trùng byte trong toàn bộ archive để kiểm tra bản sao. Kiểm tra trùng decoded-frame trước khi chốt subset và dùng metadata cho bản cắt hoặc nén lại. Chưa đưa nhóm nào vào Test.
