-- Upgrade the original 39-table design. Apply ONCE as the same migration owner.
-- No reset, no media upload, no SMTP/API call. Keeps Telegram and auth email flows.
BEGIN;
ALTER TABLE annha_private.users ADD COLUMN email_version integer NOT NULL DEFAULT 1 CHECK (email_version>0);
ALTER TABLE annha_private.email_tokens ADD COLUMN email_version integer NOT NULL DEFAULT 1 CHECK (email_version>0);
ALTER TABLE annha.notification_channels DROP CONSTRAINT notification_channels_kind_check;
ALTER TABLE annha.notification_channels ADD CONSTRAINT notification_channels_kind_check CHECK (kind IN ('telegram','email'));
ALTER TABLE annha.notification_channels
 ADD COLUMN email_version integer CHECK (email_version>0),
 ADD COLUMN event_kinds text[] NOT NULL DEFAULT ARRAY['fall','immobility','environment','device'],
 ADD COLUMN minimum_severity text NOT NULL DEFAULT 'warning' CHECK (minimum_severity IN ('info','warning','critical')),
 ADD COLUMN suppressed_at timestamptz,
 ADD COLUMN suppression_reason text CHECK (suppression_reason IN ('hard_bounce','complaint','manual')),
 ADD CONSTRAINT channel_email_version CHECK ((kind='email' AND email_version IS NOT NULL) OR (kind='telegram' AND email_version IS NULL)),
 ADD CONSTRAINT channel_event_kinds CHECK (cardinality(event_kinds) BETWEEN 1 AND 4 AND array_position(event_kinds,NULL) IS NULL AND event_kinds <@ ARRAY['fall','immobility','environment','device']::text[]),
 ADD CONSTRAINT channel_suppression CHECK ((suppressed_at IS NULL)=(suppression_reason IS NULL));
CREATE UNIQUE INDEX one_active_email_channel ON annha.notification_channels(home_id,recipient_user_id) WHERE kind='email' AND revoked_at IS NULL;

ALTER TABLE annha.notification_deliveries DROP CONSTRAINT notification_deliveries_status_check;
UPDATE annha.notification_deliveries SET status='accepted' WHERE status='sent';
ALTER TABLE annha.notification_deliveries
 ADD CONSTRAINT notification_deliveries_status_check CHECK (status IN ('pending','sending','accepted','delivered','bounced','complained','rejected','failed','cancelled','unknown')),
 ADD COLUMN email_version integer CHECK (email_version>0),
 ADD COLUMN accepted_at timestamptz,
 ADD COLUMN delivered_at timestamptz,
 ADD COLUMN last_provider_event_at timestamptz;
CREATE INDEX delivery_ready ON annha.notification_deliveries(next_attempt_at,id) WHERE status='pending';

ALTER TABLE annha.delivery_attempts DROP CONSTRAINT delivery_attempts_status_check;
UPDATE annha.delivery_attempts SET status='accepted' WHERE status='sent';
ALTER TABLE annha.delivery_attempts
 ADD CONSTRAINT delivery_attempts_status_check CHECK (status IN ('accepted','failed','unknown')),
 ADD COLUMN provider text NOT NULL DEFAULT 'legacy' CHECK (provider ~ '^[a-z0-9_-]{1,64}$'),
 ADD COLUMN provider_account_ref text NOT NULL DEFAULT 'default' CHECK (length(provider_account_ref) BETWEEN 1 AND 128),
 ADD CONSTRAINT receipt_attempt_identity UNIQUE(home_id,delivery_id,id,provider,provider_account_ref);
CREATE UNIQUE INDEX provider_message_unique ON annha.delivery_attempts(provider,provider_account_ref,provider_message_id) WHERE provider_message_id IS NOT NULL;
CREATE TABLE annha.delivery_receipts (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), home_id uuid NOT NULL,
 delivery_id uuid NOT NULL, attempt_id uuid NOT NULL,
 provider text NOT NULL CHECK (provider ~ '^[a-z0-9_-]{1,64}$'),
 provider_account_ref text NOT NULL DEFAULT 'default', provider_event_id text NOT NULL CHECK (length(provider_event_id) BETWEEN 1 AND 256),
 kind text NOT NULL CHECK (kind IN ('delivered','bounced','complained','rejected')),
 bounce_class text CHECK (bounce_class IN ('hard','soft','unknown')),
 occurred_at timestamptz NOT NULL, received_at timestamptz NOT NULL DEFAULT now(),
 metadata jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(metadata)='object' AND octet_length(metadata::text)<=8192),
 UNIQUE(provider,provider_account_ref,provider_event_id),
 FOREIGN KEY(home_id,delivery_id,attempt_id,provider,provider_account_ref) REFERENCES annha.delivery_attempts(home_id,delivery_id,id,provider,provider_account_ref),
 CHECK ((kind='bounced' AND bounce_class IS NOT NULL) OR (kind<>'bounced' AND bounce_class IS NULL))
);
CREATE INDEX receipt_delivery_time ON annha.delivery_receipts(delivery_id,occurred_at,id);
ALTER TABLE annha.delivery_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE annha.delivery_receipts FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_boundary ON annha.delivery_receipts AS RESTRICTIVE TO annha_app,annha_device,annha_worker
 USING (home_id=annha_private.context_id('app.home_id')) WITH CHECK (home_id=annha_private.context_id('app.home_id'));
DO $$ BEGIN
 EXECUTE format('CREATE POLICY migration_owner ON annha.delivery_receipts TO %I USING (true) WITH CHECK (true)',current_user);
END $$;
CREATE POLICY worker_tenant ON annha.delivery_receipts TO annha_worker USING (true) WITH CHECK (true);
CREATE POLICY app_owner_read ON annha.delivery_receipts FOR SELECT TO annha_app USING (annha_private.can_home(home_id,true));
GRANT SELECT ON annha.delivery_receipts TO annha_app;
GRANT SELECT,INSERT,DELETE ON annha.delivery_receipts TO annha_worker;
-- User-facing role cannot clear bounce/complaint suppression or retarget a channel.
REVOKE INSERT,UPDATE ON annha.notification_channels FROM annha_app;
GRANT INSERT(id,home_id,recipient_user_id,kind,label,enabled,allow_media,media_consent_at,consent_by,email_version,event_kinds,minimum_severity) ON annha.notification_channels TO annha_app;
GRANT UPDATE(label,enabled,allow_media,media_consent_at,consent_by,email_version,event_kinds,minimum_severity,revoked_at) ON annha.notification_channels TO annha_app;
CREATE TRIGGER notification_identity_immutable BEFORE UPDATE ON annha.notification_channels FOR EACH ROW
 EXECUTE FUNCTION annha_private.immutable_keys('id','home_id','recipient_user_id','kind');

CREATE FUNCTION annha_private.validate_notification_channel() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE recipient annha_private.users%ROWTYPE;
BEGIN
 IF NEW.enabled AND NEW.revoked_at IS NULL THEN
  IF NOT EXISTS(SELECT 1 FROM annha_private.home_memberships WHERE home_id=NEW.home_id AND user_id=NEW.recipient_user_id AND revoked_at IS NULL) THEN
   RAISE EXCEPTION 'Recipient membership is inactive' USING ERRCODE='23514';
  END IF;
  IF NEW.kind='email' THEN
   SELECT * INTO recipient FROM annha_private.users WHERE id=NEW.recipient_user_id;
   IF recipient.email_verified_at IS NULL OR recipient.email_version<>NEW.email_version OR recipient.disabled_at IS NOT NULL OR recipient.deleted_at IS NOT NULL THEN
    RAISE EXCEPTION 'A current verified account email is required' USING ERRCODE='23514';
   END IF;
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER notification_verified_recipient BEFORE INSERT OR UPDATE ON annha.notification_channels FOR EACH ROW EXECUTE FUNCTION annha_private.validate_notification_channel();
CREATE FUNCTION annha_private.invalidate_changed_email() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF NEW.email IS DISTINCT FROM OLD.email THEN
  NEW.email_version=OLD.email_version+1;
  NEW.email_verified_at=NULL;
  NEW.auth_version=OLD.auth_version+1;
  UPDATE annha_private.email_tokens SET consumed_at=COALESCE(consumed_at,now()) WHERE user_id=OLD.id;
  UPDATE annha_private.sessions SET revoked_at=COALESCE(revoked_at,now()) WHERE user_id=OLD.id;
  UPDATE annha.notification_channels SET enabled=false WHERE recipient_user_id=OLD.id AND kind='email';
  UPDATE annha.notification_deliveries d SET status='cancelled'
   FROM annha.notification_channels c WHERE c.id=d.channel_id AND c.recipient_user_id=OLD.id AND c.kind='email' AND d.status='pending';
 ELSE
  IF NEW.email_version<>OLD.email_version THEN RAISE EXCEPTION 'Email version changes only with address' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER email_change BEFORE UPDATE ON annha_private.users FOR EACH ROW EXECUTE FUNCTION annha_private.invalidate_changed_email();
CREATE FUNCTION annha_private.validate_email_token_version() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM annha_private.users WHERE id=NEW.user_id AND email_version<>NEW.email_version) THEN
  RAISE EXCEPTION 'Email token is bound to a stale address' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER email_token_version BEFORE INSERT ON annha_private.email_tokens FOR EACH ROW EXECUTE FUNCTION annha_private.validate_email_token_version();
-- Bind delivery to the current address version; no duplicate cleartext recipient email.
CREATE FUNCTION annha_private.bind_delivery_email() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE channel annha.notification_channels%ROWTYPE;
BEGIN
 SELECT * INTO channel FROM annha.notification_channels WHERE id=NEW.channel_id AND home_id=NEW.home_id;
 IF FOUND THEN
  IF channel.kind='email' THEN
   IF NEW.email_version IS NULL THEN NEW.email_version=channel.email_version; END IF;
   IF NEW.email_version<>channel.email_version THEN RAISE EXCEPTION 'Stale email delivery version' USING ERRCODE='23514'; END IF;
  ELSIF NEW.email_version IS NOT NULL THEN
   RAISE EXCEPTION 'Telegram delivery has no email version' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER delivery_email_binding BEFORE INSERT ON annha.notification_deliveries FOR EACH ROW EXECUTE FUNCTION annha_private.bind_delivery_email();
CREATE TRIGGER delivery_identity_immutable BEFORE UPDATE ON annha.notification_deliveries FOR EACH ROW
 EXECUTE FUNCTION annha_private.immutable_keys('id','home_id','camera_id','event_id','channel_id','generation','email_version');
-- Call immediately before each external send; the backend must still validate its session/job.
CREATE FUNCTION annha_private.can_dispatch_notification(delivery uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT EXISTS (
  SELECT 1 FROM annha.notification_deliveries d
  JOIN annha.notification_channels c ON c.id=d.channel_id AND c.home_id=d.home_id
  JOIN annha.events e ON e.id=d.event_id AND e.home_id=d.home_id
  JOIN annha_private.users u ON u.id=c.recipient_user_id
  JOIN annha_private.home_memberships m ON m.home_id=d.home_id AND m.user_id=u.id
  LEFT JOIN annha_private.camera_grants g ON g.home_id=d.home_id AND g.camera_id=d.camera_id AND g.user_id=u.id
  WHERE d.id=delivery AND d.home_id=annha_private.context_id('app.home_id') AND d.status IN ('pending','sending')
   AND c.enabled AND c.revoked_at IS NULL AND c.suppressed_at IS NULL
   AND m.revoked_at IS NULL AND u.disabled_at IS NULL AND u.deleted_at IS NULL
   AND (m.role='owner' OR g.can_view)
   AND e.status='OPEN' AND e.kind=ANY(c.event_kinds)
   AND CASE e.severity WHEN 'critical' THEN 3 WHEN 'warning' THEN 2 ELSE 1 END >= CASE c.minimum_severity WHEN 'critical' THEN 3 WHEN 'warning' THEN 2 ELSE 1 END
   AND (c.kind='telegram' OR (u.email_verified_at IS NOT NULL AND d.email_version=c.email_version AND c.email_version=u.email_version))
 )
$$;
REVOKE EXECUTE ON FUNCTION annha_private.validate_notification_channel(),annha_private.invalidate_changed_email(),annha_private.bind_delivery_email(),annha_private.validate_email_token_version(),annha_private.can_dispatch_notification(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION annha_private.can_dispatch_notification(uuid) TO annha_worker;
COMMIT;
