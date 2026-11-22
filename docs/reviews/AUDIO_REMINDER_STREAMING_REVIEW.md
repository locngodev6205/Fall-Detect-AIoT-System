# Independent review · AnNhà audio

**Base SHA** `f16e2d672a0b27ec36da281f1d91a85002d3dd00` (`main`)

**Head SHA for implementation and tests** `a7cd9febe988e18333805bbdf78f91d0e4e2bef2`

**Full branch head** See the Draft PR head or the branch history. This file is added by the final documentation commit, whose own SHA cannot be embedded in its content.

**Status** LOCAL TESTED. Pi acceptance pending.

## Commits

- `5b0800f2893a91b91e49ddebe00d44ba956d8e68` · Playback, reminders, durable results and incremental streaming.
- `a7cd9febe988e18333805bbdf78f91d0e4e2bef2` · Automated tests and repeatable local benchmarks.
- The final documentation commit adds this review package and updates the Device API notes.

## Findings addressed

| Priority | Finding at base | Change |
| --- | --- | --- |
| P0 | Priority admission and child registration were separate in `AudioPlayer.play_file`. | Serialize sink ownership, preempt lower priority audio and preserve gas immunity to silence. |
| P1 | Command polling waited for long file playback. Reminders and speaker tests could record success when the player started. | Bounded worker, terminal result after child exit, persistent command receipts and occurrence reports. |
| P1 | Reminder catch-up missed occurrences across midnight, and missing uploaded assets could turn into TTS. | Compare timestamps and local occurrence dates. Preserve upload source and report missing asset. |
| P1 | PostgreSQL used the current revision and receipt time as the scheduled time. The conflict target also exceeded the insert-only device role. | Resolve the original revision from the occurrence and use idempotent INSERT under the existing role. |
| P1 | Pi buffered all microphone chunks and only played at Stop. | Session-long Opus decode and PCM output with bounded flow control and cleanup. |
| P2 | Config application and device cache readiness were reported together. | Keep configuration applied while surfacing missing audio assets during background prefetch. |

## Audio flow

```text
Before
Web command → FastAPI → device poll → playback wait on Edge I/O
Reminder → config/cache → scheduler → spawn → played
Microphone → MediaRecorder → WebSocket → Pi session buffer → Stop → file → speaker

After
Web command → FastAPI → device poll → bounded worker → Bluetooth → durable terminal ACK
Reminder → config/cache → occurrence claim → bounded worker → Bluetooth → SQLite outbox → FastAPI
Microphone → MediaRecorder/Opus → authenticated relay → FFmpeg stdin → PCM → Bluetooth
                                           ↑ per-chunk receipt from Pi
```

## Components and compatibility

- Edge `audio_player.py`, `worker.py` and `main_edge.py` handle file playback and priority. `live_input.py` and `live_streamer.py` own the live player and stream cleanup.
- Edge `scheduler.py` and `device_client.py` handle the time window, asset cache, deduplication and durable results.
- Backend `audio_relay.py` is shared by the SQLite and PostgreSQL WebSocket adapters. `pgapi.py` resolves revision metadata using existing tables. Backend schema migrations are unnecessary. Edge adds a local SQLite outbox.
- Frontend `LiveAudio.jsx` negotiates the stream and owns microphone cleanup. `Reminders.jsx` explains catch-up. The new Push-to-Talk handshake requires compatible frontend, backend and Edge versions. JPEG and PTZ regressions are covered by the Edge tests.
- Detailed failure semantics, benchmark scripts and rollback are in the [audio hardening report](../AUDIO_HARDENING_REPORT.md).

## Tests on the review branch

- `python -m unittest discover -s fall_detect/tests -p 'test_*audio*.py'` · 15 PASS.
- `python -m unittest fall_detect.tests.test_group1_sensors fall_detect.tests.test_group2_device_client fall_detect.tests.test_group3_tracking_ptz fall_detect.tests.test_group5_main_edge` · 11 PASS, using an isolated SQLite Docker backend with the worktree source mounted read-only.
- `python -m unittest backend.tests.test_audio_relay backend.tests.test_media_storage` plus the three audio/device cases of `backend.tests.test_business.BusinessTests` identified in the audit report · 17 PASS.
- Five targeted cases in `backend.tests.test_postgres.PostgresTests`, listed in the audit report, with `ANNHA_TEST_ENV` pointing to a disposable PostgreSQL 16 fixture and remote providers disabled · 5 PASS.
- `npm --prefix frontend run build`, `python -m compileall -q backend/src fall_detect/edge scripts/audio` and `git diff --check` · PASS.
- Local benchmarks from the implementation worktree. The 65-second fixture recorded 14 heartbeat calls and 66 scheduler checks. Decoder first PCM median was 93.6 ms for WebM and 218.9 ms for Ogg, peak RSS about 47 MiB, and CPU below 6% of one development-host core. These assays used a fixture output.

## Raspberry Pi verification

The read-only SSH retry reached the Pi, but the configured key was rejected. Hardware playback, acoustic latency, CPU/RAM on Pi, Bluetooth disconnect, stop tail and real browser-to-speaker acceptance remain pending.

## Outstanding issues and regression risks

- P0 · No open P0 issue confirmed locally. Verify priority and sink routing on the target using a safe, isolated fixture before acceptance.
- P1 · Measure physical playback, Stop/disconnect, device resource use and latency drift. Roll out the handshake participants together after review.
- P2 · Relay state is per process. Multi-worker deployment needs routing coordination. A crash between the JSON claim and outbox write can omit an execution record. Offline clocks and legacy SQLite deletion can affect history as described in the audit.
- The patch was ported from a diverged Edge checkout. Resolve overlaps deliberately if it is later integrated with that checkout's uncommitted fall-detection and maintenance changes.

## Review checklist

- [ ] Trace gas/fall preemption, silence behavior, and player ownership during Stop, shutdown or simultaneous starts.
- [ ] Check execution durability before playback and after exit, retries on uncertain ACK and stale schedules across timezone, DST and offline updates.
- [ ] Validate origin, token and camera permissions, per-camera session exclusivity, queued byte limits and child cleanup.
- [ ] Check PostgreSQL revision metadata and idempotent writes with device-role permissions.
- [ ] Review dependency and sink selection on Raspberry Pi and independently confirm microphone-to-speaker latency.

## Draft PR #2 · Follow-up on four P1 findings

The findings were reproduced against review head `4ee47904b9887bcc6598601fb316bfa2f8425721`.

| Finding | Verified behavior and change | Regression evidence |
| --- | --- | --- |
| Offline scheduling | `_background_io_loop` called the scheduler after synchronous HTTP. The runtime now starts a separate reminder loop every five seconds using the shared shutdown event. Scheduler evaluation reads cached config and queues work on the existing audio worker. | Each of telemetry, heartbeat, command polling and snapshot upload is blocked in a real fixture thread while the scheduler advances through 125 virtual seconds. A cached reminder with zero late tolerance plays in its scheduled minute. |
| Durable command ACK | A terminal ACK receipt was dropped on any HTTP 404/409. Deletion now requires HTTP 200 with a matching status. Both backends expose the persisted terminal state on a conflicting 409. A reconciled discrepancy retains both statuses on disk for review. Generic 409, 404, transport failure and unconfirmed responses retain the receipt for retry. | The Edge fixture verifies conflicting and expired terminal states, unconfirmed HTTP responses, and retry after restart. Backend integration verifies same-state idempotency and structured conflicts on SQLite and PostgreSQL. |
| Emergency siren | Cooldown was set before the speaker and child process were ready. An in-flight reservation now prevents concurrent duplicate starts. Only a successful, uninterrupted player exit commits the cooldown, measured from the original trigger. Failed or interrupted playback releases the reservation. | Fixtures verify missing speaker recovery, nonzero child exit, gas immunity to silence and emergency preemption. No physical siren was triggered. |
| Streaming readiness | LiveInput previously assumed `pw-cat` would exist and returned after spawn even when the player immediately exited. It now checks FFmpeg and the backend-specific player, accepts `pw-play` when `pw-cat` is absent, verifies the targeted BlueZ node and resolves its serial on PipeWire, and reaps both processes on early startup failure. | Fixtures cover missing dependencies, `pw-play` selection, analog ID reuse, early child exit, cleanup and an `unavailable` reply. FFmpeg fixture tests still confirm incremental PCM. |

A stalled HTTP call can still delay other network operations within the I/O thread. Cached scheduling is independent of that thread. An uncached asset can still consume time on the audio worker, and schedule edits made remotely only take effect after config reaches the Pi. Unconfirmed ACKs retry with a 60-second backoff. Reconciled conflicts remain in the Edge SQLite outbox for investigation. The added receipt columns migrate locally on Edge startup. Backend schema is unchanged.

Push-to-Talk startup verifies dependencies, validates the selected PipeWire node and checks for immediate child failures. Device `ready` confirms those checks completed. A failure that occurs when decoding or attaching the PCM stream can surface on a later chunk. The Pi rejected the read-only SSH retry with `Permission denied (publickey,password)`. Hardware dependency versions, actual sink routing, Bluetooth playback and acoustic latency remain unverified.

Follow-up test commands and counts appear below. Earlier benchmarks above describe the original patch. No AI model, OTA code or production database was changed.

### Follow-up verification

- `python -m unittest fall_detect.tests.test_audio_hardening fall_detect.tests.test_group4_audio_scheduler` · 22 PASS.
- `python -m unittest fall_detect.tests.test_group1_sensors fall_detect.tests.test_group2_device_client fall_detect.tests.test_group3_tracking_ptz fall_detect.tests.test_group5_main_edge` · 11 PASS, isolated SQLite Docker fixture.
- `backend.tests.test_audio_relay`, `backend.tests.test_media_storage` and the three targeted `BusinessTests` listed in the audit · 17 PASS using a temporary SQLite database.
- Five targeted `PostgresTests` listed in the audit · 5 PASS using an isolated PostgreSQL 16 instance.
- `python scripts/audio/benchmark_decoder.py` · PASS for both codecs. First PCM after startup was 11.3 ms median for WebM and 217.4 ms for Ogg on the development host. This run measures from the first input bytes after the startup probe and excludes microphone capture and Bluetooth.
- `python -m compileall -q backend/src fall_detect/edge fall_detect/tests scripts/audio` and `git diff --check` · PASS.

## Acceptance follow-up from `ba24c49671af18cefd02e3f445f5355571ae8207`

### Safe preemption fixture

`python -m unittest fall_detect.tests.test_audio_acceptance_fixtures` runs real child processes that ignore SIGTERM. A silent `true` process stands in for emergency playback. Timing starts at the emergency trigger. The completion measurement includes reaping the displaced processes, explicitly through the session owner for Push-to-Talk. The fixture budget is 500 ms. This measures process control on the development host and excludes Bluetooth discovery, audio-server scheduling and acoustic output.

| Event and source | Prior emergency spawn | Updated emergency spawn | Updated completion | Result |
| --- | ---: | ---: | ---: | --- |
| Gas during file playback | 1004.5 ms | 1.5 ms | 3.2 ms | PASS |
| Fall during file playback | 1003.9 ms | 3.9 ms | 7.1 ms | PASS |
| Gas during Push-to-Talk | 0.3 ms | 0.3 ms | 1.1 ms | PASS |
| Fall during Push-to-Talk | 0.4 ms | 0.3 ms | 1.3 ms | PASS |

Both file scenarios failed the fixture budget before the fix because the player got a full SIGTERM grace period. Emergency preemption now kills the displaced file process immediately and waits briefly to reap it. Normal shutdown and silence retain their existing behavior.

### Durable ACK capacity

An atomic reservation limits new unconfirmed audio ACK receipts to 512. A command that cannot reserve space remains pending on the backend until the backlog drains or the command expires. Existing unconfirmed receipts are retained even if an upgraded device starts over the limit. Reconciled conflict history is capped at 256, ordered by local receipt insertion. Tests verify that saturation preserves unconfirmed data, ACK recovery restores capacity, and pruning touches only reconciled history. These are logical row limits for command receipts. SQLite can retain freed pages, and reminder execution reports use a separate table.

### Raspberry Pi acceptance

Read-only SSH reached the Pi and returned `Permission denied (publickey,password)` with batch mode and strict host-key validation. Inventory of runtime and dependencies, sink selection and audio output, TTS/WAV/MP3, offline reminders, browser-to-speaker streaming, Stop latency, Bluetooth disconnect and Pi CPU/RAM are **BLOCKED**. No physical alarm or audio fixture was run, no service was restarted and no code was deployed. Once key access and a separate test sink/runtime are available, follow the hardware procedure in the audit report. Physical preemption must include Bluetooth discovery and measure actual speaker output.

### Acceptance regression results

- `python -m unittest fall_detect.tests.test_audio_acceptance_fixtures fall_detect.tests.test_audio_hardening fall_detect.tests.test_group4_audio_scheduler` · 25 PASS. This run observed at most 6.5 ms for trigger-to-cleanup in the preemption fixture.
- `python -m unittest fall_detect.tests.test_group1_sensors fall_detect.tests.test_group2_device_client fall_detect.tests.test_group3_tracking_ptz fall_detect.tests.test_group5_main_edge` · 11 PASS with the isolated SQLite Docker fixture.
- `python -m compileall -q fall_detect/edge fall_detect/tests` and `git diff --check` · PASS.

## Classroom demo verification on Raspberry Pi 4

The running `annha-edge.service` reported release `0.1.0` at commit `483adb543a6a8cad76065ace2f70f7d9508a84bc`. The deployed Edge file hashes differ from PR #2 at `ddd7136a883812816d6071a03fcc0f099998cdf6`. Deployed Push-to-Talk still joins its chunks on Stop, and the release lacks `live_input.py`. The service retained PID 1248 throughout the test.

- Sony SRS-XB13 was the selected BlueZ sink. PipeWire and WirePlumber were active, and FFmpeg 7.1.5 decoded WAV and MP3. Both low-volume test tones reached the speaker and were heard by the operator.
- A short Vietnamese speech asset reached the physical speaker, but the operator reported choppy and unintelligible speech. Two comparison WAVs, one unpadded and one with leading and trailing silence, both exited with code 0. The operator reported that both comparison WAVs still sounded choppy or unintelligible. A separately generated five-second continuous 48 kHz stereo tone also sounded interrupted. The targeted BlueZ sink and player both showed ERR=0 in the sampled PipeWire counters and the player exited 0. This reproduces the audible issue on direct Bluetooth playback without the app, codec input, or TTS. The specific cause downstream remains unverified. In the first Pi session, temporarily extracted eSpeak NG generated and played a 2.88-second Vietnamese WAV. The system still lacks eSpeak NG, so runtime offline synthesis remains blocked until that dependency is provisioned.
- The exact PR scheduler ran out of a temporary directory, with only a cached audio resolver and no backend configured. A one-time schedule was empty before the due minute, returned `played` at about 0.91 seconds into the minute and returned no duplicate.
- In the isolated browser test, Chrome with a synthetic microphone sent 13 chunks via the PR relay. The Pi showed an active PipeWire link to SRS-XB13 before Stop. Chrome closed with code 1000. Separate direct fixture playback reaped both child processes on Stop. The browser tunnel ended without a WebSocket close frame at teardown, so the full browser disconnect path and a real microphone on the deployed UI still need a final demo check.
- The 25 focused audio regression tests passed. No deployed files, service restarts, OTA, or changes to the production backend were needed.

For classroom deployment, stage the tested PR revision beside the current release using a separate checkout and demo cache. Pair the matching demo frontend and backend with the staged Edge and prepare eSpeak NG or cache the TTS assets required for the presentation. Leave the existing service online during staging. Switch runtime ownership of the camera and speaker only during an approved cutover. Keep release 0.1.0 available so the service can be switched back and verified if the demo fails.

### Bluetooth follow-up and demo staging

- Pi runtime inventory showed BlueZ 5.82, PipeWire 1.4.2, WirePlumber 0.5.8, and a connected SRS-XB13 on A2DP/SBC. Wi-Fi was associated at 5745 MHz with a signal of -57 dBm. Sampled CPU idle was 59–72%, with no I/O wait. This Pi Wi-Fi link was on 5 GHz during the check. External 2.4 GHz interference remains unverified.
- A direct 48 kHz stereo WAV was played twice with per-player latency requests of 200 and 600 ms. Both runs exited 0 and the sampled error counters for the player and BlueZ sink stayed at 0. The player quantum changed from 9600 to 28800 frames, while the BlueZ node stayed at 2048 frames. The operator confirmed dropout in both trials when played separately. Increasing the player buffer did not resolve the audible failure.
- Installed eSpeak NG 1.52.0 and its four new dependencies, with no package upgrades or removals. The offline Vietnamese voice produced a 2.87-second WAV and playback exited 0. The operator reported interrupted or hard-to-understand speech during the separate listening check. The running AnNhà service remained active with PID 1248.
- Edge source is staged at `~/annha-audio-demo-cba5ea0`, pinned to `cba5ea0f523e0a928778f5bcef764881cef3146b`. The staged audio modules import in the Pi runtime interpreter. The backend relay and SQLite integration passed seven tests in isolation. The existing frontend build matches this revision's application source. The staged Edge is not a full release bundle and has not taken ownership of the camera or speaker. The demo stack still needs an authorized cutover and a live mic test.
- The Pi exposes a 3.5 mm ALSA output. No USB playback device appeared in `aplay -l`. If a powered analog speaker or a USB speaker is available, test it explicitly during demo prep. The Edge Bluetooth-only routing guard remains in place.
- Keep release `0.1.0` and its configuration active while staging. A cutover should use matching demo web, backend, and Edge with separate test configuration and cache. Record the active service entry point before switching so rollback can restore `0.1.0`. No service restart, routing change, merge, or OTA was performed.

### Physical 3.5 mm comparison

With a 3.5 mm device connected, the operator confirmed that a five-second continuous 48 kHz stereo tone and the offline eSpeak NG Vietnamese sentence were clear and uninterrupted. Each was played separately using the explicitly selected bcm2835 Headphones PipeWire node, with fallback disabled and 12% stream volume. Both children exited 0. The same listener heard dropouts on the Bluetooth comparison at both 200 and 600 ms. This validates the analog output as a hardware fallback. The deployed default sink and Bluetooth-only runtime routing were left in place. Integrated Reminder and Push-to-Talk through the wired output still require a staged demo test and authorization before runtime cutover.

### Wired audio output

Set `ANNHA_AUDIO_OUTPUT=analog` in the Edge env file. Existing local configurations with `analog_demo` still work. The default is `analog` for devices without an explicit local setting or a saved camera preference. A saved camera preference wins. Existing explicit local Bluetooth settings are preserved until a camera preference is applied. Analog mode selects a PipeWire sink whose ALSA card is exactly `bcm2835 Headphones`, targets its object serial, and fails closed if it cannot find it. File playback, TTS, reminders, local warning audio and Push-to-Talk share that selection. The wired output scales volume per stream to at most 25%, preserving the volume setting's relative range. Bluetooth commands are unavailable in analog mode. Neither mode sets the system default sink.

**Staging and cutover**

1. The Pi checkout at `~/annha-audio-demo-cba5ea0` runs the tested Edge source. Keep the demo env and cache separate under `~/annha-audio-analog-demo`. The isolated PTT fixture uses a loopback tunnel. For the class demo, first configure a reachable matching backend and frontend with the newer WebSocket protocol, a demo camera/account and separate backend data. Put the demo device credentials only in the private demo env file.
2. Keep `annha-edge.service` and release `0.1.0` running during prep. Before a full-runtime cutover, supply the normal model/dependencies in a separate demo checkout or release bundle. Confirm that the demo env explicitly selects analog, points to the demo backend, and uses its own cache. The CLI default cache is relative to its source checkout.
3. After the operator approves downtime, stop the current service and verify that its process released camera/serial. Run exactly one candidate Edge with the separate env and matching web/backend. Verify the demo controls and media routing. Do not install an OTA or overwrite the active release.
4. To roll back, stop the candidate and start the original `annha-edge.service`. Verify its working directory is still release `0.1.0`, then verify the current camera and sensor functions. The staging database, env and cache stay separate.

Focused regression tests passed (29), and the frontend build succeeded. Listener-confirmed WAV, MP3 and offline Vietnamese TTS passed through the real `AudioPlayer` targeting headphone serial 59. A cached one-time reminder with no backend configured started 0.40 seconds into the due minute on the repeat test, completed, and returned no duplicate. The listener heard it exactly once. The priority and local warning routing were verified with safe subprocess fixtures. No physical gas or fall alarm was triggered.

The physical live acceptance used Chrome with the operator's real microphone and the PR's actual `LiveAudio` React component, an isolated FastAPI `AudioRelay` with fixture identity, and the staged Edge on Pi. The operator heard audio while speaking and confirmed the speaker went quiet on Stop. Pi logged target serial 59 and `PTT STOP: -9 -9 busy=False` twice. The integrated staging path is demo-ready. The full installed service still requires the approved cutover above.

### Camera-managed audio output

`GET/PUT /api/cameras/{camera_id}/audio-output` uses the existing camera revision on SQLite and PostgreSQL. PUT requires the camera's audio permission. The Edge reports its actual mode, revision and readiness in the next heartbeat. The selector and test command distinguish pending requests from Edge confirmation. The PostgreSQL compiler preserves the setting across reminder and smart-mode revisions. There is no database migration. Edge accepts `analog_demo` as a legacy local alias of `analog`.

Pi acceptance on code `5729980` used the PR React card in Chrome, a separate real SQLite backend, and only the PR audio/config client on the Pi. After an API switch to analog, the frontend API first reported pending, then actual analog and applied revision 2. The test command reached executed and the operator heard it on the wired speaker. The reverse switch reached Bluetooth and revision 3. The test chime and a five-second WAV both reached executed, but the operator reported dropouts in the longer Sony SRS-XB13 playback. The real React selector then switched to analog revision 4 and displayed wired ready only after the Pi report. An isolated Edge restart with an unreachable backend restored analog from its cache and rediscovered serial 59.

A route change waits for the current file, live session or emergency sequence before applying. No mode silently falls back to another sink or modifies the system default. The device-level Ready state reflects that a sink was found. Speaker quality was independently assessed by listening. Wired TTS, reminders and microphone Stop were already heard on the previous staging revision. Those flows were not retested through the full installed runtime during this follow-up. The original service retained PID 1248 and the system's default output remained SRS-XB13. A coordinated frontend/backend/Edge cutover and full runtime validation require operator approval.
