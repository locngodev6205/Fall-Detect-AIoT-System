# PR-03 · Mở rộng Dataset V2.1

## Nguồn và đơn vị thống kê

CAUCAFall v5 bổ sung bối cảnh nhà ở với các nhóm hành động quỳ, cúi nhặt đồ, ngồi xuống, nhảy và đi bộ. AVI gốc được tra theo thư mục subject/action của nhà phát hành và đối chiếu SHA-256. Dùng bản phát hành temporal của OmniFall để lấy chính xác khoảng chuyển động Fall (mã 1), loại phần sau ngã khỏi khoảng Fall. Subject, tên recording, camera, độ dài và tính liên tục của timeline được đối chiếu trước preflight. Bằng chứng này kết hợp nguồn video gốc với annotation tái gán nhãn do nhóm OmniFall công bố. [CAUCAFall v5](https://data.mendeley.com/datasets/7w7fccy7ky/5) · [Bảng CAUCAFall của OmniFall](https://huggingface.co/datasets/simplexsigil2/omnifall/blob/main/labels/caucafall.csv) · [Quy ước nhãn](https://huggingface.co/datasets/simplexsigil2/omnifall/blob/main/LABELS.md)

Một recording Fall CAUCAFall có một khoảng Fall được chấp nhận. Một recording No Fall là một lần thực hiện hoạt động. Nhiều lần thực hiện từ cùng người vẫn có tương quan. Đếm số recording và số subject riêng, đồng thời coi subject là đơn vị chia nhóm. Tất cả recording từ một subject vào cùng một tập. Nhóm nguồn cũ có subject chưa xác định chỉ được đưa vào Train. Hai recording Test V2.0 được giữ ngoài V2.1. Holdout của V2.1 chỉ gồm CAUCAFall, nên kết quả nghiên cứu sẽ phản ánh nguồn này.

## Đề xuất quy mô Test theo độ bất định

- **Fall Recall theo sự kiện.** Chốt quy tắc một cảnh báo khớp một lần ngã và độ trễ tối đa trước khi mở Test. Nếu kỳ vọng recall 90% và muốn nửa độ rộng Wilson 95% khoảng 5 điểm phần trăm thì cần khoảng **141 sự kiện ngã độc lập hiệu dụng**. Nếu chưa có ước lượng recall đáng tin cậy, dùng giả định bảo thủ p = 0,5, cần 381. Công thức nửa độ rộng là `z * sqrt(p*(1-p)/n + z*z/(4*n*n)) / (1 + z*z/n)` với z ≈ 1,96. Các lần ngã cùng người hoặc địa điểm có tương quan, cần lấy mẫu thêm người/địa điểm và tính khoảng tin cậy theo cụm. Ví dụ, với mỗi người m sự kiện và ICC ρ, thiết kế cân bằng cho hệ số `1 + (m-1)ρ`. Ước lượng ICC từ dữ liệu phát triển hoặc dùng giả định bảo thủ trước khi lấy mẫu.
- **Báo giả trên trial ADL.** Nếu tỷ lệ dự kiến 5% và muốn nửa độ rộng Wilson 95% khoảng 2,5 điểm phần trăm, cần khoảng **304 trial ADL độc lập hiệu dụng**. Nếu quan sát 0 báo giả và chỉ muốn cận trên một phía 95% dưới 5%, cần tối thiểu 59 trial độc lập. Điều kiện 0 lỗi dùng cận nhị thức `1 - 0,05^(1/n)`.
- **Báo giả trên giờ camera.** Đây là chỉ số vận hành chính. Với mục tiêu minh họa nhỏ hơn 0,1 báo giả/giờ và 0 báo giả quan sát được, cận Poisson một phía 95% là `-ln(0,05) / T`, cần khoảng **30 giờ No Fall**. Thu phiên liên tục từ nhiều phòng, người, điều kiện ánh sáng và khung giờ. Báo cáo theo cụm phòng/phiên nếu báo giả dồn theo bối cảnh. Chốt quy tắc gộp cảnh báo lặp và tiêu chí cuối trước khi thu Test. Những con số trên là thiết kế theo độ bất định, còn định mức chấp nhận thực tế cần được thống nhất trước khi đánh giá.
- **Đánh giá end-to-end.** Đếm cả sự kiện có ground truth nhưng mất pose hoặc không tạo được cửa sổ vì đây có thể là lần bỏ sót. Tập NPY chỉ phản ánh các recording qua quality gate. Trước đánh giá chính thức cần manifest raw theo subject holdout giữ cả trial không qua pose gate, cùng thời lượng quan sát hợp lệ và mốc camera bị gián đoạn. Dữ liệu clip ngắn hiện tại chưa ước lượng được báo giả/giờ ở hiện trường.

Test giữ `REVIEW_REQUIRED`. Chọn model và threshold trên Train/Validation. Chỉ chạy Test sau khi khóa model, threshold, quy tắc khớp sự kiện, báo cáo và phê duyệt digest Test.

## Kết quả ở snapshot V2.1

| Tập | Recording Fall | Recording No Fall | Nhóm chia tập | Subject CAUCAFall |
| --- | ---: | ---: | ---: | ---: |
| Train | 21 | 26 | 17 | 4 |
| Validation | 7 | 13 | 3 | 3 |
| Test | 6 | 11 | 3 | 3 |
| Tổng | 34 | 50 | 23 | 10 |

**84 recording duy nhất** qua preflight. CAUCAFall bổ sung 26 Fall và 42 No Fall. Train mang tiếp 4 Fall Montréal, 4 Fall URFD và 8 No Fall URFD. Montréal giữ một nhóm bảo thủ, còn 12 recording URFD chia theo recording trong Train. Tính độc lập theo người được kiểm tra trong CAUCAFall. Với phần cũ, danh tính theo trial chưa đủ để cộng thêm subject độc lập. Validation và Test mỗi tập có ba subject cho cả hai lớp. Tỷ lệ theo recording là 56,0% / 23,8% / 20,2% sau khi tăng số nhóm holdout.

Tải đủ **100/100 AVI CAUCAFall** và xác minh checksum gốc. Năm video không qua đối chiếu timeline vì độ dài hoặc tính liên tục của annotation lệch quy tắc. Trong 95 video CAUCAFall còn lại, 17 thiếu overlap Fall hợp lệ và 10 thiếu cửa sổ pose liên tục. Tỷ lệ frame mất pose là 2.815/18.889 (14,90%) trong 95 video này. Không có ngã về phía trước nào qua cổng cửa sổ của snapshot. Các trial có annotation hợp lệ nhưng thiếu cửa sổ vẫn được giữ trong danh mục raw để đánh giá end-to-end. Test có hoạt động quỳ, cúi nhặt đồ, ngồi xuống, nhảy và đi bộ. Đây là dữ liệu dàn dựng trong một nguồn holdout, nên không suy rộng trực tiếp sang phòng hoặc camera khác.

Có 889 cửa sổ 30 × 51 ở 10 Hz để dùng trong pipeline. Chúng không được tính vào quy mô mẫu đánh giá. Danh mục raw Test gồm **15 lần ngã, 12 trial ADL trên 3 subject**, trong đó 9 Fall và 1 ADL không qua cổng cửa sổ. Tổng thời gian ADL raw là **131,95 giây**. Kể cả giả sử mô hình bắt được cả 15 lần ngã và các lần ngã độc lập, cận dưới Wilson 95% chỉ khoảng 79,6%. Tương quan trong cùng subject làm giảm lượng thông tin hơn nữa. Năm recording không khớp timeline vẫn nằm ngoài danh mục đánh giá.

## Tái lập và kiểm chứng

Dataset nằm tại `../annha-recovery-payutch-v1/verified-expansion-v21/annha-v2.1` tính từ repo. Thư mục cha có AVI theo subject/action từ nhà phát hành, pose CSV từ extractor `annha-pose-v2`, `publisher-folders.json`, `media-evidence-ranges.json`, CSV OmniFall, các danh sách loại và danh mục raw Test. Tất cả nằm ngoài Git.

```bash
data=../annha-recovery-payutch-v1/verified-expansion-v21
pilot=../annha-recovery-payutch-v1/verified-expansion-v2/annha-v2.0

# Dùng đường dẫn output chưa tồn tại khi tái tạo dataset.
python scripts/ml/caucafall_sources.py "$data" \
  --evidence "$data/media-evidence-ranges.json" --pilot "$pilot"
python scripts/ml/dataset_v2.py build "$data/sources-official.csv" "$data/annha-v2.1" \
  --version v2.1 --seed 42 --mode official --min-holdout-groups 3 \
  --train-only-source urfd --train-only-source mcfd
python scripts/ml/dataset_v2.py verify "$data/annha-v2.1" --verify-sources
```

- SHA-256 logic Dataset V2.1: `c30892818ed564c8c93169390092a17f1d380db7ef65c2ef4857360dc87fe191`.
- SHA-256 byte `manifest.json`: `3c2b4f2930ad678a7fb6cf8621d67916f3a416300d07c590b8d8c7ba92b28dd3`.
- SHA-256 danh mục raw Test: `4a33a4bf6d42e6df891fcaeafb5d7231807b5b64b1ce3f4a5d8972970c0d7fd2`.
- V2.0 vẫn qua verifier với SHA-256 tệp manifest `40f8a04b140dea7e8738ba06ec38a9d54c03ada0bfd350621081883ccb81e1fb`.

Dataset V2.1 dùng được để trình review thử nghiệm nghiên cứu trên Train và Validation. Giữ Test đóng và chưa mở PR-04 trong đợt này. Trước khi coi PR-04 là đánh giá đáng tin cậy, cần holdout đủ sự kiện, subject và thời lượng ADL theo mục tiêu khoảng tin cậy đã thống nhất. Không huấn luyện hay cập nhật production.

`verify --verify-sources` chạy thành công và trả cùng thống kê với build. Kiểm tra riêng không thấy giao nhau giữa các split theo subject, group, recording ID, SHA video, hash frame giải mã hay hash cửa sổ/feature. Hai recording Test V2.0 không trùng với bất kỳ recording V2.1 nào theo ID và hai hash video. Loader mở được Train/Validation và chặn Test khi chưa duyệt. Toàn bộ bộ kiểm thử Edge đạt **55/55**.
