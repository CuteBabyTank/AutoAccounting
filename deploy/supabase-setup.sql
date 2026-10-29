-- AutoAccounting on Supabase: app role + lockdown (run once, as postgres, in the Supabase SQL editor).
-- Replace CHANGE_ME with a long random password first (openssl rand -hex 24; hex needs no escaping).
-- Mirrors SnagStock's snagstock_app setup.

-- 1) Facts: Supabase's postgres role should show rolbypassrls = true (the nightly backup relies on it).
SELECT rolname, rolsuper, rolbypassrls, rolcreaterole FROM pg_roles WHERE rolname = current_user;

-- 2) App role: owns every aa_* table it creates on boot (startup_migrations), and is subject to RLS.
--    Never point the app at postgres: it has BYPASSRLS, which silently turns firm isolation off.
CREATE ROLE aa_app LOGIN PASSWORD 'CHANGE_ME' NOBYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE;
GRANT USAGE, CREATE ON SCHEMA public TO aa_app;
GRANT aa_app TO postgres;  -- lets postgres inspect, dump and repair app-owned objects

ALTER ROLE aa_app SET statement_timeout = 0;
ALTER ROLE aa_app SET idle_in_transaction_session_timeout = 0;
ALTER ROLE aa_app SET timezone = 'UTC';

-- 3) Global search: trigram indexes (schema.search_index_statements finds pg_trgm in whichever schema it lives).
CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA extensions;
GRANT USAGE ON SCHEMA extensions TO aa_app;

-- 4) Belt and braces: the Data API roles can't touch public even if the Data API is turned back on.
REVOKE ALL ON ALL TABLES    IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM anon, authenticated;
REVOKE USAGE ON SCHEMA public FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE aa_app IN SCHEMA public REVOKE ALL ON TABLES    FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE aa_app IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE aa_app IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM anon, authenticated;

-- 5) Check: aa_app must show rolbypassrls = false.
SELECT rolname, rolbypassrls, rolsuper FROM pg_roles WHERE rolname = 'aa_app';
