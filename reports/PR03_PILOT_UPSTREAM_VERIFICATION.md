# PR-03 · Đối chiếu upstream cho bốn clip pilot

**Preflight chính thức tăng từ 0/4 lên 1/4 clip. G3 vẫn BLOCKED.** Chưa có đủ nhóm độc lập và hai lớp để tạo Train, Validation và Test.

## Đối chiếu hai clip Fall

Dùng B-MCFD commit `ffcb4d60e3ea491973434b248047eb40fa1b51ea`. Đã kiểm tra `segments_corrected.csv`, `camera_delay_corrected.csv` và tài liệu provenance. Hai AVI là bản của góc quay gốc tải qua mirror Montréal công khai. Endpoint trả bản AVI hoặc ZIP bọc AVI. Phép đo dùng bản AVI đã giải mã đủ frame. FFmpeg in cảnh báo macroblock trong quá trình giải mã nguồn, nên sai số được báo từ các khung đọc được. [Bảng phân đoạn](https://github.com/xiaoran007/B-MCFD/blob/ffcb4d60e3ea491973434b248047eb40fa1b51ea/data/metadata/segments_corrected.csv) · [Độ trễ camera](https://github.com/xiaoran007/B-MCFD/blob/ffcb4d60e3ea491973434b248047eb40fa1b51ea/data/metadata/camera_delay_corrected.csv) · [Mirror Montréal](https://www.kaggle.com/datasets/tuyenldvn/multiple-cameras-fall-dataset)

Trên cả 120 frame của mỗi clip, so sánh descriptor ảnh xám 48×32 và tìm điểm cắt liên tục theo bước 1 hoặc 4 frame. Điểm khớp tốt nhất là bước 4 ở cả hai clip, phù hợp AVI 120 FPS và MP4 30 FPS. Với mỗi frame Kaggle, đối chiếu độc lập trong phạm vi ±4 frame nguồn quanh phép ánh xạ. Cả 240 frame có điểm khớp gần nhất tại đúng vị trí dự đoán.

| Clip | Tệp nguồn | Frame nguồn đầu clip | Mean cosine error | Phương án khác gần nhất cách ít nhất 4 frame hoặc khác stride |
| --- | --- | ---: | ---: | ---: |
| S_F1_cam5 | chute01/cam5.avi | 840 | 0,00005052 | 0,005489 |
| S_F4_cam6 | chute04/cam6.avi | 320 | 0,00005357 | 0,010635 |

Công thức với chỉ số frame nguồn đếm từ 0 là `camera_frame = aligned_frame + delay_frames` và `clip_seconds = (camera_frame - offset) / 120`. Delay lần lượt là +23 và +82. Chuyển từng đoạn mã 2 riêng biệt, giữ hai lần ngã của scenario 4 tách nhau. Dùng timestamp của frame cuối theo convention khoảng bao gồm hai đầu. Độ lượng tử là 1 frame AVI (8,33 ms), còn hình ảnh clip chỉ hiện mỗi 33,33 ms. Sai số khớp cục bộ quan sát là 0 frame ở cả hai clip. Đây là sai số của phép căn khung, chưa xác định sai số gán mốc của tác giả. Không coi mốc bắt đầu đoạn tư thế tiếp theo là một mốc tiếp xúc đất đã đo. [Ngữ nghĩa căn timeline](https://github.com/xiaoran007/B-MCFD/blob/main/docs/metadata-semantics.md)

## Kết quả bốn clip

| Clip | Source group | Nhãn và mốc ngã trong clip | Chất lượng pose ở stride 3 | Trạng thái và bằng chứng |
| --- | --- | --- | ---: | --- |
| S_F1_cam5.mp4 | mcfd-chute01 | Fall 2,192–2,425 giây | 1 cửa sổ pose | UPSTREAM_VERIFIED. Khớp 120/120 frame. Đoạn mã 2 dài 0,233 giây, dưới ngưỡng hardening |
| S_F4_cam6.mp4 | mcfd-chute04 | Fall 0,417–0,633 và 3,025–3,333 giây | 3 cửa sổ pose | UPSTREAM_VERIFIED. Khớp 120/120 frame. Sự kiện đầu quá ngắn. Sự kiện thứ hai qua preflight, có 2 cửa sổ đạt quy tắc |
| B_D_0195.mp4 | Chưa xác minh | Ứng viên No Fall. Ảnh kiểm tra cho thấy người nằm trên giường | 1 cửa sổ pose | UNVERIFIED. Chưa có bản ghi nguồn hoặc nhãn do người xem xác nhận hết clip |
| B_D_0203.mp4 | Chưa xác minh | Ứng viên No Fall. Ảnh kiểm tra cho thấy người ngồi rồi nằm xuống giường | 4 cửa sổ pose | UNVERIFIED. Chưa có bản ghi nguồn hoặc nhãn do người xem xác nhận hết clip |

Không có mục HUMAN_VERIFIED. Sự kiện thứ hai của S_F4_cam6 có khoảng 0,308 giây theo mốc upstream. Kết quả preflight sát ngưỡng 0,3 giây và nhạy với việc thay đổi ranh giới annotation. Hai cửa sổ nominal bắt đầu ở 0,6 và 0,9 giây. Không gộp hay kéo dài nhãn sự kiện. So với trace 30 FPS, Lite và Full đều có pose trên 7/7 frame ở khoảng F1 và 10/10 frame ở lần ngã thứ hai của F4. Lite mất 1/6, Full mất 0/6 ở lần ngã đầu F4. Phạm vi này quá nhỏ để ước lượng tỷ lệ bỏ sót chung.

Đã đọc danh mục archive Figshare bằng byte range. Cấu trúc dùng thư mục subject/activity và tên video timestamp, chưa có đối chiếu tới hai mã B_D. Hai endpoint danh mục Fall Vision trên Harvard Dataverse trả HTTP 403. Vì vậy chưa gán nhóm hoặc subject cho hai clip theo tên. [Figshare v2](https://figshare.com/articles/dataset/Sensor-Based_Fall_Detection_Dataset_with_2017_Activities_from_29_Subjects/28596332/2) · [Fall Vision](https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/75QPKK)

## Rà soát và phương án thay thế

Bộ review cạnh dataset gồm `review-four-clips.html`, link video local, contact sheet, mốc upstream và form annotation. Hai file `*-alignment.json` ghi checksum, offset, khoảng đã ánh xạ, sai số và các ứng viên cạnh tranh. `pilot-preflight-with-evidence.json` ghi quyết định của quality gate theo từng sự kiện. Các dữ liệu này không nằm trong Git.

Nếu chưa lấy được lineage cho No Fall, ưu tiên ADL gốc có sequence ID và bảng timestamp của URFD, ví dụ `adl-01-cam0` và `adl-02-cam0`. Kiểm tra subject và chất lượng pose trước khi gán hai nhóm độc lập. Với Fall, ưu tiên thử góc gốc B-MCFD ở scenario khác có đoạn mã 2 dài hơn 0,3 giây, ví dụ scenario 6 có khoảng frame căn chỉnh 583–629. Tái trích pose và chạy preflight trên đúng phiên bản video gốc trước khi chấp nhận. [URFD chính thức](https://fenix.ur.edu.pl/mkepski/ds/uf.html)

Chưa tạo Dataset V2, chưa khóa Test và chưa mở PR-04.
