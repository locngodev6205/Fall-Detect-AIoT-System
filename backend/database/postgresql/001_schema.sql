-- AnNha target schema, PostgreSQL 16+, 2026-10-29.
-- NEW EMPTY DATABASE ONLY. Run as migration owner; never as application login.
-- No cloud connection, secret, seed user or destructive migration is included.
BEGIN;
CREATE ROLE annha_app NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION;
CREATE ROLE annha_auth NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION;
CREATE ROLE annha_device NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION;
CREATE ROLE annha_worker NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION;
CREATE SCHEMA annha;
CREATE SCHEMA annha_private;
REVOKE ALL ON SCHEMA annha, annha_private FROM PUBLIC;

CREATE TABLE annha_private.users (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 email text NOT NULL CHECK (email = lower(btrim(email)) AND length(email) BETWEEN 3 AND 254),
 name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 120),
 password_hash text NOT NULL, -- encoded algorithm + parameters + salt + hash; no plaintext
 email_verified_at timestamptz, auth_version integer NOT NULL DEFAULT 1 CHECK (auth_version > 0),
 disabled_at timestamptz, deleted_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(email)
);
CREATE TABLE annha_private.sessions (
 token_hash bytea PRIMARY KEY CHECK (octet_length(token_hash)=32),
 user_id uuid NOT NULL REFERENCES annha_private.users,
 csrf_hash bytea NOT NULL CHECK (octet_length(csrf_hash)=32),
 auth_version integer NOT NULL CHECK (auth_version > 0),
 created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL,
 revoked_at timestamptz, last_seen_at timestamptz,
 CHECK (expires_at > created_at)
);
CREATE INDEX sessions_user_active ON annha_private.sessions(user_id, expires_at) WHERE revoked_at IS NULL;
CREATE TABLE annha_private.email_tokens (
 token_hash bytea PRIMARY KEY CHECK (octet_length(token_hash)=32),
 user_id uuid NOT NULL REFERENCES annha_private.users,
 purpose text NOT NULL CHECK (purpose IN ('verify_email','reset_password')),
 created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL,
 consumed_at timestamptz, CHECK (expires_at > created_at)
);
CREATE INDEX email_tokens_expiry ON annha_private.email_tokens(expires_at);
CREATE TABLE annha_private.rate_limits (
 key_hash bytea PRIMARY KEY CHECK (octet_length(key_hash)=32),
 hits integer NOT NULL CHECK (hits>=0), window_end timestamptz NOT NULL
);
CREATE TABLE annha_private.security_events (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid REFERENCES annha_private.users,
 action text NOT NULL, outcome text NOT NULL CHECK (outcome IN ('success','denied','failed')),
 subject_hash bytea CHECK (subject_hash IS NULL OR octet_length(subject_hash)=32),
 request_id uuid, details jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(details)='object'),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX security_event_user_time ON annha_private.security_events(user_id,created_at DESC);
CREATE TABLE annha_private.device_registry (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), serial_number text UNIQUE,
 model text, created_at timestamptz NOT NULL DEFAULT now(), retired_at timestamptz
);
CREATE TABLE annha.homes (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 120),
 timezone text NOT NULL DEFAULT 'Asia/Ho_Chi_Minh',
 created_by uuid NOT NULL REFERENCES annha_private.users,
 created_at timestamptz NOT NULL DEFAULT now(), archived_at timestamptz
);
CREATE TABLE annha_private.home_memberships (
 home_id uuid NOT NULL REFERENCES annha.homes, user_id uuid NOT NULL REFERENCES annha_private.users,
 role text NOT NULL CHECK (role IN ('owner','caregiver','viewer')),
 granted_by uuid REFERENCES annha_private.users,
 created_at timestamptz NOT NULL DEFAULT now(), revoked_at timestamptz,
 version integer NOT NULL DEFAULT 1 CHECK (version>0), PRIMARY KEY(home_id,user_id)
);
CREATE UNIQUE INDEX one_active_owner ON annha_private.home_memberships(home_id) WHERE role='owner' AND revoked_at IS NULL;
CREATE INDEX membership_user ON annha_private.home_memberships(user_id,home_id) WHERE revoked_at IS NULL;
CREATE TABLE annha.rooms (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), home_id uuid NOT NULL REFERENCES annha.homes,
 name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 120),
 created_at timestamptz NOT NULL DEFAULT now(), archived_at timestamptz, UNIQUE(home_id,id)
);
-- A camera is an ownership deployment, NOT the reusable physical device.
-- Transfer: retire old deployment; create new camera id. Never reparent historical rows.
CREATE TABLE annha.cameras (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), home_id uuid NOT NULL REFERENCES annha.homes,
 room_id uuid NOT NULL, device_id uuid NOT NULL REFERENCES annha_private.device_registry,
 name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 120),
 capabilities jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(capabilities)='object'),
 observation text NOT NULL DEFAULT 'unknown' CHECK (observation IN ('unknown','clear','no_person','occluded','camera_error')),
 last_seen_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(), retired_at timestamptz,
 UNIQUE(home_id,id), UNIQUE(id,device_id),
 FOREIGN KEY(home_id,room_id) REFERENCES annha.rooms(home_id,id)
);
CREATE UNIQUE INDEX one_active_deployment ON annha.cameras(device_id) WHERE retired_at IS NULL;
CREATE INDEX camera_home_room ON annha.cameras(home_id,room_id);
CREATE TABLE annha_private.camera_grants (
 home_id uuid NOT NULL, camera_id uuid NOT NULL, user_id uuid NOT NULL,
 can_view boolean NOT NULL DEFAULT true, can_handle_events boolean NOT NULL DEFAULT false,
 can_play_audio boolean NOT NULL DEFAULT false, can_edit_reminders boolean NOT NULL DEFAULT false,
 PRIMARY KEY(home_id,camera_id,user_id),
 FOREIGN KEY(home_id,user_id) REFERENCES annha_private.home_memberships(home_id,user_id),
 FOREIGN KEY(home_id,camera_id) REFERENCES annha.cameras(home_id,id),
 CHECK (can_view OR NOT (can_handle_events OR can_play_audio OR can_edit_reminders))
);
CREATE INDEX camera_grant_user ON annha_private.camera_grants(user_id,home_id,camera_id);
CREATE TABLE annha_private.device_credentials (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), device_id uuid NOT NULL REFERENCES annha_private.device_registry,
 camera_id uuid, token_hash bytea NOT NULL UNIQUE CHECK (octet_length(token_hash)=32),
 created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz, revoked_at timestamptz, last_used_at timestamptz,
 FOREIGN KEY(camera_id,device_id) REFERENCES annha.cameras(id,device_id),
 CHECK (expires_at IS NULL OR expires_at>created_at)
);
CREATE INDEX credential_camera ON annha_private.device_credentials(camera_id) WHERE revoked_at IS NULL;
CREATE TABLE annha_private.pairing_codes (
 code_hash bytea PRIMARY KEY CHECK (octet_length(code_hash)=32), device_id uuid NOT NULL REFERENCES annha_private.device_registry,
 created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL,
 consumed_at timestamptz, claimed_camera_id uuid,
 FOREIGN KEY(claimed_camera_id,device_id) REFERENCES annha.cameras(id,device_id),
 CHECK (expires_at>created_at), CHECK ((consumed_at IS NULL)=(claimed_camera_id IS NULL))
);
CREATE TABLE annha_private.invitations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), home_id uuid NOT NULL REFERENCES annha.homes,
 email text NOT NULL CHECK (email=lower(btrim(email))), role text NOT NULL CHECK (role IN ('caregiver','viewer')),
 token_hash bytea NOT NULL UNIQUE CHECK (octet_length(token_hash)=32),
 invited_by uuid NOT NULL REFERENCES annha_private.users, accepted_by uuid REFERENCES annha_private.users,
 status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','accepted','declined','revoked','expired')),
 created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL, accepted_at timestamptz,
 UNIQUE(home_id,id), CHECK (expires_at>created_at),
 CHECK (status<>'accepted' OR (accepted_by IS NOT NULL AND accepted_at IS NOT NULL))
);
CREATE UNIQUE INDEX one_pending_invitation ON annha_private.invitations(home_id,email) WHERE status='pending';
CREATE TABLE annha_private.invitation_camera_grants (
 home_id uuid NOT NULL, invitation_id uuid NOT NULL, camera_id uuid NOT NULL,
 can_view boolean NOT NULL DEFAULT true, can_handle_events boolean NOT NULL DEFAULT false,
 can_play_audio boolean NOT NULL DEFAULT false, can_edit_reminders boolean NOT NULL DEFAULT false,
 PRIMARY KEY(invitation_id,camera_id),
 FOREIGN KEY(home_id,invitation_id) REFERENCES annha_private.invitations(home_id,id),
 FOREIGN KEY(home_id,camera_id) REFERENCES annha.cameras(home_id,id),
 CHECK (can_view OR NOT (can_handle_events OR can_play_audio OR can_edit_reminders))
);
CREATE TABLE annha.home_settings (
 home_id uuid PRIMARY KEY REFERENCES annha.homes,
 retention_days integer NOT NULL DEFAULT 14 CHECK (retention_days BETWEEN 1 AND 90),
 telemetry_retention_days integer NOT NULL DEFAULT 14 CHECK (telemetry_retention_days BETWEEN 1 AND 365),
 event_retention_days integer NOT NULL DEFAULT 365 CHECK (event_retention_days BETWEEN 1 AND 3650),
 temperature_low double precision NOT NULL DEFAULT 16 CHECK (temperature_low BETWEEN -20 AND 80),
 temperature_high double precision NOT NULL DEFAULT 35 CHECK (temperature_high BETWEEN -20 AND 80),
 humidity_high double precision NOT NULL DEFAULT 85 CHECK (humidity_high BETWEEN 0 AND 100),
 gas_high double precision NOT NULL DEFAULT 700 CHECK (gas_high>=0 AND gas_high<'Infinity'::float8),
 gas_unit text NOT NULL DEFAULT 'ADC' CHECK (gas_unit IN ('ADC','ppm')),
 environment_hold_seconds integer NOT NULL DEFAULT 10 CHECK (environment_hold_seconds BETWEEN 0 AND 3600),
 hysteresis double precision NOT NULL DEFAULT 2 CHECK (hysteresis BETWEEN 0 AND 100),
 updated_at timestamptz NOT NULL DEFAULT now(), CHECK (temperature_low<temperature_high)
);
CREATE TABLE annha.camera_configurations (
 home_id uuid NOT NULL, camera_id uuid NOT NULL, version integer NOT NULL CHECK (version>0),
 payload jsonb NOT NULL CHECK (jsonb_typeof(payload)='object'),
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(home_id,camera_id,version), FOREIGN KEY(home_id,camera_id) REFERENCES annha.cameras(home_id,id),
 CHECK (NOT payload ? 'zones' OR payload->'zones'='[]'::jsonb),
 CHECK (NOT payload ? 'reference' OR payload->'reference'='{}'::jsonb)
);
CREATE TABLE annha.camera_config_state (
 home_id uuid NOT NULL, camera_id uuid NOT NULL, desired_version integer NOT NULL,
 applied_version integer, error text, applied_at timestamptz,
 PRIMARY KEY(home_id,camera_id),
 FOREIGN KEY(home_id,camera_id,desired_version) REFERENCES annha.camera_configurations DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(home_id,camera_id,applied_version) REFERENCES annha.camera_configurations DEFERRABLE INITIALLY DEFERRED,
 CHECK (applied_version IS NULL OR applied_version<=desired_version)
);
CREATE TABLE annha.config_acknowledgements (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), home_id uuid NOT NULL, camera_id uuid NOT NULL,
 message_id text NOT NULL, version integer NOT NULL, success boolean NOT NULL, error text,
 received_at timestamptz NOT NULL DEFAULT now(), UNIQUE(camera_id,message_id),
 FOREIGN KEY(home_id,camera_id,version) REFERENCES annha.camera_configurations
);
CREATE TABLE annha.events (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), home_id uuid NOT NULL, camera_id uuid NOT NULL,
 source_id text NOT NULL CHECK (length(source_id) BETWEEN 1 AND 128),
 latest_sequence bigint NOT NULL DEFAULT 1 CHECK (latest_sequence>0),
 kind text NOT NULL CHECK (kind IN ('fall','immobility','environment','device')),
 severity text NOT NULL CHECK (severity IN ('info','warning','critical')),
 observation text NOT NULL CHECK (observation IN ('suspected','abnormal','recovered','unknown')),
 status text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','ACKNOWLEDGED','RESOLVED','FALSE_ALARM')),
 first_observed_at timestamptz NOT NULL, last_observed_at timestamptz NOT NULL,
 received_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 expires_at timestamptz, reason text NOT NULL DEFAULT '', duration_s double precision CHECK (duration_s BETWEEN 0 AND 604800),
 model_score double precision CHECK (model_score BETWEEN 0 AND 1), config_version integer,
 UNIQUE(camera_id,source_id), UNIQUE(home_id,camera_id,id), UNIQUE(home_id,id),
 FOREIGN KEY(home_id,camera_id) REFERENCES annha.cameras(home_id,id),
 FOREIGN KEY(home_id,camera_id,config_version) REFERENCES annha.camera_configurations
);
CREATE INDEX event_home_feed ON annha.events(home_id,received_at DESC,id);
CREATE INDEX event_open ON annha.events(home_id,status,received_at DESC) WHERE status IN ('OPEN','ACKNOWLEDGED');
CREATE INDEX event_camera_time ON annha.events(camera_id,first_observed_at DESC);
CREATE TABLE annha.event_updates (
 home_id uuid NOT NULL, camera_id uuid NOT NULL, event_id uuid NOT NULL, sequence bigint NOT NULL CHECK (sequence>0),
 observed_at timestamptz NOT NULL, received_at timestamptz NOT NULL DEFAULT now(),
 observation text NOT NULL CHECK (observation IN ('suspected','abnormal','recovered','unknown')),
 severity text NOT NULL CHECK (severity IN ('info','warning','critical')),
 payload jsonb NOT NULL CHECK (jsonb_typeof(payload)='object'),
 PRIMARY KEY(event_id,sequence), FOREIGN KEY(home_id,camera_id,event_id) REFERENCES annha.events(home_id,camera_id,id)
);
CREATE TABLE annha.event_actions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), home_id uuid NOT NULL, camera_id uuid NOT NULL, event_id uuid NOT NULL,
 user_id uuid NOT NULL REFERENCES annha_private.users,
 action text NOT NULL CHECK (action IN ('acknowledge','resolve','safe','false_alarm','note','silence')),
 note text NOT NULL DEFAULT '' CHECK (length(note)<=2000),
 confirmed_abnormal boolean NOT NULL DEFAULT false, silence_until timestamptz,
 request_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(user_id,request_id), FOREIGN KEY(home_id,camera_id,event_id) REFERENCES annha.events(home_id,camera_id,id),
 CHECK (action<>'silence' OR silence_until IS NOT NULL)
);
CREATE INDEX event_action_history ON annha.event_actions(event_id,created_at,id);
CREATE TABLE annha.telemetry_batches (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), home_id uuid NOT NULL, camera_id uuid NOT NULL,
 message_id text NOT NULL CHECK (length(message_id) BETWEEN 1 AND 128),
 observed_at timestamptz NOT NULL, received_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(camera_id,message_id), UNIQUE(home_id,camera_id,id),
 FOREIGN KEY(home_id,camera_id) REFERENCES annha.cameras(home_id,id)
);
CREATE INDEX telemetry_camera_time ON annha.telemetry_batches(camera_id,observed_at DESC);
CREATE INDEX telemetry_received_brin ON annha.telemetry_batches USING brin(received_at);
CREATE TABLE annha.sensor_readings (
 home_id uuid NOT NULL, camera_id uuid NOT NULL, batch_id uuid NOT NULL,
 metric text NOT NULL CHECK (metric IN ('temperature','humidity','gas','light')),
 value double precision, unit text NOT NULL,
 quality text NOT NULL CHECK (quality IN ('valid','error','warming_up')),
 PRIMARY KEY(batch_id,metric), FOREIGN KEY(home_id,camera_id,batch_id) REFERENCES annha.telemetry_batches(home_id,camera_id,id) ON DELETE CASCADE,
 CHECK (quality<>'valid' OR value IS NOT NULL),
 CHECK (value IS NULL OR (value>'-Infinity'::float8 AND value<'Infinity'::float8)),
 CHECK ((metric='temperature' AND unit='C') OR (metric='humidity' AND unit='%') OR (metric='gas' AND unit IN ('ADC','ppm')) OR (metric='light' AND unit='lux'))
);
CREATE TABLE annha.monitor_states (
 home_id uuid NOT NULL, camera_id uuid NOT NULL, monitor_key text NOT NULL,
 active boolean NOT NULL DEFAULT false, since_at timestamptz, event_id uuid,
 state jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(state)='object'), updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(camera_id,monitor_key), FOREIGN KEY(home_id,camera_id) REFERENCES annha.cameras(home_id,id),
 FOREIGN KEY(home_id,camera_id,event_id) REFERENCES annha.events(home_id,camera_id,id)
);
CREATE TABLE annha.home_storage (
 home_id uuid PRIMARY KEY REFERENCES annha.homes,
 quota_bytes bigint NOT NULL DEFAULT 536870912 CHECK (quota_bytes>0),
 used_bytes bigint NOT NULL DEFAULT 0 CHECK (used_bytes>=0),
 reserved_bytes bigint NOT NULL DEFAULT 0 CHECK (reserved_bytes>=0),
 updated_at timestamptz NOT NULL DEFAULT now(), CHECK (used_bytes+reserved_bytes<=quota_bytes)
);
CREATE TABLE annha.media_assets (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), home_id uuid NOT NULL, camera_id uuid NOT NULL, event_id uuid,
 kind text NOT NULL CHECK (kind IN ('snapshot','event_image','event_clip','audio','tts')),
 name text NOT NULL CHECK (length(name) BETWEEN 1 AND 160),
 mime_type text NOT NULL CHECK (mime_type IN ('image/jpeg','image/png','video/mp4','video/webm','audio/webm','audio/mpeg','audio/wav','audio/ogg')),
 size_bytes bigint CHECK (size_bytes BETWEEN 0 AND 26214400), reserved_bytes bigint NOT NULL DEFAULT 0 CHECK (reserved_bytes BETWEEN 0 AND 26214400),
 status text NOT NULL DEFAULT 'uploading' CHECK (status IN ('uploading','processing','ready','failed','deleting','deleted','expired')),
 provider text NOT NULL DEFAULT 'cloudinary' CHECK (provider IN ('cloudinary','local')),
 provider_environment text, provider_asset_id text, public_id text, resource_type text CHECK (resource_type IN ('image','video','raw')),
 delivery_type text CHECK (delivery_type='authenticated'), provider_version bigint,
 local_object_key text, sha256 bytea CHECK (sha256 IS NULL OR octet_length(sha256)=32),
 width integer CHECK (width>0), height integer CHECK (height>0), duration_s double precision CHECK (duration_s>=0 AND duration_s<'Infinity'::float8),
 captured_from timestamptz, captured_to timestamptz,
 upload_key text NOT NULL, created_by uuid REFERENCES annha_private.users,
 created_at timestamptz NOT NULL DEFAULT now(), ready_at timestamptz, expires_at timestamptz,
 deletion_requested_at timestamptz, deleted_at timestamptz, error_code text,
 UNIQUE(home_id,camera_id,id), UNIQUE(camera_id,upload_key), UNIQUE(provider,provider_environment,provider_asset_id), UNIQUE(provider,provider_environment,public_id,resource_type,delivery_type),
 FOREIGN KEY(home_id,camera_id) REFERENCES annha.cameras(home_id,id),
 FOREIGN KEY(home_id,camera_id,event_id) REFERENCES annha.events(home_id,camera_id,id),
 CHECK (kind NOT IN ('event_image','event_clip') OR event_id IS NOT NULL),
 CHECK (kind NOT IN ('audio','tts','snapshot') OR event_id IS NULL),
 CHECK ((kind IN ('audio','tts') AND mime_type LIKE 'audio/%') OR (kind IN ('snapshot','event_image') AND mime_type LIKE 'image/%') OR (kind='event_clip' AND mime_type LIKE 'video/%')),
 CHECK (status<>'ready' OR (size_bytes IS NOT NULL AND ready_at IS NOT NULL AND
   ((provider='cloudinary' AND provider_environment IS NOT NULL AND provider_asset_id IS NOT NULL AND public_id IS NOT NULL AND resource_type IS NOT NULL AND delivery_type IS NOT DISTINCT FROM 'authenticated' AND provider_version IS NOT NULL)
    OR (provider='local' AND local_object_key IS NOT NULL))))
);
CREATE INDEX media_event ON annha.media_assets(event_id,created_at);
CREATE INDEX media_home_status ON annha.media_assets(home_id,status,created_at DESC);
CREATE INDEX media_expiration ON annha.media_assets(expires_at) WHERE status='ready' AND expires_at IS NOT NULL;
CREATE TABLE annha.reminders (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), home_id uuid NOT NULL, camera_id uuid NOT NULL,
 name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 120),
 enabled boolean NOT NULL DEFAULT true, current_version integer NOT NULL CHECK (current_version>0),
 created_by uuid NOT NULL REFERENCES annha_private.users,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), deleted_at timestamptz,
 UNIQUE(home_id,camera_id,id), FOREIGN KEY(home_id,camera_id) REFERENCES annha.cameras(home_id,id)
);
CREATE TABLE annha.reminder_revisions (
 home_id uuid NOT NULL, camera_id uuid NOT NULL, reminder_id uuid NOT NULL, version integer NOT NULL CHECK (version>0),
 local_time time NOT NULL, timezone text NOT NULL DEFAULT 'Asia/Ho_Chi_Minh',
 weekdays smallint[] NOT NULL DEFAULT ARRAY[0,1,2,3,4,5,6]::smallint[], once_date date,
 source text NOT NULL CHECK (source IN ('tts','audio')), text_content text, asset_id uuid,
 volume smallint NOT NULL DEFAULT 70 CHECK (volume BETWEEN 0 AND 100), late_seconds integer NOT NULL DEFAULT 0 CHECK (late_seconds BETWEEN 0 AND 3600),
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(home_id,camera_id,reminder_id,version),
 FOREIGN KEY(home_id,camera_id,reminder_id) REFERENCES annha.reminders(home_id,camera_id,id),
 FOREIGN KEY(home_id,camera_id,asset_id) REFERENCES annha.media_assets(home_id,camera_id,id),
 CHECK (weekdays <@ ARRAY[0,1,2,3,4,5,6]::smallint[]), CHECK (array_position(weekdays,NULL) IS NULL),
 CHECK ((once_date IS NOT NULL AND cardinality(weekdays)=0) OR (once_date IS NULL AND cardinality(weekdays) BETWEEN 1 AND 7)),
 CHECK ((source='tts' AND text_content IS NOT NULL AND length(btrim(text_content)) BETWEEN 1 AND 3000) OR (source='audio' AND asset_id IS NOT NULL))
);
ALTER TABLE annha.reminders ADD CONSTRAINT reminder_current_revision FOREIGN KEY(home_id,camera_id,id,current_version)
 REFERENCES annha.reminder_revisions(home_id,camera_id,reminder_id,version) DEFERRABLE INITIALLY DEFERRED;
CREATE TABLE annha.reminder_executions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), home_id uuid NOT NULL, camera_id uuid NOT NULL,
 reminder_id uuid NOT NULL, reminder_version integer NOT NULL, occurrence_key text NOT NULL,
 scheduled_at timestamptz NOT NULL, executed_at timestamptz, received_at timestamptz NOT NULL DEFAULT now(),
 status text NOT NULL CHECK (status IN ('played','failed','skipped')), detail text NOT NULL DEFAULT '',
 UNIQUE(camera_id,reminder_id,occurrence_key),
 FOREIGN KEY(home_id,camera_id,reminder_id,reminder_version) REFERENCES annha.reminder_revisions(home_id,camera_id,reminder_id,version)
);
CREATE INDEX execution_camera_time ON annha.reminder_executions(camera_id,scheduled_at DESC);
CREATE TABLE annha.commands (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), home_id uuid NOT NULL, camera_id uuid NOT NULL,
 requested_by uuid NOT NULL REFERENCES annha_private.users, idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 8 AND 128),
 kind text NOT NULL CHECK (kind IN ('play_audio','test_speaker','silence')), asset_id uuid,
 payload jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(payload)='object'),
 status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','accepted','executing','executed','failed','expired')),
 created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL,
 accepted_at timestamptz, completed_at timestamptz, result jsonb,
 UNIQUE(requested_by,idempotency_key),
 FOREIGN KEY(home_id,camera_id) REFERENCES annha.cameras(home_id,id),
 FOREIGN KEY(home_id,camera_id,asset_id) REFERENCES annha.media_assets(home_id,camera_id,id),
 CHECK (expires_at>created_at AND expires_at<=created_at+interval '5 minutes'),
 CHECK (kind<>'play_audio' OR asset_id IS NOT NULL)
);
CREATE INDEX command_pending ON annha.commands(camera_id,expires_at) WHERE status IN ('pending','accepted');
CREATE TABLE annha.notification_channels (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), home_id uuid NOT NULL, recipient_user_id uuid NOT NULL,
 kind text NOT NULL DEFAULT 'telegram' CHECK (kind='telegram'), label text NOT NULL,
 enabled boolean NOT NULL DEFAULT false, allow_media boolean NOT NULL DEFAULT false,
 media_consent_at timestamptz, consent_by uuid REFERENCES annha_private.users,
 created_at timestamptz NOT NULL DEFAULT now(), revoked_at timestamptz, UNIQUE(home_id,id),
 FOREIGN KEY(home_id,recipient_user_id) REFERENCES annha_private.home_memberships(home_id,user_id),
 CHECK (NOT allow_media OR (media_consent_at IS NOT NULL AND consent_by IS NOT NULL))
);
CREATE TABLE annha_private.notification_secrets (
 home_id uuid NOT NULL, channel_id uuid PRIMARY KEY, destination_ciphertext bytea NOT NULL, key_id text NOT NULL,
 FOREIGN KEY(home_id,channel_id) REFERENCES annha.notification_channels(home_id,id)
);
CREATE TABLE annha.notification_deliveries (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), home_id uuid NOT NULL, camera_id uuid NOT NULL, event_id uuid NOT NULL,
 channel_id uuid NOT NULL, generation integer NOT NULL DEFAULT 1 CHECK (generation>0),
 status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','sending','sent','failed','cancelled')),
 attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count>=0), sent_count integer NOT NULL DEFAULT 0 CHECK (sent_count>=0),
 next_attempt_at timestamptz NOT NULL DEFAULT now(), last_error_code text, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(event_id,channel_id,generation),
 FOREIGN KEY(home_id,camera_id,event_id) REFERENCES annha.events(home_id,camera_id,id),
 FOREIGN KEY(home_id,channel_id) REFERENCES annha.notification_channels(home_id,id)
);
CREATE TABLE annha.delivery_attempts (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), home_id uuid NOT NULL, delivery_id uuid NOT NULL REFERENCES annha.notification_deliveries,
 attempt integer NOT NULL CHECK (attempt>0), status text NOT NULL CHECK (status IN ('sent','failed','unknown')),
 provider_message_id text, error_code text, created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(delivery_id,attempt)
);
ALTER TABLE annha.notification_deliveries ADD CONSTRAINT delivery_home_id_unique UNIQUE(home_id,id);
ALTER TABLE annha.delivery_attempts DROP CONSTRAINT delivery_attempts_delivery_id_fkey;
ALTER TABLE annha.delivery_attempts ADD FOREIGN KEY(home_id,delivery_id) REFERENCES annha.notification_deliveries(home_id,id);
CREATE TABLE annha.live_sessions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), home_id uuid NOT NULL, camera_id uuid NOT NULL,
 user_id uuid NOT NULL REFERENCES annha_private.users,
 kind text NOT NULL CHECK (kind IN ('video','push_to_talk')),
 created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL, closed_at timestamptz, close_reason text,
 FOREIGN KEY(home_id,camera_id) REFERENCES annha.cameras(home_id,id),
 CHECK (expires_at>created_at), CHECK (kind<>'push_to_talk' OR expires_at<=created_at+interval '60 seconds')
);
CREATE TABLE annha.audit_logs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), home_id uuid NOT NULL REFERENCES annha.homes,
 actor_type text NOT NULL CHECK (actor_type IN ('user','device','system')),
 user_id uuid REFERENCES annha_private.users, camera_id uuid,
 action text NOT NULL, target_type text NOT NULL, target_id uuid,
 request_id uuid, details jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(details)='object'),
 created_at timestamptz NOT NULL DEFAULT now(), FOREIGN KEY(home_id,camera_id) REFERENCES annha.cameras(home_id,id),
 CHECK ((actor_type='user' AND user_id IS NOT NULL) OR (actor_type='device' AND camera_id IS NOT NULL) OR actor_type='system')
);
CREATE INDEX audit_home_time ON annha.audit_logs(home_id,created_at DESC);
-- Global trusted queues are NOT exposed to end users/devices.
CREATE TABLE annha_private.job_queue (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), home_id uuid REFERENCES annha.homes,
 kind text NOT NULL CHECK (kind IN ('email','tts','upload','delete_media','notify','retention','compile_config')),
 asset_id uuid, payload jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(payload)='object'),
 secret_ciphertext bytea, key_id text, idempotency_key text NOT NULL UNIQUE,
 status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','running','done','failed','cancelled')),
 attempts integer NOT NULL DEFAULT 0 CHECK (attempts>=0), available_at timestamptz NOT NULL DEFAULT now(),
 lease_owner uuid, lease_until timestamptz, last_error_code text,
 created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz,
 CHECK ((secret_ciphertext IS NULL)=(key_id IS NULL)),
 CHECK (asset_id IS NULL OR home_id IS NOT NULL),
 CHECK (kind NOT IN ('upload','delete_media','tts') OR (home_id IS NOT NULL AND asset_id IS NOT NULL))
);
ALTER TABLE annha.media_assets ADD CONSTRAINT asset_home_id_unique UNIQUE(home_id,id);
ALTER TABLE annha_private.job_queue ADD FOREIGN KEY(home_id,asset_id) REFERENCES annha.media_assets(home_id,id);
CREATE INDEX jobs_claim ON annha_private.job_queue(available_at,id) WHERE status IN ('pending','running');
CREATE TABLE annha_private.legacy_records (
 source_table text NOT NULL, source_key text NOT NULL, home_id uuid REFERENCES annha.homes,
 payload jsonb NOT NULL, imported_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(source_table,source_key)
);
-- Validation not expressible as a simple CHECK; no extensions required.
CREATE FUNCTION annha_private.valid_schedule() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_timezone_names WHERE name=NEW.timezone) THEN
  RAISE EXCEPTION 'Unknown IANA timezone' USING ERRCODE='23514';
 END IF;
 IF TG_TABLE_NAME='reminder_revisions' THEN
  IF cardinality(NEW.weekdays)<>(SELECT count(DISTINCT x) FROM unnest(NEW.weekdays) x) THEN
   RAISE EXCEPTION 'Duplicate weekday' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER home_timezone BEFORE INSERT OR UPDATE ON annha.homes FOR EACH ROW EXECUTE FUNCTION annha_private.valid_schedule();
CREATE TRIGGER reminder_timezone BEFORE INSERT OR UPDATE ON annha.reminder_revisions FOR EACH ROW EXECUTE FUNCTION annha_private.valid_schedule();
CREATE FUNCTION annha_private.require_home_owner() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE target uuid;
BEGIN
 IF TG_TABLE_NAME='homes' THEN target=NEW.id;
 ELSE target=COALESCE(NEW.home_id,OLD.home_id); END IF;
 IF EXISTS(SELECT 1 FROM annha.homes WHERE id=target) AND
    (SELECT count(*) FROM annha_private.home_memberships WHERE home_id=target AND role='owner' AND revoked_at IS NULL)<>1 THEN
  RAISE EXCEPTION 'Home must retain exactly one active owner' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER home_requires_owner AFTER INSERT ON annha.homes DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION annha_private.require_home_owner();
CREATE CONSTRAINT TRIGGER membership_requires_owner AFTER INSERT OR UPDATE OR DELETE ON annha_private.home_memberships DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION annha_private.require_home_owner();
CREATE FUNCTION annha_private.require_audio_asset() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE asset_kind text;
BEGIN
 IF NEW.asset_id IS NOT NULL THEN
  SELECT kind INTO asset_kind FROM annha.media_assets WHERE id=NEW.asset_id AND home_id=NEW.home_id AND camera_id=NEW.camera_id;
  IF FOUND AND asset_kind NOT IN ('audio','tts') THEN
   RAISE EXCEPTION 'An audio asset is required' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER reminder_audio_asset BEFORE INSERT OR UPDATE ON annha.reminder_revisions FOR EACH ROW EXECUTE FUNCTION annha_private.require_audio_asset();
CREATE TRIGGER command_audio_asset BEFORE INSERT OR UPDATE ON annha.commands FOR EACH ROW EXECUTE FUNCTION annha_private.require_audio_asset();
CREATE FUNCTION annha_private.immutable_keys() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE key text;
BEGIN
 FOREACH key IN ARRAY TG_ARGV LOOP
  IF to_jsonb(NEW)->key IS DISTINCT FROM to_jsonb(OLD)->key THEN
   RAISE EXCEPTION 'Immutable key: %',key USING ERRCODE='23514';
  END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER membership_identity_immutable BEFORE UPDATE ON annha_private.home_memberships FOR EACH ROW EXECUTE FUNCTION annha_private.immutable_keys('home_id','user_id');
CREATE TRIGGER camera_deployment_immutable BEFORE UPDATE ON annha.cameras FOR EACH ROW EXECUTE FUNCTION annha_private.immutable_keys('id','home_id','device_id');
CREATE TRIGGER event_identity_immutable BEFORE UPDATE ON annha.events FOR EACH ROW EXECUTE FUNCTION annha_private.immutable_keys('id','home_id','camera_id','source_id','kind');
CREATE TRIGGER asset_identity_immutable BEFORE UPDATE ON annha.media_assets FOR EACH ROW EXECUTE FUNCTION annha_private.immutable_keys('id','home_id','camera_id','event_id','kind');
CREATE TRIGGER reminder_identity_immutable BEFORE UPDATE ON annha.reminders FOR EACH ROW EXECUTE FUNCTION annha_private.immutable_keys('id','home_id','camera_id','created_by');
CREATE TRIGGER command_identity_immutable BEFORE UPDATE ON annha.commands FOR EACH ROW EXECUTE FUNCTION annha_private.immutable_keys('id','home_id','camera_id','requested_by','idempotency_key','kind','expires_at');
COMMIT;
