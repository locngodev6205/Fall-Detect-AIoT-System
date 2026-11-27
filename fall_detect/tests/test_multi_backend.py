from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from fall_detect.edge import main_edge
from fall_detect.edge.pairing import secondary_credentials, secondary_pairing_path
from fall_detect.update.updater import TemporaryNetworkError, Updater, atomic_json


def response(data, status=200):
    return SimpleNamespace(status_code=status, json=lambda: data, text="")


@pytest.fixture
def runtime(tmp_path):
    with ExitStack() as stack:
        for name in ("ArduinoBridge", "PanTiltTracker", "BluetoothSpeakerManager", "AudioPlayer"):
            stack.enter_context(patch.object(main_edge, name))
        runtime = main_edge.AnNhaEdgeRuntime(
            base_url="http://localhost:8188", device_token="local-test",
            backend_2=("https://demo.example", "cloud-test"), cache_dir=tmp_path)
        yield runtime
        runtime.audio_worker.stop()
        for client, _, _, _ in runtime._backends:
            client.stop()


def test_pairing_does_not_open_an_incomplete_pairing_or_touch_primary(tmp_path):
    env_path = tmp_path / "app.env"
    primary = tmp_path / ".env.edge.pairing-app.env.json"
    primary.write_text("unchanged")
    peer = secondary_pairing_path(env_path)
    values = {"ANNHA_BACKEND_2_ENABLED": "true", "ANNHA_BACKEND_2_BASE_URL": "https://demo.example/"}
    assert secondary_credentials({}, env_path) is None
    for paired in (False, True):
        atomic_json(peer, {"base_url": "https://demo.example", "token": "cloud-test", "paired": paired})
        assert secondary_credentials(values, env_path) == ("https://demo.example",
                                                            "cloud-test" if paired else "")
    assert primary.read_text() == "unchanged"
    with pytest.raises(ValueError):
        secondary_credentials(values, env_path, primary_url="https://demo.example")


def test_two_lanes_share_hardware_and_route_http_commands_and_config(runtime):
    first, second = runtime._backends
    for constructor in (main_edge.ArduinoBridge, main_edge.PanTiltTracker, main_edge.AudioPlayer):
        constructor.assert_called_once()
    requests = []
    for version, threshold, (client, scheduler, _, _) in zip((9, 2), (.87, .72), (first, second)):
        def request(method, path, json_body=None, origin=client, ver=version, value=threshold):
            requests.append((origin.base_url, origin._headers()["Authorization"], method, path, json_body))
            if path.endswith("/config"):
                return response({"version": ver, "smart_modes": {"fall_confidence_threshold": value}})
            if path.endswith("/commands"):
                return response([{"id": "same-id", "kind": "ptz_move"}])
            if "/commands/" in path:
                return response({"status": json_body["status"]})
            return response({})

        client._request = request
        runtime.tracker.execute_ptz_command.return_value = True, "moved"
        client.send_heartbeat(camera_ok=True)
        client.send_telemetry({})
        client.sync_config()
        assert client.poll_and_execute_commands() == 1
        assert client.applied_version == version
        assert scheduler.asset_resolver.__self__ is client
        assert scheduler.execution_reporter.__self__ is client
    first[0].sync_config()
    assert runtime._fall_threshold == .72
    assert runtime.tracker.execute_ptz_command.call_count == 2
    assert first[0].cache_dir != second[0].cache_dir
    assert not second[0].tb.enabled
    for host, token, version in ((first[0].base_url, "local-test", 9), (second[0].base_url, "cloud-test", 2)):
        own = [(path, body) for url, auth, method, path, body in requests if url == host and auth == f"Bearer {token}"]
        assert any(path.endswith("/heartbeat") for path, _ in own)
        assert any(path.endswith("/telemetry") for path, _ in own)
        assert any(path.endswith("/config/ack") and body["version"] == version for path, body in own)
        assert any("/commands/same-id" in path and body["status"] == "executed" for path, body in own)


def test_fall_fanout_retries_only_the_failing_backend(runtime):
    first, second = [lane[0] for lane in runtime._backends]
    first._request = MagicMock(return_value=response({"id": "first-event"}))
    second._request = MagicMock(side_effect=[OSError("offline"), response({"id": "second-event"})])
    runtime.handle_fall_detected(.91, "fixture")
    first._request.assert_not_called()
    second._request.assert_not_called()
    runtime.audio.trigger_emergency_siren.assert_called_once()
    first._flush_outbox()
    second._flush_outbox()
    assert runtime.unreported_alert
    second._flush_outbox()
    assert not runtime.unreported_alert
    first_event = first._request.call_args.kwargs["json_body"]
    assert [call.kwargs["json_body"] for call in second._request.call_args_list] == [first_event, first_event]


def test_ota_recovery_uses_origin_and_an_offline_peer_does_not_stop_polling(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    atomic_json(shared / "updater.json", {"backend_url": "http://localhost", "device_token": "first"})
    updater = Updater(tmp_path)
    try:
        secondary = ("https://demo.example", "second")
        updater._backend_2 = lambda: secondary
        report_routes = []
        updater.report = lambda *args: report_routes.append((updater.base, updater.token))
        atomic_json(updater.journal, {"job": {"id": "duplicate-id"}, "outcome": "failed",
                                     "origin": updater._origin(secondary)})
        visited = []

        def tick(*, cleanup):
            visited.append((updater.base, updater.token))
            if updater.base == updater.primary[0]:
                raise TemporaryNetworkError("offline")
            return False

        updater.tick = tick
        updater.run_cycle()
        assert report_routes == [secondary]
        assert not updater.journal.exists()
        assert visited == [updater.primary, secondary]
    finally:
        updater.lock.close()


def test_one_jpeg_is_published_to_both_streams(runtime):
    first, second = [lane[2] for lane in runtime._backends]
    jpeg = b"\xff\xd8\xfftest-jpeg"
    runtime._publish_frame(jpeg)
    assert first.get_latest_jpeg() is jpeg
    assert second.get_latest_jpeg() is jpeg
    runtime._publish_frame(None)
    assert first.get_latest_jpeg() is second.get_latest_jpeg() is None


def test_immobility_recovery_stays_ordered_while_one_backend_is_offline(runtime):
    first, second = runtime._backends
    for _, _, _, events in (first, second):
        events.submit(SimpleNamespace(transition=main_edge.State.INACTIVE, duration_s=30))
        events.submit(SimpleNamespace(transition=main_edge.State.RECOVERED, duration_s=31))
    first[0]._request = MagicMock(return_value=response({"id": "first-event"}))
    second[0]._request = MagicMock(side_effect=[
        OSError("offline"), response({"id": "second-event"}), response({"id": "second-event"}),
    ])
    for stamp in (1, 2, 6, 7):
        for client, _, _, events in (first, second):
            events.flush(client, stamp)
    for lane, sequences in ((first, [1, 2]), (second, [1, 1, 2])):
        payloads = [call.kwargs["json_body"] for call in lane[0]._request.call_args_list]
        assert [body["sequence"] for body in payloads] == sequences
        assert len({body["event_id"] for body in payloads}) == 1
