import subprocess
import sys

import pytest

from erd_generator import sql_parser


def test_schema_import_does_not_load_rendering_dependencies():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import erd_generator.schema; "
            "assert not any(m in sys.modules for m in "
            "('erd_generator.cli', 'erd_generator.drawio', 'erd_generator.layout', 'networkx'))",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_load_results_are_independent_of_legacy_last_failures(tmp_path):
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "V1.sql").write_text("CREATE TABLE bad (", encoding="utf-8")
    sql_parser.load_schema_from_migrations(str(broken))
    before = sql_parser.get_last_parse_failures()
    good = tmp_path / "good"
    good.mkdir()
    (good / "V1.sql").write_text("CREATE TABLE good (id int);", encoding="utf-8")
    result = sql_parser.load_schema_result(str(good))
    assert set(result.schema) == {"good"}
    assert not result.failures
    assert sql_parser.get_last_parse_failures() == before


@pytest.mark.parametrize("missing", [True, False])
def test_load_result_rejects_missing_or_empty_inputs(tmp_path, missing):
    with pytest.raises(ValueError, match="migration"):
        sql_parser.load_schema_result(
            str(tmp_path / "missing" if missing else tmp_path)
        )


def test_versioned_migrations_use_numeric_version_order(tmp_path):
    (tmp_path / "V10__drop.sql").write_text("DROP TABLE a;", encoding="utf-8")
    (tmp_path / "V2__create.sql").write_text(
        "CREATE TABLE a (id int);", encoding="utf-8"
    )
    assert not sql_parser.load_schema_result(str(tmp_path)).schema


def test_invalid_encoding_is_not_silently_discarded(tmp_path):
    (tmp_path / "V1.sql").write_bytes(b"CREATE TABLE a (x\xff int);")
    with pytest.raises(UnicodeError):
        sql_parser.load_schema_result(str(tmp_path))


def test_diagnostics_do_not_print_sql_payload(capsys):
    failures = []
    sql_parser.parse_schema_from_sql(
        "CREATE TABLE secret_payload (", {}, failures=failures
    )
    captured = capsys.readouterr()
    assert "secret_payload" not in captured.out + captured.err
    assert failures


def test_parse_error_reports_original_file_line():
    failures = []
    sql_parser.parse_schema_from_sql(
        "CREATE TABLE a (id int);\n\nCREATE TABLE broken (",
        {},
        source="V2.sql",
        failures=failures,
    )
    assert failures[0].line == 3
    assert failures[0].source == "V2.sql"
