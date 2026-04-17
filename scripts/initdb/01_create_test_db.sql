-- scripts/initdb/01_create_test_db.sql
--
-- Creates the jobmatcher_test database alongside jobmatcher_dev on first
-- container boot.  This script is mounted into
-- /docker-entrypoint-initdb.d/ and runs only when the Postgres volume is
-- empty (fresh container).
--
-- Existing dev setups (non-empty volume) must run this manually once:
--   docker exec job-matcher-pr-dev-db-1 \
--     psql -U jobmatcher -d postgres \
--     -c "CREATE DATABASE jobmatcher_test;"
--
-- The IF NOT EXISTS clause makes repeated runs safe (e.g. when the volume
-- is recreated after a teardown).

SELECT 'CREATE DATABASE jobmatcher_test'
WHERE NOT EXISTS (
    SELECT FROM pg_database WHERE datname = 'jobmatcher_test'
)\gexec
