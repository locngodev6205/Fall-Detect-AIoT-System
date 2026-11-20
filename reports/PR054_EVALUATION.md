# PR-05.4 · Đánh giá mô hình

E0 tái lập trên 84 recording phát triển với 2.011 candidate windows và 1.509 scores. Tensor và score offline/streaming sai lệch 0. Event metrics giống PR-05.3 với policy threshold 0,5 và cooldown 2 giây. Tập chấm cam kết 15 Fall và 14 ADL từ ba người, coverage 14/15 cho E0 và cả ba seed E1. Mỗi Fall tính một lần theo cùng deadline PR-04.1. Không báo FP theo giờ từ các trial ngắn.

Kết quả local chứa metric theo subject và action, cùng timeline từng recording. Seed 42 tái lập baseline, gồm ca nhặt đồ báo giả. Các seed khác dao động về cả Fall Recall, FP và delay. Không xác định được thay đổi do mở rộng V3 vì chưa chạy E2 và chưa có prospective evaluation. **GENERALIZATION_NOT_ESTABLISHED.**
