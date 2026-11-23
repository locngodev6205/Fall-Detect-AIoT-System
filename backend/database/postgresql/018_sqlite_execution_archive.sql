BEGIN;
CREATE TABLE annha_private.sqlite_execution_archive (
 id uuid PRIMARY KEY,
 source_record jsonb NOT NULL CHECK (jsonb_typeof(source_record) = 'object' AND source_record->>'id' = id::text),
 archived_at timestamptz NOT NULL DEFAULT now()
);
REVOKE ALL ON annha_private.sqlite_execution_archive FROM PUBLIC,annha_app,annha_auth,annha_device,annha_worker;
COMMIT;
