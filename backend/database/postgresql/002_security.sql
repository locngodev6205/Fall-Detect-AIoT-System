-- Apply after 001_schema.sql using the same migration owner.
BEGIN;
CREATE FUNCTION annha_private.context_id(key text) RETURNS uuid LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT nullif(current_setting(key,true),'')::uuid
$$;
CREATE FUNCTION annha_private.can_home(target uuid, owner_only boolean DEFAULT false) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT EXISTS (
  SELECT 1 FROM annha_private.home_memberships m JOIN annha_private.users u ON u.id=m.user_id
  WHERE m.home_id=target AND m.user_id=annha_private.context_id('app.user_id') AND m.revoked_at IS NULL
   AND u.disabled_at IS NULL AND u.deleted_at IS NULL AND (NOT owner_only OR m.role='owner')
 )
$$;
CREATE FUNCTION annha_private.can_camera(target_home uuid, target_camera uuid, action text DEFAULT 'view') RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT EXISTS (
  SELECT 1 FROM annha_private.home_memberships m JOIN annha_private.users u ON u.id=m.user_id
  LEFT JOIN annha_private.camera_grants g ON g.home_id=m.home_id AND g.user_id=m.user_id AND g.camera_id=target_camera
  WHERE m.home_id=target_home AND m.user_id=annha_private.context_id('app.user_id') AND m.revoked_at IS NULL
   AND u.disabled_at IS NULL AND u.deleted_at IS NULL
   AND (m.role='owner' OR (g.can_view AND
    (action='view' OR (m.role='caregiver' AND CASE action
      WHEN 'events' THEN g.can_handle_events WHEN 'audio' THEN g.can_play_audio WHEN 'schedules' THEN g.can_edit_reminders ELSE false END))))
 )
$$;
-- Internal private tables are available only to trusted control-plane / job workers.
REVOKE ALL ON ALL TABLES IN SCHEMA annha_private FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA annha FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA annha_private FROM PUBLIC;
GRANT USAGE ON SCHEMA annha,annha_private TO annha_app,annha_auth,annha_device,annha_worker;
GRANT EXECUTE ON FUNCTION annha_private.context_id(text),annha_private.can_home(uuid,boolean),annha_private.can_camera(uuid,uuid,text)
 TO annha_app,annha_device,annha_worker;
GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA annha_private TO annha_auth;
REVOKE UPDATE,DELETE ON annha_private.security_events FROM annha_auth;
GRANT SELECT,INSERT,UPDATE,DELETE ON annha_private.job_queue TO annha_worker;
GRANT SELECT,INSERT,UPDATE,DELETE ON annha_private.notification_secrets TO annha_worker;
-- No runtime role owns a table, can create objects, bypass RLS or alter policies.
DO $$
DECLARE item record; home_column text;
BEGIN
 FOR item IN SELECT tablename FROM pg_tables WHERE schemaname='annha' LOOP
  home_column=CASE WHEN item.tablename='homes' THEN 'id' ELSE 'home_id' END;
  EXECUTE format('ALTER TABLE annha.%I ENABLE ROW LEVEL SECURITY',item.tablename);
  EXECUTE format('ALTER TABLE annha.%I FORCE ROW LEVEL SECURITY',item.tablename);
  EXECUTE format('CREATE POLICY tenant_boundary ON annha.%I AS RESTRICTIVE FOR ALL TO annha_app,annha_device,annha_worker USING (%I=annha_private.context_id(''app.home_id'')) WITH CHECK (%I=annha_private.context_id(''app.home_id''))',item.tablename,home_column,home_column);
  -- The migration owner has an explicit maintenance policy; never use its login in the API.
  EXECUTE format('CREATE POLICY migration_owner ON annha.%I FOR ALL TO %I USING (true) WITH CHECK (true)',item.tablename,current_user);
  EXECUTE format('CREATE POLICY worker_tenant ON annha.%I FOR ALL TO annha_worker USING (true) WITH CHECK (true)',item.tablename);
 END LOOP;
END $$;
GRANT EXECUTE ON FUNCTION annha_private.context_id(text) TO annha_auth;
-- Control-plane bootstrap/provisioning/member administration has no direct event/media privileges.
GRANT SELECT,INSERT,UPDATE ON annha.homes,annha.rooms,annha.cameras TO annha_auth;
CREATE POLICY control_plane ON annha.homes TO annha_auth USING (true) WITH CHECK (true);
CREATE POLICY control_plane ON annha.rooms TO annha_auth USING (true) WITH CHECK (true);
CREATE POLICY control_plane ON annha.cameras TO annha_auth USING (true) WITH CHECK (true);
GRANT INSERT ON annha.home_settings,annha.home_storage TO annha_auth;
CREATE POLICY control_defaults ON annha.home_settings FOR INSERT TO annha_auth WITH CHECK (home_id=annha_private.context_id('app.home_id'));
CREATE POLICY control_defaults ON annha.home_storage FOR INSERT TO annha_auth WITH CHECK (home_id=annha_private.context_id('app.home_id'));
GRANT INSERT ON annha.audit_logs TO annha_auth;
CREATE POLICY control_audit ON annha.audit_logs FOR INSERT TO annha_auth
 WITH CHECK (home_id=annha_private.context_id('app.home_id'));
-- Runtime business worker is trusted but must choose a tenant for each transaction.
GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA annha TO annha_worker;
REVOKE UPDATE,DELETE ON annha.audit_logs,annha.camera_configurations,annha.reminder_revisions FROM annha_worker;
REVOKE UPDATE ON annha.event_updates,annha.event_actions,annha.delivery_attempts,annha.reminder_executions FROM annha_worker;
-- SELECT is not granted over users, passwords, session hashes or token tables to app/device/worker.
GRANT SELECT ON annha.homes,annha.rooms,annha.cameras,annha.camera_configurations,annha.camera_config_state,
 annha.config_acknowledgements,annha.events,annha.event_updates,annha.event_actions,annha.telemetry_batches,
 annha.sensor_readings,annha.monitor_states,annha.media_assets,annha.reminders,annha.reminder_revisions,
 annha.reminder_executions,annha.commands,annha.live_sessions,annha.home_settings,annha.home_storage,
 annha.notification_channels,annha.notification_deliveries,annha.delivery_attempts,annha.audit_logs TO annha_app;
CREATE POLICY app_read ON annha.homes FOR SELECT TO annha_app USING (annha_private.can_home(id));
CREATE POLICY app_read ON annha.rooms FOR SELECT TO annha_app USING (
 annha_private.can_home(home_id,true) OR EXISTS(SELECT 1 FROM annha.cameras c WHERE c.home_id=rooms.home_id AND c.room_id=rooms.id AND annha_private.can_camera(c.home_id,c.id)));
CREATE POLICY app_read ON annha.cameras FOR SELECT TO annha_app USING (annha_private.can_camera(home_id,id));
DO $$
DECLARE name text;
BEGIN
 FOREACH name IN ARRAY ARRAY['camera_configurations','camera_config_state','config_acknowledgements','events','event_updates','event_actions','telemetry_batches','sensor_readings','monitor_states','media_assets','reminders','reminder_revisions','reminder_executions','commands'] LOOP
  EXECUTE format('CREATE POLICY app_read ON annha.%I FOR SELECT TO annha_app USING (annha_private.can_camera(home_id,camera_id))',name);
 END LOOP;
 FOREACH name IN ARRAY ARRAY['home_settings','home_storage','notification_channels','notification_deliveries','delivery_attempts','audit_logs'] LOOP
  EXECUTE format('CREATE POLICY app_owner_read ON annha.%I FOR SELECT TO annha_app USING (annha_private.can_home(home_id,true))',name);
 END LOOP;
END $$;
GRANT UPDATE(name,timezone,archived_at) ON annha.homes TO annha_app;
CREATE POLICY owner_edit ON annha.homes FOR UPDATE TO annha_app USING (annha_private.can_home(id,true)) WITH CHECK (annha_private.can_home(id,true));
GRANT INSERT,UPDATE ON annha.rooms TO annha_app;
CREATE POLICY owner_insert ON annha.rooms FOR INSERT TO annha_app WITH CHECK (annha_private.can_home(home_id,true));
CREATE POLICY owner_edit ON annha.rooms FOR UPDATE TO annha_app USING (annha_private.can_home(home_id,true)) WITH CHECK (annha_private.can_home(home_id,true));
GRANT UPDATE(name,room_id,retired_at) ON annha.cameras TO annha_app;
CREATE POLICY owner_edit ON annha.cameras FOR UPDATE TO annha_app USING (annha_private.can_home(home_id,true)) WITH CHECK (annha_private.can_home(home_id,true));
GRANT UPDATE ON annha.home_settings TO annha_app;
CREATE POLICY owner_edit ON annha.home_settings FOR UPDATE TO annha_app USING (annha_private.can_home(home_id,true)) WITH CHECK (annha_private.can_home(home_id,true));
GRANT UPDATE(status,updated_at) ON annha.events TO annha_app;
CREATE POLICY handler_edit ON annha.events FOR UPDATE TO annha_app USING (annha_private.can_camera(home_id,camera_id,'events')) WITH CHECK (annha_private.can_camera(home_id,camera_id,'events'));
GRANT INSERT ON annha.event_actions TO annha_app;
CREATE POLICY handler_action ON annha.event_actions FOR INSERT TO annha_app WITH CHECK (annha_private.can_camera(home_id,camera_id,'events') AND user_id=annha_private.context_id('app.user_id'));
GRANT INSERT ON annha.media_assets TO annha_app;
CREATE POLICY audio_upload ON annha.media_assets FOR INSERT TO annha_app WITH CHECK (annha_private.can_camera(home_id,camera_id,'audio') AND kind IN ('audio','tts') AND status IN ('uploading','processing') AND created_by=annha_private.context_id('app.user_id'));
GRANT UPDATE(status,deletion_requested_at) ON annha.media_assets TO annha_app;
CREATE POLICY owner_remove_media ON annha.media_assets FOR UPDATE TO annha_app USING (annha_private.can_home(home_id,true)) WITH CHECK (annha_private.can_home(home_id,true) AND status='deleting');
GRANT INSERT ON annha.reminders TO annha_app;
GRANT UPDATE(name,enabled,current_version,updated_at,deleted_at) ON annha.reminders TO annha_app;
CREATE POLICY schedule_insert ON annha.reminders FOR INSERT TO annha_app WITH CHECK (annha_private.can_camera(home_id,camera_id,'schedules') AND created_by=annha_private.context_id('app.user_id'));
CREATE POLICY schedule_edit ON annha.reminders FOR UPDATE TO annha_app USING (annha_private.can_camera(home_id,camera_id,'schedules')) WITH CHECK (annha_private.can_camera(home_id,camera_id,'schedules'));
GRANT INSERT ON annha.reminder_revisions TO annha_app;
CREATE POLICY schedule_revision ON annha.reminder_revisions FOR INSERT TO annha_app WITH CHECK (annha_private.can_camera(home_id,camera_id,'schedules'));
GRANT INSERT ON annha.commands TO annha_app;
CREATE POLICY send_command ON annha.commands FOR INSERT TO annha_app WITH CHECK (
 requested_by=annha_private.context_id('app.user_id') AND status='pending' AND
 (annha_private.can_camera(home_id,camera_id,'audio') OR (kind='silence' AND annha_private.can_camera(home_id,camera_id,'events'))));
GRANT INSERT,UPDATE ON annha.notification_channels TO annha_app;
CREATE POLICY channel_owner ON annha.notification_channels TO annha_app USING (annha_private.can_home(home_id,true)) WITH CHECK (annha_private.can_home(home_id,true));
GRANT INSERT,UPDATE ON annha.live_sessions TO annha_app;
CREATE POLICY live_own ON annha.live_sessions TO annha_app
 USING (user_id=annha_private.context_id('app.user_id') AND annha_private.can_camera(home_id,camera_id))
 WITH CHECK (user_id=annha_private.context_id('app.user_id') AND annha_private.can_camera(home_id,camera_id,CASE WHEN kind='push_to_talk' THEN 'audio' ELSE 'view' END));
GRANT INSERT ON annha.audit_logs TO annha_app;
CREATE POLICY app_audit ON annha.audit_logs FOR INSERT TO annha_app WITH CHECK (actor_type='user' AND user_id=annha_private.context_id('app.user_id') AND annha_private.can_home(home_id));
-- Device role is assigned only after backend verifies and maps a device credential.
GRANT SELECT ON annha.camera_configurations,annha.camera_config_state,annha.media_assets,annha.commands,annha.reminders,annha.reminder_revisions TO annha_device;
DO $$
DECLARE name text;
BEGIN
 FOREACH name IN ARRAY ARRAY['camera_configurations','camera_config_state','media_assets','commands','reminders','reminder_revisions'] LOOP
  EXECUTE format('CREATE POLICY device_read ON annha.%I FOR SELECT TO annha_device USING (camera_id=annha_private.context_id(''app.camera_id''))',name);
 END LOOP;
 FOREACH name IN ARRAY ARRAY['config_acknowledgements','events','event_updates','telemetry_batches','sensor_readings','reminder_executions'] LOOP
  EXECUTE format('CREATE POLICY device_insert ON annha.%I FOR INSERT TO annha_device WITH CHECK (camera_id=annha_private.context_id(''app.camera_id''))',name);
 END LOOP;
END $$;
GRANT INSERT ON annha.config_acknowledgements,annha.event_updates,annha.telemetry_batches,annha.sensor_readings,annha.reminder_executions TO annha_device;
GRANT INSERT(id,home_id,camera_id,source_id,latest_sequence,kind,severity,observation,first_observed_at,last_observed_at,reason,duration_s,model_score,config_version) ON annha.events TO annha_device;
-- Event upsert/read is mediated by the trusted ingest service; devices cannot set human status.
CREATE POLICY device_evidence ON annha.media_assets FOR INSERT TO annha_device WITH CHECK (camera_id=annha_private.context_id('app.camera_id') AND kind IN ('snapshot','event_image','event_clip') AND status='uploading');
GRANT INSERT(id,home_id,camera_id,event_id,kind,name,mime_type,reserved_bytes,upload_key,captured_from,captured_to) ON annha.media_assets TO annha_device;
GRANT UPDATE(status,accepted_at,completed_at,result) ON annha.commands TO annha_device;
CREATE POLICY device_command_ack ON annha.commands FOR UPDATE TO annha_device
 USING (camera_id=annha_private.context_id('app.camera_id'))
 WITH CHECK (camera_id=annha_private.context_id('app.camera_id') AND status IN ('accepted','executing','executed','failed'));
-- Backend must reject expired command execution and invalid state transitions under row lock.
-- Harden future objects created by this migration owner too.
ALTER DEFAULT PRIVILEGES IN SCHEMA annha,annha_private REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA annha,annha_private REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
COMMIT;
