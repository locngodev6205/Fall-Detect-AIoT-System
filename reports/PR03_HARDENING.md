# PR-03 · Hardening sau review

Mốc đối chiếu là commit `14c7d4e2f16175a76441ec5f241cb246d0fb2ed2`. Chính sách dưới đây thay cho quy tắc giao khoảng ngã trong các báo cáo PR-03 trước đó.

## Quy tắc nhãn cửa sổ

Cửa sổ gồm 30 mẫu tại 10 Hz cách 2,9 giây giữa hai mẫu ngoài cùng. Với Fall, cửa sổ phải chứa mốc bắt đầu ngã và ít nhất 3 mẫu trên lưới trong khoảng sự kiện. Mức giao tối thiểu bằng `max(0.3, min(0.6, (event_end - event_start) / 2))` giây. Giá trị này là chính sách bảo thủ được cố định cho lượt build hiện tại. Hiệu quả của mốc 0,3–0,6 giây cần được đánh giá sau khi có nhãn đủ tốt. Cả 30 mẫu phải có pose chuẩn hóa hợp lệ. Khoảng Fall dưới 0,3 giây không đủ qua quy tắc này.

Cửa sổ chỉ chạm biên, thiếu thời lượng giao, bắt đầu sau mốc ngã hoặc thiếu pose bị bỏ qua. Các cửa sổ bị bỏ không được chuyển thành No Fall. No Fall chính thức phải đến từ clip có nhãn No Fall đã xác minh.

## Preflight, nhóm và cổng Test

`dataset_v2.py preflight sources.csv` chạy mặc định ở chế độ chính thức. Lệnh trả video đủ điều kiện và lý do loại từng video. Builder chạy cùng preflight trước khi chia split. Dùng `--preflight-report preflight.json` để lưu kết quả ngay cả khi không đủ nhóm để chia. Các lý do gồm sai hash hoặc metadata nguồn, thiếu provenance, lỗi CSV/timestamp, clip quá ngắn, thiếu pose liên tục và thiếu bằng chứng trong khoảng ngã.

Bổ sung các cột sau vào `sources.csv` cho bộ chính thức:

| Cột | Yêu cầu |
| --- | --- |
| `provenance_status`, `source_ref`, `expected_video_sha256` | Trạng thái `VERIFIED`, tham chiếu nguồn và SHA-256 đã kiểm tra. Builder tính lại hash video và so với sidecar keypoint |
| `source_group`, `group_status`, `group_evidence` | ID nhóm, trạng thái `VERIFIED` và bằng chứng cùng lần quay hoặc phiên ghi |
| `annotation_status`, `annotation_source`, `reviewer` | `HUMAN_VERIFIED` hoặc `UPSTREAM_VERIFIED`, kèm nguồn và người chịu trách nhiệm đối chiếu |
| `event_start`, `event_end` | Bắt buộc với Fall. Hai mốc tính theo giây trên chính clip hiện tại |
| `cross_source_group`, `cross_source_evidence` | Tùy chọn, dùng cùng mã khi xác nhận một sự kiện xuất hiện ở nhiều bộ nguồn và có bằng chứng đối chiếu |

`source_group` và subject ID được hiểu trong phạm vi `source_dataset`. ID nhóm trùng tên ở hai nguồn không tự gộp. Trùng byte, trùng khung hình giải mã và liên kết liên nguồn đã xác minh vẫn gộp nhóm. Clip bị loại vì pose hoặc CSV vẫn có thể nối hai nhóm nếu chứng cứ nguồn của clip đó đủ. Verifier tái lập split từ seed và kiểm tra lại chính sách nhãn, provenance, preflight và khóa Test.

`--mode research` cho phép tạo bộ thăm dò khi thiếu metadata. Bộ nghiên cứu có `g3_eligible=false`, `g3_status=BLOCKED_RESEARCH_ONLY`, không khóa Test chính thức và loader chỉ mở split Test với `purpose='research_evaluation'`. Bộ chính thức qua gate vẫn có `g3_status=REVIEW_REQUIRED` cho đến khi có nghiệm thu thực tế. Manifest cũ cần build lại để áp dụng chính sách mới.

## Kết quả pilot

Đã đối chiếu SHA-256 của bốn clip nguồn và trích lại keypoint bằng Lite, 10 Hz, 30 mẫu, stride 3.

| Clip | Nhãn thư mục | Cửa sổ pose kỹ thuật | Preflight chính thức |
| --- | --- | ---: | --- |
| S_F1_cam5 | Fall | 1 | Thiếu mốc ngã đã xác minh và bằng chứng nhóm nguồn |
| S_F4_cam6 | Fall | 3 | Thiếu mốc ngã đã xác minh và bằng chứng nhóm nguồn |
| B_D_0195 | No Fall | 1 | Thiếu xác minh nhãn và lineage |
| B_D_0203 | No Fall | 4 | Thiếu xác minh nhãn và lineage |

**0/4 clip chính thức đủ điều kiện.** Chín cửa sổ là kiểm tra pose trên dữ liệu thật, chưa gán nhãn hay chia tập. Phiếu rà soát, preflight JSON và CSV pose mới nằm ở `annha-recovery-payutch-v1/hardening-pilot-preflight` ngoài Git. Khi xem hai clip Fall, nhập mốc thực vào công cụ annotation và lưu lịch sử. Với No Fall cần xem trọn clip và xác nhận nhãn. Cả bốn cần bằng chứng nhóm độc lập trước khi vào bộ chính thức. Chưa có Dataset V2, khóa Test hoặc G3 PASS.

## Tương thích Edge

Regression so sánh offline với `PoseSampler` khi mất frame, mất pose và có khoảng gián đoạn timestamp dài. Các đoạn pose liên tục và tensor hợp lệ khớp nhau. Offline giữ đầy đủ mẫu trống ở khoảng gián đoạn. Edge thu gọn khoảng trống thành tín hiệu reset để tránh xử lý một chuỗi mẫu rỗng dài. Hai đường cùng cắt cửa sổ tại chỗ gián đoạn. Timestamp lặp bị từ chối. Không đổi sampler hoặc preprocessing production.
