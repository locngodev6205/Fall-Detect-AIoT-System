-- Do not dispatch notifications for archived homes, even if an old job remains.
BEGIN;
CREATE OR REPLACE FUNCTION annha_private.can_dispatch_notification(delivery uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT EXISTS (
  SELECT 1 FROM annha.notification_deliveries d
  JOIN annha.notification_channels c ON c.id=d.channel_id AND c.home_id=d.home_id
  JOIN annha.events e ON e.id=d.event_id AND e.home_id=d.home_id
  JOIN annha.homes h ON h.id=d.home_id AND h.archived_at IS NULL
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
COMMIT;
