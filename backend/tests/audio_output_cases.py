"""Shared camera configuration contract for SQLite and PostgreSQL integration suites."""


def exercise_audio_output(test):
    user, _ = test.account('audio-output@example.com')
    home, _, camera, provision = test.home_camera(user)
    device = test.device(provision)
    camera_path = f"/api/cameras/{camera['id']}"
    route = camera_path + "/audio-output"
    test.assertEqual(user.get(route).json()['mode'], 'analog')
    test.assertEqual(user.put(route, json={'mode': 'analog_demo'}).status_code, 422)
    revision = user.put(route, json={'mode': 'analog'})
    test.assertEqual(revision.status_code, 200, revision.text)
    test.assertIsNone(revision.json()['actual_mode'])
    test.assertTrue(revision.json()['switching'])
    reminder = user.post(f"/api/homes/{home['id']}/reminders", json={
        'camera_id': camera['id'], 'name': 'Nhắc uống nước', 'time': '07:00', 'text': 'Nhớ uống nước',
    })
    test.assertEqual(reminder.status_code, 201, reminder.text)
    modes = user.get(camera_path + "/smart-modes").json()['smart_modes']
    smart = user.put(camera_path + "/smart-modes", json={**modes, 'night_mode_enabled': False})
    test.assertEqual(smart.status_code, 200, smart.text)
    config = device.get('/api/device/config').json()
    test.assertEqual(config['audio_output'], 'analog')
    version = config['version']
    ack = device.post('/api/device/config/ack', json={'version':version, 'success':True})
    test.assertEqual(ack.status_code, 200, ack.text)
    test.assertTrue(user.get(route).json()['switching'])
    for mode, ready in [('analog', True), ('bluetooth', False)]:
        if mode == 'bluetooth':
            test.assertEqual(user.put(route, json={'mode': mode}).status_code, 200)
            version = device.get('/api/device/config').json()['version']
            test.assertEqual(device.post('/api/device/config/ack', json={'version':version, 'success':True}).status_code, 200)
        heartbeat = device.post('/api/device/heartbeat', json={'audio_output':{
            'mode':mode, 'ready':ready, 'version':version, 'error':'' if ready else 'Loa chưa sẵn sàng',
        }})
        test.assertEqual(heartbeat.status_code, 200, heartbeat.text)
        actual = user.get(route).json()
        test.assertEqual((actual['actual_mode'], actual['ready'], actual['switching']), (mode,ready,False))
        if not ready:
            test.assertEqual(actual['error'], 'Loa chưa sẵn sàng')
    refreshed = user.put(camera_path + "/smart-modes", json={**modes, 'night_mode_enabled': True})
    test.assertEqual(refreshed.status_code, 200, refreshed.text)
    test.assertEqual(device.get('/api/device/config').json()['audio_output'], 'bluetooth')
