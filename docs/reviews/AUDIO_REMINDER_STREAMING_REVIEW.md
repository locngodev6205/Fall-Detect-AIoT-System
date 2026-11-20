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
