"""Regression tests use expected SQL semantics, not rendered snapshots."""

from pathlib import Path

import pytest

from erd_generator.fk_config import apply_foreign_key_config, load_foreign_key_config
from erd_generator.sql_parser import (
    get_last_parse_failures,
    load_schema_from_migrations,
    parse_schema_from_sql,
)


def parse(sql):
    schema, failures = {}, []
    parse_schema_from_sql(sql, schema, failures=failures)
    assert not failures
    return schema


@pytest.mark.parametrize(
    "drop", ["DROP TABLE public.a", "DROP TABLE IF EXISTS public.a"]
)
def test_drop_table_removes_incoming_foreign_keys(drop):
    schema = parse(f"""
        CREATE TABLE public.a (id int PRIMARY KEY);
        CREATE TABLE public.b (id int REFERENCES public.a(id));
        {drop} CASCADE;
    """)
    assert set(schema) == {"public.b"}
    assert not schema["public.b"].foreign_keys


def test_drop_multiple_tables():
    assert not parse(
        "CREATE TABLE a (id int); CREATE TABLE b (id int); DROP TABLE a, b;"
    )


def test_drop_columns_removes_local_indexes_and_constraints():
    schema = parse("""
        CREATE TABLE a (id int PRIMARY KEY, gone int, also_gone text);
        CREATE INDEX ix ON a(gone);
        ALTER TABLE a DROP COLUMN gone, DROP COLUMN also_gone;
    """)
    assert [c.name for c in schema["a"].columns] == ["id"]
    assert not schema["a"].indexes


@pytest.mark.parametrize("columns", ["gone", "id, gone"])
def test_drop_column_clears_removed_unique_constraint_registration(columns):
    table = parse(f"""
        CREATE TABLE a (
            id int, gone text,
            CONSTRAINT keep UNIQUE (id),
            CONSTRAINT removed UNIQUE ({columns})
        );
        ALTER TABLE a DROP COLUMN gone;
    """)["a"]
    assert [index.name for index in table.indexes] == ["keep"]
    assert table.constraint_types == {"keep": "unique"}


@pytest.mark.parametrize(
    "kind", ["PRIMARY KEY (id)", "UNIQUE (id)", "FOREIGN KEY (id) REFERENCES b(id)"]
)
def test_drop_constraint(kind):
    table = parse(f"""
        CREATE TABLE b (id int PRIMARY KEY);
        CREATE TABLE a (id int, CONSTRAINT doomed {kind});
        ALTER TABLE a DROP CONSTRAINT doomed;
    """)["a"]
    assert not table.constraint_types
    assert not table.primary_key
    assert not table.foreign_keys
    assert not table.indexes


def test_drop_renamed_index():
    schema = parse("""
        CREATE TABLE a (id int);
        CREATE INDEX ix ON a(id);
        ALTER INDEX ix RENAME TO renamed;
        DROP INDEX renamed;
    """)
    assert not schema["a"].indexes


@pytest.mark.parametrize("rename", [False, True])
def test_qualified_index_operations_respect_schema(rename):
    update = (
        "ALTER INDEX one.ix RENAME TO changed; DROP INDEX one.changed;"
        if rename
        else "DROP INDEX one.ix;"
    )
    schema = parse(f"""
        CREATE TABLE one.a (id int);
        CREATE TABLE two.a (id int);
        CREATE INDEX ix ON one.a(id);
        CREATE INDEX ix ON two.a(id);
        {update}
    """)
    assert not schema["one.a"].indexes
    assert [i.name for i in schema["two.a"].indexes] == ["ix"]


def test_drop_column_cascade_removes_incoming_fk():
    schema = parse("""
        CREATE TABLE a (id int PRIMARY KEY, keep text);
        CREATE TABLE b (ref int, CONSTRAINT fk_a FOREIGN KEY (ref) REFERENCES a(id));
        ALTER TABLE a DROP COLUMN id CASCADE;
    """)
    assert not schema["b"].foreign_keys
    assert not schema["b"].constraint_types
    assert [c.name for c in schema["a"].columns] == ["keep"]


def test_dropping_part_of_primary_key_removes_whole_constraint():
    table = parse(
        "CREATE TABLE a (tenant int, id int, CONSTRAINT pk_a PRIMARY KEY (tenant, id)); ALTER TABLE a DROP COLUMN tenant;"
    )["a"]
    assert not table.primary_key
    assert not table.primary_key_name
    assert "pk_a" not in table.constraint_types
    assert not table.columns[0].is_primary_key


def test_renames_update_foreign_key_endpoints():
    schema = parse("""
        CREATE TABLE public.a (id int PRIMARY KEY, parent_id int REFERENCES public.a(id));
        CREATE TABLE public.b (a_id int REFERENCES public.a(id));
        ALTER TABLE public.a RENAME TO renamed;
        ALTER TABLE public.renamed RENAME COLUMN id TO key;
    """)
    assert set(schema) == {"public.renamed", "public.b"}
    assert schema["public.b"].foreign_keys[0].ref_table == "public.renamed"
    assert schema["public.b"].foreign_keys[0].ref_columns == ("key",)
    assert schema["public.renamed"].foreign_keys[0].ref_columns == ("key",)


@pytest.mark.parametrize(
    "clause,nullable", [("SET NOT NULL", False), ("DROP NOT NULL", True)]
)
def test_alter_nullability(clause, nullable):
    table = parse(f"CREATE TABLE a (id int); ALTER TABLE a ALTER COLUMN id {clause};")[
        "a"
    ]
    assert table.columns[0].nullable is nullable


def test_index_method_and_expression_metadata():
    index = parse(
        "CREATE TABLE a (email text); CREATE UNIQUE INDEX ix ON a USING btree (lower(email)) WHERE email IS NOT NULL;"
    )["a"].indexes[0]
    assert index.method == "BTREE"
    assert index.expression_columns == ("LOWER(email)",)
    assert index.unique
    assert index.where == "email IS NOT NULL"


def test_sample_migrations_have_expected_final_schema():
    root = Path(__file__).resolve().parents[1]
    schema = load_schema_from_migrations(str(root / "db/migration"))
    failures = get_last_parse_failures()
    entries, source = load_foreign_key_config(
        str(root / "sample_fk_config.yaml"), failures
    )
    apply_foreign_key_config(schema, entries, config_source=source)
    assert not failures
    assert set(schema) == {
        "public.users",
        "public.purchase_orders",
        "public.products",
        "public.order_items",
        "public.roles",
    }
    assert sum(len(t.columns) for t in schema.values()) == 21
    assert sum(len(t.foreign_keys) for t in schema.values()) == 5
    # The original inline email UNIQUE and the later named UNIQUE both remain.
    assert sum(len(t.indexes) for t in schema.values()) == 7
    assert [i.name for i in schema["public.users"].indexes] == [
        "",
        "users_email_unique",
        "users_email_status_unique",
        "idx_users_active_email",
        "idx_users_lower_email",
    ]
    assert schema["public.users"].get_column("last_login") is None
    assert schema["public.purchase_orders"].get_column("order_label") is None
    assert schema["public.users"].get_column("status").nullable is False


def test_malformed_sql_records_failure():
    schema, failures = {}, []
    parse_schema_from_sql(
        "CREATE TABLE a (", schema, source="broken.sql", failures=failures
    )
    assert not schema
    assert failures[0].source == "broken.sql"
    assert "Parse error" in failures[0].reason
