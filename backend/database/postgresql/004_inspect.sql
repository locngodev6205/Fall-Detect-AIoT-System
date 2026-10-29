-- Read-only catalog report. No application rows or secrets are returned.
BEGIN READ ONLY;
SELECT version() AS postgres_version;
SELECT schemaname,count(*) AS tables FROM pg_tables
 WHERE schemaname IN ('annha','annha_private') GROUP BY schemaname ORDER BY schemaname;
SELECT count(*) AS business_tables,
 count(*) FILTER (WHERE c.relrowsecurity AND c.relforcerowsecurity) AS rls_forced_tables
 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='annha' AND c.relkind='r';
SELECT rolname,rolcanlogin,rolsuper,rolbypassrls,rolcreaterole,rolcreatedb FROM pg_roles
 WHERE rolname IN ('annha_app','annha_auth','annha_device','annha_worker') ORDER BY rolname;
SELECT r.rolname AS member,p.rolname AS granted_role FROM pg_auth_members m
 JOIN pg_roles r ON r.oid=m.member JOIN pg_roles p ON p.oid=m.roleid
 WHERE r.rolname LIKE 'annha_%' ORDER BY r.rolname,p.rolname;
COMMIT;
