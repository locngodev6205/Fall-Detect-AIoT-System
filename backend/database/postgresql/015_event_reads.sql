-- Track each member's read receipt; the API acknowledges open events for handlers.
BEGIN;
CREATE TABLE annha.event_reads (
 home_id uuid NOT NULL,
 camera_id uuid NOT NULL,
 event_id uuid NOT NULL,
 user_id uuid NOT NULL REFERENCES annha_private.users(id),
 read_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(event_id,user_id),
 FOREIGN KEY(home_id,camera_id,event_id) REFERENCES annha.events(home_id,camera_id,id) ON DELETE CASCADE
);
ALTER TABLE annha.event_reads ENABLE ROW LEVEL SECURITY;
ALTER TABLE annha.event_reads FORCE ROW LEVEL SECURITY;
REVOKE ALL ON annha.event_reads FROM PUBLIC,annha_auth,annha_device,annha_worker;
GRANT SELECT,INSERT ON annha.event_reads TO annha_app;
CREATE POLICY event_reads_self_select ON annha.event_reads FOR SELECT TO annha_app
 USING (user_id=annha_private.context_id('app.user_id') AND annha_private.can_camera(home_id,camera_id));
CREATE POLICY event_reads_self_insert ON annha.event_reads FOR INSERT TO annha_app
 WITH CHECK (user_id=annha_private.context_id('app.user_id') AND annha_private.can_camera(home_id,camera_id));
COMMIT;
