# PR-05.2 · Kiểm tra camera có hướng dẫn

## Readiness

SSH strict host verification thành công. Sandbox nghiên cứu và checkpoint E4-42 khớp checksum. Camera /dev/video0 rảnh và Edge production không chạy lúc kiểm tra. Runner đọc 28/28 frame ở 640×480, 10,58 FPS gồm cả MediaPipe Lite. Không phát hiện frame đen và cả 27 cặp frame liên tiếp thay đổi. MediaPipe xử lý đủ 28 frame, chưa thấy landmark trong lần kiểm tra trước khi người tham gia vào vị trí. Góc nhìn cơ thể sẽ kiểm tra ở bước standing. Không lưu hình ảnh.

## Các bước

Standing, walking, sit-stand, pick-up và leave-reenter chạy từng bước khi người tham gia xác nhận READY. Không có scenario nào bắt đầu trước khi xác nhận. Mỗi lượt ghi JSON metrics ngoài Git. Chỉ phân loại simulated alert là báo giả khi thời điểm alert nằm trong khoảng ADL được người tham gia xác nhận.

```bash
python -m research.guided_test --camera 0 --checkpoint full-E4-42.pt prepare
python -m research.guided_test --camera 0 --checkpoint full-E4-42.pt start --scenario standing --seconds 30 --output standing.json
```

## Bước 1 · Standing

Người tham gia xác nhận đã đứng trước camera trước khi bắt đầu đo. Pi xử lý 311 frame ở 640×480 trong 30,06 giây. FPS quan sát sau read 10,50 và FPS toàn phiên 10,34. Pose khả dụng 275/311 (88,4%), thiếu pose khả dụng 36 frame, tất cả frame có landmark thô. Pose khả dụng đầu tiên ở 3,91 giây và duy trì đến hết phiên. Có 81/93 cửa sổ được chấm (87,1%), P(Fall) cao nhất 0,0541 và 0 cảnh báo giả lập.

MediaPipe p50/p95/p99 88,08/93,43/128,88 ms. GRU p50/p95/p99 5,96/8,95/10,24 ms. CPU trung bình tương đương 102,2% một core, peak RSS 384,8 MiB, nhiệt độ cuối 58,9 °C và throttle 0x0. Không ngắt camera, reset timestamp hoặc lỗi model. Đây là một trial đứng yên, đánh giá phạm vi hoạt động bình thường.

## Bước 2 · Walking với preview VNC

Người tham gia yêu cầu bắt đầu bước đi bộ và xem lại trên VNC. Đo 30,03 giây ở 640×480 với cùng luồng camera cho preview và suy luận. Preview nội bộ tự đóng cuối lượt. 295 frame, input 9,95 FPS và xử lý toàn phiên 9,82 FPS. Pose khả dụng 293/295 (99,3%), 91/92 cửa sổ được chấm, P(Fall) tối đa 0,0632 và 0 cảnh báo giả lập. Có một reset do khoảng timestamp, không ngắt camera và không lỗi model. Chờ xác nhận hoạt động của người tham gia trước khi đánh dấu trial ADL đã xác minh.

MediaPipe p50/p95/p99 91,58/97,94/115,10 ms. GRU 6,11/12,31/15,59 ms. CPU tương đương 100,4% một core, peak RSS 385,6 MiB, nhiệt cuối 60,9 °C, throttle 0x0. Đây là số đo có bật preview. Chênh lệch FPS so với đứng yên đồng thời bao gồm khác biệt hoạt động, nên chưa thể quy cho riêng preview.

## Bước 3 · Sit-down / stand-up với preview VNC

Lượt 30,09 giây tại 640×480 có 297 frame, input 9,98 FPS và xử lý 9,87 FPS. Pose khả dụng 297/297 frame. GRU chấm 93/93 cửa sổ, P(Fall) tối đa 0,0333 và không có cảnh báo giả lập. Không reset timestamp, mất kết nối camera hoặc lỗi model. Chờ người tham gia xác nhận hoạt động trong lượt đo.

MediaPipe p50/p95/p99 91,47/98,87/116,19 ms. GRU 6,02/12,18/17,83 ms. CPU tương đương 101,0% một core, peak RSS 384,4 MiB, nhiệt cuối 61,8 °C, throttle 0x0. Không có sự kiện ngã hoặc dispatch cảnh báo để đo độ trễ phát hiện.

## Bước 4 · Cúi nhặt đồ với preview VNC

Lượt 30,04 giây có 286 frame, 9,52 FPS xử lý, 273 frame có pose hợp lệ (95,5%) và 74/93 cửa sổ được chấm. P(Fall) tối đa 0,9601. Có năm cảnh báo giả lập tại timestamp cửa sổ 3,82 / 14,92 / 19,42 / 23,32 / 26,02 giây. Chờ xác nhận hoạt động và khoảng thời gian ADL để phân loại báo giả. Không có lỗi model, reset timestamp hoặc mất camera.

MediaPipe p50/p95/p99 93,23/102,14/171,58 ms. GRU 6,10/12,46/26,99 ms. Peak RSS 385,0 MiB, nhiệt cuối 62,8 °C, throttle 0x0.

## Bước 5 · Ra khỏi khung rồi quay lại với preview VNC

Lượt 30,05 giây xử lý 300 frame ở 9,98 FPS. Pose khả dụng 112/300 frame, GRU chấm 19/93 cửa sổ, điểm Fall tối đa 0,0347 và không có cảnh báo giả lập. Camera không mất kết nối và không reset timestamp. Đây là kiểm tra mất pose trong luồng, chưa thử rút cáp camera.

Hai khoảng dài mất pose là 4,63–14,96 giây và 18,16–22,97 giây. Timestamp cuối của cửa sổ hợp lệ đầu tiên sau khi pose trở lại là 16,97 và 25,07 giây. Khoảng từ pose trở lại đến timestamp cửa sổ lần lượt là 2,01 và 2,10 giây. Không có cảnh báo lặp quan sát được. Các mốc là chuyển trạng thái pose tự động, chưa có xác nhận mốc hành động từ người tham gia.

MediaPipe p50/p95/p99 91,12/100,10/181,63 ms. GRU 5,95/14,87/17,48 ms. CPU tương đương 98,5% một core, peak RSS 385,3 MiB, nhiệt cuối 62,3 °C, throttle 0x0.

## Trạng thái xác minh

Đã đo đủ năm lượt theo yêu cầu. Người tham gia xác nhận lượt đứng yên và ngồi/đứng. Các lượt đi bộ, cúi nhặt đồ và ra/vào khung còn thiếu xác nhận hành động sau đo. Năm cảnh báo ở lượt cúi nhặt đồ giữ trạng thái chờ phân loại. Không tính Recall từ các lượt ADL này. Preview chỉ hiển thị tại desktop VNC của Pi, tự đóng cuối lượt và không lưu hình ảnh.

## Xác minh bổ sung từ PR-05.3

Chủ dự án xác nhận toàn bộ trial cúi nhặt đồ là No Fall. Cả năm cảnh báo giả lập được phân loại FP trong cùng một trial. Các mốc cảnh báo và trạng thái ghi nhận ban đầu ở trên được giữ để đối chiếu. Xem [PR053_CONFIRMED_INCIDENT.md](PR053_CONFIRMED_INCIDENT.md).
