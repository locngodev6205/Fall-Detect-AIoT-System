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
