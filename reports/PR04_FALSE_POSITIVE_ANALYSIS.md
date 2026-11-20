# PR-04.1 · False positives trên Validation

Ba recording báo giả của GRU 20 + gap trong PR-04 được kiểm tra bằng xác suất, timestamp và RGB contact sheet từ raw Validation. Bảng dùng checkpoint E4 full seed 42 của đợt kiểm chứng. Visibility trung bình tính trên toàn bộ 17 landmark ở tối đa 1,9 giây trước peak, kể cả frame không có landmark.

| Recording | Alert mới (s) | Peak timestamp / P(Fall) | Visibility TB / frame mất toàn bộ | Quan sát RGB quanh peak |
|---|---|---|---|---|
| SitDownS7 | 6,70 | 7,00 / 0,969 | 0,875 · 0/39 | Người đã ngồi trên ghế ở cả ba ảnh. |
| PickupobjectS9 | 3,40 và 7,90 | 8,50 / 0,980 | 0,745 · 2/39 | Người cúi xuống đưa tay về phía sàn. |
| WalkS7 | 1,90 | 2,50 / 0,919 | 0,827 · 0/39 | Người đứng thẳng và bước qua khoảng trống trong phòng. |

Đây là hard negatives có căn cứ từ nhãn upstream và ảnh. SitDownS7 vẫn báo ở E1 seed 42 và E4 seed 42/43, nhưng không báo ở E4 seed 44. PickupobjectS9 không báo ở E1 seed 42 và báo ở cả ba seed E4. E4 seed 44 giảm xuống 1/14 trial ADL báo giả, nhưng việc giảm này không ổn định giữa seed. So với PR-04, seed 42 vẫn báo trên cùng ba trial, trong đó cúi nhặt đồ phát hai alert sau cooldown. Ba loại hành động nên được bổ sung từ người và bối cảnh phát triển mới, giữ nguyên nhãn. Chưa đo báo giả theo giờ từ các clip ngắn.
