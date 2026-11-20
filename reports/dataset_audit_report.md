# PR-03 · Kiểm kê dữ liệu trong workspace

Video ID trong bảng là đường dẫn cục bộ dùng để kiểm kê. Chưa có metadata xác nhận ID nguồn, bộ nguồn hoặc người tham gia cho bảy clip. Nhãn theo thư mục chỉ là gợi ý. Không có manifest nhãn cho bốn clip demo. Không tạo bộ Train/Validation/Test từ các clip này.

| Video | Nhãn theo thư mục | Kích thước | FPS ghi trong video | Khung trích xuất | Khung không có pose | Điểm thiếu hoặc visibility < 0,3 |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| fall_detect/sample_videos/fall_example_1.mp4 | Chưa có | 640×360 | 1199/50 | 272 | 0 | 120 |
| fall_detect/sample_videos/fall_example_2.mp4 | Chưa có | 1280×720 | 30/1 | 122 | 0 | 87 |
| fall_detect/sample_videos/fall_example_3.mp4 | Chưa có | 960×540 | 30/1 | 88 | 2 | 141 |
| fall_detect/sample_videos/fall_example_4.mp4 | Chưa có | 1280×720 | 30/1 | 120 | 0 | 96 |
| fall_detect/sample_videos/fall/20240912_101331.mp4 | fall | 1920×1080 | 30/1 | 56 | 0 | 37 |
| fall_detect/sample_videos/fall/20240912_114002.mp4 | fall | 1920×1080 | 30/1 | 56 | 10 | 170 |
| fall_detect/sample_videos/no_fall/B_D_0017.mp4 | no_fall | 1920×1080 | 120/1 | 360 | 0 | 102 |

MediaPipe Lite đọc 1.074 khung hình, trong đó có 12 khung không có pose và 753 điểm thiếu hoặc visibility thấp. Timestamp do extractor xuất tăng nghiêm ngặt và landmark không có NaN/Inf trong lượt kiểm tra. Extractor PR-02 có fallback theo FPS, nên kết quả này chưa xác minh timestamp thô của video. Chưa có số sequence huấn luyện theo video vì thiếu annotation và split gốc.

## Checksum video

| Tên video | SHA-256 file | SHA-256 track hình giải mã |
| --- | --- | --- |
| fall_example_1.mp4 | e56e913b1f25ac729706f14e5dd10075486502df255f4264848fa55118444554 | 09ff0b22ffa69ab800222c532e05e9a7097cbcb3d7fc1a928ab51a6235f9cfd2 |
| fall_example_2.mp4 | f5465d2026051e583c7822fd7afe20dc919bd166400ca57204e23a6fb415b15e | 2d35d1246c19548e66a71e1d94c62755525245ed04c42b183cef2a3be08ed0dd |
| fall_example_3.mp4 | 3c3b0a93abe26f70ee2b46664dc06c65da0854c0a070389c051d2b2028cafa66 | 1e49aeead914fe7fa085b45233cf25b329a48d9c43e07f6c9866f5eb2f94a0c1 |
| fall_example_4.mp4 | 66eb756c6e574f52f7f4f87fb6dd6a5643e381f9ae780bd2a2dece6ef5518b84 | 311ff38db95181d59a8765d9b7a97239d225cf7cd17f88aa3713b55d9ea96605 |
| 20240912_101331.mp4 | dd25557649524498a975e62383096b827521fc4c22c55c74a8a76f3636d93a41 | 3d33fbbf2135d93bde3e1d46b8f935a68e0710730d0dbaaac5ddeb692a62f113 |
| 20240912_114002.mp4 | d2c2b0e27f4c3b23b65c429db73c30863dec539278deed5689e6c6e0b67cbe30 | bd258face29782648a522209ec9ce2003b0f252de36497279da0483878e56634 |
| B_D_0017.mp4 | 91e977ac5392aae1740f4a633cd0e2d1edff1e8fc07909fac74eb50f94923f05 | 2c75b3ff05dc4b66a1290157a5929c72e43f10fc9ede00a617da94075cebe54f |

Không có hai checksum file hoặc track hình giải mã giống nhau.

## CSV báo cáo lỗi

Có 581 dòng lỗi với 492 tiền tố tên video. 36 tiền tố xuất hiện ở cả Validation và Test. Xem [báo cáo rò rỉ](PR03_LEAKAGE_REPORT.md) để biết giới hạn của bằng chứng. Không còn CSV keypoint, NPY hay metadata nguồn trong checkout để xác nhận hash sequence, số người, số cửa sổ theo video, tỷ lệ lớp hoặc mức giao nhau giữa cửa sổ ở tập gốc.
