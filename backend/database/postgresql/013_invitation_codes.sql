-- MVP invitation codes; existing email invitations and data are preserved.
BEGIN;
ALTER TABLE annha_private.home_memberships
 DROP CONSTRAINT home_memberships_role_check;
ALTER TABLE annha_private.home_memberships
 ADD CONSTRAINT home_memberships_role_check CHECK(role IN ('owner','caregiver','viewer','member'));

CREATE TABLE annha_private.invitation_codes (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 home_id uuid NOT NULL REFERENCES annha.homes(id),
 code_hash bytea NOT NULL UNIQUE CHECK(octet_length(code_hash)=32),
 created_by uuid NOT NULL REFERENCES annha_private.users(id),
 created_at timestamptz NOT NULL DEFAULT now(),
 expires_at timestamptz NOT NULL DEFAULT now()+interval '7 days',
 used_by uuid REFERENCES annha_private.users(id),
 used_at timestamptz,
 revoked_at timestamptz,
 CHECK(expires_at>created_at),
 CHECK((used_by IS NULL)=(used_at IS NULL)),
 CHECK(used_at IS NULL OR revoked_at IS NULL)
);
CREATE INDEX invitation_codes_home_recent ON annha_private.invitation_codes(home_id,created_at DESC);
ALTER TABLE annha_private.invitation_codes ENABLE ROW LEVEL SECURITY;
ALTER TABLE annha_private.invitation_codes FORCE ROW LEVEL SECURITY;
-- Trusted auth control plane authorizes owner and verified user in API transactions,
-- as with existing memberships/invitations. Business/device/worker roles have no access.
CREATE POLICY auth_invitation_codes ON annha_private.invitation_codes
 FOR ALL TO annha_auth USING(true) WITH CHECK(true);
CREATE POLICY migration_owner_invitation_codes ON annha_private.invitation_codes
 FOR ALL TO CURRENT_USER USING(true) WITH CHECK(true);
REVOKE ALL ON annha_private.invitation_codes FROM PUBLIC,annha_app,annha_device,annha_worker;
GRANT SELECT,INSERT,UPDATE ON annha_private.invitation_codes TO annha_auth;
COMMIT;
