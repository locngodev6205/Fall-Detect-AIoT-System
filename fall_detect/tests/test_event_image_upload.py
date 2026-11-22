from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from fall_detect.edge.client.device_client import DeviceClient


class EventImageUploadTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.client = DeviceClient('http://fixture', 'fixture', cache_dir=Path(temporary.name))
        self.client._request = Mock()
        self.jpeg = b'\xff\xd8\xfffixture'

    @staticmethod
    def response(status=200, **payload):
        return Mock(status_code=status, text='', json=Mock(return_value=payload))

    def test_event_and_image_replay_keep_both_original_ids(self):
        self.client._request.side_effect = [
            TimeoutError(), TimeoutError(), self.response(id='server-event'),
            self.response(status=503), self.response(id='image', status=201),
        ]
        self.assertIsNone(self.client.send_event(kind='fall', severity='critical',
            observation='abnormal', reason='fixture', event_id='local-event', jpeg_evidence=self.jpeg))
        self.client._flush_outbox()
        self.client._flush_outbox()
        self.client._flush_outbox()
        event_calls, image_calls = self.client._request.call_args_list[:3], self.client._request.call_args_list[3:]
        self.assertTrue(all(call.kwargs['json_body']['event_id']=='local-event' for call in event_calls))
        self.assertTrue(all('_evidence_jpeg' not in call.kwargs['json_body'] for call in event_calls))
        self.assertEqual([call.args[1] for call in image_calls], ['/api/device/evidence?event_id=server-event'] * 2)
        self.assertEqual([call.kwargs['data'] for call in image_calls], [self.jpeg] * 2)

    def test_telemetry_verifies_response_message_before_uploading(self):
        self.client._request.side_effect = [
            TimeoutError(),
            self.response(message_id='batch-a', events=[{'id':'server-a'}]),
            self.response(id='image', status=201),
            self.response(message_id='unexpected-batch', events=[{'id':'wrong-event'}]),
        ]
        self.assertFalse(self.client.send_telemetry({}, message_id='batch-a', jpeg_evidence=self.jpeg))
        self.client._flush_outbox()
        self.assertTrue(self.client.send_telemetry({}, message_id='batch-b', jpeg_evidence=self.jpeg))
        self.client._flush_outbox()
        uploads = [call.args[1] for call in self.client._request.call_args_list if 'evidence' in call.args[1]]
        self.assertEqual(uploads, ['/api/device/evidence?event_id=server-a'])
