# Tối ưu tải dữ liệu và hoàn thiện giao diện — 29/10/2026

## Thay đổi hiện hành

- Bỏ banner/nhãn/tiền tố Demo khỏi giao diện và tên tài khoản, nhà, camera, âm thanh, lịch nhắc đã seed. Các bản ghi/ID/quyền và email/mật khẩu đăng nhập được giữ nguyên. File credentials nội bộ vẫn là `.secrets/demo-credentials.json`.
- Không còn chế độ trình bày riêng bỏ qua sự kiện của dữ liệu seed: mọi sự kiện OPEN/ACKNOWLEDGED đi qua luồng cảnh báo thông thường. Trường `is_demo` cũ còn trong API để tương thích; frontend không dùng nó để lọc cảnh báo.
- Trang chọn nhà có ảnh bìa gốc, vai trò, số phòng, số camera trong phạm vi quyền, múi giờ dễ đọc, thao tác làm mới/mở nhà/tạo nhà. Nhà mới chưa có thiết bị vẫn có ảnh minh hoạ.
- Sự kiện có icon theo loại; thẻ cảm biến có icon và số đo gọn; trạng thái trống dùng icon đúng ngữ cảnh. Ảnh phòng/camera chưa kết nối vẫn dùng ảnh thiết kế gốc có nhãn minh hoạ.
- Giữ cấu trúc 2 nhà, mỗi nhà 4 phòng/camera. Hai nhà có chủ sở hữu/phạm vi riêng; trang chọn nhà chỉ hiện những nhà tài khoản được cấp quyền, không tự mở rộng quyền để hiện cả hai.

## Nút thắt và cách sửa

1. Mỗi transaction trước đây gửi SET ROLE và từng giá trị context thành nhiều lượt truy vấn đồng bộ qua mạng đến Neon. `pgdb.connect()` hiện gom các context vào một SELECT và dùng Psycopg pipeline trong transaction explicit. BEGIN/SET LOCAL ROLE/context vẫn chạy theo thứ tự; COMMIT/ROLLBACK vẫn xác nhận, không giữ context khi trả kết nối cho pool. Không cache session hoặc quyền truy cập. Tham khảo [Psycopg pipeline](https://www.psycopg.org/psycopg3/docs/advanced/pipeline.html).
2. Feed sự kiện trước đây đọc payload/actions/media riêng cho từng sự kiện, rồi lặp tra actor. Nay đọc theo nhóm ID đã được RLS cho phép, gom actor một lần và giữ nguyên hình dạng response; chi phí mạng không tăng tuyến tính theo số bản ghi trong feed.
3. Camera đọc state/snapshot metadata theo nhóm thay vì query từng camera. Membership/grant và danh sách nhà được aggregate trong SQL thay vì mở thêm transaction cho từng nhà; room/camera count được tính trên server.
4. Telemetry trước đây đọc readings riêng cho từng batch. Nay SQL tổng hợp readings theo batch trong một truy vấn có giới hạn, giữ thứ tự theo `observed_at` và các trường response hiện có.
5. Session chỉ lấy những trường cần cho xác thực; không tải password hash trên mỗi request dữ liệu. Kiểm tra token/expiry/revocation/auth_version vẫn chạy mỗi request.
6. Frontend hiển thị camera/phòng khi hai phần này sẵn sàng, không chặn bởi feed sự kiện/lịch nhắc. Phần chưa nhận được dữ liệu có loading riêng; không dùng số 0 hoặc thông báo “không có sự kiện” thay dữ liệu chưa tải. Trang nhà/tài khoản/lời mời không kéo cả bộ dữ liệu của nhà khi không cần. Poll định kỳ tạm ngừng khi tab bị ẩn.

## Kết quả đo trước/sau

Đo qua cùng ứng dụng Docker tại localhost:8188 và Neon production, ba mẫu cho mỗi mục, lấy trung vị. Browser dùng Chrome headless với viewport desktop 1440×1000; mỗi lượt mở trang mới, chung một context đã đăng nhập. Đây là số đo trong điều kiện máy/mạng hiện tại, không phải cam kết SLA hay load test.

| Phép đo | Trước | Sau |
|---|---:|---:|
| Tổng quan: từ điều hướng đến khi đủ 4 thẻ phòng | 9.942 ms | 2.392 ms |
| Môi trường: từ click đến khi có lịch sử số đo | 9.932 ms | 1.352 ms |
| API danh sách nhà | 1.347 ms | 594 ms |
| API camera | 1.705 ms | 984 ms |
| API phòng | 1.437 ms | 856 ms |
| API sự kiện | 5.913 ms | 1.262 ms |
| API lịch nhắc | 1.697 ms | 861 ms |
| API telemetry | 4.919 ms | 1.292 ms |

Tổng quan nhanh hơn khoảng 4,2 lần; Môi trường khoảng 7,3 lần trong phép đo này. Payload HTTP không được rút bớt lịch sử hoặc bỏ trường để đạt số đo; danh sách nhà có thêm các count hữu ích. Lợi ích chính là giảm truy vấn lặp/lượt mạng, không khẳng định mọi response đều ít byte hơn.

Dữ liệu JSON/log gốc trong `.secrets/load-before.json`, `load-after.json`, `page-before.json`, `page-after.json` và các file log tương ứng; không đưa vào Git. Cách đo lại, chạy lần lượt để tránh hai benchmark tranh tài nguyên:

```bash
python3 scripts/qa/measure_api.py --output .secrets/load-current.json --runs 3
node scripts/qa/measure_load.mjs --output .secrets/page-current.json
```

## Kiểm chứng

- Bộ PostgreSQL: 9 testcase PASS trong 138,216 giây, gồm các luồng nghiệp vụ hiện có và ca mới gây lỗi SQL rồi kiểm tra rollback, reset role/context, thiếu tenant mặc định không thấy camera, và kết nối được tái sử dụng an toàn.
- Build frontend và ba testcase ảnh/phòng mới/nhãn kết nối đã qua.
- Bộ browser kiểm tra desktop/mobile, các vai trò, ảnh chọn nhà, không còn tiền tố Demo trong các tên hiển thị, modal tạo nhà/mở nhà, sự kiện bình thường, ACK object, phòng mới/nhà trống, refresh/error/retry và luồng hình hết hạn. Kết quả chạy cuối cùng nằm trong `artifacts/ui-review/checks.json` và `.secrets/performance-ui-tests.log`.
- Tối ưu hiệu năng giữ nguyên TLS và CSRF; backend tiếp tục dùng login giới hạn quyền. Phần quản lý nhà bổ sung migration 007/008 để chặn truy cập và thông báo khi nhà được lưu trữ. Chưa đo tải đồng thời lớn hay kết nối Pi/servo/cảm biến thật.

## Vận hành

`normalize_seed_labels.py` là thao tác chuẩn hoá nhãn dữ liệu đã seed, dùng migration owner trực tiếp tại máy quản trị. Script chỉ sửa nhãn/tên và mô tả fixture đã biết; không xoá bản ghi, không đổi ownership/email/password/token. Không đưa owner URL vào container để chạy script.

Ảnh bìa/thumbnails tiếp tục là file gốc `/images/living.png`, `/images/bedroom.png`, `/images/entrance.png`. Các nhãn trung thực “Ảnh minh hoạ”, “Chưa kết nối”, “Ảnh gần nhất” vẫn được giữ; dữ liệu seed không biến thiết bị thành online hay ảnh minh hoạ thành bằng chứng thật.


## Phân trang, bộ lọc và luồng quản lý nhà

- Sự kiện: 10 bản ghi/trang, lọc phòng, camera, trạng thái, loại, 24 giờ/7 ngày/30 ngày hoặc toàn bộ. Backend truy vấn dữ liệu theo quyền rồi mới đếm/phân trang, không giới hạn tìm kiếm ở 100 bản ghi đầu. Thứ tự `received_at DESC, id DESC` ổn định khi trùng thời gian. Bộ lọc đổi sẽ về trang 1. API cũ không truyền `page` vẫn trả array để giữ tương thích.
- Endpoint `GET /api/homes/{id}/events?page=1&page_size=10&room_id=...&camera_id=...&kind=fall&status=OPEN&hours=24` trả `{items,total,page,page_size,total_pages}`. Page size tối đa 50; giá trị sai trả 422. Bộ lọc truy vấn parameterized SQL và vẫn chịu RLS.
- Lịch nhắc, âm thanh, lịch sử phát, lệnh, thành viên, lời mời, thông báo và nhật ký: chia 10 mục/trang trên tập dữ liệu API hiện có. Nhà 4 thẻ/trang, camera 6 thẻ/trang. Các endpoint lịch sử vốn có giới hạn server vẫn giữ giới hạn đó; phân trang giao diện không phải tải toàn bộ lịch sử vô hạn.
- Bảng số đo 10 hàng/trang trên tối đa 500 bản ghi trong khoảng chọn. Biểu đồ đường chọn riêng nhiệt độ/độ ẩm/gas, không trộn đơn vị vào cùng một trục. Mẫu lỗi, thiếu, khác đơn vị được ngắt; không giả thành 0. Chart.js được tải riêng khi mở Môi trường để giảm bundle khởi động.
- Thẻ lời nhắc có đệm ngang 24px desktop, 20px mobile; trạng thái không kéo dài lấp thẻ. Nút phân trang có nhãn truy cập, trang đang chọn, trạng thái vô hiệu ở đầu/cuối.
- Logo đưa về Tổng quan, nút Đăng xuất riêng trên thanh đầu/sidebar. Tạo nhà xong có thể chọn **Thiết lập sau**, tiếp tục vào nhà khi chưa ghép thiết bị.
- Chủ nhà chọn **Xoá nhà** tại danh sách nhà và nhập đúng tên để xác nhận. Đây là lưu trữ mềm: giữ lịch sử, ẩn nhà khỏi danh sách; RLS chặn truy cập theo ID cũ, thu hồi credential thiết bị/lời mời, tắt lịch và thông báo, hết hạn lệnh. Không xoá vật lý dữ liệu. Kiểm tra thông báo trước dispatch cũng loại nhà đã lưu trữ; tác vụ gửi ra ngoài đã thực sự bắt đầu không thể thu hồi.
- Migration `007_home_archiving.sql` và `008_archived_home_notifications.sql` chạy qua `scripts/cloud/deploy_postgres.py`, có checksum ledger; không sửa migration cũ đã áp dụng.


## Kiểm chứng sau cập nhật phân trang (29/10/2026)

- `npm run build`: PASS, entry JS khoảng 366 kB và chunk biểu đồ riêng khoảng 157 kB (trước gzip). Không còn cảnh báo chunk trên 500 kB.
- `npm run test:frontend`: 9/9 PASS, gồm phân trang không trùng, clamp trang khi danh sách ngắn lại, danh sách trống và dữ liệu biểu đồ lỗi/khác đơn vị.
- `ANNHA_TEST_ENV=.secrets/neon-test-runtime.env python3 -m unittest backend.tests.test_postgres -v`: 10/10 PASS trong 155,145 giây trên nhánh Neon tách biệt. Ca mới tạo 13 sự kiện, kiểm tra trang 10+3, bộ lọc kết hợp, từ chối người ngoài, xác nhận tên sai, lưu trữ nhà, thiết bị bị thu hồi, RLS chặn đọc và lịch sử còn nguyên.
- Migration 007/008 đã áp dụng production bằng runner có ledger; dữ liệu nhà hiện có không bị xoá. Docker frontend/backend đã dựng lại và backend healthy.
- Browser fixture cho 23 sự kiện chỉ tồn tại trong Playwright interception, không được ghi vào Neon production. Kiểm tra modal xoá nhà dừng trước bước xác nhận; không xoá nhà bạn đang dùng.


### Nghe thử và dropdown

Form lịch nhắc cho phép phát thử TTS trước khi lưu, hoặc nghe file âm thanh đang chọn. Trình phát áp dụng âm lượng của form; đổi nội dung/camera/nguồn/file sẽ huỷ request cũ, dừng và thu hồi blob URL cũ. Nếu trình duyệt chặn tự phát sau khi tạo giọng, người dùng vẫn có controls để bấm phát. Đóng form không tạo lịch hoặc lệnh phát. TTS dùng API có CSRF, quyền camera và rate limit; preview không lưu vào Neon hay thư viện media.

Các select một lựa chọn dùng chevron inset 16px và đệm nội dung phải 44px. Vẫn dùng phần tử select thật để giữ thao tác bàn phím/mobile; chế độ forced colors trả lại mũi tên native.


### Ghi âm trong form và lịch sử dễ hiểu (29/10/2026)

- Nguồn **Ghi âm trực tiếp** nằm ngay trong form Tạo/Chỉnh sửa lời nhắc: bắt đầu/dừng (tối đa 2 phút), nghe lại, ghi lại, dùng bản ghi rồi lưu lịch. Microphone chỉ bật khi bấm bắt đầu; dừng/đóng form sẽ dừng các track. Chưa có bản ghi đã chọn thì không thể lưu lịch âm thanh. Upload vẫn kiểm tra quyền âm thanh, định dạng, dung lượng và quota qua API hiện có.
- Bản ghi chỉ được tải lên khi chọn **Dùng bản ghi này**; chưa gửi lệnh phát đến Pi. Trường hợp từ chối quyền/không có microphone/định dạng chưa hỗ trợ có hướng dẫn trên form.
- **Lịch sử thông báo** và **Hoạt động trong nhà** đóng mặc định, chỉ tải dữ liệu khi mở. Mô tả hoạt động bằng tiếng Việt; backend lấy tên người thực hiện theo lô. Trạng thái thông báo có bộ nhãn riêng: `accepted` là dịch vụ gửi đã tiếp nhận, không phải thiết bị hay người thân đã nhận/đọc.
- Mục Các phòng có khoảng cách trên 28px, padding trên 24px và đường phân cách; từng hàng đệm ngang 12px, nút Thêm phòng cách danh sách 22px.
- Build PASS. Frontend 10/10 PASS. Bộ backend 10 ca hồi quy đã PASS; ca mới kiểm tra TTS có CSRF/quyền/phản hồi WAV, không tạo asset/lịch và API lịch sử trả đúng dữ liệu đã PASS riêng (16,041 giây).
- Browser: bộ tổng thể 34 kiểm tra PASS; 6 kiểm tra preview thực (WAV do backend tạo, giải mã được trong Chrome, file âm thanh có sẵn, âm lượng, invalidation, chevron/mobile) PASS; 6 kiểm tra recording/settings PASS. Test ghi âm dùng microphone giả của Chrome và chặn upload/lưu lịch bằng fixture trong browser: xác nhận WebM giải mã được, track dừng, payload đúng, từ chối quyền có hướng dẫn. Không dùng microphone thật của người dùng, không tạo lịch/asset giả trong Neon production từ test này.
- Log: `.secrets/ux-ui-tests.log`, `audio-preview-api-tests.log`, `audio-preview-ui-tests.log`, `recording-settings-ui-tests.log`; ảnh và JSON kết quả trong `artifacts/ui-review/` (đều không đưa vào Git).
