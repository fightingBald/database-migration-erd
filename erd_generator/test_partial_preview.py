from copy import deepcopy

from erd_generator.schema import Column, ForeignKey, Table
from erd_generator import sql_parser, validation


def test_preview_omits_invalid_tables_and_relationships_without_changing_input():
    schema = {
        "parent": Table("parent", [Column("id")], primary_key={"id"}),
        "broken": Table("broken", [Column("id")], primary_key={"missing"}),
        "child": Table(
            "child",
            [Column("parent_id"), Column("other_id")],
            foreign_keys=[
                ForeignKey(("parent_id",), "parent", ()),
                ForeignKey(("other_id",), "broken", ("id",), "fk_broken"),
                ForeignKey(("other_id",), "absent", ("id",), "fk_absent"),
            ],
            constraint_types={"fk_broken": "foreign_key", "fk_absent": "foreign_key"},
        ),
    }
    before = deepcopy(schema)
    preview, omissions = validation.preview_schema(schema)
    assert schema == before
    assert set(preview) == {"parent", "child"}
    assert not validation.validate_schema(preview).errors
    assert preview["child"].foreign_keys == [
        ForeignKey(("parent_id",), "parent", ("id",))
    ]
    assert not preview["child"].constraint_types
    assert len(omissions) == 3
    assert all("omitted" in reason.lower() for reason in omissions)
    assert "broken" in " ".join(omissions) and "absent" in " ".join(omissions)


def test_statement_failure_rolls_back_rename_and_continues_without_payload(monkeypatch):
    original = sql_parser._handle_alter

    def reject_after_mutation(statement, schema):
        original(statement, schema)
        raise ValueError("private_payload")

    monkeypatch.setattr(sql_parser, "_handle_alter", reject_after_mutation)
    schema, failures = {}, []
    sql_parser.parse_schema_from_sql(
        "CREATE TABLE parent(id int PRIMARY KEY);\n"
        "CREATE TABLE child(parent_id int REFERENCES parent(id));\n"
        "ALTER TABLE parent RENAME TO renamed;\n"
        "CREATE TABLE following(id int);",
        schema,
        source="migration.sql",
        failures=failures,
    )
    assert set(schema) == {"parent", "child", "following"}
    assert schema["child"].foreign_keys[0].ref_table == "parent"
    assert len(failures) == 1 and failures[0].line == 3
    assert "private_payload" not in failures[0].reason


def test_skipped_command_summary_is_local_to_each_load(tmp_path):
    (tmp_path / "V1.sql").write_text(
        "CREATE TABLE books(id int); CREATE VIEW available AS SELECT id FROM books;"
        "CALL refresh(); CALL refresh();"
    )
    first = sql_parser.load_schema_result(str(tmp_path))
    second = sql_parser.load_schema_result(str(tmp_path))
    assert first.skipped == second.skipped == {"CREATE VIEW": 1, "CALL": 2}
