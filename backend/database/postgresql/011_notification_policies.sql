-- Add per-recipient camera scope and reminder policy. No media or history is deleted.
BEGIN;

ALTER TABLE annha.notification_channels
 ADD COLUMN camera_scope_all boolean NOT NULL DEFAULT true;
GRANT INSERT(camera_scope_all),UPDATE(camera_scope_all) ON annha.notification_channels TO annha_app;

CREATE TABLE annha.notification_channel_cameras (
 home_id uuid NOT NULL,
 channel_id uuid NOT NULL,
 camera_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(channel_id,camera_id),
 FOREIGN KEY(home_id,channel_id) REFERENCES annha.notification_channels(home_id,id) ON DELETE CASCADE,
 FOREIGN KEY(home_id,camera_id) REFERENCES annha.cameras(home_id,id) ON DELETE CASCADE
);
ALTER TABLE annha.notification_channel_cameras ENABLE ROW LEVEL SECURITY;
ALTER TABLE annha.notification_channel_cameras FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_boundary ON annha.notification_channel_cameras AS RESTRICTIVE FOR ALL
 TO annha_app,annha_worker USING (home_id=annha_private.context_id('app.home_id'))
 WITH CHECK (home_id=annha_private.context_id('app.home_id'));
CREATE POLICY worker_tenant ON annha.notification_channel_cameras FOR ALL TO annha_worker
 USING (true) WITH CHECK (true);
DO $$ BEGIN
 EXECUTE format('CREATE POLICY migration_owner ON annha.notification_channel_cameras FOR ALL TO %I USING (true) WITH CHECK (true)',current_user);
END $$;
CREATE POLICY app_owner_read ON annha.notification_channel_cameras FOR SELECT TO annha_app
 USING (annha_private.can_home(home_id,true));
CREATE POLICY app_owner_insert ON annha.notification_channel_cameras FOR INSERT TO annha_app
 WITH CHECK (annha_private.can_home(home_id,true));
CREATE POLICY app_owner_delete ON annha.notification_channel_cameras FOR DELETE TO annha_app
 USING (annha_private.can_home(home_id,true));
GRANT SELECT,INSERT,DELETE ON annha.notification_channel_cameras TO annha_app;
GRANT SELECT,INSERT,UPDATE,DELETE ON annha.notification_channel_cameras TO annha_worker;

ALTER TABLE annha.home_settings
 ADD COLUMN notification_reminder_interval_seconds integer NOT NULL DEFAULT 900
   CHECK (notification_reminder_interval_seconds BETWEEN 300 AND 86400),
 ADD COLUMN notification_max_reminders integer NOT NULL DEFAULT 3
   CHECK (notification_max_reminders BETWEEN 0 AND 5);

ALTER TABLE annha.notification_deliveries
 ADD COLUMN dispatch_kind text NOT NULL DEFAULT 'legacy'
   CHECK (dispatch_kind IN ('initial','reminder','legacy')),
 ADD COLUMN reminder_number integer NOT NULL DEFAULT 0 CHECK (reminder_number BETWEEN 0 AND 5),
 ADD COLUMN last_dispatch_at timestamptz,
 ADD COLUMN media_result text NOT NULL DEFAULT 'not_requested'
   CHECK (media_result IN ('not_requested','consent_disabled','missing','unavailable','sent','text_fallback')),
 ADD CONSTRAINT delivery_reminder_identity CHECK (
   (dispatch_kind='initial' AND reminder_number=0) OR
   (dispatch_kind='reminder' AND reminder_number BETWEEN 1 AND 5) OR
   (dispatch_kind='legacy' AND reminder_number=0)
 );

CREATE INDEX notification_reminder_due ON annha.notification_deliveries(home_id,event_id,channel_id,generation DESC)
 WHERE status IN ('accepted','unknown');

CREATE OR REPLACE FUNCTION annha_private.can_dispatch_notification(delivery uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT EXISTS (
  SELECT 1 FROM annha.notification_deliveries d
  JOIN annha.notification_channels c ON c.id=d.channel_id AND c.home_id=d.home_id
  JOIN annha.events e ON e.id=d.event_id AND e.home_id=d.home_id
  JOIN annha.homes h ON h.id=d.home_id AND h.archived_at IS NULL
  JOIN annha_private.users u ON u.id=c.recipient_user_id
  JOIN annha_private.home_memberships m ON m.home_id=d.home_id AND m.user_id=u.id
  LEFT JOIN annha_private.camera_grants g ON g.home_id=d.home_id AND g.camera_id=d.camera_id AND g.user_id=u.id
  WHERE d.id=delivery AND d.home_id=annha_private.context_id('app.home_id')
   AND d.status IN ('pending','sending')
   AND c.enabled AND c.revoked_at IS NULL AND c.suppressed_at IS NULL
   AND m.revoked_at IS NULL AND u.disabled_at IS NULL AND u.deleted_at IS NULL
   AND m.role IN ('owner','caregiver')
   AND (m.role='owner' OR g.can_view)
   AND (c.camera_scope_all OR EXISTS (
      SELECT 1 FROM annha.notification_channel_cameras s
      WHERE s.home_id=d.home_id AND s.channel_id=c.id AND s.camera_id=d.camera_id
   ))
   AND e.status='OPEN' AND e.kind=ANY(c.event_kinds)
   AND CASE e.severity WHEN 'critical' THEN 3 WHEN 'warning' THEN 2 ELSE 1 END >=
       CASE c.minimum_severity WHEN 'critical' THEN 3 WHEN 'warning' THEN 2 ELSE 1 END
   AND (c.kind='telegram' OR (u.email_verified_at IS NOT NULL AND d.email_version=c.email_version AND c.email_version=u.email_version))
 )
$$;

CREATE OR REPLACE FUNCTION annha_private.can_schedule_notification_reminder(delivery uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT EXISTS (
  SELECT 1 FROM annha.notification_deliveries d
  JOIN annha.notification_channels c ON c.id=d.channel_id AND c.home_id=d.home_id
  JOIN annha.events e ON e.id=d.event_id AND e.home_id=d.home_id
  JOIN annha.homes h ON h.id=d.home_id AND h.archived_at IS NULL
  JOIN annha_private.users u ON u.id=c.recipient_user_id
  JOIN annha_private.home_memberships m ON m.home_id=d.home_id AND m.user_id=u.id
  LEFT JOIN annha_private.camera_grants g ON g.home_id=d.home_id AND g.camera_id=d.camera_id AND g.user_id=u.id
  WHERE d.id=delivery AND d.home_id=annha_private.context_id('app.home_id')
   AND d.status IN ('accepted','unknown') AND d.dispatch_kind IN ('initial','reminder')
   AND c.enabled AND c.revoked_at IS NULL AND c.suppressed_at IS NULL
   AND m.revoked_at IS NULL AND u.disabled_at IS NULL AND u.deleted_at IS NULL
   AND m.role IN ('owner','caregiver') AND (m.role='owner' OR g.can_view)
   AND (c.camera_scope_all OR EXISTS (SELECT 1 FROM annha.notification_channel_cameras s
     WHERE s.home_id=d.home_id AND s.channel_id=c.id AND s.camera_id=d.camera_id))
   AND e.status='OPEN' AND e.kind=ANY(c.event_kinds)
   AND CASE e.severity WHEN 'critical' THEN 3 WHEN 'warning' THEN 2 ELSE 1 END >=
       CASE c.minimum_severity WHEN 'critical' THEN 3 WHEN 'warning' THEN 2 ELSE 1 END
   AND (c.kind='telegram' OR (u.email_verified_at IS NOT NULL AND d.email_version=c.email_version AND c.email_version=u.email_version))
 )
$$;

REVOKE EXECUTE ON FUNCTION annha_private.can_dispatch_notification(uuid),
 annha_private.can_schedule_notification_reminder(uuid) FROM PUBLIC,annha_app,annha_auth,annha_device;
GRANT EXECUTE ON FUNCTION annha_private.can_dispatch_notification(uuid),
 annha_private.can_schedule_notification_reminder(uuid) TO annha_worker;

COMMIT;
