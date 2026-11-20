# PR-03 · Trạng thái nghiệm thu G3

| Mức | Trạng thái |
| --- | --- |
| G3-SUBSET | BLOCKED |
| G3-FULL | BLOCKED |

Pilot có 24 clip ưu tiên, gồm 12 Fall và 12 No Fall theo nhãn archive. Bốn clip có ít nhất một cửa sổ kỹ thuật 30 mẫu. Số nhãn Fall hoặc No Fall đã xác minh, nhóm độc lập, cửa sổ huấn luyện và split đã khóa đều là 0. Không có Dataset V2 hoặc SHA-256 của manifest huấn luyện. 38 clip đã được đo Lite/Full theo từng frame, chưa có tỷ lệ mất pose trong thời gian ngã đã được xác minh.

Giữ 96 clip còn lại trong hàng đợi. Mở rộng sau khi người xem kiểm tra video pilot, ghi annotation có provenance và xác minh lineage. Giữ clip ngắn cho nghiên cứu cửa sổ 10–20 mẫu. Chỉ chạy builder và khóa Test khi cả hai lớp có đủ nhóm độc lập cho ba tập. Chưa huấn luyện lại, thay model production hoặc sửa backend và cảnh báo.
