import logging

import pytest

from erd_generator.sql_parser import parse_schema_from_sql


def parse(sql):
    schema, failures = {}, []
    parse_schema_from_sql(sql, schema, source="migration.sql", failures=failures)
    return schema, failures


@pytest.mark.parametrize(
    "command",
    [
        "CREATE SCHEMA app",
        'CREATE SCHEMA IF NOT EXISTS "CREATE" AUTHORIZATION owner',
        "CREATE SCHEMA AUTHORIZATION CURRENT_USER",
        "CREATE ROLE reader WITH NOLOGIN",
        "CREATE USER reader WITH PASSWORD 'private;credential'",
        "GRANT SELECT ON TABLE public.before TO reader",
        "GRANT SELECT ON ALL TABLES IN SCHEMA public TO reader",
        "REVOKE INSERT ON TABLE public.before FROM reader",
        "ALTER DEFAULT PRIVILEGES FOR ROLE owner IN SCHEMA public GRANT SELECT ON TABLES TO reader",
        "ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC",
        "CREATE FUNCTION f() RETURNS void LANGUAGE plpgsql AS $$BEGIN DROP TABLE public.before; END;$$",
        "CREATE OR REPLACE PROCEDURE p() LANGUAGE plpgsql AS $p$BEGIN CREATE TABLE never_run (id int); END;$p$",
    ],
)
def test_neutral_commands_do_not_stop_or_change_schema(command, caplog):
    with caplog.at_level(logging.DEBUG, logger="erd_generator.sql_parser"):
        schema, failures = parse(
            f"CREATE TABLE public.before (id int);\n{command};\n"
            "CREATE TABLE public.after (id int);"
        )
    assert not failures
    assert set(schema) == {"public.before", "public.after"}
    assert "SQL skipped for ERD" in caplog.text
    assert "private;credential" not in caplog.text


@pytest.mark.parametrize(
    "opening,closing",
    [
        ("DO $$", "$$"),
        ("DO LANGUAGE plpgsql $migration$", "$migration$"),
        ("DO $Tag$", "$Tag$ LANGUAGE plpgsql"),
    ],
)
def test_straight_line_do_applies_static_ddl_and_then_continues(opening, closing):
    schema, failures = parse(f"""
        {opening}
        BEGIN
            CREATE TABLE parent (id int PRIMARY KEY);
            CREATE TABLE child (id int PRIMARY KEY, parent_id int REFERENCES parent(id));
            ALTER TABLE child ADD COLUMN note text DEFAULT $text$a;b$text$;
            CREATE INDEX child_parent ON child(parent_id);
            CREATE TABLE removed (id int);
            DROP TABLE removed;
        END;
        {closing};
        CREATE TABLE following (id int);
    """)
    assert not failures
    assert set(schema) == {"parent", "child", "following"}
    assert [c.name for c in schema["child"].columns] == ["id", "parent_id", "note"]
    assert schema["child"].foreign_keys[0].ref_table == "parent"
    assert schema["child"].indexes[0].name == "child_parent"


def test_do_with_only_neutral_commands_and_constant_notice():
    schema, failures = parse("""
        DO $body$
        BEGIN
            CREATE ROLE reader NOLOGIN;
            CREATE SCHEMA app;
            GRANT USAGE ON SCHEMA app TO reader;
            NULL;
            RAISE NOTICE $$done; no schema changes$$;
        END;
        $body$;
        CREATE TABLE app.items (id int);
    """)
    assert not failures
    assert set(schema) == {"app.items"}


@pytest.mark.parametrize(
    "body",
    [
        "IF true THEN CREATE TABLE uncertain(id int); END IF;",
        "FOR i IN 1..2 LOOP CREATE TABLE uncertain(id int); END LOOP;",
        "EXECUTE 'CREATE TABLE secret_payload(id int)';",
        "PERFORM changes_schema();",
        "SELECT changes_schema();",
        "CALL changes_schema();",
        "RAISE EXCEPTION 'abort transaction';",
        "RAISE NOTICE '%', changes_schema();",
        "BEGIN CREATE TABLE nested(id int); END;",
        "DO $nested$BEGIN CREATE TABLE nested(id int); END;$nested$;",
        "EXCEPTION WHEN OTHERS THEN NULL;",
    ],
)
def test_unsupported_do_never_partially_applies_a_block(body):
    schema, failures = parse(
        "CREATE TABLE keep (id int);\n"
        "DO $$\nBEGIN\n"
        "CREATE TABLE staged (id int);\n"
        f"{body}\nEND;\n$$;\n"
        "CREATE TABLE following (id int);"
    )
    assert set(schema) == {"keep", "following"}
    assert len(failures) == 1
    assert "Unsupported DO" in failures[0].reason
    assert failures[0].line == 5
    assert "secret_payload" not in failures[0].reason


@pytest.mark.parametrize(
    "command",
    [
        "DO $$DECLARE x int; BEGIN NULL; END;$$",
        "DO LANGUAGE plpython3u $$pass$$",
        "DO $$BEGIN CREATE TABLE invalid(id int) END;$$",
        "CREATE SCHEMA app CREATE TABLE embedded (id int)",
        "ALTER SCHEMA app RENAME TO renamed",
        "DROP SCHEMA app CASCADE",
        "CALL changes_schema()",
    ],
)
def test_unsupported_schema_and_procedural_commands_remain_errors(command):
    schema, failures = parse(f"CREATE TABLE keep(id int);\n{command};")
    assert set(schema) == {"keep"}
    assert failures and all(f.severity == "error" for f in failures)


def test_lexical_error_has_file_and_statement_line_without_payload():
    _, failures = parse(
        "CREATE TABLE keep(id int);\n\nDO $tag$\nBEGIN\n"
        "RAISE NOTICE 'secret_payload';\nEND;"
    )
    assert len(failures) == 1
    assert failures[0].source == "migration.sql"
    assert failures[0].line == 3
    assert "Unterminated SQL token" in failures[0].reason
    assert "secret_payload" not in failures[0].reason
