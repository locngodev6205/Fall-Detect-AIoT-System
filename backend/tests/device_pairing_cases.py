"""Exercise self-enrollment through the real API with either database adapter."""
from concurrent.futures import ThreadPoolExecutor
import secrets
from unittest.mock import patch

from backend.src import device_pairing


def exercise_self_enrollment(case):
    owner, _ = case.account('pairing-owner@example.com')
    other, _ = case.account('pairing-other@example.com')
    home, room, _, _ = case.home_camera(owner)
    other_home, other_room, _, _ = case.home_camera(other)
    path = f"/api/homes/{home['id']}/cameras/claim"
    other_path = f"/api/homes/{other_home['id']}/cameras/claim"
    token = secrets.token_urlsafe(40)
    device = case.device({'device_token': token})
    endpoint = '/api/device/pairing-ticket'

    case.assertEqual(case.client.post(endpoint).status_code, 401)
    case.assertEqual(device.get('/api/device/config').status_code, 401)
    with patch.object(device_pairing, 'TTL_SECONDS', -1):
        expired = device.post(endpoint).json()['pairing_code']
    issued = device.post(endpoint)
    case.assertEqual(issued.status_code, 200, issued.text)
    case.assertNotIn(token, issued.text)
    code = issued.json()['pairing_code']
    payload = {'code': code, 'name': 'Pi tự ghép', 'room_id': room['id']}
    case.assertEqual(device.get('/api/device/config').status_code, 401)
    case.assertEqual(case.client.post(path, json=payload).status_code, 401)
    case.assertEqual(other.post(path, json=payload).status_code, 404)
    case.assertEqual(owner.post(path, json={**payload, 'code': expired}).status_code, 400)
    tampered = code[:8] + ('A' if code[8] != 'A' else 'B') + code[9:]
    case.assertEqual(owner.post(path, json={**payload, 'code': tampered}).status_code, 400)
    case.assertIn(owner.post(path, json={**payload, 'room_id': other_room['id']}).status_code, (404, 422))
    case.assertEqual(device.get('/api/device/config').status_code, 401)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(owner.post, path, json=payload)
        second = pool.submit(owner.post, path, json=payload)
        claims = [first.result(), second.result()]
    for claim in claims:
        case.assertEqual(claim.status_code, 201, claim.text)
    camera = claims[0].json()['id']
    case.assertEqual(claims[1].json()['id'], camera)
    case.assertEqual(other.post(other_path, json={**payload, 'room_id': other_room['id']}).status_code, 400)
    config = device.get('/api/device/config')
    case.assertEqual(config.status_code, 200, config.text)
    case.assertGreater(config.json()['version'], 0)
    heartbeat = device.post('/api/device/heartbeat', json={'observation': 'clear', 'capabilities': {'camera': True}})
    case.assertEqual(heartbeat.status_code, 200, heartbeat.text)
    listed = owner.get(f"/api/homes/{home['id']}/cameras").json()
    case.assertEqual(sum(c['id'] == camera and c['online'] for c in listed), 1)

    case.assertEqual(owner.delete(f'/api/cameras/{camera}').status_code, 200)
    case.assertEqual(device.get('/api/device/config').status_code, 401)
    case.assertEqual(owner.post(path, json=payload).status_code, 400)
