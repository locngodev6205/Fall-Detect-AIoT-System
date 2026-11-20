# PR-03 · Nghiệm thu G3

**Dataset verification đạt. G3-SUBSET đang REVIEW_REQUIRED. G3-FULL chưa đạt.** Subset có 18 video, 15 nhóm và 98 cửa sổ được kiểm chứng. Hai lớp hiện diện trong từng tập. Test chỉ có một recording mỗi lớp và chưa xác minh độc lập theo người. Kết quả phù hợp để trình nghiệm thu một subset nghiên cứu, với độ bất định cao nếu dùng để ước lượng hiệu năng thực tế.

## Duyệt subset

Manifest ghi `g3_eligible=true` để xác định đầu vào có thể được trình duyệt. Trạng thái `REVIEW_REQUIRED` yêu cầu phê duyệt riêng. Sau khi người review kiểm tra nguồn, nhãn, kết quả kiểm thử và chấp nhận giới hạn, chạy từ repo:

```bash
python scripts/ml/dataset_v2.py approve-subset \
  ../annha-recovery-payutch-v1/verified-expansion-v2/annha-v2.0 \
  --sha256 70ada1f05bbac20af1d2548fa43d1d4cb6bf3abac926fcc9f146914ae53c8b62 \
  --reviewer '<người duyệt>' --evidence '<tham chiếu biên bản>'
```

Lệnh xác minh lại nguồn và ghi biên nhận local gắn với digest và nhóm Test. Loader chính thức kiểm tra biên nhận, digest dự kiến và `purpose=final_evaluation` khi mở Test. Biên nhận phục vụ truy vết quyết định trong workspace. Quyền ghi thư mục dataset vẫn cần được quản lý ở hệ thống tệp.

## Phần còn thiếu

Muốn đánh giá chính thức, bổ sung recording độc lập cho cả hai lớp và thu thập ánh xạ subject do nguồn công bố hoặc thông tin kiểm chứng khi thu thập mới. Bổ sung ADL từ môi trường thứ hai để có thể kiểm tra cross-source hai lớp. Cần định số recording cho từng lớp theo độ rộng khoảng tin cậy mong muốn trước khi khóa Test mới. Với hiện trạng, tối thiểu cần thêm một recording độc lập mỗi lớp chỉ để Test có nhiều hơn một recording mỗi lớp. Mức đó vẫn quá nhỏ để kết luận production.

Không mở PR-04 trong đợt này.

## Kết quả kiểm thử

Bộ pytest Edge trong worktree review đạt **51/51**. Regression test kiểm tra Test bị từ chối khi thiếu phê duyệt hoặc digest không đúng, và đường đọc sau khi bộ fixture được duyệt. Dataset thật đã qua `verify --verify-sources`. Trạng thái của dataset thật tiếp tục là `REVIEW_REQUIRED`.
