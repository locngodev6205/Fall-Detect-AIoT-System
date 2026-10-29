-- Run ONLY in an isolated test database after 001 + 002. All fixture data rolls back.
\set ON_ERROR_STOP on
BEGIN;
CREATE FUNCTION pg_temp.assert_true(ok boolean, label text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN IF ok IS DISTINCT FROM true THEN RAISE EXCEPTION 'FAIL: %',label; END IF; END $$;
CREATE FUNCTION pg_temp.expect_error(statement text, expected_state text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE actual text;
BEGIN
 BEGIN EXECUTE statement;
 EXCEPTION WHEN OTHERS THEN
  GET STACKED DIAGNOSTICS actual=RETURNED_SQLSTATE;
  IF actual<>expected_state THEN RAISE EXCEPTION 'Expected %, got %: %',expected_state,actual,SQLERRM; END IF;
  RETURN;
 END;
 RAISE EXCEPTION 'Expected SQLSTATE %, statement succeeded: %',expected_state,statement;
END $$;
-- Fixed, synthetic IDs; no real accounts, camera, network, mail or media upload.
INSERT INTO annha_private.users(id,email,name,password_hash) VALUES
 ('10000000-0000-0000-0000-000000000001','owner-a@example.test','Owner A','fixture-not-a-password'),
 ('10000000-0000-0000-0000-000000000002','owner-b@example.test','Owner B','fixture-not-a-password'),
 ('10000000-0000-0000-0000-000000000003','viewer@example.test','Viewer','fixture-not-a-password'),
 ('10000000-0000-0000-0000-000000000004','caregiver@example.test','Caregiver','fixture-not-a-password');
INSERT INTO annha.homes(id,name,created_by) VALUES
 ('20000000-0000-0000-0000-000000000001','Home A','10000000-0000-0000-0000-000000000001'),
 ('20000000-0000-0000-0000-000000000002','Home B','10000000-0000-0000-0000-000000000002');
INSERT INTO annha_private.home_memberships(home_id,user_id,role) VALUES
 ('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','owner'),
 ('20000000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000002','owner'),
 ('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000003','viewer'),
 ('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000004','caregiver');
INSERT INTO annha.rooms(id,home_id,name) VALUES
 ('30000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','Room A'),
 ('30000000-0000-0000-0000-000000000002','20000000-0000-0000-0000-000000000002','Room B');
INSERT INTO annha_private.device_registry(id) SELECT ('40000000-0000-0000-0000-'||lpad(i::text,12,'0'))::uuid FROM generate_series(1,3) i;
INSERT INTO annha.cameras(id,home_id,room_id,device_id,name) VALUES
 ('50000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000001','40000000-0000-0000-0000-000000000001','A1'),
 ('50000000-0000-0000-0000-000000000002','20000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000001','40000000-0000-0000-0000-000000000002','A2'),
 ('50000000-0000-0000-0000-000000000003','20000000-0000-0000-0000-000000000002','30000000-0000-0000-0000-000000000002','40000000-0000-0000-0000-000000000003','B1');
INSERT INTO annha_private.camera_grants(home_id,camera_id,user_id,can_handle_events,can_play_audio,can_edit_reminders) VALUES
 ('20000000-0000-0000-0000-000000000001','50000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000003',true,true,true), -- viewer must still NOT control
 ('20000000-0000-0000-0000-000000000001','50000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000004',false,true,true);
INSERT INTO annha.events(id,home_id,camera_id,source_id,kind,severity,observation,first_observed_at,last_observed_at)
 SELECT ('60000000-0000-0000-0000-'||right(id::text,12))::uuid,home_id,id,'edge-event-1','fall','critical','abnormal',now(),now() FROM annha.cameras;
INSERT INTO annha.media_assets(id,home_id,camera_id,event_id,kind,name,mime_type,upload_key)
 SELECT ('80000000-0000-0000-0000-'||right(camera_id::text,12))::uuid,home_id,camera_id,id,'event_image','Evidence','image/jpeg','image-1' FROM annha.events;
INSERT INTO annha.home_storage(home_id) SELECT id FROM annha.homes;
INSERT INTO annha.camera_configurations(home_id,camera_id,version,payload) SELECT home_id,id,1,'{"zones":[],"reference":{}}' FROM annha.cameras;
SET CONSTRAINTS ALL IMMEDIATE;
SELECT pg_temp.assert_true((SELECT bool_and(c.relrowsecurity AND c.relforcerowsecurity) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='annha' AND c.relkind='r'),'RLS forced on all business tables');
SELECT pg_temp.assert_true(NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname IN ('annha_app','annha_device','annha_worker','annha_auth') AND (rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolcanlogin)),'runtime groups have no elevated privileges/logins');
SELECT pg_temp.expect_error($q$UPDATE annha_private.home_memberships SET revoked_at=now() WHERE home_id='20000000-0000-0000-0000-000000000001' AND role='owner'$q$,'23514');
SELECT pg_temp.expect_error($q$UPDATE annha.cameras SET home_id='20000000-0000-0000-0000-000000000002' WHERE id='50000000-0000-0000-0000-000000000001'$q$,'23514');
SELECT pg_temp.expect_error($q$INSERT INTO annha.camera_configurations(home_id,camera_id,version,payload) VALUES('20000000-0000-0000-0000-000000000001','50000000-0000-0000-0000-000000000001',2,'{"zones":[{"id":"old-sofa"}]}')$q$,'23514');
SELECT pg_temp.expect_error($q$INSERT INTO annha.events(home_id,camera_id,source_id,kind,severity,observation,first_observed_at,last_observed_at) VALUES('20000000-0000-0000-0000-000000000001','50000000-0000-0000-0000-000000000001','edge-event-1','fall','critical','abnormal',now(),now())$q$,'23505');
SELECT pg_temp.expect_error($q$UPDATE annha.home_storage SET reserved_bytes=quota_bytes+1 WHERE home_id='20000000-0000-0000-0000-000000000001'$q$,'23514');
SELECT pg_temp.expect_error($q$UPDATE annha.media_assets SET status='ready',size_bytes=10,ready_at=now() WHERE id='80000000-0000-0000-0000-000000000001'$q$,'23514');
SELECT pg_temp.expect_error($q$UPDATE annha.media_assets SET status='ready',size_bytes=10,ready_at=now(),provider_environment='fixture',provider_asset_id='cloud-id',public_id='private-image',resource_type='image',provider_version=1,delivery_type=NULL WHERE id='80000000-0000-0000-0000-000000000001'$q$,'23514');
-- No tenant context = no data, even if a developer forgets a WHERE clause.
SET LOCAL ROLE annha_app;
SELECT pg_temp.assert_true((SELECT count(*)=0 FROM annha.cameras),'missing context defaults to deny');
SELECT set_config('app.home_id','20000000-0000-0000-0000-000000000001',true);
SELECT set_config('app.user_id','10000000-0000-0000-0000-000000000001',true);
SELECT pg_temp.assert_true((SELECT count(*)=2 FROM annha.cameras),'owner sees own cameras only');
SELECT pg_temp.assert_true((SELECT count(*)=2 FROM annha.events),'cross-home event isolation');
SELECT pg_temp.expect_error('SELECT * FROM annha_private.users','42501');
SELECT pg_temp.expect_error('SELECT * FROM annha_private.sessions','42501');
SELECT pg_temp.expect_error('SELECT * FROM annha_private.security_events','42501');
SELECT pg_temp.expect_error('SELECT * FROM annha_private.device_credentials','42501');
SELECT pg_temp.expect_error('SELECT * FROM annha_private.job_queue','42501');
SELECT pg_temp.expect_error('TRUNCATE annha.events','42501');
SELECT pg_temp.expect_error('ALTER TABLE annha.events DISABLE ROW LEVEL SECURITY','42501');
SELECT set_config('app.home_id','20000000-0000-0000-0000-000000000002',true);
SELECT pg_temp.assert_true((SELECT count(*)=0 FROM annha.cameras),'selecting another home cannot bypass membership');
SELECT set_config('app.home_id','20000000-0000-0000-0000-000000000001',true);
SELECT set_config('app.user_id','10000000-0000-0000-0000-000000000003',true);
SELECT pg_temp.assert_true((SELECT count(*)=1 FROM annha.cameras),'viewer camera scope');
SELECT pg_temp.assert_true((SELECT count(*)=1 FROM annha.media_assets),'viewer evidence scope');
SELECT pg_temp.assert_true(NOT annha_private.can_camera('20000000-0000-0000-0000-000000000001','50000000-0000-0000-0000-000000000001','audio'),'viewer cannot inherit stale control flags');
SELECT pg_temp.expect_error($q$INSERT INTO annha.commands(home_id,camera_id,requested_by,idempotency_key,kind,expires_at) VALUES('20000000-0000-0000-0000-000000000001','50000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000003','viewer-command','test_speaker',now()+interval '1 minute')$q$,'42501');
SELECT set_config('app.user_id','10000000-0000-0000-0000-000000000004',true);
INSERT INTO annha.commands(id,home_id,camera_id,requested_by,idempotency_key,kind,expires_at) VALUES('90000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','50000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000004','caregiver-command','test_speaker',now()+interval '1 minute');
SELECT pg_temp.expect_error($q$INSERT INTO annha.commands(home_id,camera_id,requested_by,idempotency_key,kind,expires_at) VALUES('20000000-0000-0000-0000-000000000001','50000000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000004','out-of-scope-command','test_speaker',now()+interval '1 minute')$q$,'42501');
SET CONSTRAINTS annha.reminder_current_revision DEFERRED;
INSERT INTO annha.reminders(id,home_id,camera_id,name,current_version,created_by) VALUES('a0000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','50000000-0000-0000-0000-000000000001','Breakfast',1,'10000000-0000-0000-0000-000000000004');
SELECT pg_temp.expect_error($q$INSERT INTO annha.reminder_revisions(home_id,camera_id,reminder_id,version,local_time,source,text_content,weekdays) VALUES('20000000-0000-0000-0000-000000000001','50000000-0000-0000-0000-000000000001','a0000000-0000-0000-0000-000000000001',1,'07:00','tts','Breakfast',ARRAY[1,1]::smallint[])$q$,'23514');
SELECT pg_temp.expect_error($q$INSERT INTO annha.reminder_revisions(home_id,camera_id,reminder_id,version,local_time,source) VALUES('20000000-0000-0000-0000-000000000001','50000000-0000-0000-0000-000000000001','a0000000-0000-0000-0000-000000000001',1,'07:00','tts')$q$,'23514');
INSERT INTO annha.reminder_revisions(home_id,camera_id,reminder_id,version,local_time,source,text_content) VALUES('20000000-0000-0000-0000-000000000001','50000000-0000-0000-0000-000000000001','a0000000-0000-0000-0000-000000000001',1,'07:00','tts','Breakfast');
SET CONSTRAINTS annha.reminder_current_revision IMMEDIATE;
SELECT pg_temp.expect_error($q$INSERT INTO annha.event_actions(home_id,camera_id,event_id,user_id,action,request_id) VALUES('20000000-0000-0000-0000-000000000001','50000000-0000-0000-0000-000000000001','60000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000004','acknowledge',gen_random_uuid())$q$,'42501');
SELECT set_config('app.user_id','10000000-0000-0000-0000-000000000001',true);
UPDATE annha.reminders SET name='Owner edited schedule' WHERE id='a0000000-0000-0000-0000-000000000001';
SELECT pg_temp.assert_true((SELECT name='Owner edited schedule' FROM annha.reminders WHERE id='a0000000-0000-0000-0000-000000000001'),'owner can edit caregiver-created reminder');
INSERT INTO annha.event_actions(home_id,camera_id,event_id,user_id,action,request_id) VALUES('20000000-0000-0000-0000-000000000001','50000000-0000-0000-0000-000000000001','60000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','acknowledge',gen_random_uuid());
UPDATE annha.events SET status='ACKNOWLEDGED' WHERE id='60000000-0000-0000-0000-000000000001';
SELECT pg_temp.assert_true((SELECT status='ACKNOWLEDGED' AND observation='abnormal' FROM annha.events WHERE id='60000000-0000-0000-0000-000000000001'),'human handling separate from observation');
SELECT pg_temp.expect_error($q$UPDATE annha.event_actions SET note='rewrite history'$q$,'42501');
SELECT pg_temp.expect_error($q$UPDATE annha.events SET source_id='rewrite identity'$q$,'42501');
-- Revoke membership: subsequent queries in the same role/context lose access.
RESET ROLE;
UPDATE annha_private.home_memberships SET revoked_at=now(),version=version+1 WHERE home_id='20000000-0000-0000-0000-000000000001' AND user_id='10000000-0000-0000-0000-000000000003';
SET LOCAL ROLE annha_app;
SELECT set_config('app.user_id','10000000-0000-0000-0000-000000000003',true);
SELECT pg_temp.assert_true((SELECT count(*)=0 FROM annha.media_assets),'revoked member cannot read evidence');
-- A device cannot touch another camera in the same home.
RESET ROLE;
SET LOCAL ROLE annha_device;
SELECT set_config('app.camera_id','50000000-0000-0000-0000-000000000001',true);
SELECT pg_temp.assert_true((SELECT count(*)=1 FROM annha.media_assets),'device media scope');
SELECT pg_temp.expect_error($q$INSERT INTO annha.telemetry_batches(home_id,camera_id,message_id,observed_at) VALUES('20000000-0000-0000-0000-000000000001','50000000-0000-0000-0000-000000000002','forged-camera',now())$q$,'42501');
SELECT pg_temp.expect_error($q$INSERT INTO annha.events(home_id,camera_id,source_id,kind,severity,observation,first_observed_at,last_observed_at,status) VALUES('20000000-0000-0000-0000-000000000001','50000000-0000-0000-0000-000000000001','forged-status','fall','critical','abnormal',now(),now(),'RESOLVED')$q$,'42501');
INSERT INTO annha.telemetry_batches(id,home_id,camera_id,message_id,observed_at) VALUES('70000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','50000000-0000-0000-0000-000000000001','measurement-1',now());
SELECT pg_temp.expect_error($q$INSERT INTO annha.telemetry_batches(home_id,camera_id,message_id,observed_at) VALUES('20000000-0000-0000-0000-000000000001','50000000-0000-0000-0000-000000000001','measurement-1',now())$q$,'23505');
SELECT pg_temp.expect_error($q$INSERT INTO annha.sensor_readings(home_id,camera_id,batch_id,metric,value,unit,quality) VALUES('20000000-0000-0000-0000-000000000001','50000000-0000-0000-0000-000000000001','70000000-0000-0000-0000-000000000001','gas','NaN','ADC','valid')$q$,'23514');
INSERT INTO annha.sensor_readings(home_id,camera_id,batch_id,metric,value,unit,quality) VALUES('20000000-0000-0000-0000-000000000001','50000000-0000-0000-0000-000000000001','70000000-0000-0000-0000-000000000001','gas',NULL,'ADC','error');
SELECT pg_temp.expect_error($q$INSERT INTO annha.media_assets(home_id,camera_id,kind,name,mime_type,upload_key) VALUES('20000000-0000-0000-0000-000000000001','50000000-0000-0000-0000-000000000001','audio','Forged audio','audio/wav','forged-audio')$q$,'42501');
-- Even a trusted worker must choose one tenant and obey composite foreign keys.
RESET ROLE;
SET LOCAL ROLE annha_worker;
SELECT pg_temp.assert_true((SELECT count(*)=2 FROM annha.cameras),'worker tenant isolation');
SELECT pg_temp.expect_error($q$INSERT INTO annha.media_assets(home_id,camera_id,event_id,kind,name,mime_type,upload_key) VALUES('20000000-0000-0000-0000-000000000001','50000000-0000-0000-0000-000000000001','60000000-0000-0000-0000-000000000003','event_image','Cross-home event','image/jpeg','foreign-event')$q$,'23503');
SELECT pg_temp.expect_error($q$INSERT INTO annha.commands(home_id,camera_id,requested_by,idempotency_key,kind,expires_at,asset_id) VALUES('20000000-0000-0000-0000-000000000001','50000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','image-not-audio','play_audio',now()+interval '1 minute','80000000-0000-0000-0000-000000000001')$q$,'23514');
SELECT pg_temp.expect_error($q$INSERT INTO annha.commands(home_id,camera_id,requested_by,idempotency_key,kind,expires_at,asset_id) VALUES('20000000-0000-0000-0000-000000000001','50000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','foreign-asset','play_audio',now()+interval '1 minute','80000000-0000-0000-0000-000000000003')$q$,'23503');
SELECT pg_temp.expect_error($q$UPDATE annha.camera_configurations SET payload='{}'$q$,'42501');
SELECT pg_temp.expect_error($q$DELETE FROM annha.audit_logs$q$,'42501');
SELECT set_config('app.home_id','',true);
SELECT pg_temp.assert_true((SELECT count(*)=0 FROM annha.events),'cleared context denies worker tenant reads');
RESET ROLE;
ROLLBACK;
\echo 'PASS: schema invariants, tenant/camera RLS, viewer/caregiver controls, revocation, token secrecy, device isolation, idempotency, media constraints, quota and immutable history.'
