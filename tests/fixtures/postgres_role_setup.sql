-- +migrate Up

-- Fictional library reader role; exercises conditional PostgreSQL setup.
-- +migrate StatementBegin
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT FROM pg_roles
        WHERE rolname = 'demo_library_reader'
    ) THEN
        CREATE ROLE demo_library_reader
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
        'GRANT CONNECT ON DATABASE %I TO demo_library_reader',
        CURRENT_DATABASE()
    );
END
$$;
-- +migrate StatementEnd

GRANT USAGE
    ON SCHEMA demo_library
    TO demo_library_reader;

-- Grant read-only access to existing and future tables

GRANT SELECT
    ON ALL TABLES IN SCHEMA demo_library
    TO demo_library_reader;

ALTER DEFAULT PRIVILEGES IN SCHEMA demo_library
    GRANT SELECT
    ON TABLES
    TO demo_library_reader;

-- +migrate StatementEnd
