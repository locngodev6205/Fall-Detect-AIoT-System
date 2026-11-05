-- Add persistent Telegram pairing and long-poll progress state.
-- Additive only: no existing notification settings, messages, or media are removed.
BEGIN;

CREATE TABLE annha_private.telegram_pairings (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 home_id uuid NOT NULL,
 channel_id uuid NOT NULL,
 recipient_user_id uuid NOT NULL,
 token_hash bytea NOT NULL UNIQUE CHECK (octet_length(token_hash)=32),
 created_by uuid NOT NULL REFERENCES annha_private.users(id),
 created_at timestamptz NOT NULL DEFAULT now(),
 expires_at timestamptz NOT NULL,
 revoked_at timestamptz,
 completed_at timestamptz,
 provider_update_id bigint UNIQUE CHECK (provider_update_id IS NULL OR provider_update_id>=0),
 FOREIGN KEY(home_id,channel_id) REFERENCES annha.notification_channels(home_id,id) ON DELETE CASCADE,
 FOREIGN KEY(home_id,recipient_user_id) REFERENCES annha_private.home_memberships(home_id,user_id),
 CHECK (expires_at>created_at AND expires_at<=created_at+interval '15 minutes'),
 CHECK ((completed_at IS NULL)=(provider_update_id IS NULL)),
 CHECK (completed_at IS NULL OR revoked_at IS NULL)
);
CREATE INDEX telegram_pairing_recipient_recent
 ON annha_private.telegram_pairings(home_id,recipient_user_id,created_at DESC);
CREATE INDEX telegram_pairing_expiry
 ON annha_private.telegram_pairings(expires_at);

-- Only the trusted worker consumes pairing tokens. RLS is forced even if this
-- table is later queried by a table owner that is subject to FORCE RLS.
ALTER TABLE annha_private.telegram_pairings ENABLE ROW LEVEL SECURITY;
ALTER TABLE annha_private.telegram_pairings FORCE ROW LEVEL SECURITY;
CREATE POLICY worker_telegram_pairings ON annha_private.telegram_pairings
 FOR ALL TO annha_worker USING (true) WITH CHECK (true);
CREATE POLICY migration_owner_telegram_pairings ON annha_private.telegram_pairings
 FOR ALL TO CURRENT_USER USING (true) WITH CHECK (true);
REVOKE ALL ON annha_private.telegram_pairings FROM PUBLIC,annha_app,annha_auth,annha_device;
GRANT SELECT,INSERT,UPDATE,DELETE ON annha_private.telegram_pairings TO annha_worker;
GRANT SELECT(home_id,user_id,role,revoked_at) ON annha_private.home_memberships TO annha_worker;
GRANT SELECT(id,disabled_at,deleted_at) ON annha_private.users TO annha_worker;

-- Offset is advanced only after an update was processed or safely ignored.
-- The advisory transaction lock in the worker serializes consumers for a bot.
CREATE TABLE annha_private.telegram_polling_state (
 bot_ref bytea PRIMARY KEY CHECK (octet_length(bot_ref)=32),
 next_offset bigint NOT NULL DEFAULT 0 CHECK (next_offset>=0),
 last_poll_at timestamptz,
 updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE annha_private.telegram_polling_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE annha_private.telegram_polling_state FORCE ROW LEVEL SECURITY;
CREATE POLICY worker_telegram_polling_state ON annha_private.telegram_polling_state
 FOR ALL TO annha_worker USING (true) WITH CHECK (true);
CREATE POLICY migration_owner_telegram_polling_state ON annha_private.telegram_polling_state
 FOR ALL TO CURRENT_USER USING (true) WITH CHECK (true);
REVOKE ALL ON annha_private.telegram_polling_state FROM PUBLIC,annha_app,annha_auth,annha_device;
GRANT SELECT,INSERT,UPDATE,DELETE ON annha_private.telegram_polling_state TO annha_worker;

COMMIT;
