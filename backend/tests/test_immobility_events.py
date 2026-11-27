"""Verify immobility and recovery through the real API without notification workers."""
from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/"fall_detect"))

from backend.src import device_updates
from backend.tests import test_business
from edge.main_edge import AnNhaEdgeRuntime


def test_smart_modes_sync_and_immobility_event_recovery(tmp_path, monkeypatch):
    fixture = test_business.BusinessTests()
    fixture.setUp()
    try:
        owner, _ = fixture.account("immobility@example.test")
        home, _, camera, provision = fixture.home_camera(owner)
        device = fixture.device(provision)
        runtime = AnNhaEdgeRuntime(base_url="http://127.0.0.1:1", device_token="test", cache_dir=tmp_path,
                                   force_mock_hardware=True)
        path = f'/api/cameras/{camera["id"]}/smart-modes'
        _, _, other, _ = fixture.home_camera(owner)
        other_path = f'/api/cameras/{other["id"]}/smart-modes'
        for invalid in (0, -1, 604801, 31.5, True):
            assert owner.put(path, json={"immobility_timeout_seconds": invalid}).status_code == 422

        def request(method, endpoint, *, json_body=None):
            return device.request(method, endpoint, json=json_body)

        monkeypatch.setattr(runtime.client, "_request", request)

        def sync(**changes):
            response = owner.put(path, json=changes)
            assert response.status_code == 200, response.text
            desired = response.json()["desired_version"]
            assert response.json()["applied_version"] < desired
            assert runtime.client.sync_config()["version"] == desired
            assert runtime.client.applied_version == desired
            assert owner.get(path).json()["applied_version"] == desired

        sync(immobility_detection=True, immobility_timeout_seconds=210, fall_detection=False)
        assert owner.get(path).json()["smart_modes"]["fall_confidence_threshold"] == 0.85
        for invalid in (-0.01, 1.01, True, "NaN", "Infinity", None):
            assert owner.put(path, json={"fall_confidence_threshold": invalid}).status_code == 422
        runtime._fall_detector = SimpleNamespace(confidence_threshold=0.85, sequence_buffer=[object()])
        buffer = runtime._fall_detector.sequence_buffer
        sync(fall_confidence_threshold=0.70)
        assert runtime._fall_detector.confidence_threshold == 0.70
        assert runtime._fall_detector.sequence_buffer is buffer and len(buffer) == 1
        assert runtime.client.current_config["smart_modes"]["immobility_timeout_seconds"] == 210
        assert not runtime.client.current_config["smart_modes"]["fall_detection"]
        assert owner.get(other_path).json()["smart_modes"]["fall_confidence_threshold"] == 0.85
        restarted = AnNhaEdgeRuntime(base_url="http://127.0.0.1:1", device_token="test", cache_dir=tmp_path,
                                     force_mock_hardware=True)
        try:
            assert restarted._fall_threshold == 0.70
        finally:
            restarted.client.stop()
        sync(fall_confidence_threshold=0.85)
        assert runtime._fall_detector.confidence_threshold == 0.85
        runtime._observe_immobility(0)
        assert runtime.immobility.duration_s == 210
        sync(immobility_detection=False, immobility_timeout_seconds=120)
        assert owner.get(other_path).json()["smart_modes"]["immobility_timeout_seconds"] == 600

        def frame(i, x):
            landmarks = SimpleNamespace(landmark=[SimpleNamespace(x=x, y=.5, visibility=.95)]*33)
            runtime._observe_immobility(i/5, landmarks, {"pan": 90, "tilt": 90, "moving": 0})

        with owner.websocket_connect(f'/ws/alerts?home_id={home["id"]}') as alerts:
            for i in range(175):
                frame(i, .4)
            assert runtime.immobility_reading.state.value == "UNKNOWN"
            assert runtime.immobility.duration_s == 120
            sync(immobility_detection=True, immobility_timeout_seconds=30)
            for i in range(175, 315):
                frame(i, .4)
            # Edge may ACK two versions between consecutive camera frames.
            sync(immobility_detection=False)
            sync(immobility_detection=True)
            for i in range(315, 345):
                frame(i, .4)
            assert runtime.immobility.duration_s == 30
            client = runtime.client
            runtime.immobility_events.flush(client, 69.)
            assert owner.get(f'/api/homes/{home["id"]}/events').json() == []
            for i in range(345, 495):
                frame(i, .4)
            runtime.immobility_events.flush(client, 99.)
            assert runtime.immobility_events.pending is None
            assert len(owner.get(f'/api/homes/{home["id"]}/events').json()) == 1
            opened = alerts.receive_json()
            assert opened["observation"] == "abnormal"
            assert opened["sequence"] == 1
            sync(immobility_detection=False)
            frame(495, .4)
            assert runtime.immobility_reading.state.value == "UNKNOWN"
            sync(immobility_detection=True)
            for i in range(496, 680):
                frame(i, .4)
            runtime.immobility_events.flush(client, 136.)
            assert len(owner.get(f'/api/homes/{home["id"]}/events').json()) == 1
            assert runtime.immobility_events.event_id == opened["source_id"]
            for i in range(680, 692):
                frame(i, min(.9, .4+.035*(i-680)))
            runtime.immobility_events.flush(client, 139.)
            assert runtime.immobility_events.pending is None
            recovered = alerts.receive_json()
            assert recovered["id"] == opened["id"]
            assert recovered["observation"] == "recovered"
            assert recovered["sequence"] == 2
        history = owner.get(f'/api/homes/{home["id"]}/events').json()
        assert len(history) == 1
        assert history[0]["payload"]["duration_s"] >= 30
        assert history[0]["status"] == "OPEN"
        assert device_updates.blocked(camera["id"])
        response = owner.post(f'/api/events/{opened["id"]}/actions', json={"action": "resolve"})
        assert response.status_code == 200, response.text
        assert not device_updates.blocked(camera["id"])
    finally:
        fixture.tearDown()
