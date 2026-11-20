# PR-04.1 · False negatives trên Validation

Ba ca FN gốc của PR-04 thuộc subject 6. Dưới đây là replay E4 full seed 42 với giao thức cảnh báo mới. Số mẫu mất tính trên lưới 10 Hz trong một giây trước, toàn bộ Fall và một giây sau. Cửa sổ trong vùng match không dùng annotation khi infer. Đồ thị xác suất theo thời gian và contact sheet cho các ca có score được lưu ngoài Git trong `pr04.1/controlled`.

| Recording | Fall (s) | Mất trước / trong / sau | Cửa sổ chấm được trong vùng match | Max P trong vùng match | Chẩn đoán |
|---|---|---|---:|---:|---|
| FallForwardS6 | 2,36–5,20 | 10/10 · 16/29 · 0/10 | 0 | — | Thiếu đầu vào ở vùng chấm. Alert 6,70 s nằm sau deadline 5,36 s. |
| FallLeftS6 | 1,08–3,64 | 0/10 · 16/26 · 0/10 | 1 | 0,166 tại 1,90 s | Đầu vào thưa và score thấp hơn 0,5. |
| FallRightS6 | 2,90–5,12 | 0/10 · 17/23 · 10/10 | 2 | 0,020 tại 3,40 s | Đầu vào thưa và score thấp. Full khôi phục pose và phát hiện với checkpoint PR-04. |

Trong 15 Fall Validation, E1 strict có 7 ca không có đầu vào trong vùng chấm. E4 còn 1 ca thiếu đầu vào ở cả ba seed. Với E4 seed 42, đây là **1 FN trực tiếp do thiếu đầu vào** trong tổng 5 FN theo giao thức mới. Bốn FN còn lại có ít nhất một score. Không dùng số này để suy ra tác động nhân quả của MediaPipe lên cả bốn. Trường hợp ngã trái và phải có bằng chứng đầu vào thưa, đồng thời model chấm thấp.

Subject 6 chỉ đạt 1–3/5 Fall giữa ba seed E4 full, thấp hơn hai subject kia ở seed 42 và 44. Ba ca gốc thiếu 49/78 mẫu trong khoảng ngã với Lite. Full cải thiện hai ca và còn bỏ sót ngã trước. Nguyên nhân thị giác cụ thể và mức độ ảnh hưởng của từng tư thế chưa được xác minh trên nguồn khác. Ngã trước toàn Validation đạt 2/3, 0/3 và 2/3 giữa ba seed E4 full.
