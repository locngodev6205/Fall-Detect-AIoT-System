import io
import json
import os
import unittest
import urllib.error
from contextlib import contextmanager
from email.message import Message
from unittest.mock import patch

from backend.src import pgservices
from backend.src import telegram_poller


class _Result:
    def __init__(self,row=None): self.row=row
    def fetchone(self): return self.row


class _PollConnection:
    def __init__(self,locked=True,offset=0): self.locked=locked;self.offset=offset;self.last_poll=False;self.statements=[]
    def execute(self,sql,params=()):
        self.statements.append((sql,params))
        if 'pg_try_advisory_xact_lock' in sql: return _Result({'locked':self.locked})
        if 'to_regclass' in sql: return _Result({'pairings':'telegram_pairings','state':'telegram_polling_state','can_pair':True,'can_poll':True})
        if 'INSERT INTO annha_private.telegram_polling_state' in sql: return _Result()
        if 'SELECT next_offset FROM annha_private.telegram_polling_state' in sql: return _Result({'next_offset':self.offset})
        if 'SET next_offset=GREATEST' in sql:
            self.offset=max(self.offset,int(params[0]));return _Result()
        if 'SET last_poll_at=now()' in sql: self.last_poll=True;return _Result()
        return _Result()


class TelegramPollingTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'poller-mock-secret','TELEGRAM_UPDATE_MODE':'polling','DATABASE_BACKEND':'postgres'})
        self.env.start();self.addCleanup(self.env.stop)

    def _connect(self,conn):
        @contextmanager
        def connect(*_args,**_kwargs): yield conn
        return connect

    def test_batch_processes_each_update_before_advancing_persistent_offset(self):
        conn=_PollConnection(offset=100)
        updates=[{'update_id':101,'message':{'text':'/start mockPairingToken_1234567890'}},
                 {'update_id':105,'message':{'text':'not a pairing'}}]
        calls=[]
        def api(method,payload=None,timeout=5):
            calls.append((method,payload,timeout))
            return {'url':''} if method=='getWebhookInfo' else updates
        with patch('backend.src.telegram_poller.db.connect',side_effect=self._connect(conn)), \
             patch('backend.src.telegram_poller.services.telegram_poll_api',side_effect=api), \
             patch('backend.src.telegram_poller.services.process_telegram_pairing_update',side_effect=['linked','ignored']) as process:
            self.assertEqual(telegram_poller.poll_once(),'polled')
        self.assertEqual(process.call_count,2)
        self.assertEqual(conn.offset,106)
        self.assertTrue(conn.last_poll)
        get_updates=[item for item in calls if item[0]=='getUpdates'][0]
        self.assertEqual(get_updates[1]['offset'],100)
        self.assertEqual(get_updates[1]['timeout'],30)
        self.assertEqual(get_updates[2],45)

    def test_restart_reuses_committed_offset_and_replay_is_idempotent(self):
        conn=_PollConnection(offset=106)
        calls=[]
        def api(method,payload=None,timeout=5):
            calls.append((method,payload))
            return {'url':''} if method=='getWebhookInfo' else [{'update_id':105,'message':{'text':'/start mockPairingToken_1234567890'}}]
        with patch('backend.src.telegram_poller.db.connect',side_effect=self._connect(conn)), \
             patch('backend.src.telegram_poller.services.telegram_poll_api',side_effect=api), \
             patch('backend.src.telegram_poller.services.process_telegram_pairing_update',return_value='duplicate') as process:
            self.assertEqual(telegram_poller.poll_once(),'polled')
        self.assertEqual(calls[1][1]['offset'],106)
        self.assertEqual(process.call_args.kwargs['conn'],conn)
        self.assertEqual(conn.offset,106)

    def test_advisory_lock_prevents_second_consumer_from_calling_telegram(self):
        conn=_PollConnection(locked=False)
        with patch('backend.src.telegram_poller.db.connect',side_effect=self._connect(conn)), \
             patch('backend.src.telegram_poller.services.telegram_poll_api') as api:
            self.assertEqual(telegram_poller.poll_once(),'consumer_active')
        api.assert_not_called()

    def test_existing_webhook_blocks_polling_without_changing_bot_configuration(self):
        conn=_PollConnection()
        with patch('backend.src.telegram_poller.db.connect',side_effect=self._connect(conn)), \
             patch('backend.src.telegram_poller.services.telegram_poll_api',return_value={'url':'https://existing.invalid/hook'}) as api:
            self.assertEqual(telegram_poller.poll_once(),'webhook_present')
        self.assertEqual(api.call_args.args[0],'getWebhookInfo')
        self.assertEqual(api.call_count,1)
        self.assertFalse(conn.last_poll)

    def test_processing_failure_does_not_advance_offset(self):
        conn=_PollConnection(offset=44)
        def api(method,payload=None,timeout=5):
            return {'url':''} if method=='getWebhookInfo' else [{'update_id':44,'message':{'text':'/start mockPairingToken_1234567890'}}]
        with patch('backend.src.telegram_poller.db.connect',side_effect=self._connect(conn)), \
             patch('backend.src.telegram_poller.services.telegram_poll_api',side_effect=api), \
             patch('backend.src.telegram_poller.services.process_telegram_pairing_update',side_effect=RuntimeError('fixture failure')):
            with self.assertRaises(RuntimeError): telegram_poller.poll_once()
        self.assertEqual(conn.offset,44)
        self.assertFalse(any('SET next_offset=GREATEST' in sql for sql,_ in conn.statements))

    def test_rate_limit_retry_after_is_parsed_without_exposing_token(self):
        headers=Message();headers['Retry-After']='9'
        error=urllib.error.HTTPError('https://api.telegram.org/mock',429,'Too Many Requests',headers,
            io.BytesIO(json.dumps({'ok':False,'error_code':429,'parameters':{'retry_after':9}}).encode()))
        with patch('backend.src.pgservices.urllib.request.urlopen',side_effect=error):
            with self.assertRaises(pgservices.TelegramPollingError) as raised:
                pgservices.telegram_poll_api('getUpdates',{'offset':0})
        self.assertEqual(raised.exception.code,'rate_limited')
        self.assertEqual(raised.exception.retry_after,9)
        self.assertNotIn('poller-mock-secret',str(raised.exception))


if __name__=='__main__': unittest.main()
