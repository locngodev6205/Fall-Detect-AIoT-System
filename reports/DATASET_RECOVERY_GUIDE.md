# PR-03 · Khôi phục và chuẩn bị dữ liệu

**Trạng thái G3 — BLOCKED_DATA_LINEAGE.** Đã xác định nguồn video công khai và xác minh hai clip local bằng SHA-256. Chưa lấy được bản NPY lịch sử qua Kaggle và chưa có bảng nối từng video với nhóm nguồn cùng khoảng thời gian té ngã. Chưa tạo Dataset V2 cho huấn luyện.

## Nguồn đã truy ra

| Nguồn | Bằng chứng | Dùng để làm gì |
| --- | --- | --- |
| `payutch/fall-video-dataset` v1, Kaggle dataset ID `7359021` | README dataset và README upstream cùng trỏ đến nguồn này. API Kaggle trả 13.976 mục trong 70 trang | Phục hồi video thật. CSV đi kèm thuộc pipeline cũ |
| `/kaggle/input/fall-dataset6` | Bản notebook tiếng Việt ở Git commit `c9ca3f0` và các notebook Bi-LSTM, LSTM, Transformer cũ | Khôi phục split NPY 30 mẫu và kiểm tra lịch sử |
| `/kaggle/input/datasets/locngodev/fall-dataset` | Đường dẫn từng NPY trong CSV phân tích lỗi của lần export model | Đối chiếu run đã xuất báo cáo. Cần đọc Input gốc để xác nhận phiên bản |
| `/kaggle/input/fall-dataset60` | Notebook Transformer 60 mẫu, Kaggle dataset ID `7602418`, datasetVersion ID `12077194` | Lịch sử model 60 mẫu, tách khỏi bộ 30 mẫu |

Metadata Kaggle được lưu trong notebook là đầu mối chính xác hơn tên mount:

| Notebook lịch sử | Kaggle dataset ID | Kaggle datasetVersion ID |
| --- | ---: | ---: |
| `fall-detection-d6-bi-lstm-v1.ipynb` | 7471210 | 11886901 |
| `fall-detection-transformer-f1-v1.ipynb` | 7577493 | 12041864 |
| `fall-detection-transformer-aug-v1.ipynb` | 7604458 | 12080007 |
| `fall-detection-d6-lstm-v1.ipynb` | Không ghi | Không ghi |

Cùng tên mount và cùng số mẫu vẫn có thể là các artifact khác nhau. Các số datasetVersion ID là mã nội bộ trong metadata, không phải số phiên bản hiển thị dùng cho tham số CLI.

Nguồn video công khai được nhà xuất bản mô tả là bản tổng hợp từ Fall Vision, bộ video Figshare của Ivan Ursul và Multiple Cameras Fall Dataset. Danh sách file Kaggle chỉ có video và CSV keypoint. Không thấy file manifest nhóm hay annotation thời điểm ngã trong danh sách công khai. Kho Figshare v2 liệt kê một archive `VideoDataset.zip`, chưa kiểm kê nội dung bên trong. Harvard Dataverse và trang bộ Montréal chưa mở được trong phiên này. Montréal có tài liệu kỹ thuật và bản đính chính cho khoảng khung hình cùng độ trễ camera. Chỉ áp dụng sau khi xác minh đúng scenario, camera và timeline của file tương ứng. [Kaggle nguồn video](https://www.kaggle.com/datasets/payutch/fall-video-dataset) · [README dự án upstream](https://github.com/punpayut/Fall-Detection) · [Fall Vision](https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/75QPKK) · [Figshare v2](https://figshare.com/articles/dataset/Sensor-Based_Fall_Detection_Dataset_with_2017_Activities_from_29_Subjects/28596332/2) · [Báo cáo Montréal](https://www-labs.iro.umontreal.ca/~labimage/Dataset/technicalReport.pdf) · [Đính chính Montréal](https://www.iro.umontreal.ca/~labimage/Dataset/Erratum-MCF.pdf)

## Thống kê và bằng chứng hiện có

| Nguồn | Fall | No Fall | Tổng |
| --- | ---: | ---: | ---: |
| Video Kaggle v1 theo thư mục | 3.140 | 3.848 | 6.988 |
| CSV Kaggle v1 theo thư mục | 3.140 | 3.848 | 6.988 |
| NPY 30 mẫu lịch sử, Train | 5.722 | 6.279 | 12.001 |
| NPY 30 mẫu lịch sử, Validation | 1.226 | 1.346 | 2.572 |
| NPY 30 mẫu lịch sử, Test | 1.226 | 1.346 | 2.572 |

Số NPY lấy từ output đã lưu của notebook. Tổng 17.145 cửa sổ trước augmentation. Notebook Transformer augmentation ghi 24.002 mẫu Train sau khi nhân bản. Chưa đối chiếu byte các NPY hoặc split thực tế từ Kaggle. Kho công khai có khoảng 16,50 GB file chưa nén theo API, trong đó khoảng 15,79 GB video và 0,70 GB CSV.

- Hai file local `Fall/Raw_Video/20240912_101331.mp4` và `No_Fall/Raw_Video/B_D_0017.mp4` khớp SHA-256 với bản tải trực tiếp từ Kaggle. Đây là đường dẫn trong archive, không phải đường dẫn trong checkout.
- **492/492 tiền tố video** trích từ CSV lỗi cũ xuất hiện trong danh mục video Kaggle. 452/511 cặp tiền tố và nhãn khớp đúng thư mục lớp. Các dòng không khớp lớp mang hậu tố `nofall_pre` hoặc `nofall_post`. Hậu tố gợi ý cửa sổ No Fall lấy từ đoạn trước hoặc sau sự kiện. Cần lineage và timestamp gốc để xác nhận.
- **1.892 stem** xuất hiện ở cả hai thư mục Fall và No Fall trong kho công khai. Dùng đường dẫn đầy đủ và checksum để định danh file. Dùng chung group khi metadata xác nhận hai clip thuộc cùng lần ghi hoặc cùng scenario nhiều camera.
- Báo cáo lỗi lịch sử có 36 tiền tố video xuất hiện ở cả Validation và Test, trong đó 31 tiền tố xuất hiện ở cả hai tập dưới cùng một nhãn báo cáo. Đây là dấu hiệu cần so với manifest gốc. Tên trùng không chứng minh hai file có cùng nội dung.
- Đã rà checkout, lịch sử Git có sẵn, thư mục tải xuống Linux và Windows, cache Kaggle và nội dung các archive ứng viên. Checkout vẫn chỉ có bảy video mẫu và CSV báo cáo lỗi. Chưa tìm được bản sao local của bộ train.
- Endpoint danh sách file cho slug ứng viên `locngodev/fall-dataset6`, `locngodev/fall-dataset` và `locngodev/fall-dataset60` đều trả HTTP 403, kể cả với cấu hình Kaggle local. Kết quả này chưa phân biệt được slug sai, quyền truy cập hay thông tin đăng nhập hết hạn.

## Kiểm tra pipeline trên hai video đã xác minh

| Video | Khung đọc được | Khoảng thời gian quan sát | Cửa sổ hợp lệ khi chạy thử extractor |
| --- | ---: | ---: | ---: |
| 20240912_101331.mp4 | 56 | 1,833 giây | 0 |
| B_D_0017.mp4 | 360 | 2,992 giây | 1 |

Hai clip đã chạy qua extractor và công cụ tạo cửa sổ `annha-pose-v2` trong thư mục tạm. Kết quả chỉ kiểm tra pipeline, chưa gán split hay dùng làm dữ liệu train. 19 bài kiểm thử G3, schema và audit đều đạt. Kiểm thử phần mềm chưa xác nhận G3 trên dataset thật.

## Khôi phục bản lịch sử và lấy video gốc

1. Mở notebook cũ trong tài khoản Kaggle từng chạy hoặc được chia sẻ. Trong phần Input của **đúng version notebook**, mở từng dataset đính kèm và ghi URL `owner/slug`, số version hiển thị, dataset ID và datasetVersion ID. Nếu không còn quyền, nhờ chủ sở hữu chia sẻ đúng version hoặc xuất archive cùng các manifest split và script tạo nhãn trước/sau ngã. Giữ bản NPY lịch sử ở thư mục riêng để đối soát.
2. Với video công khai, dùng dataset `payutch/fall-video-dataset/1`. Tải vào ổ đủ chỗ cho archive, dữ liệu giải nén và CSV mới. Giữ checksum archive để truy vết. Ví dụ chạy trong Bash với Kaggle CLI đã đăng nhập. [Tài liệu Kaggle CLI](https://github.com/Kaggle/kaggle-cli/blob/main/docs/datasets.md)

```bash
work=/data/annha-recovery
mkdir -p "$work/downloads" "$work/raw-payutch-v1" "$work/metadata" "$work/legacy-npy"

kaggle datasets files payutch/fall-video-dataset/1 --page-size 20
kaggle datasets download payutch/fall-video-dataset/1 -p "$work/downloads"
sha256sum "$work/downloads/fall-video-dataset.zip" > "$work/metadata/payutch-v1-archive.sha256"
unzip -n "$work/downloads/fall-video-dataset.zip" -d "$work/raw-payutch-v1"

# Chạy sau khi xác nhận đúng URL và số phiên bản trong Input của notebook.
kaggle datasets download 'OWNER/SLUG/VERSION' -p "$work/legacy-npy"
```

Luồng lịch sử trong repo dùng `fall_detect/utils/extract_keypoint.py` → `process_csv_data.py` → `split_dataset.py`. Biến thể 60 mẫu dùng `utils/timesteps60/extract_keypoint.py` → `create_seq.py` → `split_dataset_v2.py`. Các script split cũ chọn theo sequence sau khi tạo cửa sổ. Chỉ dùng chúng để đọc lại lịch sử. Quy trình V2 dùng builder chia theo group.

## Chuẩn bị metadata và đưa qua PR-03

Lưu bảng nguồn cùng dữ liệu dưới cấu trúc sau. Hai thư mục Raw_Video trong nhánh staging là symlink. Extractor chỉ ghi CSV mới vào staging.

```text
annha-recovery/
  raw-payutch-v1/
    Fall/Raw_Video/
    Fall/Keypoints_CSV/
    No_Fall/Raw_Video/
    No_Fall/Keypoints_CSV/
  metadata/
    annotations-original/
    sources.csv
  legacy-npy/
  stage-pose-v2/
    Fall/Raw_Video -> raw-payutch-v1/Fall/Raw_Video
    No_Fall/Raw_Video -> raw-payutch-v1/No_Fall/Raw_Video
    Fall/Keypoints_CSV_v2/
    No_Fall/Keypoints_CSV_v2/
  annha-v2/
    manifest.json
    sequences/
```

Tạo `metadata/sources.csv` bằng metadata có thể xác minh. Mỗi dòng đại diện một video hoặc một clip đã có lineage.

```csv
video_id,source_file,keypoint_csv,label,source_dataset,subject_id,source_group,event_start,event_end,scene_id,camera_id,annotation_version
```

- `video_id` duy nhất, lấy theo ID được nhà cung cấp xác nhận. Nếu chỉ có danh mục Kaggle, dùng đường dẫn đầy đủ có namespace và version làm ID của **file đang xử lý**, rồi ghi ID video gốc đã xác minh vào `source_group` khi có. Không dùng mỗi stem.
- `source_file` và `keypoint_csv` dùng đường dẫn tuyệt đối hoặc tương đối với thư mục `metadata`. Chọn CSV mới ở `Keypoints_CSV_v2`, có tên theo mẫu `<tên-video>.mp4_keypoints.csv` đối với MP4.
- `label` là `fall` hoặc `no_fall`, đối chiếu nhãn gốc. Để trống `subject_id` nếu thiếu căn cứ. Các lần quay cùng người chỉ được gom theo subject ID đã xác minh. Các góc quay hoặc đoạn cắt cùng sự kiện giữ chung `source_group`.
- Với Fall, `event_start` và `event_end` là giây trên timeline của **clip đang xử lý**. Đối chiếu PTS hoặc timestamp của CSV v2, đồng bộ camera, FPS và điểm cắt trước khi chuyển annotation từ frame sang giây. No Fall để trống hai cột sự kiện. Lưu bản annotation gốc và phiên bản đã dùng. Nếu nguồn thiếu thời điểm ngã, cần gán nhãn có kiểm tra trên video hoặc loại có ghi lý do khỏi bản build. Không gán cả thời lượng clip là Fall để vượt validate.
- Một số clip dưới 2,9 giây hoặc thiếu pose có thể không đủ 30 mẫu hợp lệ ở 10 Hz. Builder sẽ báo lỗi theo video. Ghi lại các clip bị loại và tỷ lệ lớp còn lại trước khi chạy build tiếp. Với nhiều sự kiện trong một video, lập clip có annotation riêng cùng một `source_group`.

Từ thư mục repository, chạy với Python đã có môi trường Edge/ML và FFmpeg. Sau bước trích xuất, hoàn tất `sources.csv` trước khi build.

```bash
work=/data/annha-recovery
stage="$work/stage-pose-v2"
mkdir -p "$stage/Fall" "$stage/No_Fall"
ln -s "$work/raw-payutch-v1/Fall/Raw_Video" "$stage/Fall/Raw_Video"
ln -s "$work/raw-payutch-v1/No_Fall/Raw_Video" "$stage/No_Fall/Raw_Video"

python fall_detect/utils/extract_keypoint.py --canonical --dataset "$stage"

# Sau khi sources.csv đã đầy đủ nhãn và thời gian sự kiện.
set -o pipefail
python scripts/ml/dataset_v2.py build "$work/metadata/sources.csv" "$work/annha-v2" \
  --version v2.0 --seed 42 | tee "$work/metadata/build-stats.json"
python scripts/ml/dataset_v2.py verify "$work/annha-v2" --verify-sources \
  | tee "$work/metadata/verified-stats.json"
PYTHONPATH=fall_detect python -m pytest -q \
  fall_detect/tests/test_dataset_integrity.py \
  fall_detect/tests/test_feature_schema_v2.py \
  fall_detect/tests/test_dataset_audit.py
```

Builder chia nhóm trước khi tạo cửa sổ, kiểm tra hash video và video giải mã, bỏ bản sao có cùng annotation, và dừng khi nhãn bản sao mâu thuẫn. Validator kiểm tra hash, nhóm, tensor trùng giữa các tập và khả năng tái lập split từ seed. Kiểm tra bổ sung các bản đã cắt hoặc nén lại bằng lineage vì hash có thể khác. Chỉ augment Train sau khi chốt split. Chỉ mở Test để đánh giá model đã khóa.

**Bằng chứng cần để đóng G3** gồm `manifest.json`, SHA-256 dataset, thống kê video và cửa sổ theo lớp và split, danh sách clip bị loại cùng lý do, và kết quả verify trên bộ dữ liệu thật. Chưa huấn luyện model, cập nhật production hoặc bắt đầu PR-04.
