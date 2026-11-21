"""HTTP contract shared by SQLite and PostgreSQL event integration suites."""
from uuid import uuid4


def exercise_event_management(case, owner, viewer, outsider, device, home_id):
    endpoint = '/api/device/events'
    payload = {
        'event_id': 'event-management', 'kind': 'fall', 'severity': 'warning',
        'observed_at': '2026-01-01T10:00:00+00:00', 'observation': 'abnormal',
        'reason': 'Test observation',
    }
    response = device.post(endpoint, json=payload)
    case.assertEqual(response.status_code, 200, response.text)
    event_id = response.json()['id']
    path = f'/api/events/{event_id}'
    actions = path + '/actions'
    active = f'/api/homes/{home_id}/active-events'

    for client in (owner, viewer):
        case.assertFalse(client.get(path).json()['is_read'])
    case.assertEqual(viewer.get(path + '/updates').status_code, 200)
    case.assertEqual(viewer.post(actions, json={'action': 'safe'}).status_code, 403)
    for missing in (f'/api/events/{uuid4()}', '/api/events/not-an-id'):
        case.assertEqual(owner.get(missing + '/updates').status_code, 404)
        case.assertEqual(owner.post(missing + '/read').status_code, 404)
    case.assertEqual(outsider.get(path + '/updates').status_code, 404)
    case.assertEqual(outsider.post(path + '/read').status_code, 404)

    response = viewer.post(path + '/read')
    case.assertEqual(response.status_code, 200, response.text)
    case.assertTrue(viewer.get(path).json()['is_read'])
    case.assertEqual(viewer.get(path).json()['status'], 'OPEN')
    case.assertFalse(owner.get(path).json()['is_read'])
    for _ in range(2):
        case.assertEqual(owner.post(path + '/read').status_code, 200)
    event = owner.get(path).json()
    case.assertEqual(event['status'], 'ACKNOWLEDGED')
    case.assertTrue(event['is_read'])
    case.assertEqual([entry['action'] for entry in event['actions']], ['acknowledge'])
    counts = owner.get(active).json()
    case.assertEqual((counts['count'], counts['unread_count']), (1, 0))

    update = {**payload, 'sequence': 2, 'observed_at': '2026-01-01T10:00:10+00:00', 'reason': 'Second observation'}
    for _ in range(2):
        case.assertEqual(device.post(endpoint, json=update).status_code, 200)
    first = owner.get(path + '/updates?page=1&page_size=1').json()
    second = owner.get(path + '/updates?page=2&page_size=1').json()
    case.assertEqual((first['total'], first['total_pages']), (2, 2))
    case.assertEqual([first['items'][0]['sequence'], second['items'][0]['sequence']], [2, 1])
    case.assertEqual(first['items'][0]['payload']['reason'], 'Second observation')
    case.assertEqual(owner.get(path + '/updates?page=3&page_size=1').json()['items'], [])
    case.assertEqual(owner.get(path + '/updates?page_size=0').status_code, 422)

    case.assertEqual(owner.post(actions, json={'action': 'safe'}).status_code, 409)
    case.assertEqual(owner.post(actions, json={'action': 'safe', 'confirm_abnormal': True, 'note': '  '}).status_code, 409)
    result = owner.post(actions, json={'action': 'safe', 'confirm_abnormal': True, 'note': 'Đã kiểm tra'})
    case.assertEqual(result.json()['status'], 'RESOLVED', result.text)
    case.assertEqual(owner.post(actions, json={'action': 'false_alarm'}).status_code, 409)
    case.assertEqual(owner.get(path + '/updates').json()['total'], 2)

    other = device.post(endpoint, json={**payload, 'event_id': 'second-event', 'observation': 'recovered'}).json()
    bulk = owner.post(f'/api/homes/{home_id}/events/read-all').json()
    case.assertEqual(bulk, {'read_count': 1, 'acknowledged_count': 1})
    result = owner.post(f"/api/events/{other['id']}/actions", json={'action': 'false_alarm'})
    case.assertEqual(result.json()['status'], 'FALSE_ALARM', result.text)
    return path, event_id
