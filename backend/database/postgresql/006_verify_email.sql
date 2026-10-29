-- Synthetic fixtures only. Requires baseline + 005. All rows roll back.
\set ON_ERROR_STOP on
BEGIN;
CREATE FUNCTION pg_temp.assert_true(ok boolean,label text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN IF ok IS DISTINCT FROM true THEN RAISE EXCEPTION 'FAIL: %',label; END IF; END $$;
CREATE FUNCTION pg_temp.expect_error(statement text,expected_state text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE actual text;
BEGIN
 BEGIN EXECUTE statement;
 EXCEPTION WHEN OTHERS THEN
  GET STACKED DIAGNOSTICS actual=RETURNED_SQLSTATE;
  IF actual<>expected_state THEN RAISE EXCEPTION 'Expected %, got %: %',expected_state,actual,SQLERRM; END IF;
  RETURN;
 END;
 RAISE EXCEPTION 'Expected SQLSTATE %, statement succeeded',expected_state;
END $$;
INSERT INTO annha_private.users(id,email,name,password_hash,email_verified_at) VALUES
 ('10000000-0000-0000-0000-000000000001','owner-a@example.test','Owner A','fixture',now()),
 ('10000000-0000-0000-0000-000000000002','owner-b@example.test','Owner B','fixture',now()),
 ('10000000-0000-0000-0000-000000000003','viewer@example.test','Viewer','fixture',NULL);
INSERT INTO annha.homes(id,name,created_by) VALUES
 ('20000000-0000-0000-0000-000000000001','Home A','10000000-0000-0000-0000-000000000001'),
 ('20000000-0000-0000-0000-000000000002','Home B','10000000-0000-0000-0000-000000000002');
INSERT INTO annha_private.home_memberships(home_id,user_id,role) VALUES
 ('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','owner'),
 ('20000000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000002','owner'),
 ('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000003','viewer');
INSERT INTO annha.rooms(id,home_id,name) VALUES
 ('30000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','Room A'),
 ('30000000-0000-0000-0000-000000000002','20000000-0000-0000-0000-000000000002','Room B');
INSERT INTO annha_private.device_registry(id) SELECT ('40000000-0000-0000-0000-'||lpad(i::text,12,'0'))::uuid FROM generate_series(1,3) i;
INSERT INTO annha.cameras(id,home_id,room_id,device_id,name) VALUES
 ('50000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000001','40000000-0000-0000-0000-000000000001','A1'),
 ('50000000-0000-0000-0000-000000000002','20000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000001','40000000-0000-0000-0000-000000000002','A2'),
 ('50000000-0000-0000-0000-000000000003','20000000-0000-0000-0000-000000000002','30000000-0000-0000-0000-000000000002','40000000-0000-0000-0000-000000000003','B1');
INSERT INTO annha_private.camera_grants(home_id,camera_id,user_id) VALUES ('20000000-0000-0000-0000-000000000001','50000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000003');
INSERT INTO annha.events(id,home_id,camera_id,source_id,kind,severity,observation,first_observed_at,last_observed_at)
 SELECT ('60000000-0000-0000-0000-'||right(id::text,12))::uuid,home_id,id,'edge-event-1','fall','critical','abnormal',now(),now() FROM annha.cameras;
SET CONSTRAINTS ALL IMMEDIATE;
SELECT set_config('app.home_id','20000000-0000-0000-0000-000000000001',true);
SELECT set_config('app.user_id','10000000-0000-0000-0000-000000000001',true);
SET LOCAL ROLE annha_app;
SELECT pg_temp.expect_error($q$INSERT INTO annha.notification_channels(home_id,recipient_user_id,kind,label,enabled,email_version) VALUES('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000003','email','Unverified viewer',true,1)$q$,'23514');
INSERT INTO annha.notification_channels(id,home_id,recipient_user_id,kind,label,enabled,email_version) VALUES
 ('70000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','email','Owner email',true,1),
 ('70000000-0000-0000-0000-000000000002','20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','telegram','Owner Telegram',true,NULL);
SELECT pg_temp.expect_error($q$INSERT INTO annha.notification_channels(home_id,recipient_user_id,kind,label,email_version) VALUES('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','email','Duplicate email',1)$q$,'23505');
SELECT pg_temp.expect_error($q$UPDATE annha.notification_channels SET recipient_user_id='10000000-0000-0000-0000-000000000003' WHERE id='70000000-0000-0000-0000-000000000001'$q$,'42501');
SELECT pg_temp.expect_error($q$UPDATE annha.notification_channels SET suppressed_at=NULL WHERE id='70000000-0000-0000-0000-000000000001'$q$,'42501');
SELECT pg_temp.expect_error($q$INSERT INTO annha.notification_channels(home_id,recipient_user_id,kind,label,enabled,email_version) VALUES('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','email','Stale',true,99)$q$,'23514');
RESET ROLE;
INSERT INTO annha.notification_channels(id,home_id,recipient_user_id,kind,label,enabled,email_version) VALUES
 ('70000000-0000-0000-0000-000000000003','20000000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000002','email','Other home',true,1);
INSERT INTO annha.notification_deliveries(id,home_id,camera_id,event_id,channel_id) VALUES
 ('80000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','50000000-0000-0000-0000-000000000001','60000000-0000-0000-0000-000000000001','70000000-0000-0000-0000-000000000001'),
 ('80000000-0000-0000-0000-000000000002','20000000-0000-0000-0000-000000000001','50000000-0000-0000-0000-000000000001','60000000-0000-0000-0000-000000000001','70000000-0000-0000-0000-000000000002'),
 ('80000000-0000-0000-0000-000000000003','20000000-0000-0000-0000-000000000002','50000000-0000-0000-0000-000000000003','60000000-0000-0000-0000-000000000003','70000000-0000-0000-0000-000000000003');
SELECT pg_temp.assert_true((SELECT count(*)=2 FROM annha.notification_deliveries WHERE event_id='60000000-0000-0000-0000-000000000001'),'email and Telegram deliveries are independent');
SELECT pg_temp.assert_true((SELECT email_version=1 FROM annha.notification_deliveries WHERE id='80000000-0000-0000-0000-000000000001'),'delivery bound to verified address version');
SET LOCAL ROLE annha_worker;
SELECT pg_temp.assert_true(annha_private.can_dispatch_notification('80000000-0000-0000-0000-000000000001'),'verified email dispatch allowed');
SELECT pg_temp.assert_true(annha_private.can_dispatch_notification('80000000-0000-0000-0000-000000000002'),'Telegram dispatch unchanged');
SELECT pg_temp.assert_true(NOT annha_private.can_dispatch_notification('80000000-0000-0000-0000-000000000003'),'dispatch helper cannot cross home context');
UPDATE annha.notification_channels SET event_kinds=ARRAY['immobility'] WHERE id='70000000-0000-0000-0000-000000000001';
SELECT pg_temp.assert_true(NOT annha_private.can_dispatch_notification('80000000-0000-0000-0000-000000000001'),'event type preference enforced');
UPDATE annha.notification_channels SET event_kinds=ARRAY['fall'],minimum_severity='critical' WHERE id='70000000-0000-0000-0000-000000000001';
UPDATE annha.events SET severity='warning' WHERE id='60000000-0000-0000-0000-000000000001';
SELECT pg_temp.assert_true(NOT annha_private.can_dispatch_notification('80000000-0000-0000-0000-000000000001'),'minimum severity enforced');
UPDATE annha.events SET severity='critical' WHERE id='60000000-0000-0000-0000-000000000001';
UPDATE annha.notification_channels SET suppressed_at=now(),suppression_reason='complaint' WHERE id='70000000-0000-0000-0000-000000000001';
SELECT pg_temp.assert_true(NOT annha_private.can_dispatch_notification('80000000-0000-0000-0000-000000000001'),'complaint suppression enforced');
UPDATE annha.notification_channels SET suppressed_at=NULL,suppression_reason=NULL WHERE id='70000000-0000-0000-0000-000000000001';
UPDATE annha.notification_deliveries SET status='accepted',accepted_at=now() WHERE id='80000000-0000-0000-0000-000000000001';
SELECT pg_temp.assert_true((SELECT delivered_at IS NULL AND status='accepted' FROM annha.notification_deliveries WHERE id='80000000-0000-0000-0000-000000000001'),'provider acceptance is not inbox delivery');
INSERT INTO annha.delivery_attempts(id,home_id,delivery_id,attempt,status,provider,provider_message_id) VALUES
 ('90000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','80000000-0000-0000-0000-000000000001',1,'accepted','smtp','message-a');
INSERT INTO annha.delivery_receipts(home_id,delivery_id,attempt_id,provider,provider_event_id,kind,occurred_at) VALUES
 ('20000000-0000-0000-0000-000000000001','80000000-0000-0000-0000-000000000001','90000000-0000-0000-0000-000000000001','smtp','receipt-a','delivered',now());
SELECT pg_temp.expect_error($q$INSERT INTO annha.delivery_receipts(home_id,delivery_id,attempt_id,provider,provider_event_id,kind,occurred_at) VALUES('20000000-0000-0000-0000-000000000001','80000000-0000-0000-0000-000000000001','90000000-0000-0000-0000-000000000001','smtp','receipt-a','delivered',now())$q$,'23505');
SELECT pg_temp.expect_error($q$INSERT INTO annha.delivery_receipts(home_id,delivery_id,attempt_id,provider,provider_event_id,kind,occurred_at) VALUES('20000000-0000-0000-0000-000000000001','80000000-0000-0000-0000-000000000001','90000000-0000-0000-0000-000000000001','smtp','bad-bounce','bounced',now())$q$,'23514');
SET LOCAL ROLE annha_app;
SELECT pg_temp.assert_true((SELECT count(*)=1 FROM annha.delivery_receipts),'owner can read receipt metadata');
SELECT pg_temp.expect_error('DELETE FROM annha.delivery_receipts','42501');
SELECT pg_temp.expect_error($q$INSERT INTO annha.delivery_receipts(home_id,delivery_id,attempt_id,provider,provider_event_id,kind,occurred_at) VALUES('20000000-0000-0000-0000-000000000001','80000000-0000-0000-0000-000000000001','90000000-0000-0000-0000-000000000001','smtp','forged-receipt','delivered',now())$q$,'42501');
RESET ROLE;
INSERT INTO annha.delivery_attempts(id,home_id,delivery_id,attempt,status,provider) VALUES
 ('90000000-0000-0000-0000-000000000003','20000000-0000-0000-0000-000000000002','80000000-0000-0000-0000-000000000003',1,'accepted','smtp');
SET LOCAL ROLE annha_worker;
SELECT pg_temp.expect_error($q$INSERT INTO annha.delivery_receipts(home_id,delivery_id,attempt_id,provider,provider_event_id,kind,occurred_at) VALUES('20000000-0000-0000-0000-000000000001','80000000-0000-0000-0000-000000000001','90000000-0000-0000-0000-000000000003','smtp','foreign-attempt','delivered',now())$q$,'23503');
RESET ROLE;
-- Account email change invalidates old links/sessions and stops stale alert deliveries.
INSERT INTO annha_private.email_tokens(token_hash,user_id,purpose,expires_at,email_version) VALUES
 (decode(repeat('11',32),'hex'),'10000000-0000-0000-0000-000000000001','verify_email',now()+interval '1 hour',1);
INSERT INTO annha_private.sessions(token_hash,user_id,csrf_hash,auth_version,expires_at) VALUES
 (decode(repeat('22',32),'hex'),'10000000-0000-0000-0000-000000000001',decode(repeat('33',32),'hex'),1,now()+interval '1 day');
UPDATE annha.notification_deliveries SET status='pending' WHERE id='80000000-0000-0000-0000-000000000001';
UPDATE annha_private.users SET email='new-owner@example.test' WHERE id='10000000-0000-0000-0000-000000000001';
SELECT pg_temp.assert_true((SELECT email_version=2 AND email_verified_at IS NULL AND auth_version=2 FROM annha_private.users WHERE id='10000000-0000-0000-0000-000000000001'),'email change requires re-verification');
SELECT pg_temp.assert_true((SELECT NOT enabled FROM annha.notification_channels WHERE id='70000000-0000-0000-0000-000000000001'),'old email alert channel disabled');
SELECT pg_temp.assert_true((SELECT status='cancelled' FROM annha.notification_deliveries WHERE id='80000000-0000-0000-0000-000000000001'),'queued old-address mail cancelled');
SELECT pg_temp.assert_true((SELECT consumed_at IS NOT NULL FROM annha_private.email_tokens WHERE token_hash=decode(repeat('11',32),'hex')),'old verification link invalidated');
SELECT pg_temp.assert_true((SELECT revoked_at IS NOT NULL FROM annha_private.sessions WHERE token_hash=decode(repeat('22',32),'hex')),'old session revoked after email change');
SELECT pg_temp.expect_error($q$INSERT INTO annha_private.email_tokens(token_hash,user_id,purpose,expires_at,email_version) VALUES(decode(repeat('44',32),'hex'),'10000000-0000-0000-0000-000000000001','verify_email',now()+interval '1 hour',1)$q$,'23514');
INSERT INTO annha_private.job_queue(kind,idempotency_key,payload) VALUES('email','account-email-independent','{"purpose":"verify_email"}');
SELECT pg_temp.assert_true((SELECT count(*)=1 FROM annha_private.job_queue WHERE idempotency_key='account-email-independent'),'account verification mail does not depend on an alert channel');
ROLLBACK;
\echo 'PASS: email/Telegram independence, verified/version-bound recipient, preferences, suppression, provider receipts/RLS, deduplication and auth email lifecycle.'
