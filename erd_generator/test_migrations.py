import pytest

from erd_generator.sql_parser import load_schema_result, parse_schema_from_sql


@pytest.mark.parametrize("framework", ["migrate", "goose"])
@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_only_up_changes_survive_across_migrations(tmp_path, framework, ending):
    (tmp_path / "001.sql").write_text(
        ending.join(
            [
                f"-- +{framework} Up",
                "CREATE TABLE books(id int PRIMARY KEY);",
                "CREATE TABLE loans(id int PRIMARY KEY, book_id int REFERENCES books(id));",
                f"-- +{framework} Down",
                "DROP TABLE loans;",
                "DROP TABLE books;",
            ]
        )
    )
    (tmp_path / "002.sql").write_text(
        f"-- +{framework} Up\nALTER TABLE loans ADD COLUMN returned_at date;\n"
        "CREATE INDEX ix_loans_book ON loans(book_id);\n"
        f"-- +{framework} Down\nDROP INDEX ix_loans_book;\n"
        "ALTER TABLE loans DROP COLUMN returned_at;"
    )
    result = load_schema_result(str(tmp_path))
    assert not result.failures
    assert set(result.schema) == {"books", "loans"}
    assert [c.name for c in result.schema["loans"].columns] == [
        "id",
        "book_id",
        "returned_at",
    ]
    assert result.schema["loans"].foreign_keys[0].ref_table == "books"
    assert [i.name for i in result.schema["loans"].indexes] == ["ix_loans_book"]


@pytest.mark.parametrize(
    "body",
    [
        "CREATE TABLE books(note text DEFAULT $$\n-- +migrate Down\n$$);",
        "CREATE TABLE books(note text DEFAULT $message$\n-- +migrate Down\n$message$);",
        "CREATE TABLE books(note text DEFAULT '\n-- +migrate Down\n');",
        'CREATE TABLE "books\n-- +migrate Down\n"(id int);',
        "/* outer /* inner */\n-- +migrate Down\n*/\nCREATE TABLE books(id int);",
        "CREATE PROCEDURE p() LANGUAGE SQL BEGIN ATOMIC\n-- +migrate Down\nSELECT 1; END;\nCREATE TABLE books(id int);",
        "DO $$BEGIN\n-- +migrate Down\nCREATE TABLE books(id int); END;$$;",
    ],
)
def test_marker_text_inside_sql_is_not_a_direction_change(body):
    schema, failures = {}, []
    parse_schema_from_sql(
        f"-- +migrate Up\n{body}\nCREATE TABLE following(id int);\n"
        "-- +migrate Down\nDROP TABLE following;",
        schema,
        failures=failures,
    )
    assert not failures
    assert "following" in schema and len(schema) == 2


def test_fake_up_inside_comment_does_not_turn_plain_sql_into_migration():
    schema, failures = {}, []
    parse_schema_from_sql(
        "/*\n-- +migrate Up\n-- +migrate Down\n*/\nCREATE TABLE books(id int);",
        schema,
        failures=failures,
    )
    assert not failures and set(schema) == {"books"}


def test_down_contents_need_not_be_parseable():
    schema, failures = {}, []
    parse_schema_from_sql(
        "-- +migrate Up notransaction\nCREATE TABLE books(id int);\n"
        "-- +migrate Down notransaction\nDO $unclosed$",
        schema,
        failures=failures,
    )
    assert not failures and set(schema) == {"books"}


@pytest.mark.parametrize("framework", ["migrate", "goose", "Goose"])
def test_direction_annotations_are_case_insensitive(framework):
    schema, failures = {}, []
    parse_schema_from_sql(
        f"-- +{framework} up\nCREATE TABLE books(id int);\n"
        f"-- +{framework} DOWN\nDROP TABLE books;",
        schema,
        failures=failures,
    )
    assert not failures and set(schema) == {"books"}


def test_separate_down_files_are_skipped_before_reading(tmp_path):
    (tmp_path / "001.up.sql").write_text("CREATE TABLE books(id int);")
    (tmp_path / "001.down.sql").write_text("CREATE TABLE should_not_exist(id int);")
    (tmp_path / "002.down.sql").write_bytes(b"invalid utf-8: \xff")
    result = load_schema_result(str(tmp_path))
    assert not result.failures and set(result.schema) == {"books"}


@pytest.mark.parametrize(
    "sql, line",
    [
        ("-- header\n-- +migrate Down\nDROP TABLE books;", 2),
        ("-- +migrate Up\nCREATE TABLE books(id int);\n-- +migrate Up", 3),
        ("-- +migrate Up\nCREATE TABLE books(id int);\n-- +goose Down", 3),
        (
            "CREATE TABLE hidden(id int);\n-- +migrate Up\nCREATE TABLE books(id int);",
            2,
        ),
    ],
)
def test_ambiguous_directions_skip_file_and_continue(tmp_path, sql, line):
    bad = tmp_path / "001.sql"
    bad.write_text(sql)
    (tmp_path / "002.sql").write_text("CREATE TABLE following(id int);")
    result = load_schema_result(str(tmp_path))
    assert set(result.schema) == {"following"}
    assert len(result.failures) == 1
    assert result.failures[0].source == str(bad)
    assert result.failures[0].line == line
    assert "Migration" in result.failures[0].reason


def test_up_error_keeps_original_file_line():
    schema, failures = {}, []
    parse_schema_from_sql(
        "-- header\n\n-- +migrate Up\nCREATE TABLE books(id int);\n"
        "\nCREATE INDEX ix ON missing(id);\n-- +migrate Down\nDROP TABLE books;",
        schema,
        source="001.sql",
        failures=failures,
    )
    assert set(schema) == {"books"}
    assert len(failures) == 1 and failures[0].line == 6


@pytest.mark.parametrize("header", ["", "-- +migrate Up\n", "-- +goose Up\n"])
def test_plain_sql_and_up_without_down_keep_existing_behavior(header):
    schema, failures = {}, []
    parse_schema_from_sql(
        header
        + "CREATE TABLE books(id int); CREATE TABLE old(id int); DROP TABLE old;",
        schema,
        failures=failures,
    )
    assert not failures and set(schema) == {"books"}
