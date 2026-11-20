# PR-05 · Offline và streaming parity

Replay checkpoint full-E4-42 trên 84 recording phát triển Train/Validation đã ghim manifest V2.1. Không chạy Test. Offline resample cả đoạn và streaming nhận từng pose timestamp, cả hai dùng cùng grid, canonical normalization, policy 20/3/gap và checkpoint. Nhãn chỉ dùng sau khi infer.

Đối chiếu **2.011 candidate window**, gồm **1.509 score**. Mọi start/end, mask, tensor, score và transition khớp. Max sai lệch tensor và xác suất đều bằng 0. Không có reset timestamp trong batch. Reset dùng chung chính sách chia segment và bắt đầu lại stride. Trường hợp warmup, reset, pose gap và fixture 60 mẫu đi qua regression tests.

Grid-end tới thời điểm pose đầu vào đến có p50/p95/p99 là 0/11/29 ms. Đây là quantization theo timestamp recording, chưa gồm compute hay độ trễ camera. Trên raw Validation, offline, streaming grid và streaming arrival cùng 10 TP, 5 FN, 8 FP và p50/p95 delay 1,65/2,692 giây. Kết quả bitwise tensor chỉ áp dụng cùng nguồn pose CSV. Benchmark video tái trích xuất Lite/Full là phép khác, giữ model/sampler/event engine để khảo sát thay đổi pose. Kết quả video không dùng để suy ra parity camera live.

Bộ regression Edge và nghiên cứu đạt 78/78 tests. JSON parity chạy lại giống từng byte.
