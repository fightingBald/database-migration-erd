import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def run(migrations, output, root, *options):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "erd_generator",
            str(migrations),
            str(output),
            "--log-dir",
            str(root),
            *options,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_error_writes_marked_preview_then_success_cleans_it(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    sql = migrations / "V1.sql"
    sql.write_text(
        "CREATE TABLE books(id int); CREATE INDEX ix ON bokos(id); CREATE TABLE loans(id int);"
    )
    source, image = tmp_path / "schema.d2", tmp_path / "schema.svg"
    source.write_text("old source")
    image.write_text("old image")
    partial = tmp_path / "schema.partial.d2"
    result = run(migrations, source, tmp_path)
    assert result.returncode == 1
    assert source.read_text() == "old source" and image.read_text() == "old image"
    assert partial.is_file()
    assert "INCOMPLETE" in partial.read_text()
    assert "Structure not fully verified" in partial.read_text()
    assert partial.read_text().count("shape: sql_table") == 2
    assert "unknown table 'bokos'" in result.stderr
    assert str(partial) in result.stdout + result.stderr
    sql.write_text("CREATE TABLE books(id int);")
    (tmp_path / "schema.partial.svg").write_text("stale preview")
    result = run(migrations, source, tmp_path)
    assert result.returncode == 0, result.stderr
    assert "INCOMPLETE" not in source.read_text()
    assert not partial.exists() and not (tmp_path / "schema.partial.svg").exists()
    assert image.read_text() == "old image"  # Source-only never replaces the SVG.


def test_lexical_failure_skips_file_but_keeps_scanning_and_never_reuses_stale_preview(
    tmp_path,
):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1.sql").write_text(
        "CREATE TABLE untrusted(id int); DO $$BEGIN NULL;"
    )
    good = migrations / "V2.sql"
    good.write_text("CREATE TABLE following(id int);")
    output = tmp_path / "schema.d2"
    result = run(migrations, output, tmp_path)
    assert result.returncode == 1
    partial = tmp_path / "schema.partial.d2"
    assert (
        '"following"' in partial.read_text() and "untrusted" not in partial.read_text()
    )
    assert "Unterminated SQL token" in result.stderr
    good.write_text("-- no usable tables")
    result = run(migrations, output, tmp_path)
    assert result.returncode == 1 and not partial.exists() and not output.exists()


def test_invalid_foreign_keys_are_reported_and_omitted_from_preview(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1.sql").write_text(
        "CREATE TABLE parent(id int PRIMARY KEY);"
        "CREATE TABLE child(parent_id int REFERENCES parent(id), ghost_id int REFERENCES ghost(id));"
    )
    result = run(migrations, tmp_path / "schema.d2", tmp_path)
    assert result.returncode == 1
    source = (tmp_path / "schema.partial.d2").read_text()
    assert '"child"."parent_id" -> "parent"."id"' in source
    assert '-> "ghost"' not in source and source.count("shape: sql_table") == 2
    assert (
        "omitted" in result.stderr.lower()
        and "unknown target table 'ghost'" in result.stderr
    )


def test_missing_renderer_retains_only_current_partial_source(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1.sql").write_text(
        "CREATE TABLE books(id int); CREATE INDEX ix ON missing(id);"
    )
    image, source = tmp_path / "schema.svg", tmp_path / "schema.d2"
    image.write_text("old image")
    source.write_text("old source")
    (tmp_path / "schema.partial.svg").write_text("stale preview")
    result = run(migrations, image, tmp_path, "--d2-binary", "/nonexistent/d2")
    assert result.returncode == 1
    assert image.read_text() == "old image" and source.read_text() == "old source"
    assert "INCOMPLETE" in (tmp_path / "schema.partial.d2").read_text()
    assert not (tmp_path / "schema.partial.svg").exists()
    assert "D2 executable not found" in result.stderr


def test_partial_preview_reports_omitted_layout_overrides(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1.sql").write_text(
        "CREATE TABLE books(id int); CREATE INDEX ix ON missing(id);"
    )
    config = tmp_path / "layout.yaml"
    config.write_text("groups: {missing: {tables: [missing]}}")
    result = run(
        migrations, tmp_path / "schema.d2", tmp_path, "--layout-config", str(config)
    )
    assert result.returncode == 1
    assert "INCOMPLETE" in (tmp_path / "schema.partial.d2").read_text()
    assert "Layout overrides omitted" in result.stderr
    log = next((tmp_path / "parse_log").glob("*.log")).read_text()
    assert "Layout overrides omitted" in log and "unknown table 'missing'" in log


def test_copied_runtime_runs_directly_from_company_codegen_directory(tmp_path):
    tool = tmp_path / "tools" / "erd-generator"
    shutil.copytree(
        ROOT / "erd_generator",
        tool / "erd_generator",
        ignore=shutil.ignore_patterns("__pycache__", "test_*.py"),
    )
    migrations = tmp_path / "db" / "migrations"
    migrations.mkdir(parents=True)
    (migrations / "V1.sql").write_text(
        "CREATE TABLE books(id int); CREATE INDEX ix ON typo(id);"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "erd_generator",
            "./db/migrations",
            "./generated/schema.d2",
            "--log-dir",
            "./tools/erd-generator",
        ],
        cwd=tmp_path,
        env=dict(os.environ, PYTHONPATH=str(tool)),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1
    assert (tmp_path / "generated/schema.partial.d2").is_file()
    assert not (tmp_path / "generated/schema.d2").exists()
    assert len(list((tool / "parse_log").glob("*.log"))) == 1
    assert not (tmp_path / "parse_log").exists()
