# PR-05.1 · Numerical parity

Desktop chạy lại 84 recording phát triển. So với PR-05, output JSON giữ nguyên trên 2.011 windows và 1.509 scores. Validation cùng 10 TP, 5 FN, 8 FP. Regression bổ sung gap, reconnect và model lỗi kiểm tra những đường dữ liệu không có trong replay tự nhiên.

So sánh liên thiết bị dùng các pose CSV development cùng checkpoint. Kiểm tra count, start/end, mask, SHA-256 tensor float32 little-endian, score tolerance tuyệt đối **1e-5**, tensor tolerance tuyệt đối **2e-5** khi có dump hai đầu, trạng thái/model errors và số score cách 0,5 tối đa 1e-5. Score gần threshold được đánh dấu và mọi khác biệt quyết định đều làm phép kiểm tra fail, kể cả chênh lệch score dưới tolerance. Nếu hash tensor khác, kết quả ghi sai khác và cần dump định lượng riêng. Không tự suy ra lỗi số học downstream từ hash.

```bash
export PYTHONPATH=fall_detect
python -m research.parity trace "$development_pose_csv" "$checkpoint" trace.json --include-tensors
python -m research.parity compare desktop-trace.json pi-trace.json --include-tensors
```

Giữ file sidecar schema cùng CSV khi chuyển. Chạy với JSON mới. Test V2.1 giữ khóa.
## Kết quả Pi đối chiếu desktop

| Clip | Windows | Hash tensor khác | Max Δ tensor | Max Δ score | Score gần 0,5 | Decision khác |
|---|---:|---:|---:|---:|---:|---:|
| FallForwardS6 | 28 | 11 | 2.38e-07 | 5.96e-08 | 0 | 0 |
| FallLeftS7 | 29 | 7 | 1.19e-07 | 1.19e-07 | 0 | 0 |
| SitDownS9 | 34 | 26 | 2.38e-07 | 1.49e-08 | 0 | 0 |

Parity trong tolerance đạt trên batch. Mọi mask và timestamp khớp nếu structural mismatch bằng 0 (0 mismatch). Kiểm thử fixture riêng xác nhận một event flip vẫn fail dù score chênh dưới tolerance.
