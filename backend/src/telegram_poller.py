"""Single-consumer Telegram long poller with transactionally persisted offsets."""
from contextlib import suppress
import logging
import os
import signal
import threading
import time

from . import pgdb as db, pgservices as services

logger=logging.getLogger('annha.telegram.poller')
POLL_TIMEOUT_SECONDS=30
POLL_HTTP_TIMEOUT_SECONDS=45
POLLING_BACKOFF_CAP_SECONDS=60

class PollingSetupError(RuntimeError):
    pass

def _migration_ready(conn):
    row=conn.execute('''SELECT to_regclass('annha_private.telegram_pairings') AS pairings,
      to_regclass('annha_private.telegram_polling_state') AS state,
      CASE WHEN to_regclass('annha_private.telegram_pairings') IS NULL THEN false
        ELSE has_table_privilege(current_user,'annha_private.telegram_pairings','SELECT,UPDATE') END AS can_pair,
      CASE WHEN to_regclass('annha_private.telegram_polling_state') IS NULL THEN false
        ELSE has_table_privilege(current_user,'annha_private.telegram_polling_state','SELECT,INSERT,UPDATE') END AS can_poll''').fetchone()
    return bool(row and row['pairings'] and row['state'] and row['can_pair'] and row['can_poll'])

def poll_once():
    """Poll one Telegram batch and commit pairing effects and offset together."""
    bot_ref=services.telegram_bot_ref()
    if not bot_ref: raise services.TelegramPollingError('not_configured')
    with db.connect('worker') as conn:
        lock=conn.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0)) AS locked',
            (bot_ref.hex(),)).fetchone()
        if not lock or not lock['locked']:
            return 'consumer_active'
        if not _migration_ready(conn):
            return 'migration_missing'
        conn.execute('''INSERT INTO annha_private.telegram_polling_state(bot_ref,next_offset)
          VALUES(%s,0) ON CONFLICT(bot_ref) DO NOTHING''',(bot_ref,))
        state=conn.execute('SELECT next_offset FROM annha_private.telegram_polling_state WHERE bot_ref=%s FOR UPDATE',
            (bot_ref,)).fetchone()
        if not state: raise PollingSetupError('polling_state_unavailable')

        # A webhook is never changed here. Polling remains idle until an operator
        # intentionally resolves the existing bot configuration.
        webhook=services.telegram_poll_api('getWebhookInfo',timeout=8) or {}
        if not isinstance(webhook,dict): raise services.TelegramPollingError('invalid_webhook_info')
        if webhook.get('url'):
            conn.execute('''UPDATE annha_private.telegram_polling_state SET last_poll_at=NULL,updated_at=now()
              WHERE bot_ref=%s''',(bot_ref,))
            return 'webhook_present'

        updates=services.telegram_poll_api('getUpdates',{
            'offset':int(state['next_offset']),
            'timeout':POLL_TIMEOUT_SECONDS,
            'limit':100,
            'allowed_updates':['message'],
        },timeout=POLL_HTTP_TIMEOUT_SECONDS)
        if not isinstance(updates,list): raise services.TelegramPollingError('invalid_updates')
        for update in updates:
            update_id=update.get('update_id') if isinstance(update,dict) else None
            if isinstance(update_id,bool) or not isinstance(update_id,int) or update_id<0 or update_id>=9223372036854775807:
                # Keep the current offset so a malformed response cannot discard work.
                raise services.TelegramPollingError('invalid_update_id')
            services.process_telegram_pairing_update(update,conn=conn)
            conn.execute('''UPDATE annha_private.telegram_polling_state
              SET next_offset=GREATEST(next_offset,%s),updated_at=now() WHERE bot_ref=%s''',
              (update_id+1,bot_ref))
        conn.execute('''UPDATE annha_private.telegram_polling_state
          SET last_poll_at=now(),updated_at=now() WHERE bot_ref=%s''',(bot_ref,))
    return 'polled'

def _wait(stop_event,seconds):
    end=time.monotonic()+max(0,seconds)
    while not stop_event.is_set():
        remaining=end-time.monotonic()
        if remaining<=0: return
        stop_event.wait(min(1,remaining))

def run(stop_event=None):
    stop_event=stop_event or threading.Event()
    if services.telegram_update_mode()!='polling':
        logger.info('Telegram polling is inactive because update mode is not polling')
        while not stop_event.wait(60): pass
        return 0
    failures=0
    last_idle_reason=None
    while not stop_event.is_set():
        if os.getenv('DATABASE_BACKEND','sqlite').lower()!='postgres' or not services.telegram_bot_ref():
            reason='database_or_bot_not_configured'
            if reason!=last_idle_reason: logger.info('Telegram polling is waiting for server configuration')
            last_idle_reason=reason
            _wait(stop_event,30)
            continue
        try:
            if not db.POOLS: db.open_pools()
            outcome=poll_once()
            failures=0
            if outcome=='migration_missing':
                if last_idle_reason!=outcome: logger.info('Telegram polling is waiting for migration 012')
                last_idle_reason=outcome
                _wait(stop_event,30)
            elif outcome=='webhook_present':
                if last_idle_reason!=outcome: logger.warning('Telegram polling paused because this bot already has a webhook; no bot settings were changed')
                last_idle_reason=outcome
                _wait(stop_event,30)
            elif outcome=='consumer_active':
                _wait(stop_event,1)
            else:
                last_idle_reason=None
        except services.TelegramPollingError as error:
            failures+=1
            delay=error.retry_after or min(POLLING_BACKOFF_CAP_SECONDS,2**min(failures-1,6))
            logger.warning('Telegram polling paused after provider/network error (%s)',error.code)
            _wait(stop_event,delay)
        except Exception as error:
            failures+=1
            delay=min(POLLING_BACKOFF_CAP_SECONDS,2**min(failures-1,6))
            logger.warning('Telegram polling paused (%s); update offset was not advanced',type(error).__name__)
            _wait(stop_event,delay)
    with suppress(Exception): db.close_pools()
    logger.info('Telegram polling stopped')
    return 0

def main():
    stop_event=threading.Event()
    def stop(_signum,_frame): stop_event.set()
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    return run(stop_event)

if __name__=='__main__':
    raise SystemExit(main())
