# KẾ HOẠCH TRIỂN KHAI CHO CODING AGENT
## Fall-Detect-AIoT-System — nâng độ tin cậy nhận diện ngã trên Raspberry Pi 4

**Repository:** https://github.com/locngodev6205/Fall-Detect-AIoT-System
**Nhánh nguồn để kiểm tra:** `main` (lấy commit SHA thực tế khi bắt đầu).
**Tài liệu đầu vào:** `01_huan_luyen_transformer_fall_detection_aug.ipynb` và `results.zip` do chủ dự án cung cấp.
**Đối tượng:** Coding agent có quyền đọc/sửa/test repository, chạy huấn luyện khi có dataset và benchmark khi có Raspberry Pi 4.
**Mức ưu tiên:** Độ tin cậy cảnh báo > Recall sự kiện ngã > False alarms > Độ trễ > FPS > Kích thước model.
**Nguyên tắc:** Không hứa “phát hiện chính xác 100%”; không dùng test set để điều chỉnh threshold/hyperparameter; không tuyên bố hoàn thành những việc chưa chạy được.

---

## 0. Lệnh giao việc tổng quát cho agent

Bạn là **ML Engineer + Edge AI Engineer + Python QA Engineer** của dự án. Hãy thực hiện kế hoạch theo thứ tự phụ thuộc từ **P0 → P1 → P2**, tạo từng thay đổi nhỏ có unit/integration tests, ghi lại các phép đo thật, và chuẩn bị mã chạy được trên Raspberry Pi 4. **Không chỉ phân tích, hãy sửa code và tạo sản phẩm kiểm thử được**. Không tự tạo dữ liệu/metric giả để đánh dấu hoàn tất; nếu thiếu dataset/Kaggle/Pi/thiết bị thì triển khai phần có thể làm, ghi rõ `BLOCKED`, các lệnh cần chạy và dữ liệu cần bổ sung. Không đẩy model chưa được xác nhận lên đường dẫn production. Không ghi đè hiện vật gốc và không gửi alert thật trong test.

**Đầu ra cuối:** pull request/commit theo giai đoạn, `docs/ml/BASELINE_AUDIT.md`, `docs/ml/DATASET_AUDIT.md`, `docs/ml/EVALUATION_REPORT.md`, `docs/edge/RPI4_BENCHMARK.md`, manifest model, test suite và runbook deployment/rollback.

---

## 1. Thực trạng được xác nhận và rủi ro cần xử lý

### 1.1 Baseline từ kết quả được cung cấp (đo theo sequence, KHÔNG phải event)

| Mục | Giá trị | Ghi chú |
|---|---:|---|
| Accuracy Test | **88,37%** | Theo báo cáo/ma trận kết quả đã xem |
| Fall recall Test | **89,07%** | 1.092 / (1.092 + 134) |
| Fall F1 Test | **~87,98%** | Sequence-level |
| TP / TN / FP / FN Test | **1.092 / 1.181 / 165 / 134** | 2.572 sequence |
| Validation FP / FN | **160 / 122** | Từ `error_analysis_report.csv` |
| Test FP / FN | **165 / 134** | Từ `error_analysis_report.csv` |
| TFLite trong ZIP | **469.788 bytes** | SHA-256: `3349de9f88dbcf4119c5754e76a228b89cc31d763d013fe145f3bf32e4ea4b9d` |
| TFLite ở repo (lúc kiểm tra) | **320.912 bytes** | Khác kích thước; xác minh SHA lúc triển khai |
| Input của notebook | **(30, 51)** | 30 frame × 17 khớp × (x,y,confidence/visibility) |
| Transformer | **3 Encoder blocks; 4 heads; d_model=64** | Kèm dropout, augment, 5-fold CV |

**Giới hạn diễn giải:** `error_analysis_report.csv` chỉ chứa các sequence sai; không đủ để đánh giá độc lập toàn bộ phân phối xác suất, hay event-level recall / false alarms per hour. Thư mục dataset của notebook (`/kaggle/input/fall-dataset6/...`) còn khác đường dẫn xuất hiện trong CSV lỗi (`/kaggle/input/datasets/locngodev/fall-dataset/...`). Cần xác minh lineage trước khi quy kết kết quả cho dữ liệu nào.

### 1.2 Điểm nghi vấn/bug đã đọc trong repo + notebook

| ID | Tệp/đoạn | Vấn đề | Hành động |
|---|---|---|---|
| R01 | `fall_detect/edge/main_edge.py` `_on_fall` và `fall_detect/modules/detector.py` | Callback `_on_fall(confidence, **kwargs)` nhận 1 positional, còn `FallDetector.update()` gọi `on_fall_alert(raw_fall_prob, confidence_pct_str)` bằng 2 positional; có thể gây `TypeError` và mất alert | **P0 — sửa hợp đồng callback + test** |
| R02 | `fall_detect/utils/extract_keypoint.py` | 5 điểm mặt dùng indices `[0,1,2,3,4]` nhưng tên `Nose, Left Eye, Right Eye, Left Ear, Right Ear` cần mapping MediaPipe `[0,2,5,7,8]` | **P0/P1 — xác minh dữ liệu gốc, sửa extractor, retrain nếu dữ liệu cũ sai** |
| R03 | `fall_detect/utils/split_dataset.py` và `fall_detect/utils/timesteps60/split_dataset_v2.py` | Split theo sequence `.npy`, không group theo video/subject; cửa sổ chồng lấn có thể rò rỉ Train/Val/Test | **P0/P1 — group split + manifest + audit** |
| R04 | Notebook cell augment + CV | Augmentation trước `StratifiedKFold` khiến mẫu gốc/augment có thể nằm hai fold; sửa thành augment **bên trong train fold** | **P1** |
| R05 | `fall_detect/utils/extract_keypoint.py`, notebook normalization, `fall_detect/modules/skeleton.py` | Extractor lưu pixel `lm.x * width`, `lm.y * height` trong khi online dùng 0–1; chuẩn hóa theo delta Y thân người có thể sai/thổi nhiễu | **P1 — đặc tả canonical preprocessing** |
| R06 | `fall_detect/utils/process_csv_data.py` | Pivot dataframe `values=['X','Y','Confidence']` rồi `.values`: phải kiểm tra thứ tự cột thực tế có phải `[x,y,c]` cho từng keypoint hay không; không mặc định | **P1 — test thứ tự 51 đặc trưng** |
| R07 | Notebook `augment_sequence` | Gaussian jitter áp dụng trên `seq[:, :51]`, vô tình thêm noise vào `confidence` dù `enable_confidence_noise=False` | **P1 — fix + test augmentation** |
| R08 | `fall_detect/config.py` | Default threshold **0.85** khác ngưỡng tối ưu suy từ CSV **~0.36**; không copy 0.36 sang Pi một cách mù quáng | **P0/P1 — threshold thuộc model manifest** |
| R09 | `fall_detect/modules/detector.py` | Xóa toàn bộ buffer khi `person_present=False`; dễ mất cú ngã lúc pose bị khuất | **P1 — xử lý pose-lost, stale state** |
| R10 | `fall_detect/modules/detector.py` | Immobility tính từ tọa độ đã mid-hip-center; không phân biệt chính xác *nằm bất động* với đứng/ngồi yên | **P1 — không dùng immobility làm bằng chứng duy nhất; kiểm tra tư thế** |
| R11 | `fall_detect/detect.py` vs `fall_detect/edge/main_edge.py` | MediaPipe `model_complexity=1` vs `0`; cần đo đánh đổi accuracy vs FPS | **P2** |
| R12 | Model TFLite ở `results.zip` khác file repo | Có rủi ro nhầm checkpoint giữa kết quả train và triển khai | **P0 — hash, provenance, parity test** |

**Yêu cầu xác minh:** Đây là danh sách tìm thấy khi review, không phải kết luận mọi dataset đều đã mắc lỗi tương ứng. Agent phải chứng minh bằng testcase/manifest, đối chiếu đúng pipeline thực tế, rồi sửa. Nếu không xác minh được, ghi `UNVERIFIED` thay vì tự khẳng định.

---

## 2. Mục tiêu và cổng chất lượng (quality gates)

### 2.1 Mục tiêu sản phẩm

Hệ thống sử dụng camera + MediaPipe Pose + temporal classifier + event confirmation, **chạy local trên Pi 4**, vẫn phát cảnh báo tại chỗ khi backend/mạng lỗi; đồng bộ sự kiện lên backend khi có mạng; lưu tối thiểu bằng chứng cần thiết, có cấu hình bảo mật/quyền riêng tư.

### 2.2 Mục tiêu thử nghiệm (KHÔNG phải thành tích đã đạt)

- **Event-level recall ≥95%, phấn đấu ≥98%** trên bộ kiểm thử độc lập đủ đa dạng; bắt buộc báo **khoảng tin cậy** và số sự kiện.
- **False confirmed alerts <1 lần/24 giờ** trên kịch bản thường ngày dài ngày; nếu ít giờ theo dõi thì báo thẳng cỡ mẫu và không tuyên bố đạt ngưỡng.
- **Detection delay mục tiêu <2–3 giây** từ mốc sự kiện được gán nhãn, nếu khả thi trên Pi 4 và cửa sổ thời gian sử dụng; ghi rõ P50/P95 và định nghĩa mốc thời gian.
- **Camera+pose+classifier throughput mục tiêu ≥10 FPS** trên Pi 4 tại cấu hình được đo, không tính FPS preview/video stream thay cho FPS inference.
- **TFLite equivalence:** đầu ra model float so với bản huấn luyện trong sai lệch số học có thể chấp nhận; INT8 nếu hỗ trợ thì đo số lỗi bổ sung và độ trễ, không áp đặt phải dùng.
- **Không phát sinh crash/lost alert** trong bộ test mất pose, camera lỗi, callback lỗi, reconnect mạng; phải có báo trạng thái `DEGRADED`.

Nếu kết quả chưa đạt: vẫn cung cấp baseline trung thực, cải thiện định lượng và xác định blockers; **không tự điều chỉnh số liệu cho đạt**.

### 2.3 Phân loại mức ưu tiên

- **P0 — blocking triển khai:** Alert không hoạt động, model đầu vào sai, split không độc lập, không truy xuất được nguồn checkpoint, leak credential.
- **P1 — độ chính xác và tính ổn định:** Chuẩn hóa thống nhất, retrain, augmentation, event confirmation, no-pose handling, threshold calibration.
- **P2 — tối ưu vận hành:** Benchmark Pi 4, runtime packaging, INT8, sustained test, observability, rollout/rollback.

---

## 3. Giai đoạn 0 — Khóa baseline và audit hệ thống (P0)

**Mục tiêu:** tái lập chính xác trạng thái hiện tại mà không sửa model production.

**Task 0.1 — Repository & environment audit**

1. Checkout branch mới `fix/fall-detection-reliability` từ `main`; ghi commit SHA, Python version, dependency lock versions.
2. Đọc `fall_detect/detect.py`, `modules/{detector,skeleton}.py`, `edge/main_edge.py`, `config.py`, các script `utils/` và notebook gốc.
3. Liệt kê source of truth của extractor, raw video, `.npy`, label, original FPS, timestamp, video/subject ID; ghi mục nào thiếu.
4. Bảo tồn bản gốc `results.zip`, notebook, TFLite cũ; tính SHA-256 tất cả model liên quan, input/output tensor metadata, dtype, shape, ops.
5. Xác định training run/CSV path nào thực sự đã tạo TFLite trong ZIP và TFLite trong repo. Nếu không có bằng chứng, gắn `UNKNOWN_PROVENANCE`.

**Task 0.2 — Audit leakage & lỗi đặc trưng**

1. Tạo `scripts/ml/audit_dataset.py --manifest ...` trả về `video_overlap`, `subject_overlap`, `duplicate_hash_overlap`, số mẫu theo nhãn/tập, số video và tỷ lệ missing pose.
2. Parser tên tệp chỉ là bước dự đoán `source_video_id`; **phải kiểm tra bằng metadata hoặc raw video**, không suy diễn toàn bộ từ `..._seq_XXXX`.
3. Kiểm tra sự chồng lấn video/clip giữa Train/Val/Test và sự trùng augmentation.
4. Tạo fixtures MediaPipe landmarks giả với các index tách biệt để phát hiện mapping sai.
5. Tạo kiểm thử round-trip: raw MP landmark → extractor/CSV → NPY → preprocessing offline và live → vector; so sánh theo đúng contract cùng đơn vị tọa độ.

**Deliverables:**

- `docs/ml/BASELINE_AUDIT.md`: nguồn, hash, version, bảng issues `CONFIRMED/UNVERIFIED/FIXED`.
- `docs/ml/DATASET_AUDIT.md`: phương pháp/đầu vào/ảnh hưởng leakage và các hạn chế hiện có.
- `artifacts/audit/` hoặc folder tương đương **gitignored** nếu chứa dữ liệu cá nhân/video; chỉ commit báo cáo tổng hợp an toàn.

**Gate G0:** Có bảng provenance + đường dẫn đến raw data/manifest (hoặc blocker rõ ràng); test phát hiện mismatch hoạt động; không overwrite model cũ.

---

## 4. Giai đoạn 1 — Sửa lỗi luồng cảnh báo và kiểm thử end-to-end (P0)

**Task 1.1 — Chuẩn hóa callback contract**

- Ở `fall_detect/modules/detector.py` và `fall_detect/edge/main_edge.py`, sửa callback để tương thích chính xác. Ưu tiên API đơn nhất `on_fall_alert(event: FallEvent)` dưới dạng dataclass có `event_id`, `timestamp`, `confidence`, `model_version`, `source`, `reason`; hoặc nếu muốn giữ API cũ, phải sửa cả 2 phía và có test tích hợp. Không sửa một chiều.
- Unit test phải có mô hình stub output xác suất cao để buộc hệ thống kích hoạt callback; assert **đúng 1 event** sau cooldown, đủ thông tin và không `TypeError`.
- Tách lỗi callback/notification khỏi lỗi inference: thông báo lỗi không được khiến `Prediction Error` che mất kết quả model. Ghi log trace có giới hạn tần suất.
- Test `handle_fall_detected()` với mock backend/audio/telegram; **không gọi dịch vụ thật**.

**Task 1.2 — Hành vi khi lỗi phần cứng/mạng**

- Không im lặng chuyển sang mock khi thiết bị production mất camera hoặc MediaPipe/model thiếu; báo trạng thái `CAMERA_ERROR`, `MODEL_UNAVAILABLE`, `POSE_UNAVAILABLE` và cảnh báo degraded theo chính sách.
- Không chờ backend thành công mới kích hoạt cảnh báo local. Thêm queue hữu hạn cho pending events, retry có exponential backoff và idempotency key nếu hạ tầng hiện có cho phép.
- Không đưa credentials/ảnh nhạy cảm vào logs. Thực hiện test offline → reconnect → gửi một lần.
- Kiểm tra callback không chặn luồng camera lâu: event dispatch bất đồng bộ/queue với timeout và cơ chế bỏ trùng; quan sát latency.

**Task 1.3 — Cấu hình an toàn**

- Đọc và xác thực input model: tồn tại file, SHA, dtype, input shape, output shape; đối chiếu manifest tại startup; sai thì fail closed (`MODEL_UNAVAILABLE`, không tạo dự đoán ngã giả).
- Không hard-code threshold 0.36/0.85 trong logic kết luận. Threshold phải được gắn với đúng model version; nếu manifest không có, dùng giá trị legacy có ghi warning và không chứng nhận production.

**Các testcase bắt buộc:**

1. Prob > threshold → callback chạy, local alert được gọi, event queued.
2. Callback ném exception → inference vẫn sống, lỗi được ghi và retry/fallback được quản lý.
3. 2 frames cùng trigger trong cooldown → không gửi sự kiện lặp.
4. Backend mất mạng → local alert vẫn chạy, event không mất.
5. Không có model / sai shape → không phát cảnh báo `Fall` giả.
6. Reset/disable tracking → trạng thái và pending event tuân theo chính sách rõ ràng.

**Gate G1:** Tất cả tests trên xanh; có demo replay video/stub nhận đúng callback, không có side effect gửi alert thật khi chạy pytest.

---

## 5. Giai đoạn 2 — Một chuẩn preprocessing duy nhất (P1)

**Mục tiêu:** Đảm bảo cùng một frame cho ra cùng một vector training/inference, ổn định với khuất khớp và thay đổi tư thế.

### 5.1 `SkeletonFeatureSpec` và module canonical

Tạo module đề xuất `fall_detect/ml/features.py` (nếu kiến trúc repo phù hợp), export API như:

```python
@dataclass(frozen=True)
class SkeletonFeatureSpec:
    schema_version: str
    keypoints: tuple[str, ...]
    channels: tuple[str, ...]  # ('x', 'y', 'visibility')
    coordinate_space: str     # 'normalized_image' hoặc 'pixel'; phải thống nhất
    normalization: str        # ví dụ 'midhip_euclidean_torso_v2'
    sample_rate_hz: float
    window_size: int

extract_features(pose_landmarks, image_size, spec) -> np.ndarray
normalize_sequence(raw_sequence, spec) -> np.ndarray
resample_keypoints(timestamps, raw_keypoints, spec) -> np.ndarray
```

**Yêu cầu contract:**

- Keypoint order **cố định**, tách biệt với thứ tự alphabet của Pandas; 17 khớp × `[x,y,visibility]` trong từng khớp = 51 float32/khung (đối với baseline). Không nhầm confidence thành z/3D.
- Mapping MediaPipe phải lấy enum/index chính xác. Viết test ít nhất cho Nose=0, Left Eye=2, Right Eye=5, Left Ear=7, Right Ear=8.
- Chọn 1 hệ tọa độ (đề xuất image-normalized) và chuyển đổi **từ pixel ↔ normalized** đúng tỷ lệ width/height trước khi chuẩn hóa. Không tự ép legacy model dùng schema v2 nếu chưa retrain.
- Chuẩn hóa mid-hip, độ dài torso **Euclidean** và epsilon phù hợp; kiểm tra midpoint visibility; kiểm soát inf/NaN/outliers; không chia cho delta Y gần 0. Thử nghiệm alternate normalization như ablation, không tuyên bố mặc định tốt hơn khi chưa đo.
- Theo dõi thêm **tọa độ mid-hip toàn cục, vận tốc, góc thân** ở nhánh khác/feature v3 nếu có nghiên cứu; các thông tin này mất đi khi luôn center theo hông.
- Missing pose: lưu confidence/mask hợp lệ và timestamps; không điền chuỗi 0 một cách không kiểm soát; interpolation chỉ trong gap ngắn được giới hạn.
- Định nghĩa `sample_rate_hz` rõ ràng; **không coi 30 frame = 1 giây** nếu Pi xử lý chậm. Sequence window 30 tại 15 Hz = 2 giây; train và deploy phải cùng sampling contract.
- Mọi preprocessing version thay đổi đều kéo theo một model/artifact version mới, không ghi đè model đã được benchmark.

### 5.2 Sửa các nguồn tạo dataset

- `fall_detect/utils/extract_keypoint.py`: mapping enum đúng; lưu metadata nguồn video, native FPS, ảnh gốc W/H, MediaPipe version, extractor version, timestamp/frame ID.
- `fall_detect/utils/process_csv_data.py` và `utils/timesteps60/create_seq.py`: reindex cột explicit `[X_k, Y_k, Confidence_k]` theo spec. Test `np.array([x0,y0,c0,x1,y1,c1,...])` trên fixture có giá trị phân biệt.
- Notebook: thay các hàm copy/paste bằng import canonical hoặc dùng module được đóng gói chung; kiểm tra preprocessing parity offline/live theo fixture.
- Sửa augment jitter để chỉ đụng `[:, 0::3]` và `[:, 1::3]` khi `enable_confidence_noise=False`; mọi augmentation chỉ trên train fold. Test confidence trong `[0,1]`.

### 5.3 Tests

- `test_feature_order_and_mapping.py`: 17 khớp đều đúng chỉ số và kênh.
- `test_normalization.py`: đứng/ngã ngang, hông hoặc vai confidence thấp, NaN, độ dài thân gần 0, crop/resize và tỷ lệ ảnh 4:3 so với 16:9.
- `test_train_live_parity.py`: cùng `pose_landmarks` synthetic, offline/live trả cùng float32 vector (tolerance `atol=1e-5` nếu đủ cơ sở).
- `test_augment.py`: confidence không bị jitter ngoài ý muốn, augmentation tái lập theo seed, không làm biến mất nhãn gốc.
- `test_resampling.py`: 30/15/10 FPS input thực có cùng trục thời gian mục tiêu và không dùng timestamp không thứ tự.

**Gate G2:** Parity tests xanh; manifest `feature_schema_version` rõ; các vector hợp lệ finite; chưa release model mới nếu chưa retrain bằng chuẩn này.

---

## 6. Giai đoạn 3 — Chia tập độc lập và tái lập dataset (P1)

### 6.1 Manifest bắt buộc

Tạo `data/manifest.csv` hoặc tệp được quản lý bên ngoài repository (khi dữ liệu riêng tư), với schema tối thiểu:

```csv
sample_id,video_id,subject_id,scene_id,camera_id,label,event_start_ms,event_end_ms,fps,source_video_path,split,feature_schema_version
```

- `video_id` là ID của video gốc, **không phải ID cửa sổ**. `subject_id` và `scene_id` khi biết, không tự bịa nếu không có.
- Chia theo `subject_id` khi đánh giá generalization giữa người; nếu chưa có thì theo `video_id` và báo hạn chế, tránh cùng camera/scene đan xen nếu muốn đánh giá domain shift.
- Dữ liệu test khóa cố định bằng danh sách group IDs + hash; không dùng test cho threshold/model selection.
- Lưu nguồn và version annotation. Với clip Fall, phải biết khung/giây xảy ra event để đánh giá event-level; nhãn toàn video không được mặc định là Fall cho mọi cửa sổ trong video đó.

### 6.2 Quy trình đúng

1. Kiểm tra source clips/subjects → dedup by file hash và near-duplicate nếu có.
2. **Split group trước** theo 70/15/15 hoặc tỷ lệ khả thi theo *groups*, kèm stratification nếu đủ group.
3. Tạo windows 30 frame trong từng split, gắn group ID vào từng window.
4. Train folds dùng `StratifiedGroupKFold`/`GroupKFold` trên **original, chưa augment**; augment chỉ trong train fold.
5. Chọn kiến trúc/hyperparameter bằng CV/Validation; calibration threshold chỉ Validation. **Test một lần** cho model candidate được khóa.
6. Script audit assert group overlap rỗng và không duplicate hash cross-split. Fail CI nếu khác 0.

**Lưu ý:** Nếu dataset chỉ chứa các `.npy` đã mất nguồn, agent phải đánh dấu `BLOCKED_DATA_LINEAGE` và không biến những số liệu này thành kết luận về khả năng triển khai thực. Có thể tạm train benchmark exploratory nhưng ghi rõ `NOT FOR RELEASE`.

**Gate G3:** Train/Val/Test không giao nhau theo group được chọn; augmentation không lẫn fold; có manifest và script tái lập, test report được gắn dataset hash.

---

## 7. Giai đoạn 4 — Re-train, ablation và đánh giá công bằng (P1)

**Giữ model hiện tại làm baseline**; không đổi tất cả mô hình và preprocessing một lúc. Chạy thử nghiệm có kiểm soát:

| ID | Mô hình | Đặc trưng | Mục đích |
|---|---|---|---|
| E0 | Transformer hiện tại | pipeline legacy, split được audit | Phân định vấn đề baseline |
| E1 | Transformer hiện tại | canonical 51 features v2, group split | Giá trị việc sửa pipeline |
| E2 | TCN hoặc 1D-CNN | canonical 51 features | Đối chiếu latency / recall trên edge |
| E3 | GRU nhỏ | canonical 51 features | Baseline temporal rẻ |
| E4 | Model tốt nhất từ E1–E3 | thêm global/kinematics features có version | Kiểm tra lợi ích động học |

**Các ablation** (từng yếu tố riêng): 15 vs 30 Hz nếu dataset cho phép; 30 vs 60 timesteps; Euclidean vs old torso normalization; augmentation với/không rotation; visibility/mask; MediaPipe complexity 0 vs 1; class weighting/focal loss khi cần; subject split vs video split.

**Điều kiện huấn luyện:**

- Seed cố định; lưu Python/TensorFlow/MediaPipe/NumPy versions, git SHA, config JSON/YAML, dataset hash, split hash.
- CV trên train; early stopping theo metric validation chính thức, đảm bảo đúng shape metric (binary output) và checkpoint tốt nhất.
- Thu toàn bộ prob của Validation để chọn threshold tối ưu F2 hoặc F1 có ràng buộc false alarm; **ghi method và threshold rõ**.
- Tối ưu trên event-level metrics nếu annotation cho phép; sequence-level F1 chỉ là chỉ số phụ.
- Báo `precision/recall/F1/F2/confusion matrix`, PR-AUC, ROC-AUC khi phù hợp, calibration plot/Brier score và error cases. Với event: sensitivity, false alarms/hour, detection delay P50/P95.
- Bootstrap CI theo video/subject, không bootstrap cửa sổ chồng lấn như những điểm độc lập.
- Lưu danh sách FP/FN gồm `video_id`, time range, lighting, occlusion, behavior, pose confidence để thực hiện hard-negative mining.
- Không train trên `results.zip` vì ZIP chỉ có model/kết quả/CSV các lỗi, không có dataset `.npy` đầy đủ.

**Outputs:**

```text
artifacts/models/<run_id>/
  model.tflite
  model.keras                     # hoặc SavedModel nếu phù hợp
  model_manifest.json
  training_config.json
  splits_manifest.json
  val_metrics.json
  test_metrics.json              # chỉ sau khi chọn xong model
  calibration.json
  confusion_matrix.png
  fp_fn_review.csv
```

**Ví dụ `model_manifest.json`:**

```json
{
  "model_version": "candidate-v2",
  "sha256": "REPLACE_WITH_ACTUAL_HASH",
  "input_shape": [1, 30, 51],
  "input_dtype": "float32",
  "feature_schema_version": "skeleton-v2",
  "fps_hz": 15,
  "window_seconds": 2.0,
  "fall_threshold": null,
  "threshold_optimized_on": "validation_only",
  "dataset_manifest_sha256": "REPLACE_WITH_ACTUAL_HASH",
  "git_commit": "REPLACE_WITH_ACTUAL_SHA",
  "status": "candidate_not_released"
}
```

**Lưu ý:** `fall_threshold=null` chỉ là placeholder; **không release** khi chưa có threshold đo thật và manifest hoàn chỉnh.

**Gate G4:** Có báo cáo so sánh trên cùng held-out groups, chọn model theo tiêu chí định trước; model candidate có manifest; không tiết lộ nhãn Test trong training pipeline.

---

## 8. Giai đoạn 5 — Nhận diện sự kiện thay vì chỉ phân loại cửa sổ (P1)

**Mục tiêu:** biến xác suất của model thành quyết định an toàn, giảm FP/FN và có khả năng hồi phục khi pose mất tạm thời.

### 8.1 State machine đề xuất

```text
NORMAL
  ├── evidence above entry threshold --> SUSPECTED_FALL
  └── unavailable pose/camera -------> DEGRADED / POSE_LOST
SUSPECTED_FALL
  ├── supporting motion/posture evidence --> CONFIRMING
  ├── confidence drops/recovery -------> NORMAL
  └── critical evidence/high confidence --> EARLY_ALERT (optional)
CONFIRMING
  ├── sustained evidence within time budget --> CONFIRMED_FALL
  ├── verified recovery / cancel -------> NORMAL
  └── pose lost --> manage with uncertainty, NOT reset evidence instantly
CONFIRMED_FALL
  ├── local alert + durable event -> remote notification
  └── cooldown/recovery -> NORMAL
```

**Quan trọng:** Không đặt điều kiện phải nằm bất động 30–120 giây mới cảnh báo. Đây là tín hiệu xác nhận phụ, không thay thế nhận diện chuyển động ngã.

### 8.2 Thiết kế chi tiết

- Sliding window dựa trên timestamp + resampling, chạy inference theo stride có đo latency; history là deque có giới hạn.
- Temporal smoothing bằng EMA/majority của xác suất theo thời gian, nhưng phải kiểm soát detection delay; cân chỉnh trên Validation, không chọn ngẫu nhiên.
- Hai ngưỡng/hysteresis (`enter_threshold`, `exit_threshold`), điều kiện số cửa sổ liên tiếp và confirm timeout được **calibrate/ablation**, không mặc định số tùy ý.
- Mất pose ngắn: không xóa 30 frame ngay lập tức; đánh dấu missing, giữ pending event trong grace period, và tránh reuse frame stale như dữ liệu mới. Mất pose dài: chuyển `DEGRADED` và reset có kiểm soát.
- Bổ sung tư thế sau ngã (orientation, relative body height, keypoint visibility), mức chuyển động tâm cơ thể và kết luận recovered; đánh giá được tương tác với camera PTZ/camera moving (camera tự dịch chuyển không được nhầm thành chuyển động người).
- Đảm bảo mỗi cú ngã sinh **một event ID**; cooldown không che mất cú ngã mới của một người khác hoặc sau một khoảng hồi phục, theo khả năng single/multi-person thực sự của pose pipeline.
- Xử lý chuỗi ngắn/biên frame, no person, playback hết video; không tự kết luận `no_fall` khi model không đủ input — dùng `UNKNOWN`/`COLLECTING`.

**Automated tests:** no fall/cúi thấp/đi ngủ/ngồi mạnh/ngã thực/pose bị khuất 1–2 giây/ngã ra ngoài khung hình/paused camera/timestamp trùng và lệch; kiểm thử cooldown, duplicate notifications, alert latency và recovery.

**Gate G5:** Replay suite có annotation nhận đúng event count, thời điểm và trạng thái theo test; không phát alert liên tục cho cùng một cú ngã; regressions có report.

---

## 9. Giai đoạn 6 — Triển khai và tối ưu trên Raspberry Pi 4 (P2)

### 9.1 Chẩn đoán môi trường và đóng gói

- Ghi chính xác **Raspberry Pi OS version, 32/64-bit, Python, CPU temperature, RAM, camera model, power supply**, kiến trúc `aarch64/armv7l`.
- Test dependency compatibility giữa `mediapipe==0.10.14`, `tflite-runtime==2.14.0`, OpenCV và Python **trên OS/architecture thực tế**; không giả định `pip install -r requirements.txt` luôn thành công.
- Nếu wheel không có cho platform, ghi blocker; thử interpreter tương thích khác theo phiên bản đã test, không phá production environment.
- Tạo `scripts/edge/preflight.py`, `scripts/edge/benchmark_pi.py`, `scripts/edge/replay_video.py`, `scripts/edge/verify_model.py`, hướng dẫn `docs/edge/RPI4_DEPLOY.md`.
- Cho phép `--headless`, chọn camera ID/stream, giới hạn CPU threads, log có xoay vòng; systemd chỉ khi tests pass.

### 9.2 Benchmark đúng end-to-end

Đo **ít nhất** các thành phần: camera capture, BGR→RGB, MediaPipe Pose, feature extraction, temporal model inference, state machine, encode frame, event upload; log mỗi tầng P50/P95/P99 và CPU/RAM/temp.

Kịch bản đo:

1. Raspberry Pi idle.
2. Camera 640×480, no GUI, tracking on, local only.
3. Camera + stream + pan/tilt + backend connectivity.
4. 15/30 phút liên tục; sau đó 2–24 giờ soak tùy thiết bị/schedule.
5. Thay đổi ánh sáng, khuất khớp, camera movement nếu có.

Đo throughput **các frame đã được Pose inference**, không lấy FPS đọc camera hay stream làm FPS AI. Track timestamp to detect frame drops/stale frames. Thu chênh lệch giữa timestamp bắt đầu ngã và callback alert.

### 9.3 TFLite và quantization

- Bắt đầu với TFLite float32 đã pass parity (baseline).
- Thử dynamic-range quantization, rồi INT8 representative dataset **chỉ từ Train**, nếu operators tương thích. Khi INT8 input/output là quantized, implement scale/zero_point đúng tensor metadata; không hard-code float32 trong interpreter.
- Chạy SavedModel/Keras ↔ TFLite parity trên tập mẫu độc lập, sau đó đo chênh lệch event-level performance và FPS trên Pi thật.
- Chọn model theo **trade-off có số liệu**; nếu quantized version giảm recall rõ, giữ float32.

### 9.4 Vận hành an toàn

- Khi camera/pose/model lỗi: log/telemetry `DEGRADED`, không hiển thị `NO_FALL` như đang giám sát bình thường.
- Bảo vệ secret trong `.env` và quyền truy cập thiết bị; không commit ảnh nhạy cảm; retention policy cho event snapshots/video.
- Rollout gắn manifest version/hash; giữ bản trước để rollback nhanh; có `scripts/edge/rollback.sh` hoặc hướng dẫn tương đương.
- Backend có thể sập mà local alert vẫn khả dụng; record event một cách idempotent theo `event_id`.
- Thu telemetry: model version, timestamp, sensor health, uptime, input sampling Hz, actual inference FPS, latency, event ID, error codes.

**Gate G6:** Có benchmark thật trên Pi 4 cho *đúng phiên bản* model triển khai; demo local alert khi backend offline; runbook hoàn chỉnh; tài liệu ghi rõ mục nào chưa đo được nếu chưa có Pi.

---

## 10. Giai đoạn 7 — Field validation và cải tiến theo lỗi (P2)

1. Lập danh sách tình huống sinh hoạt bình thường: đi, quay người, cúi nhặt đồ, ngồi/phịch xuống ghế, nằm giường, đứng dậy, quỳ, làm rơi vật, camera PTZ chuyển động.
2. Tình huống Fall an toàn: ngã trước, sau, ngang, trượt khỏi ghế/giường, một phần cơ thể ngoài camera; quay trên đệm dày và có người giám sát, **không yêu cầu người cao tuổi thực hiện cú ngã thật**.
3. Tách theo subject/room/camera khỏi training groups; đánh dấu begin/end fall event từ video hoặc log, kiểm tra inter-annotator consistency nếu có thể.
4. Thu FP/hour theo thời gian hoạt động thực; sensitivity theo số sự kiện thực; alert delay; tỷ lệ `POSE_LOST` và trạng thái degraded.
5. Phân tích mọi FP/FN theo nhóm: lighting, side-view, camera movement, occlusion, out-of-frame, lying-down. Thêm hard negatives vào **Train ở phiên bản kế tiếp**, bảo tồn Test gốc và giữ external holdout mới.
6. Báo cáo bất kỳ failure mode nào không giải quyết được chỉ bằng camera (che khuất, mất điện/camera) và tùy chọn **sensor fusion IMU/cảm biến** ở roadmap sau khi xác định ích lợi.

**Gate G7:** Báo cáo thực nghiệm có video IDs, event annotations, số giờ theo dõi, số events, recall CI, FP/hour và latency; không diễn đạt “an toàn cho sử dụng y tế” nếu chưa được đánh giá/kiểm định phù hợp.

---

## 11. Danh sách thay đổi file cụ thể (định hướng, không tạo file trùng vô ích)

| Ưu tiên | File | Công việc |
|---|---|---|
| P0 | `fall_detect/edge/main_edge.py` | Sửa callback fall event, async queue, trạng thái degraded, log version |
| P0 | `fall_detect/modules/detector.py` | API sự kiện, threshold từ manifest, exception isolation, missing pose handling theo kế hoạch |
| P0 | `fall_detect/config.py` | Model/threshold/version validation, cấu hình thống nhất; giữ backward compatibility |
| P0 | `fall_detect/tests/test_group5_main_edge.py` | Test callback, no network, cooldown, mất backend |
| P0 | `scripts/ml/audit_dataset.py` (mới) | Audit trùng group/hash, split và provenance |
| P1 | `fall_detect/utils/extract_keypoint.py` | Fix mapping index và metadata, không silent overwrite dữ liệu cũ |
| P1 | `fall_detect/utils/process_csv_data.py` | Canonical feature order + tests |
| P1 | `fall_detect/utils/timesteps60/create_seq.py` | Áp dụng feature contract, timestamp/gap policy |
| P1 | `fall_detect/utils/split_dataset.py` | Group split/dedup |
| P1 | `fall_detect/utils/timesteps60/split_dataset_v2.py` | Group split hoặc deprecate có migration |
| P1 | `fall_detect/modules/skeleton.py` | Dùng shared feature contract, normalization có version |
| P1 | `fall_detect/notebooks/01_huan_luyen_transformer_fall_detection_aug.ipynb` | Augment đúng, fold đúng, export manifest, lưu run metadata |
| P1 | `fall_detect/ml/` (mới khi cần) | Shared preprocessing/resampling/model manifest/temporal event engine |
| P2 | `fall_detect/requirements.txt` | Dependencies đã xác thực cho Pi OS/Python version |
| P2 | `fall_detect/run_edge.sh` | Preflight, rõ khi lỗi, logging/launch phù hợp |
| P2 | `docs/ml/`, `docs/edge/` (mới) | Audit/report/benchmark/deploy/rollback |

**Không phá hỏng các luồng không thuộc ML:** camera PTZ, Arduino sensors, Bluetooth audio, backend/Telegram/Cloudinary và quyền truy cập. Test regressions liên quan trước khi merge.

---

## 12. Kế hoạch commit/PR đề xuất

| PR | Nội dung | Điều kiện merge |
|---|---|---|
| **PR-01** | Audit artifacts + bugfix callback & tests | G0 + G1, demo alert mock thành công |
| **PR-02** | Shared preprocessing + keypoint mapping + schema tests | G2, parity offline/live |
| **PR-03** | Dataset manifest + leakage-free split + CV fix | G3, zero group/hash overlap |
| **PR-04** | Training pipeline + baseline/E1–E3 + threshold/model manifest | G4, evaluation reproducible |
| **PR-05** | Event state machine + replay regression tests | G5, event metrics + latency |
| **PR-06** | Pi packaging/benchmark/quantization + runbook | G6, Pi evidence |
| **PR-07** | Field validation + hard-negative analysis | G7, field report |

Nếu không có quyền tạo PR, agent commit cục bộ thành các mốc tương ứng và xuất diff/patch + các lệnh tái hiện. **Không tự push vào `main`, không ghi đè model production/DB và không kích hoạt thông báo thật khi test**.

---

## 13. Cấu trúc test & câu lệnh nghiệm thu mẫu

Tên command dưới đây là **contract mong muốn cần agent tạo/hoàn thiện**, không phải các lệnh khẳng định đã tồn tại trong repo hiện tại.

```bash
# Từ repo root, trên PC/Linux developer
python -m pytest fall_detect/tests -q
python scripts/ml/audit_dataset.py --manifest data/manifest.csv --fail-on-overlap
python scripts/ml/evaluate.py --config configs/ml/eval.yaml --split val
python scripts/ml/replay_video.py --video path/to/held_out_fall.mp4 --report artifacts/replay/fall.json

# Trên Raspberry Pi 4 (chỉ khi đã có hardware + dependencies hợp lệ)
python scripts/edge/preflight.py
python scripts/edge/verify_model.py --model artifacts/models/<run_id>/model.tflite --manifest artifacts/models/<run_id>/model_manifest.json
python scripts/edge/benchmark_pi.py --camera 0 --seconds 900 --headless --out artifacts/benchmarks/pi4.json
```

**Các assert CI cốt lõi:**

```text
ASSERT cross_split_video_overlap == 0
ASSERT cross_split_subject_overlap == 0  # nếu có subject IDs
ASSERT cross_split_augmented_parent_overlap == 0
ASSERT model_manifest.sha256 == actual_model_sha256
ASSERT input.shape == manifest.input_shape
ASSERT input.dtype == manifest.input_dtype
ASSERT offline_live_feature_parity == PASS
ASSERT all_preprocessed_features_are_finite == True
ASSERT alert_callback_high_probability == CALLED_ONCE
ASSERT network_failure_does_not_block_local_alert == True
ASSERT no_real_notification_sent_in_tests == True
```

Không chạy test dataset/benchmark thật khi không có đầu vào; phải trả `SKIPPED/BLOCKED` có lý do, không để pass giả.

---

## 14. Ma trận nghiệm thu theo tình huống

| Kịch bản | Kết quả mong đợi |
|---|---|
| Phát hiện ngã và callback hợp lệ | Ghi nhận đúng 1 event, local alert trước, backend nhận sau |
| Ngã và mất pose 1–2 giây | Không mất lịch sử bằng cách reset tức thì; kết luận dựa trên confidence còn lại, hoặc báo không chắc chắn |
| Người biến mất khỏi camera | Trạng thái `POSE_LOST/NO_PERSON` đúng; không phát `NO_FALL` như bằng chứng không có ngã |
| Người nằm yên trên giường | Không tự động kết luận fall chỉ vì bất động |
| Ngã rồi tự đứng dậy | Ghi nhận sự kiện nếu đủ chứng cứ, sau đó recovery/cancel theo policy |
| Thiếu model / model sai input | Không chạy `FallDetector` sai shape, có log/telemetry degraded |
| Backend down / mất Wi‑Fi | Local alert chạy; event ghi queue/retry nếu hỗ trợ |
| Pi throttling / FPS giảm | Resampling/timestamps vẫn đúng; đo latency và báo degradation |
| Camera PTZ xoay | Không nhầm chuyển động do camera là chuyển động thân người nếu có thể kiểm soát |
| TFLite khác hash được gắn trong manifest | Startup fail-safe, không phát cảnh báo từ model không xác minh |

---

## 15. Format báo cáo agent SAU MỖI PR / GIAI ĐOẠN

Agent phải gửi báo cáo ngắn theo form sau:

```markdown
## Phase / PR: <id>
- Trạng thái: DONE / PARTIAL / BLOCKED
- Commit SHA / PR link:
- File changed:
- Root cause (có bằng chứng):
- Thiết kế thay đổi:
- Lệnh test đã chạy + output PASS/FAIL/SKIP:
- Metrics trước → sau (dataset/scene/split/run_id cùng định nghĩa):
- Model hash / feature schema / threshold (nếu có):
- Vấn đề tồn đọng và rủi ro:
- Blocker cần chủ dự án cung cấp (nếu có):
- Việc tiếp theo:
```

### Dữ liệu/thiết bị cần chủ dự án cung cấp nếu agent không có quyền truy cập

- Kaggle dataset đầy đủ (raw videos + `.npy` + cách tạo, quyền truy cập), hoặc đường dẫn rõ tới dữ liệu.
- Metadata xác thực `video_id`, người tham gia, nhãn sự kiện và timestamp nếu có.
- Raspberry Pi 4 thực tế, hệ điều hành, camera và quyền SSH nếu cần benchmark.
- Xác nhận môi trường gửi cảnh báo giả lập (`TEST_MODE`) và chính sách giữ ảnh/video.

**Nguyên tắc cuối:** Có thể hoàn thành đầy đủ các phần code/test trên máy phát triển mà **chưa** kết luận performance trên Pi 4. Chỉ đánh dấu đạt cổng đo phần cứng khi có kết quả thật của thiết bị và đúng SHA model triển khai.

---

## 16. Thứ tự bắt đầu ngay — chỉ dẫn ngắn dành cho agent

**Bắt đầu bằng PR-01, không tự động mở rộng phạm vi.** Lần lượt: (1) đọc repository và xác minh callback signature, (2) tạo test tái hiện không phát được cảnh báo, (3) sửa API callback, (4) test offline local alert/cooldown và no-side-effects, (5) kiểm tra hash các model + viết `BASELINE_AUDIT.md`, (6) nộp diff/tests/những blockers liên quan dataset/Pi. Sau khi PR-01 đạt gate, chuyển sang PR-02, rồi tiếp tục các phase theo dependency. Nếu có dữ liệu/thiết bị, được phép triển khai hết trong một đợt nhưng vẫn tách commit, giữ cổng chất lượng.
