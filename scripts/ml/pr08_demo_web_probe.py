"""Send one measured replay event through the existing web API in a temporary SQLite fixture."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.src import db
from backend.tests.test_business import BusinessTests


def probe(result):
    stamps = result["events"]["baseline"]
    if len(stamps) != 1:
        raise ValueError("Web probe requires a replay with exactly one baseline event")
    fixture = BusinessTests()
    fixture.setUp()  # Temporary database, workers and MQTT disabled.
    try:
        owner, _ = fixture.account("pr08-replay@example.test")
        home, _, _, provision = fixture.home_camera(owner)
        device = fixture.device(provision)
        payload = dict(event_id="pr08-replay-episode", kind="fall", severity="critical",
                       observation="abnormal", observed_at=db.now(),
                       reason=f"Offline replay at {stamps[0]:.2f}s")
        with owner.websocket_connect(f'/ws/alerts?home_id={home["id"]}') as alerts:
            response = device.post("/api/device/events", json=payload)
            response.raise_for_status()
            event_id = response.json()["id"]
            assert alerts.receive_json()["id"] == event_id
        retry = device.post("/api/device/events", json=payload)
        retry.raise_for_status()
        assert retry.json()["id"] == event_id
        history = owner.get(f'/api/homes/{home["id"]}/events')
        history.raise_for_status()
        assert [item["id"] for item in history.json()] == [event_id]
        return dict(replay_timestamp=stamps[0], api=response.status_code,
                    events_in_history=1, websocket_event=True, retry_reused_event=True)
    finally:
        fixture.tearDown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("replay", type=Path)
    print(json.dumps(probe(json.loads(parser.parse_args().replay.read_text())), indent=2))
