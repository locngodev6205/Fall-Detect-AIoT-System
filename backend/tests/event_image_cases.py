from datetime import datetime, timedelta, timezone


def exercise_telemetry_evidence(test):
    owner, _ = test.account('telemetry-image@example.invalid')
    home, _, camera, provision = test.home_camera(owner)
    device = test.device(provision)
    url = f"/api/homes/{home['id']}/settings"
    settings = owner.get(url).json()
    settings.update(environment_hold_seconds=0, temperature_high=30, hysteresis=2)
    response = owner.put(url, json=settings)
    test.assertEqual(response.status_code, 200, response.text)

    stamp = datetime.now(timezone.utc) - timedelta(seconds=4)

    def send(message, seconds, value):
        result = device.post('/api/device/telemetry', json={
            'message_id': message,
            'observed_at': (stamp + timedelta(seconds=seconds)).isoformat(),
            'readings': {'temperature': {'value': value, 'unit': 'C'}},
        })
        test.assertEqual(result.status_code, 200, result.text)
        return result.json()['events']

    created = send('hot-1', 0, 34)
    test.assertEqual(len(created), 1)
    event_id = created[0]['id']
    test.assertEqual(send('hot-2', 1, 35), [])
    test.assertEqual(send('recovered', 2, 27), [])
    test.assertEqual(send('hot-1', 0, 34), created)
    _, _, _, other_provision = test.home_camera(owner)
    other = test.device(other_provision)
    endpoint = f'/api/device/evidence?event_id={event_id}'
    headers = {'Content-Type': 'image/jpeg'}
    jpeg = b'\xff\xd8\xff' + b'fixture only'
    test.assertEqual(other.post(endpoint, content=jpeg, headers=headers).status_code, 404)
    test.assertEqual(device.post(endpoint, content=b'invalid', headers=headers).status_code, 415)
    first = device.post(endpoint, content=jpeg, headers=headers)
    replay = device.post(endpoint, content=jpeg, headers=headers)
    test.assertEqual(first.status_code, 201, first.text)
    test.assertEqual(replay.status_code, 201, replay.text)
    test.assertEqual(first.json()['id'], replay.json()['id'])
    detail = owner.get(f'/api/events/{event_id}')
    test.assertEqual(detail.status_code, 200, detail.text)
    test.assertEqual([asset['id'] for asset in detail.json()['evidence']], [first.json()['id']])
    test.assertEqual(owner.get(f"/api/assets/{first.json()['id']}").content, jpeg)
