"""Shared HTTP and WebSocket release contract for SQLite and PostgreSQL."""

from pathlib import Path


def exercise_edge_021_contract(self):
    from importlib import import_module
    import sys
    from unittest.mock import patch

    with patch.object(sys, 'path', [*sys.path, str(Path(__file__).resolve().parents[2] / 'fall_detect')]):
        DeviceClient = import_module('edge.client.device_client').DeviceClient

    owner, _ = self.account('immobility-contract@example.test')
    home, _, camera, provision = self.home_camera(owner)
    device = self.device(provision)
    path = f"/api/cameras/{camera['id']}"
    initial = owner.get(path + '/smart-modes').json()
    self.assertEqual((initial['desired_version'], initial['applied_version']), (1, 0))
    saved = owner.put(path + '/smart-modes', json={
        'immobility_detection': True, 'immobility_timeout_seconds': 30,
    })
    self.assertEqual(saved.status_code, 200, saved.text)
    self.assertEqual((saved.json()['desired_version'], saved.json()['applied_version']), (2, 0))
    self.assertTrue(saved.json()['smart_modes']['servo_tracking'])
    self.assertTrue(saved.json()['smart_modes']['fall_detection'])

    edge = DeviceClient('http://testserver', provision['device_token'],
                        cache_dir=Path(self.temp.name) / 'edge-cache')
    self.addCleanup(edge.stop)
    calls = []

    def request(method, url, *, json_body=None):
        result = device.request(method, url, json=json_body)
        calls.append((method, url, json_body, result.status_code))
        return result

    with patch.object(edge, '_request', side_effect=request):
        heartbeat = edge.send_heartbeat(audio_output={'mode': 'analog', 'ready': True, 'error': ''})
        self.assertIsNotNone(heartbeat, calls)
        self.assertEqual(heartbeat['desired_version'], 2)
        self.assertEqual(edge.applied_version, 2)
        self.assertEqual(edge.current_config['version'], 2)
        self.assertTrue(edge.current_config['smart_modes']['immobility_detection'])
        self.assertEqual(edge.current_config['smart_modes']['immobility_timeout_seconds'], 30)
        self.assertEqual(calls[0][1:], ('/api/device/heartbeat', {
            'observation': 'clear', 'capabilities': {'camera': True, 'speaker': True, 'sensors': True},
            'audio_output': {'mode': 'analog', 'ready': True, 'error': '', 'version': 0},
        }, 200))
        self.assertTrue(any(url == '/api/device/config/ack' and body['version'] == 2 and code == 200
                            for _, url, body, code in calls))
        self.assertEqual(owner.get(path + '/smart-modes').json()['applied_version'], 2)
        refreshed = owner.put(path + '/smart-modes', json={'show_landmarks': False})
        self.assertEqual(refreshed.json()['smart_modes']['immobility_timeout_seconds'], 30)
        self.assertEqual(owner.put(path + '/smart-modes', json={'immobility_timeout_seconds': 31}).status_code, 422)

        pending = owner.post(path + '/commands', json={
            'kind': 'ptz_move', 'direction': 'RIGHT', 'degrees': 5,
            'ttl_seconds': 30, 'idempotency_key': 'contract-ptz',
        })
        self.assertEqual(pending.status_code, 201, pending.text)
        command_id = pending.json()['id']
        commands = device.get('/api/device/commands').json()
        self.assertIn(command_id, [command['id'] for command in commands])
        for status in ('accepted', 'executing', 'executed'):
            ack = device.post(f'/api/device/commands/{command_id}/ack', json={'status': status})
            self.assertEqual(ack.status_code, 200, ack.text)
        with owner.websocket_connect(f"/ws/alerts?home_id={home['id']}") as ws:
            incident = edge.send_event(kind='immobility', severity='warning', observation='abnormal',
                                       reason='Fixture', event_id='immobility-contract', sequence=1, duration_s=30)
            self.assertIsNotNone(incident, calls)
            message = ws.receive_json()
            self.assertEqual((message['id'], message['observation']), (incident['id'], 'abnormal'))
            recovered = edge.send_event(kind='immobility', severity='info', observation='recovered',
                                        reason='Fixture', event_id='immobility-contract', sequence=2, duration_s=31)
            self.assertIsNotNone(recovered, calls)
            message = ws.receive_json()
            self.assertEqual((message['id'], message['observation']), (incident['id'], 'recovered'))
            self.assertEqual((incident['id'], incident['sequence']), (recovered['id'], 1))
            self.assertEqual(recovered['sequence'], 2)
    history = owner.get(f"/api/homes/{home['id']}/events").json()
    self.assertEqual([(e['id'], e['observation']) for e in history], [(incident['id'], 'recovered')])
