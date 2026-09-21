import logging

import pytest

from erd_generator import sql_parser


def parse(sql):
    schema, failures = {}, []
    sql_parser.parse_schema_from_sql(
        sql, schema, source="migration.sql", failures=failures
    )
    return schema, failures


@pytest.mark.parametrize(
    "command",
    [
        "CREATE VIEW app.summary AS SELECT id FROM app.parent",
        'CREATE OR REPLACE TEMPORARY RECURSIVE VIEW "Summary"(id) AS SELECT 1',
        "CREATE PROCEDURE p(n integer = 1) LANGUAGE plpgsql AS $$BEGIN DROP TABLE app.parent; END;$$",
        "CREATE OR REPLACE PROCEDURE p(label text = 'private;value') LANGUAGE SQL AS 'DROP TABLE app.parent;'",
        "CREATE PROCEDURE p() LANGUAGE SQL BEGIN ATOMIC SELECT CASE WHEN true THEN 1 ELSE 0 END; CREATE TABLE never_run(id int); END",
        "CALL app.p(label => 'private;value')",
        "DROP PROCEDURE IF EXISTS app.p(IN n integer), app.q(text) CASCADE",
        "CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA app VERSION '1.0' CASCADE",
        "DROP MATERIALIZED VIEW IF EXISTS app.old, app.older CASCADE",
    ],
)
def test_excluded_objects_keep_only_tables_and_foreign_keys(command, caplog):
    with caplog.at_level(logging.DEBUG, logger="erd_generator.sql_parser"):
        schema, failures = parse(
            "CREATE TABLE app.parent(id int PRIMARY KEY);\n"
            f"/* migration step */ {command};\n"
            "CREATE TABLE app.child(id int, parent_id int REFERENCES app.parent(id));"
        )
    assert not failures
    assert set(schema) == {"app.parent", "app.child"}
    assert schema["app.child"].foreign_keys[0].ref_table == "app.parent"
    assert "SQL skipped for ERD" in caplog.text
    assert "private;value" not in caplog.text


def test_procedure_and_view_definitions_bypass_sqlglot(monkeypatch):
    def unexpected_parse(*args, **kwargs):
        pytest.fail("Excluded definitions must be recognized before sqlglot.parse")

    monkeypatch.setattr(sql_parser.sqlglot, "parse", unexpected_parse)
    schema, failures = parse(
        "CREATE PROCEDURE p(n int = 1) LANGUAGE SQL AS $$SELECT n;$$;"
        "CREATE VIEW v AS SELECT 1;"
        "CREATE MATERIALIZED VIEW mv WITH (fillfactor=90) AS SELECT 1 WITH NO DATA;"
        "CREATE UNIQUE INDEX ix ON mv((unsupported_expression(1)));"
        "CALL p(); DROP PROCEDURE p(integer); CREATE EXTENSION pg_trgm;"
        "DROP MATERIALIZED VIEW mv;"
    )
    assert not failures and not schema


@pytest.mark.parametrize(
    "view,target",
    [
        ("app.summary", "app.summary"),
        ("APP.SUMMARY", "app.summary"),
        ('"Mixed"."Snapshot"', '"Mixed"."Snapshot"'),
        ('"a.b"."c"', '"a.b"."c"'),
        ('"say""hello"', '"say""hello"'),
    ],
)
def test_only_indexes_of_recorded_materialized_views_are_skipped(view, target):
    schema, failures = parse(
        "CREATE TABLE app.items(id int);"
        f"CREATE MATERIALIZED VIEW IF NOT EXISTS {view}(id) WITH (fillfactor=90) "
        "AS SELECT id FROM app.items WITH NO DATA;"
        f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS ix_view ON {target}(id);"
        f"CREATE INDEX ON {target}((lower(id::text)));"
        "CREATE INDEX ix_items ON app.items(id);"
    )
    assert not failures
    assert set(schema) == {"app.items"}
    assert [i.name for i in schema["app.items"].indexes] == ["ix_items"]


@pytest.mark.parametrize(
    "setup,target",
    [
        ("", "missing"),
        ("CREATE VIEW summary AS SELECT 1 AS id;", "summary"),
        ("CREATE MATERIALIZED VIEW app.summary AS SELECT 1 AS id;", "summary"),
        ("CREATE MATERIALIZED VIEW app.summary AS SELECT 1 AS id;", "other.summary"),
        (
            'CREATE MATERIALIZED VIEW "Mixed".summary AS SELECT 1 AS id;',
            "mixed.summary",
        ),
        ('CREATE MATERIALIZED VIEW "a.b".c AS SELECT 1 AS id;', 'a."b.c"'),
        (
            "CREATE MATERIALIZED VIEW summary AS SELECT 1 AS id; DROP MATERIALIZED VIEW summary;",
            "summary",
        ),
    ],
)
def test_unknown_or_dropped_index_targets_remain_errors(setup, target):
    schema, failures = parse(f"{setup}\nCREATE INDEX ix ON {target}(id);")
    assert not schema
    assert len(failures) == 1
    assert "Index references unknown table" in failures[0].reason
    assert failures[0].source == "migration.sql" and failures[0].line == 2


def test_materialized_view_lifecycle_across_ordered_files_and_isolated_loads(tmp_path):
    (tmp_path / "V1__tables.sql").write_text("CREATE TABLE items(id int);")
    (tmp_path / "V2__views.sql").write_text(
        "CREATE MATERIALIZED VIEW a AS SELECT id FROM items;"
        "CREATE MATERIALIZED VIEW b AS SELECT id FROM items;"
    )
    (tmp_path / "V3__indexes.sql").write_text("CREATE INDEX ix_a ON a(id);")
    (tmp_path / "V4__drop.sql").write_text(
        "DROP MATERIALIZED VIEW IF EXISTS a, b CASCADE;"
        "CREATE TABLE a(id int); CREATE INDEX ix_real ON a(id);"
        "CREATE MATERIALIZED VIEW b AS SELECT id FROM items;"
    )
    (tmp_path / "V10__indexes.sql").write_text("CREATE INDEX ix_b ON b(id);")
    result = sql_parser.load_schema_result(str(tmp_path))
    assert not result.failures
    assert set(result.schema) == {"items", "a"}
    assert result.schema["a"].indexes[0].name == "ix_real"
    other = tmp_path / "unrelated"
    other.mkdir()
    (other / "V1.sql").write_text("CREATE INDEX ix_b ON b(id);")
    assert (
        "unknown table" in sql_parser.load_schema_result(str(other)).failures[0].reason
    )


def test_explicit_context_spans_sql_chunks_without_becoming_global_state():
    from erd_generator.postgres_exclusions import SQLParseContext

    context = SQLParseContext()
    schema, failures = {}, []
    for sql in (
        "CREATE MATERIALIZED VIEW summary AS SELECT 1 AS id;",
        "CREATE INDEX ix ON summary(id);",
    ):
        sql_parser.parse_schema_from_sql(
            sql, schema, failures=failures, context=context
        )
    assert not failures and not schema
    _, independent_failures = parse("CREATE INDEX ix ON summary(id);")
    assert len(independent_failures) == 1


@pytest.mark.parametrize("name", ["items", '"Mixed".items', 'library."Mixed"'])
def test_existing_table_indexes_cannot_be_hidden_by_view_if_not_exists(name):
    schema, failures = parse(
        f"CREATE TABLE {name}(id int);"
        f"CREATE MATERIALIZED VIEW IF NOT EXISTS {name} AS SELECT 1 AS id;"
        f"CREATE INDEX ix_items ON {name}(id);"
    )
    assert not failures
    assert [index.name for index in next(iter(schema.values())).indexes] == ["ix_items"]
    _, failures = parse(
        f"CREATE TABLE {name}(id int);"
        f"CREATE MATERIALIZED VIEW IF NOT EXISTS {name} AS SELECT 1 AS id;"
        f"DROP TABLE {name}; CREATE INDEX ix_missing ON {name}(id);"
    )
    assert len(failures) == 1 and "unknown table" in failures[0].reason


@pytest.mark.parametrize("fail_block", [False, True])
def test_do_changes_to_view_registry_are_atomic(fail_block):
    operation = "CREATE MATERIALIZED VIEW created AS SELECT 1 AS id; DROP MATERIALIZED VIEW kept;"
    if fail_block:
        operation += "CALL unknown_effects();"
    _, failures = parse(
        "CREATE MATERIALIZED VIEW kept AS SELECT 1 AS id;"
        f"DO $$BEGIN {operation} END;$$;"
        "CREATE INDEX ix_kept ON kept(id); CREATE INDEX ix_created ON created(id);"
    )
    reasons = [failure.reason for failure in failures]
    if fail_block:
        assert len(reasons) == 2
        assert "Unsupported DO" in reasons[0]
        assert "unknown table 'created'" in reasons[1]
    else:
        assert len(reasons) == 1 and "unknown table 'kept'" in reasons[0]


@pytest.mark.parametrize(
    "command",
    [
        "CREATE MATERIALIZED VIEW",
        "DROP MATERIALIZED VIEW a,",
        "CREATE VIEW",
        "CREATE PROCEDURE p() LANGUAGE SQL BEGIN ATOMIC CREATE TABLE leaked(id int);",
        "CREATE PROCEDURE p() LANGUAGE SQL AS $broken$ SELECT 1;",
    ],
)
def test_incomplete_statements_still_fail_without_leaking_body_ddl(command):
    schema, failures = parse(command)
    assert failures and not schema
