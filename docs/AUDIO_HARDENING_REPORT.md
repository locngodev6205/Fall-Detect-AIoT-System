# AnNhà Audio Hardening

**Trạng thái LOCAL TESTED** · 20/11/2026 · Worktree `AnNha-audio-review`, nhánh `review/audio-reminder-streaming-hardening`, gốc `f16e2d6`.

Patch được phát triển trong worktree riêng từ `a385018` rồi chuyển sang `origin/main`. Checkout đang có thay đổi được giữ riêng. Tại main, runtime chưa có module trạng thái OTA của nhánh gốc. Các phép đo hiệu năng dưới đây là từ lượt kiểm thử local trước khi chuyển patch. Kết quả chạy lại trên nhánh review nằm trong hồ sơ review.

## Audit tại HEAD

| Chức năng | Điểm thực thi | Kết quả xác minh ở baseline | Ưu tiên | Sửa và kiểm thử |
| --- | --- | --- | --- | --- |
| Ghi âm và tải file | `ReminderRecording.jsx`, `AudioPicker.jsx`, `Reminders.jsx`, `api.py`, `pgapi.py` | Bản ghi tạo media asset để phát lại. Upload và quyền gắn với camera. | P2 | Giữ luồng upload. Kiểm tra quyền đọc asset và tạo lệnh bằng test SQLite và PostgreSQL. |
| TTS và trạng thái asset | `tts.py`, `pgservices.py`, `services.py`, `DeviceClient.sync_config`, `ReminderScheduler._play_reminder` | TTS backend có vòng đời asset riêng. Edge tải asset trước khi áp dụng config, bỏ qua lỗi tải và dùng TTS/chime khi thiếu audio. | P1 | Tải trước bằng worker riêng, báo thiếu asset ở ACK cấu hình. File upload thiếu trả `failed`, TTS được phép tổng hợp tiếng Việt cục bộ. Test asset offline, eSpeak không có và config ACK. |
| Phát thủ công và thử loa | `DeviceClient.poll_and_execute_commands`, `AnNhaEdgeRuntime._on_web_command`, `AudioPlayer.execute_audio_command`, `BluetoothSpeakerCard.jsx` | `play_audio` giữ vòng lặp I/O đến khi hết file. Thử loa ACK thành công lúc tạo process. | P1 | Worker tuần tự có giới hạn, receipt bền vững trước khi phát, ACK cuối sau exit code. Test WAV dài, worker đầy và restart. |
| Đồng thời và ưu tiên | `AudioPlayer.play_file`, `trigger_emergency_siren`, `silence`, `BluetoothSpeakerManager` | Việc khởi chạy và ghi nhận process tách rời. Hai yêu cầu đồng thời có thể chiếm loa sai thứ tự. Cơ chế bảo vệ gas trong silence đã có. | P0 | Tuần tự hóa quyền phát, chuyển giải mã file ra ngoài đoạn khóa. Cảnh báo ngắt phiên thường, gas thắng fall. Test preemption, exit code lỗi và loa ngắt bằng fixture. |
| Lịch offline, ngày và Night Mode | `ReminderScheduler.evaluate_due`, `models.Reminder`, `Reminders.jsx` | Grace có mức sàn 60 giây và tính cả đúng mốc giây 60. So lịch theo ngày hiện tại nên cửa sổ bù qua nửa đêm bị bỏ. Night Mode bỏ qua lịch thường. | P1 | So theo timestamp, xét ngày lịch và DST. Giữ Night Mode. Test once, weekly, daily, DST, giây 59/60, qua nửa đêm, khởi động lại. |
| Lịch sử thực thi | `ReminderScheduler`, `DeviceClient.report_execution`, `pgapi.execution`, `api.execution` | `played` lúc khởi chạy. Lỗi HTTP và restart làm mất báo cáo trong RAM. PostgreSQL gán thời điểm nhận và revision hiện tại. Kiểm thử với role Device xác nhận câu INSERT cũ có conflict target yêu cầu quyền SELECT không được cấp. | P1 | Ghi nhận kết quả sau khi player thoát, outbox SQLite cục bộ, retry và idempotency. PostgreSQL truy xuất revision ghi trong occurrence và dùng conflict handling tương thích với quyền INSERT-only hiện tại. SQLite legacy lưu trường `created_at` theo hợp đồng cũ. |
| Push-to-Talk | `LiveAudio.jsx`, `media.py`, `pgmedia.py`, `LiveStreamer._audio_loop`, `AudioPlayer` | Trình duyệt gửi chunk trong khi ghi. Pi gom cả phiên và ghi file ở `stop`. Relay chỉ đợi socket gửi xong, thiếu tín hiệu Pi thực sự đã nhận chunk. | P1 | Pipe FFmpeg chạy suốt phiên, mỗi camera một sender, xác nhận từ Pi và giới hạn phiên. Test PCM trước stop, chậm/mất kết nối, hai phiên và input quá giới hạn. |
| Schema và phân quyền | PostgreSQL `001_schema.sql`, `002_security.sql`, `009_schedule_tts_permissions.sql`, `010_atomic_tts_enqueue.sql` và SQLite `db.py` | Revision và execution key đã có unique constraint. Device đã có quyền SELECT revision theo camera. Quyền TTS theo schedules và quyền upload audio là hai quyền riêng. | P2 | Dùng lại bảng, quyền, API và occurrence key. Giữ Origin, phiên đăng nhập, camera permission và token của Edge. |

## AUDIO-01 · Phát file và kết quả lệnh

- `audio/worker.py`, `main_edge.py` và `client/device_client.py` đưa phát thủ công, thử loa và lịch nhắc vào một worker có sức chứa 16 việc, kể cả việc đang chạy. Bước tải file và eSpeak chạy ở worker. Heartbeat và việc xác định lịch đến hạn không chờ process phát. Lệnh `silence` giữ đường điều khiển riêng.
- `audio/audio_player.py` và `audio/bluetooth_manager.py` quản lý process, sink và ưu tiên. Thứ tự là gas, fall, audio thường gồm Push-to-Talk, rồi thử loa. Audio thường phát tuần tự. Yêu cầu thường đụng một phiên Push-to-Talk đang chạy sẽ báo bận. Cảnh báo khẩn cấp ngắt phiên thường. Silence giữ quy tắc hiện hành đối với gas. Fixture kiểm tra cảnh báo, loa thật chưa được kích hoạt.
- Lifecycle nội bộ gồm xếp hàng, chuẩn bị, phát, rồi hoàn tất hoặc kết thúc với chi tiết ngắt, hủy, timeout hoặc lỗi. Trạng thái công khai của command vẫn là `accepted → executing → executed/failed`. `executing` bao gồm thời gian chờ worker. Phát file có giới hạn chờ player 180 giây. FFmpeg chuẩn hóa dùng timeout 10 giây và giữ padding âm thanh cuối từ baseline. Exit code 0 với đúng sink là bằng chứng trình phát hoàn tất. Việc người dùng nghe thấy âm thanh cần được xác nhận riêng tại loa.
- Bản ghi âm thanh đang thực thi được lưu cục bộ trước hành động. ACK cuối còn chờ được gửi lại sau restart. Nếu Edge khởi động lại khi kết quả chưa được ghi, lệnh có trạng thái `failed` với chi tiết kết quả không xác định, theo chính sách tránh phát lặp.

## AUDIO-02 · Lịch nhắc

Luồng phát là Web → FastAPI → config/revision + media → DeviceClient/cache → scheduler → worker phát → Bluetooth. `scheduler.py` và `Reminders.jsx` thống nhất rằng giây 0–59 là phút đã hẹn. Khi `late_seconds > 0`, lịch có thể phát bù đến số giây đã cấu hình tính từ đầu phút, với điều kiện còn hợp lệ khi chuẩn bị xong. Một lần chỉ xét occurrence gần nhất. Mốc lặp ở giờ trùng DST chọn lần đầu của giờ địa phương. Giờ không tồn tại khi nhảy DST được bỏ qua. Chỉnh sửa lịch tạo revision mới theo cơ chế backend hiện có.

Edge dùng cấu hình đã áp dụng gần nhất khi offline. Lịch tắt hoặc xóa được thực thi sau khi Pi nhận cấu hình mới. Một thay đổi chưa đến thiết bị không thể hủy occurrence đã phát trong lúc Pi mất mạng. Night Mode giữ nguyên chính sách bỏ qua lịch thường. Nếu nghiệp vụ cần lời nhắc quan trọng xuyên qua Night Mode, cần phê duyệt quyền cấu hình từng lịch và tiêu chí riêng cho chế độ đó.

TTS có thể dùng asset backend hoặc eSpeak/eSpeak NG tiếng Việt cục bộ. File upload hoặc bản ghi thiếu cache được tải lại khi có kết nối. File vẫn thiếu sẽ báo lỗi thay vì phát nguồn khác. Cấu hình được áp dụng độc lập với độ sẵn sàng asset. Hai adapter backend lưu thông báo thiếu file trên ACK thành công để trang camera hiển thị. Prefetch chạy riêng và cập nhật lại cảnh báo khi cache đủ.

Occurrence key dùng ngày giờ địa phương và version. Sổ JSON tương thích với cache cũ và được ghi trước khi phát. Sau khi ghi sổ, Edge ghi nhận lần đang xử lý trong SQLite cục bộ. Khi crash trong lúc phát, lần đó không tự phát lại và báo kết quả không xác định sau restart. Cửa sổ giữa ghi sổ JSON và ghi SQLite có thể mất báo cáo nếu mất nguồn, vào lúc chưa phát. Crash sau khi phát và trước khi ghi kết quả có thể khiến lịch sử ghi `failed` dù loa đã phát. Báo cáo cuối được lưu và gửi lô giới hạn, retry tối đa mỗi 15 phút khi lỗi tạm thời. HTTP 400/404/409/422 được lưu với cờ bị từ chối để kiểm tra. Key chống trùng ở PostgreSQL và SQLite giữ một lịch sử duy nhất mỗi occurrence. PostgreSQL khôi phục revision cũ và `scheduled_at`. `executed_at` của PostgreSQL vẫn là thời điểm backend nhận. SQLite hard-delete lời nhắc có thể từ chối lịch sử đến sau, trong khi Edge giữ báo cáo bị từ chối.

## AUDIO-03 · Push-to-Talk

Browser Mic → MediaRecorder Opus → WebSocket browser → relay FastAPI → WebSocket thiết bị → một FFmpeg/phiên → PCM → một trình phát Bluetooth. Edge đưa byte liên tục vào một decoder. Các phần WebM/Ogg nối theo thứ tự trong một container. PipeWire dùng PCM s16 trong AU qua stdin để phù hợp cả phiên bản `pw-cat` chưa có `--raw`. PulseAudio dùng PCM raw với `paplay` trỏ tới sink cụ thể. PipeWire được đặt thuộc tính chặn đổi đích hoặc fallback. Cú pháp PipeWire theo [tài liệu pw-cat](https://docs.pipewire.org/page_man_pw-cat_1.html). Hành vi khi sink PulseAudio bị rút giữa phiên cần được xác nhận theo cấu hình audio daemon thực tế.

- `LiveAudio.jsx` gửi khoảng 200 ms mỗi chunk, yêu cầu 48 kbit/s, đóng track và socket khi stop hoặc đổi camera. Phiên mới có đối tượng riêng để sự kiện/callback cũ không dọn nhầm phiên mới.
- `audio_relay.py`, `media.py` và `pgmedia.py` giữ endpoint browser/device và thêm handshake nội bộ có ID phiên. Browser nhận `ready` sau xác nhận từ Edge. Relay chuyển từng chunk khi Pi xác nhận đã nhận chunk trước. Giới hạn 32 KiB/chunk, 1 MiB dữ liệu và 60 giây/phiên. Browser chủ động dừng nếu hàng đợi socket vượt 12 KiB. Giới hạn đường ống từ kernel cùng deadline ghi 350 ms giúp chặn receiver chậm. ACK `received` xác nhận byte đến decoder, thời điểm nghe qua loa cần đo riêng.
- `live_streamer.py` xử lý start/stop, cleanup khi mất mạng, và reset decoder khi reconnect. Stop và cảnh báo giết player/decoder; audio đã nằm trong buffer phần cứng Bluetooth có thể còn một đuôi ngắn. Socket JPEG giữ endpoint và cơ chế frame hiện tại. `backend/Dockerfile` giảm hàng đợi WebSocket transport xuống bốn message cho server container.
- Relay giữ kết nối trong bộ nhớ của một tiến trình. Dockerfile chạy một worker, phù hợp với triển khai hiện tại. Nhiều worker hay nhiều replica cần định tuyến cả hai socket của cùng camera về cùng tiến trình hoặc có relay chung. Để bật Push-to-Talk, deploy frontend, backend và Edge có handshake mới trong cùng đợt. Edge cũ không báo ready cho relay mới, frontend mới từ chối ready của backend cũ.

| Phương án | Đánh đổi |
| --- | --- |
| MediaRecorder + WebSocket + FFmpeg | Tái dùng UI, xác thực và endpoint. Độ trễ phụ thuộc cách browser đóng chunk, decoder, TCP và Bluetooth. |
| AudioWorklet + PCM/Opus + WebSocket | Điều khiển kích thước frame sớm hơn. PCM dùng nhiều băng thông, Opus đòi thêm codec; cả hai cần thay capture frontend. |
| WebRTC | Có jitter buffer, RTP và cơ chế điều khiển tắc nghẽn cho truyền thời gian thực. Cần signaling, endpoint media và hạ tầng NAT/TURN phù hợp. |

## Kiểm thử và hiệu năng

| Kiểm thử | Lệnh hoặc môi trường | Kết quả |
| --- | --- | --- |
| Edge scheduler, command, gas priority, offline/restart, FFmpeg, sensors | `python -m unittest fall_detect.tests.test_group1_sensors fall_detect.tests.test_group4_audio_scheduler fall_detect.tests.test_audio_hardening` | 19 PASS. Thiết bị, cảm biến và Bluetooth mô phỏng, process kiểm thử thực khi cần. |
| Relay WebSocket, media storage | `python -m unittest backend.tests.test_audio_relay backend.tests.test_media_storage` trong môi trường `backend/requirements-test.txt` | 14 PASS. Có test quyền/Origin, một sender, MIME, giới hạn, đứt kết nối, Stop và receiver chậm. |
| Edge + backend container tạm | `python -m unittest fall_detect.tests.test_group2_device_client fall_detect.tests.test_group3_tracking_ptz fall_detect.tests.test_group5_main_edge`, mount `backend/src` từ worktree vào image test chỉ đọc | 7 PASS. Kiểm tra claim, heartbeat, telemetry, ảnh JPEG, smart modes, PTZ và runtime giả lập. |
| SQLite thật cục bộ | Ba case `backend.tests.test_business.BusinessTests` gồm `test_reminder_commands_assets_and_telemetry`, `test_media_requires_scope_and_relays_frames_and_audio`, `test_device_cannot_read_other_camera_assets_or_invent_config_ack` | 3 PASS trên SQLite tạm, worker, MQTT tắt. |
| PostgreSQL 16 thật cục bộ | Năm case `backend.tests.test_postgres.PostgresTests` trên container tạm gồm `test_reminder_commands_assets_and_telemetry`, `test_media_requires_scope_and_relays_frames_and_audio`, `test_device_cannot_read_other_camera_assets_or_invent_config_ack`, `test_delayed_execution_uses_original_schedule_revision`, `test_tts_worker_finishes_asset_separately_and_quota_failure_is_retryable` | 5 PASS trên schema thực và role giới hạn. Test revision ghi đúng UTC và giữ một bản ghi khi gửi lại. |
| Frontend | `npm --prefix frontend run build` | PASS. |
| Kiểm tra diff và Python | `git diff --check`, `python -m compileall -q backend/src fall_detect/edge` | PASS. |
| File dài | `python scripts/audio/check_long_playback.py`, WAV im lặng 65 giây, FFmpeg `-re` → null, API và Bluetooth dùng fixture | Hết sau 65,71 giây. 14 heartbeat, 66 lần kiểm tra lịch, ACK `accepted → executing → executed`. |
| Decoder streaming | `python scripts/audio/benchmark_decoder.py`, 5 mẫu mỗi container, FFmpeg thật → file PCM tạm, không bật audio daemon | Kết quả phía dưới. |

Benchmark decoder đo từ lúc đẩy byte đầu đến khi đọc được hơn 1 KiB PCM. Nguồn tổng hợp khoảng 48 kbit/s và được cấp theo chu kỳ khoảng 200 ms. Các cột CPU và RSS là của decoder cục bộ. CPU tính theo phần trăm một lõi, cộng process thu fixture. Cỡ mẫu 5 nên dùng giá trị lớn nhất quan sát được.

| Container | First PCM median | Max quan sát | Đỉnh hàng đợi stdin | Đỉnh RSS FFmpeg | CPU cục bộ |
| --- | ---: | ---: | ---: | ---: | ---: |
| WebM/Opus | 93,6 ms | 93,6 ms | 1.300 B | 48.200 KiB | 5,81% |
| Ogg/Opus | 218,9 ms | 219,5 ms | 1.251 B | 48.180 KiB | 5,60% |

Đây là số đo từ byte đầu đến PCM trên máy phát triển. End-to-end, thời gian Stop ở loa, jitter, underrun/overrun âm học, CPU và RSS trên Pi đang chờ nghiệm thu.

## AUDIO-04 · Raspberry Pi 4

`ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=5 <user>@<pi-host>` trả `Permission denied (publickey,password)`. Host phản hồi nhưng khóa an toàn hiện tại không được chấp nhận. Chưa đọc được OS/kernel, commit triển khai, cấu hình service, dung lượng cache, trạng thái loa hoặc sink, và chưa kiểm thử phát trên Pi. Mọi chỉ tiêu âm học đều đang chờ phần cứng.

Khi có khóa hợp lệ, kiểm kê dependency và runtime ở chế độ chỉ đọc. Sau đó dùng checkout thử với cache và cấu hình riêng, loa thử ở âm lượng an toàn, không chạy song song process có thể điều khiển loa vận hành. Chạy chime, WAV, MP3, WebM/OGG, TTS tiếng Việt, lịch một lần gần và offline, file dài có heartbeat, Push-to-Talk, Stop, và ngắt/kết nối lại Bluetooth. Chỉ cô lập mạng trong môi trường fixture. Test gas/fall bằng fixture, không kích hoạt còi thật. Can thiệp service vận hành cần kế hoạch rollback và xác nhận trước.

Đo độ trễ âm học bằng ít nhất 30 xung đánh dấu ở đầu vào mic và bản thu gần loa với cùng đồng hồ ghi. Báo median/p95, offset so với đầu, giữa và cuối phiên 60 giây, độ trễ Stop, tiến trình còn sống sau disconnect, RSS/CPU FFmpeg và player, số lần underrun/overrun, mức đầy queue và số phiên đóng do backpressure. Lặp với LAN ổn định và giả lập mất liên kết trên mạng thử. Tiêu chí ban đầu là median dưới 1 giây, p95 dưới 2 giây, độ trễ không tích lũy, và Stop/ngắt mạng kết thúc phiên thay vì phát lại từ phiên cũ.

## Tương thích và rollback

HTTP route, schema backend, hình dạng trạng thái công khai, cache asset và danh sách occurrence cũ vẫn đọc được. SQLite mới là file cục bộ `audio_outbox.sqlite3` trên Edge. Các bảng backend và migration không cần cập nhật. JPEG, PTZ, model và camera giữ đường thực thi hiện tại. Thay đổi audio trên worktree cần được tích hợp với phiên bản đang chạy trước nghiệm thu.

Worktree gốc chưa nhận patch. Nếu cần bỏ thử nghiệm, tiếp tục làm việc ở checkout gốc và giữ nhánh thử để review. Nếu đã triển khai sau này, quay đồng bộ frontend/backend/Edge về phiên bản đã ghi nhận trước triển khai. Giữ config, cache, file sổ occurrence và outbox. Bản Edge cũ không tự gửi hàng đợi SQLite mới, nên nên đợi ACK/xuất kiểm tra số bản ghi đợi trước khi hạ phiên bản. Không reset database. Kiểm tra trạng thái service, sink, heartbeat, một lịch thử và quy tắc ưu tiên bằng fixture sau rollback.

| Ưu tiên | Hạng mục còn mở |
| --- | --- |
| P1 | Nghiệm thu Raspberry Pi và Bluetooth thật, gồm routing khi ngắt loa, tail sau Stop, deadline khởi tạo và hiệu năng xuyên suốt. |
| P1 | Đối chiếu và tích hợp các chỉnh sửa đang dang dở ở checkout ban đầu. |
| P2 | Xác minh profile tải trên LAN chậm và backend nhiều worker nếu topology triển khai thay đổi. |
| P2 | Xử lý những execution SQLite legacy bị từ chối sau hard-delete và cửa sổ mất báo cáo hiếm gặp giữa hai lần ghi đĩa, nếu vận hành cần khôi phục lịch sử đầy đủ. |
| P2 | Thiết bị cần đồng hồ hệ thống đã đồng bộ. Scheduler so thời gian tuyệt đối, chống phát trùng khi lùi giờ và giới hạn phát bù khi nhảy tới. Thời gian hệ thống sai khi offline chưa được xác minh trên Pi. |
