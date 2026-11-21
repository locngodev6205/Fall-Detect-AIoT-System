BEGIN;
CREATE TABLE annha_private.update_states (
 camera_id uuid PRIMARY KEY REFERENCES annha.cameras(id),
 payload text NOT NULL,
 last_seen double precision NOT NULL
);
CREATE TABLE annha_private.update_jobs (
 id uuid PRIMARY KEY,
 camera_id uuid NOT NULL REFERENCES annha.cameras(id),
 payload text NOT NULL
);
CREATE INDEX update_jobs_camera ON annha_private.update_jobs(camera_id);
REVOKE ALL ON annha_private.update_states,annha_private.update_jobs FROM PUBLIC,annha_app,annha_device,annha_worker;
GRANT SELECT,INSERT,UPDATE,DELETE ON annha_private.update_states,annha_private.update_jobs TO annha_auth;
GRANT SELECT ON annha.events TO annha_device;
CREATE POLICY device_update_read ON annha.events FOR SELECT TO annha_device USING (camera_id=annha_private.context_id('app.camera_id'));
COMMIT;
