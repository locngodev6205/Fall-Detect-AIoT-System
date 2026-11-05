import io
import json
import os
import tempfile
import unittest
import urllib.error
from email.message import Message
from unittest.mock import patch
from datetime import datetime, timezone

from backend.src import pgservices


class TelegramDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.token = patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN':'mock-only-token','PUBLIC_URL':'https://annha.invalid'})
        self.token.start()
        self.addCleanup(self.token.stop)

    def test_pairing_start_command_accepts_only_matching_private_chat(self):
        update={'update_id':77,'message':{'text':'/start mockPairingToken_1234567890',
          'chat':{'id':12345,'type':'private'},'from':{'id':12345}}}
        self.assertEqual(pgservices.parse_telegram_pairing_update(update,'AnNhaSafetyAlertBot'),
          {'update_id':77,'chat_id':'12345','token':'mockPairingToken_1234567890'})
        group={**update,'message':{**update['message'],'chat':{'id':-12345,'type':'group'}}}
        mismatch={**update,'message':{**update['message'],'from':{'id':999}}}
        wrong_bot={**update,'message':{**update['message'],'text':'/start@DifferentBot mockPairingToken_1234567890'}}
        self.assertIsNone(pgservices.parse_telegram_pairing_update(group,'AnNhaSafetyAlertBot'))
        self.assertIsNone(pgservices.parse_telegram_pairing_update(mismatch,'AnNhaSafetyAlertBot'))
        self.assertIsNone(pgservices.parse_telegram_pairing_update(wrong_bot,'AnNhaSafetyAlertBot'))

    def test_pairing_update_consumes_link_once_and_saves_encrypted_destination(self):
        from contextlib import contextmanager
        from datetime import timedelta

        state={'pair':{'id':'pair-1','home_id':'home-1','channel_id':'channel-1','recipient_user_id':'recipient-1',
          'created_by':'owner-1','created_at':datetime.now(timezone.utc),'expires_at':datetime.now(timezone.utc)+timedelta(minutes=5),
          'revoked_at':None,'completed_at':None,'provider_update_id':None},'secret':None,'roles':[]}
        class Result:
            def __init__(self,row=None,rowcount=0): self.row=row;self.rowcount=rowcount
            def fetchone(self): return self.row
        class Conn:
            def execute(self,sql,params=()):
                if 'SELECT home_id FROM annha_private.telegram_pairings' in sql:
                    return Result({'home_id':'home-1'})
                if 'SELECT * FROM annha_private.telegram_pairings' in sql:
                    return Result(dict(state['pair']))
                if 'SELECT 1 FROM annha_private.telegram_pairings WHERE provider_update_id' in sql:
                    return Result({'ok':1} if state['pair']['provider_update_id']==params[0] else None)
                if 'SELECT m.role,u.disabled_at,u.deleted_at' in sql:
                    return Result({'role':'caregiver','disabled_at':None,'deleted_at':None})
                if 'SELECT c.id FROM annha.notification_channels' in sql:
                    return Result({'id':'channel-1'})
                if 'INSERT INTO annha_private.notification_secrets' in sql:
                    state['secret']=params
                    return Result()
                if 'UPDATE annha_private.telegram_pairings SET completed_at' in sql:
                    state['pair']['completed_at']=datetime.now(timezone.utc)
                    state['pair']['provider_update_id']=params[0]
                    return Result({'id':'pair-1'},rowcount=1)
                return Result()
        @contextmanager
        def connect(role='worker',home=None):
            state['roles'].append((role,home));yield Conn()
        update={'update_id':77,'message':{'text':'/start mockPairingToken_1234567890',
          'chat':{'id':12345,'type':'private'},'from':{'id':12345}}}
        with patch('backend.src.pgservices.db.connect',side_effect=connect), \
             patch('backend.src.pgservices.encrypt',return_value=b'encrypted-destination') as encrypt, \
             patch('backend.src.pgservices.db.audit'):
            self.assertEqual(pgservices.process_telegram_pairing_update(update),'linked')
            self.assertEqual(pgservices.process_telegram_pairing_update(update),'duplicate')
        self.assertEqual(state['pair']['provider_update_id'],77)
        self.assertEqual(state['secret'][1:3],('channel-1',b'encrypted-destination'))
        encrypt.assert_called_once_with({'chat_id':'12345'})
        self.assertEqual(state['roles'],[('worker',None),('worker',None)])

    def test_webhook_setup_is_opt_in_and_does_not_replace_an_existing_target(self):
        from contextlib import contextmanager
        class Result:
            def fetchone(self): return {'pairings':'telegram_pairings','polling_state':'telegram_polling_state',
              'pairing_access':True,'destination_access':True}
        class Conn:
            def execute(self,*args,**kwargs): return Result()
        @contextmanager
        def connect(*args,**kwargs): yield Conn()
        old_ready=pgservices.telegram_webhook_ready
        try:
            with patch.dict(os.environ,{'TELEGRAM_UPDATE_MODE':'polling'}):
                self.assertFalse(pgservices.configure_telegram_webhook())
            with patch.dict(os.environ,{'TELEGRAM_UPDATE_MODE':'webhook','PUBLIC_URL':'https://annha.example',
              'TELEGRAM_BOT_TOKEN':'mock-only-token','TELEGRAM_BOT_USERNAME':'AnNhaSafetyAlertBot','TELEGRAM_WEBHOOK_REPLACE_EXISTING':'false'}), \
              patch('backend.src.pgservices.db.connect',side_effect=connect), \
              patch('backend.src.pgservices._telegram_api_json',return_value={'url':'https://other.example/hook'}) as api_call:
                self.assertFalse(pgservices.configure_telegram_webhook())
                self.assertEqual(api_call.call_count,1)
                self.assertEqual(api_call.call_args.args[0],'getWebhookInfo')
            self.assertFalse(pgservices.telegram_webhook_ready)
        finally:
            pgservices.telegram_webhook_ready=old_ready

    def test_send_message_acceptance_is_provider_acceptance_only(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def read(self): return json.dumps({'ok':True,'result':{'message_id':42}}).encode()
        with patch('backend.src.pgservices.urllib.request.urlopen',return_value=Response()) as request:
            message_id=pgservices.send_telegram_text('123','Xin chào AnNhà')
        self.assertEqual(message_id,'42')
        self.assertEqual(request.call_count,1)
        body=json.loads(request.call_args.args[0].data)
        self.assertEqual(body['text'],'Xin chào AnNhà')

    def test_provider_message_identity_is_scoped_to_hashed_destination(self):
        owner=pgservices.telegram_destination_ref('-1001234567')
        caregiver=pgservices.telegram_destination_ref('-1001234568')
        self.assertEqual(owner,pgservices.telegram_destination_ref('-1001234567'))
        self.assertNotEqual(owner,caregiver)
        self.assertNotIn('-1001234567',owner)

    def test_cloudinary_evidence_is_read_through_private_backend_provider(self):
        from unittest.mock import Mock
        data=b'\x89PNG\r\n\x1a\nprivate-cloudinary-image'
        provider=Mock()
        provider.open_read.return_value=io.BytesIO(data)
        row={'status':'ready','expires_at':None,'mime_type':'image/png','size_bytes':len(data),
          'width':320,'height':240,'provider':'cloudinary','created_at':datetime.now(timezone.utc)}
        with tempfile.TemporaryDirectory() as root, \
             patch('backend.src.pgservices.db.MEDIA_ROOT',root), \
             patch('backend.src.pgservices.media_storage.provider_for_asset',return_value=provider):
            content,result=pgservices._read_notification_image(row)
        self.assertEqual(result,'sent')
        self.assertEqual(content,data)
        provider.open_read.assert_called_once_with(row)

    def test_rate_limit_carries_retry_after_without_treating_it_as_success(self):
        headers=Message();headers['Retry-After']='7'
        error=urllib.error.HTTPError('https://api.telegram.org/mock',429,'Too Many Requests',headers,
            io.BytesIO(json.dumps({'ok':False,'error_code':429,'parameters':{'retry_after':7}}).encode()))
        with patch('backend.src.pgservices.urllib.request.urlopen',side_effect=error):
            with self.assertRaises(pgservices.TelegramDeliveryError) as raised:
                pgservices.send_telegram_text('123','Tin thử')
        self.assertEqual(raised.exception.code,'TelegramRateLimited')
        self.assertEqual(raised.exception.retry_after,7)
        self.assertFalse(raised.exception.ambiguous)

    def test_timeout_is_ambiguous_and_photo_rejection_is_distinct(self):
        with patch('backend.src.pgservices.urllib.request.urlopen',side_effect=TimeoutError()):
            with self.assertRaises(pgservices.TelegramDeliveryError) as raised:
                pgservices.send_telegram_text('123','Tin thử')
        self.assertEqual(raised.exception.code,'TelegramTimedOut')
        self.assertTrue(raised.exception.ambiguous)

        headers=Message()
        error=urllib.error.HTTPError('https://api.telegram.org/mock',400,'Bad Request',headers,
            io.BytesIO(json.dumps({'ok':False,'error_code':400,'description':'photo rejected'}).encode()))
        with patch('backend.src.pgservices.urllib.request.urlopen',side_effect=error):
            with self.assertRaises(pgservices.TelegramDeliveryError) as raised:
                pgservices.send_telegram_photo('123','caption','image/png',b'\x89PNG\r\n\x1a\nfixture')
        self.assertEqual(raised.exception.code,'TelegramPhotoRejected')
        self.assertFalse(raised.exception.ambiguous)

    def test_vietnamese_event_template_and_photo_caption_keep_event_link(self):
        home={'name':'Nhà có dấu tiếng Việt','timezone':'Asia/Ho_Chi_Minh'}
        event={'id':'event-123','kind':'fall','severity':'warning','camera_name':'Camera cửa trước',
          'room_name':'Phòng khách','first_observed_at':datetime(2026,11,4,2,30,tzinfo=timezone.utc),
          'reason':'Phát hiện dấu hiệu cần kiểm tra <b>'}
        text=pgservices.format_telegram_event(home,event)
        caption=pgservices.format_telegram_caption(home,event)
        self.assertIn('Nhà có dấu tiếng Việt',text)
        self.assertIn('Phòng khách · Camera cửa trước',text)
        self.assertIn('https://annha.invalid/#/event/event-123',text)
        self.assertIn('https://annha.invalid/#/event/event-123',caption)
        self.assertLessEqual(len(text),4096)
        self.assertLessEqual(len(caption),1024)
        self.assertIn('<b>',text)  # plain text; no HTML parse mode is enabled

    def test_telegram_test_endpoint_acceptance_and_rate_limit_are_mocked(self):
        from contextlib import contextmanager
        from fastapi import HTTPException
        from backend.src import pgapi

        class Conn:
            def execute(self, sql, params=()):
                if 'SELECT m.role,u.name' in sql:
                    return Result({'role':'owner','name':'Người nhận','disabled_at':None,'deleted_at':None})
                if 'SELECT 1 FROM annha_private.camera_grants' in sql:
                    return Result({'ok':1})
                if "kind='telegram'" in sql:
                    return Result({'id':'channel-1'})
                if 'SELECT name FROM annha.homes' in sql:
                    return Result({'name':'Nhà AnNhà'})
                if 'SELECT destination_ciphertext' in sql:
                    return Result({'destination_ciphertext':'encrypted-chat-id'})
                return Result(None)

        class Result:
            def __init__(self, row): self.row = row
            def fetchone(self): return self.row

        @contextmanager
        def connect(*args, **kwargs): yield Conn()

        with patch('backend.src.pgapi.membership'), patch('backend.src.pgapi.throttle'), \
             patch('backend.src.pgapi.db.connect', side_effect=connect), \
             patch('backend.src.pgapi.db.audit'), \
             patch('backend.src.pgapi.svc.decrypt', return_value={'chat_id':'123456'}), \
             patch('backend.src.pgapi.svc.send_telegram_text', return_value='message-7') as send:
            accepted=pgapi.telegram_connection_test('home-1','recipient-1',{'id':'owner-1'})
            self.assertEqual(accepted['status'],'accepted')
            self.assertEqual(accepted['provider_message_id'],'message-7')
            self.assertEqual(send.call_count,1)
            self.assertEqual(send.call_args.args[0],'123456')

        limited=pgservices.TelegramDeliveryError('TelegramRateLimited',7)
        with patch('backend.src.pgapi.membership'), patch('backend.src.pgapi.throttle'), \
             patch('backend.src.pgapi.db.connect', side_effect=connect), \
             patch('backend.src.pgapi.svc.decrypt', return_value={'chat_id':'123456'}), \
             patch('backend.src.pgapi.svc.send_telegram_text', side_effect=limited) as send:
            with self.assertRaises(HTTPException) as raised:
                pgapi.telegram_connection_test('home-1','recipient-1',{'id':'owner-1'})
        self.assertEqual(raised.exception.status_code,502)
        self.assertIn('thử lại',raised.exception.detail.lower())
        send.assert_called_once()

    def test_worker_respects_telegram_retry_after_and_does_not_retry_early(self):
        from contextlib import contextmanager

        home='home-1';delivery='delivery-1';channel_id='channel-1';event_id='event-1'
        state={'due':True,'send_calls':0,'attempt':None,'update':None}
        job={'id':delivery,'event_id':event_id,'camera_id':'camera-1','channel_id':channel_id,
             'generation':1,'attempt_count':0,'email_version':1}
        channel={'id':channel_id,'kind':'telegram','allow_media':False,'recipient_user_id':'recipient-1'}
        event={'id':event_id,'home_id':home,'kind':'fall','severity':'warning','camera_id':'camera-1',
               'camera_name':'Camera','room_name':'Phòng khách','home_name':'Nhà AnNhà','timezone':'Asia/Ho_Chi_Minh',
               'first_observed_at':datetime(2026,11,4,2,30,tzinfo=timezone.utc),'reason':'Cần kiểm tra'}

        class Result:
            def __init__(self, rows=None, row=None): self.rows=rows or [];self.row=row
            def fetchall(self): return self.rows
            def fetchone(self): return self.row
            def __iter__(self): return iter(self.rows)

        class Conn:
            def execute(self, sql, params=()):
                if 'SELECT id FROM annha.homes' in sql: return Result(rows=[{'id':home}])
                if 'SELECT d.id,d.event_id' in sql: return Result(rows=[])
                if "status='pending'" in sql and 'FOR UPDATE SKIP LOCKED' in sql:
                    return Result(row=job.copy() if state['due'] else None)
                if 'can_dispatch_notification' in sql: return Result(row={'ok':True})
                if 'FROM annha.notification_channels WHERE id=' in sql: return Result(row=channel)
                if 'SELECT e.*,c.name AS camera_name' in sql: return Result(row=event)
                if 'FROM annha_private.notification_secrets' in sql: return Result(row={'destination_ciphertext':'encrypted'})
                if 'SELECT c.allow_media,s.destination_ciphertext' in sql: return Result(row={'allow_media':False,'destination_ciphertext':'encrypted'})
                if sql.startswith('INSERT INTO annha.delivery_attempts'):
                    state['attempt']=params
                    return Result(row=None)
                if 'UPDATE annha.notification_deliveries SET status=%s,last_error_code=%s' in sql:
                    state['update']=params;state['due']=False
                return Result(row=None)

        @contextmanager
        def connect(*args, **kwargs): yield Conn()

        def rate_limited(*args, **kwargs):
            state['send_calls']+=1
            raise pgservices.TelegramDeliveryError('TelegramRateLimited',7)

        with patch('backend.src.pgservices.db.connect',side_effect=connect), \
             patch('backend.src.pgservices.decrypt',return_value={'chat_id':'123456'}), \
             patch('backend.src.pgservices.send_telegram_text',side_effect=rate_limited):
            pgservices.process_notifications()
            pgservices.process_notifications()
        self.assertEqual(state['send_calls'],1)
        self.assertIsNotNone(state['attempt'])
        self.assertEqual(state['attempt'][3],'failed')  # attempt receipt reflects provider failure
        self.assertEqual(state['attempt'][7],'TelegramRateLimited')
        self.assertEqual(state['update'][0],'pending')
        self.assertEqual(state['update'][2],0)
        self.assertEqual(state['update'][4],__import__('datetime').timedelta(seconds=7))

    def test_duplicate_event_sequence_returns_without_queueing_another_notification(self):
        from contextlib import contextmanager
        from backend.src.models import EventInput

        statements=[]
        old={'id':'event-1','home_id':'home-1','camera_id':'camera-1','source_id':'source-1',
             'latest_sequence':4,'kind':'fall','status':'OPEN'}

        class Result:
            def __init__(self,row): self.row=row
            def fetchone(self): return self.row

        class Conn:
            def execute(self,sql,params=()):
                statements.append(sql)
                if 'SELECT id FROM annha.cameras' in sql: return Result({'id':'camera-1'})
                if 'SELECT * FROM annha.events WHERE camera_id=' in sql: return Result(old)
                return Result(None)

        @contextmanager
        def connect(*args, **kwargs): yield Conn()

        payload=EventInput(event_id='source-1',sequence=4,kind='fall',severity='warning',
            observed_at='2026-11-04T10:00:00+07:00')
        with patch('backend.src.pgservices.db.connect',side_effect=connect), \
             patch('backend.src.pgservices.event_public',return_value={'id':'event-1'}) as public:
            event,changed=pgservices.ingest_event({'home_id':'home-1','id':'camera-1'},payload)
        self.assertEqual(event,{'id':'event-1'})
        self.assertFalse(changed)
        self.assertEqual(len(statements),2)
        public.assert_called_once()
        self.assertIs(public.call_args.args[1],old)


if __name__ == '__main__':
    unittest.main()
