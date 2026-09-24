"""Prove setup blocks harmless without choosing branches or executing SQL."""

import logging

import pytest

from erd_generator.sql_parser import parse_schema_from_sql


def parse_block(body):
    schema, failures = {}, []
    parse_schema_from_sql(
        "CREATE TABLE keep(id int PRIMARY KEY);\n"
        f"DO $migration$\nBEGIN\n{body}\nEND;\n$migration$;\n"
        "CREATE TABLE following(id int, keep_id int REFERENCES keep(id));",
        schema,
        source="migration.sql",
        failures=failures,
    )
    return schema, failures


@pytest.mark.parametrize(
    "body",
    [
        """IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reader') THEN
               CREATE ROLE reader NOLOGIN;
           END IF;""",
        """IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'reader') THEN
               CREATE USER reader PASSWORD 'private;credential';
           ELSE
               GRANT SELECT ON TABLE keep TO reader;
           END IF;""",
        """IF EXISTS (SELECT * FROM pg_roles WHERE rolname = 'reader') THEN
               IF true THEN GRANT SELECT ON keep TO reader; ELSE NULL; END IF;
           ELSIF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reader') THEN
               CREATE ROLE reader;
           ELSE
               RAISE NOTICE 'no changes';
           END IF;""",
        """IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'reader') THEN
               EXECUTE format('CREATE ROLE %I NOLOGIN', 'reader');
           END IF;
           EXECUTE format('GRANT CONNECT ON DATABASE %I TO reader', current_database());
           ALTER DEFAULT PRIVILEGES GRANT SELECT ON TABLES TO reader;""",
        "EXECUTE 'GRANT SELECT ON TABLE keep TO reader';",
        "EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), 'reader');",
        "EXECUTE pg_catalog.format('GRANT USAGE ON SCHEMA %I TO %I', pg_catalog.current_schema(), CURRENT_USER);",
        "EXECUTE format('CREATE USER %1$I PASSWORD %2$L', 'reader', 'private;credential');",
        "EXECUTE format($cmd$GRANT %1$I TO %2$I; REVOKE %1$I FROM %2$I$cmd$, 'reader', 'owner');",
        "EXECUTE format('GRANT %1$I TO %2$I', 'reader', SESSION_USER);",
        "EXECUTE format('CREATE ROLE \"reader%%\"');",
        "EXECUTE format('GRANT SELECT ON keep TO %I', 'reader; DROP TABLE keep; --');",
    ],
    ids=[
        "missing-role",
        "qualified-catalog-and-else",
        "nested-and-elsif",
        "conditional-role-and-current-database-grant",
        "literal-grant",
        "formatted-grant",
        "qualified-builtins",
        "positional-and-password",
        "multiple-neutral-commands",
        "session-user",
        "escaped-percent",
        "quoted-argument-is-not-sql",
    ],
)
def test_neutral_setup_do_keeps_tables_and_relationships(body, caplog):
    with caplog.at_level(logging.DEBUG, logger="erd_generator.sql_parser"):
        schema, failures = parse_block(body)
    assert not failures
    assert set(schema) == {"keep", "following"}
    assert schema["following"].foreign_keys[0].ref_table == "keep"
    assert "SQL skipped for ERD" in caplog.text
    assert "private;credential" not in caplog.text


@pytest.mark.parametrize(
    "body",
    [
        "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='reader') THEN CREATE TABLE uncertain(id int); END IF;",
        "IF true THEN GRANT SELECT ON keep TO reader; ELSE DROP TABLE keep; END IF;",
        "IF true THEN NULL; ELSIF false THEN ALTER TABLE keep ADD COLUMN hidden int; END IF;",
        "IF changes_schema() THEN CREATE ROLE reader; END IF;",
        "IF EXISTS (SELECT changes_schema() FROM pg_roles WHERE rolname='reader') THEN CREATE ROLE reader; END IF;",
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=changes_schema()) THEN CREATE ROLE reader; END IF;",
        "IF EXISTS (SELECT 1 FROM app.pg_roles WHERE rolname='reader') THEN CREATE ROLE reader; END IF;",
        "IF true THEN CREATE ROLE reader; END;",
        "IF true THEN CREATE ROLE reader; ELSE NULL; ELSE NULL; END IF;",
        "IF true THEN CREATE ROLE reader; ELSE NULL; ELSIF false THEN NULL; END IF;",
        "EXECUTE format('CREATE TABLE %I(id int)', 'uncertain');",
        "EXECUTE format('DROP TABLE %I', 'keep');",
        "EXECUTE format('GRANT SELECT ON keep TO reader; DROP TABLE %I', 'keep');",
        "EXECUTE format('GRANT SELECT ON keep TO %s', current_user);",
        "EXECUTE format(sql_template, 'reader');",
        "EXECUTE format('GRANT SELECT ON keep TO %I', changes_schema());",
        "EXECUTE format('GRANT SELECT ON keep TO reader', changes_schema());",
        "EXECUTE public.format('GRANT SELECT ON keep TO %I', 'reader');",
        "EXECUTE format('GRANT SELECT ON keep TO %I', (SELECT changes_schema()));",
        "EXECUTE format('GRANT SELECT ON keep TO %I', 'reader'::custom_type);",
        "EXECUTE format('GRANT SELECT ON keep TO %2$I', 'reader');",
        "EXECUTE format('GRANT SELECT ON keep TO %0$I', 'reader');",
        "EXECUTE format('GRANT SELECT ON keep TO %10I', 'reader');",
        "EXECUTE format('GRANT SELECT ON keep TO %', 'reader');",
        "EXECUTE format('GRANT SELECT ON keep TO \"%I\"', 'reader');",
        "EXECUTE format($cmd$CREATE USER reader PASSWORD '%L'$cmd$, 'private;credential');",
        "EXECUTE format('GRANT SELECT ON keep TO reader -- %I', 'reader');",
        "EXECUTE 'GRANT SELECT ON keep TO ' || sql_fragment;",
        "EXECUTE 'GRANT SELECT ON keep TO reader' USING changes_schema();",
        "IF true THEN CALL changes_schema(); END IF;",
        "FOR i IN 1..2 LOOP GRANT SELECT ON keep TO reader; END LOOP;",
    ],
)
def test_unknown_effects_remain_errors_and_do_not_change_schema(body):
    schema, failures = parse_block(body)
    assert set(schema) == {"keep", "following"}
    assert [column.name for column in schema["keep"].columns] == ["id"]
    assert len(failures) == 1
    assert "Unsupported DO" in failures[0].reason
    assert failures[0].source == "migration.sql"
    assert failures[0].line == 4
    assert "private;credential" not in failures[0].reason


def test_conditional_block_mixed_with_structural_ddl_stays_atomic():
    schema, failures = parse_block(
        "CREATE TABLE staged(id int);\nIF true THEN CREATE ROLE reader; END IF;"
    )
    assert failures
    assert set(schema) == {"keep", "following"}
