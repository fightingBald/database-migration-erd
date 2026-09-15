-- +migrate Up

-- Group setup
-- +migrate StatementBegin
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT FROM pg_roles
        WHERE rolname = 'analytics_reader'
    ) THEN
        CREATE ROLE analytics_reader
            NOSUPERUSER
            NOCREATEDB
            NOCREATEROLE
            NOINHERIT;
    END IF;
END
$$;
-- +migrate StatementEnd

-- Grant database connection & schema access
-- +migrate StatementBegin
DO $$
BEGIN
    EXECUTE format(
        'GRANT CONNECT ON DATABASE %I TO analytics_reader',
        CURRENT_DATABASE()
    );
END
$$;
-- +migrate StatementEnd

GRANT USAGE
    ON SCHEMA analytics_v1
    TO analytics_reader;

-- Grant read-only access to existing and future tables

GRANT SELECT
    ON ALL TABLES IN SCHEMA analytics_v1
    TO analytics_reader;

ALTER DEFAULT PRIVILEGES IN SCHEMA analytics_v1
    GRANT SELECT
    ON TABLES
    TO analytics_reader;

-- +migrate StatementEnd
