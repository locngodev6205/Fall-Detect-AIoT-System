-- Archived homes must fail closed for application reads/writes, including known resource IDs.
BEGIN;
CREATE OR REPLACE FUNCTION annha_private.can_home(target uuid, owner_only boolean DEFAULT false) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT EXISTS (
  SELECT 1 FROM annha_private.home_memberships m JOIN annha_private.users u ON u.id=m.user_id
  JOIN annha.homes h ON h.id=m.home_id AND h.archived_at IS NULL
  WHERE m.home_id=target AND m.user_id=annha_private.context_id('app.user_id') AND m.revoked_at IS NULL
   AND u.disabled_at IS NULL AND u.deleted_at IS NULL AND (NOT owner_only OR m.role='owner')
 )
$$;
CREATE OR REPLACE FUNCTION annha_private.can_camera(target_home uuid, target_camera uuid, action text DEFAULT 'view') RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT EXISTS (
  SELECT 1 FROM annha_private.home_memberships m JOIN annha_private.users u ON u.id=m.user_id
  JOIN annha.homes h ON h.id=m.home_id AND h.archived_at IS NULL
  LEFT JOIN annha_private.camera_grants g ON g.home_id=m.home_id AND g.user_id=m.user_id AND g.camera_id=target_camera
  WHERE m.home_id=target_home AND m.user_id=annha_private.context_id('app.user_id') AND m.revoked_at IS NULL
   AND u.disabled_at IS NULL AND u.deleted_at IS NULL
   AND (m.role='owner' OR (g.can_view AND
    (action='view' OR (m.role='caregiver' AND CASE action
      WHEN 'events' THEN g.can_handle_events WHEN 'audio' THEN g.can_play_audio WHEN 'schedules' THEN g.can_edit_reminders ELSE false END))))
 )
$$;
COMMIT;
