# PR-05.4 · Quy trình thu hard negatives

Trên Pi dùng sandbox research riêng, checkpoint có SHA ghim, cùng Python đã có NumPy, OpenCV, MediaPipe và PyTorch. Kiểm tra Edge dừng và camera rảnh trước khi thử. Sau readiness, báo CAMERA READY và mô tả dữ liệu thu trong 30–60 giây. Chỉ bắt đầu sau xác nhận đồng ý lưu pose. Preview VNC chỉ mở nội bộ nếu được đồng ý. Một lượt chỉ làm một hoạt động an toàn. Sau khi camera nhả, người phụ trách kiểm tra kết quả và xác nhận toàn lượt là No Fall, hoặc loại nếu không rõ.

```bash
export PYTHONPATH=fall_detect
python -m research.collect prepare --camera 0 --checkpoint "$checkpoint"
python -m research.collect start --checkpoint "$checkpoint" --metadata "$trial_json" --output "$new_private_directory" --consent-pose --seconds 30
python -m research.collect label "$new_private_directory" --verified NO_FALL
python -m research.collect validate "$new_private_directory" --confirmed
python -m research.diagnostics replay --input "$new_private_directory/trace.jsonl" --checkpoint "$checkpoint"
```

Metadata chứa recording, subject, session, source, camera_setup, activity, split, consent và retention_days. Dùng bí danh, mã setup và mã nguồn riêng. Ví dụ (chỉ là mẫu, chưa có người đồng ý):

```json
{"recording":"trial-001","subject":"volunteer-a","session":"session-a","source":"lab-a","camera_setup":"setup-a","activity":"pick-up","split":"train","consent":false,"retention_days":14}
```

Thư mục mới quyền 0700, pose JSONL quyền 0600. Lưu trong thư mục riêng ngoài repo, trên Pi có thể dùng tmpfs. Ghi nhận hạn lưu trong manifest, người phụ trách xóa cả thư mục theo yêu cầu hoặc khi hết hạn. Không có xóa tự động, lưu RGB, upload hoặc thu nền. Xác minh thời điểm từng động tác ngoài CLI nếu cần. Nhãn NO_FALL hiện áp cho toàn trial.
