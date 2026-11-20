# PR-05.3 · Quyết định nghiên cứu

Giữ baseline cho nghiên cứu. Hysteresis chỉ đáng thử trên development mới vì giảm một alert muộn ở clip Fall nhưng chưa giảm FP khi cúi. Chưa có chính sách nào trong bốn cấu hình đủ căn cứ làm mặc định staging.

**BLOCKED_BY_DATA.** Chưa retrain. Thu hard negatives có đồng ý theo recording gồm cúi rồi đứng lên, cúi giữ lâu, nhặt vật ở nhiều khoảng cách, ngồi và nằm có chủ đích. Lấy nhiều người, bối cảnh và góc camera. Ghi provenance, khoảng hoạt động, visibility/missingness và tách Train/Validation theo subject và nguồn ghi. Chọn cấu hình trên Train/group-aware CV. Kiểm tra tiến cứu với nhóm mới và dữ liệu Fall có nhãn độc lập trước khi kết luận giảm FP vẫn giữ Recall. Không dùng Test V2.1.

**NOT_MEASURED.** Chưa chạy phiên người thật mới với trace. Trước khi thu, kiểm tra camera/preview, thông báo CAMERA READY, xin xác nhận loại dữ liệu, thời lượng, đường dẫn và cách xóa. Dùng trace metrics trước và chỉ thêm pose khi đồng ý. Chưa mở PR-06, không đổi model, threshold hay kênh cảnh báo production.
