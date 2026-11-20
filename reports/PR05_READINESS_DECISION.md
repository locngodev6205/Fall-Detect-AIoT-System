# PR-05 · Quyết định sẵn sàng

**Prototype desktop đã chạy. Chưa mở PR-06 tích hợp với AnNhà.** Replay cho parity mức window/score trên pose CSV và tái lập event metrics PR-04.1. GRU 20 + gap phát hiện đúng hạn 10/15 lần ngã. Một trong năm FN thiếu đầu vào trong vùng match, số còn lại cần cải thiện phân loại hoặc quyết định theo thời gian.

Giữ Lite và một xác nhận làm mặc định benchmark. Full tăng cửa sổ đủ điều kiện nhưng không tăng Recall trên batch video đối chiếu và tốn thêm CPU. Hai xác nhận không giảm báo giả ADL và làm xấu Recall cùng độ trễ. Pi 4 vẫn NOT_MEASURED. Cần đo Lite/Full, camera và khả năng phục hồi khi mất kết nối trên Pi trước khi chọn runtime cho staging. Cần thêm môi trường/subject và ADL liên tục trước khi đánh giá alert rate. Test V2.1 giữ khóa, không inference và không phê duyệt G3. Model production và kênh cảnh báo giữ nguyên.

Hiện vật benchmark ngoài Git ở `annha-recovery-payutch-v1/pr05`. Tái lập từ repo với `PYTHONPATH=fall_detect python scripts/ml/pr05_replay.py "$data_root" "$checkpoint" "$output"`. Thêm `--video` cho phép so Lite/Full trên tám AVI development. Chọn đường dẫn JSON mới. Chạy `python -m research.benchmark --help` cho phép đo file hoặc camera tách biệt.
