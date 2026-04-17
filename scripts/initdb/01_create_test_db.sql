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
-- Postgres lacks CREATE DATABASE IF NOT EXISTS, so we use a
-- SELECT ... WHERE NOT EXISTS + \gexec idiom to be idempotent
-- (safe to run on an existing volume without raising an error).

SELECT 'CREATE DATABASE jobmatcher_test'
WHERE NOT EXISTS (
    SELECT FROM pg_database WHERE datname = 'jobmatcher_test'
)\gexec
