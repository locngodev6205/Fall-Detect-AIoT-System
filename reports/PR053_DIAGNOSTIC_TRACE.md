# PR-05.3 · Trace chẩn đoán

Runner chỉ bật trace khi truyền `--trace`. JSONL ghi source time và thời điểm frame đến theo đồng hồ phiên, pose validity, khoảng start/end trên grid, mask, eligibility, score, latency và transitions của event engine. Có mốc reset, latch/cooldown, schema, SHA checkpoint và checksum trace. Thư mục mới quyền 0700, trace quyền 0600. Không ghi RGB. Chỉ bật `--consent-pose-trace` khi người tham gia đã đồng ý lưu các điểm pose dùng để replay.

```bash
export PYTHONPATH=fall_detect
python -m research.guided_test --checkpoint "$checkpoint" prepare
# Sau khi người tham gia đồng ý rõ phạm vi 30 giây và thư mục lưu:
python -m research.guided_test --checkpoint "$checkpoint" start --scenario pick-up --seconds 30 --output "$metrics" --trace "$private_dir" --consent-pose-trace
python -m research.diagnostics replay --input "$private_dir/trace.jsonl" --checkpoint "$checkpoint"
```

Dùng thư mục nghiên cứu local ngoài Git, ghi rõ đường dẫn trước khi thu. Xóa thư mục trial theo yêu cầu người tham gia. Trên Pi có thể dùng tmpfs và không tải dữ liệu người tham gia ra ngoài. Trace chỉ có metrics cho phép đọc timeline nhưng không thể suy luận lại.

**VERIFIED trên desktop.** Replay trace CAUCAFall PickupobjectS9 tái tạo 31 candidate windows, mask và quyết định giống nhau, max sai lệch score 0 trong tolerance 1e-5. Unit fixture bao phủ gap, camera reset, latch, file quyền riêng, checksum đổi và từ chối rescore trace không chứa pose.

**VERIFIED trên Pi 4.** Trace phát triển SitDownS9 tạo và replay 34 cửa sổ, max sai lệch score 0. Không mở camera. Toàn bộ suite Edge và nghiên cứu đạt 88/88.
