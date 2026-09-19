import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def cli(*args, env=None):
    return subprocess.run(
        [sys.executable, "-m", "erd_generator", *map(str, args)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )


def input_args(tmp_path, suffix="d2", *, positional=False):
    migrations = tmp_path / "input" / "migrations"
    migrations.mkdir(parents=True, exist_ok=True)
    (migrations / "V1.sql").write_text(
        "CREATE TABLE parent (id BIGINT PRIMARY KEY);\n"
        "CREATE TABLE child (id BIGINT PRIMARY KEY, parent_id BIGINT);\n"
        "CREATE TABLE obsolete (id INT);\n"
    )
    (migrations / "V2.sql").write_text("DROP TABLE obsolete;\n")
    config = migrations.parent / "fk.yaml"
    config.write_text("child:\n  fks:\n    - [parent_id, parent, id]\n")
    paths = (
        [migrations, tmp_path / f"schema.{suffix}"]
        if positional
        else [
            "--migrations",
            migrations,
            "--out",
            tmp_path / f"schema.{suffix}",
        ]
    )
    return [
        *paths,
        "--fk-config",
        config,
        "--log-dir",
        tmp_path,
    ]


def test_default_entrypoint_generates_d2_without_starting_renderer(tmp_path):
    result = cli(*input_args(tmp_path), "--d2-binary", "/nonexistent/d2")
    # A renderer-only flag must not be silently ignored in source-only mode.
    assert result.returncode == 2
    result = cli(*input_args(tmp_path))
    assert result.returncode == 0, result.stderr
    source = (tmp_path / "schema.d2").read_text()
    assert "layout-engine: elk" in source
    assert source.count("shape: sql_table") == 2
    assert "obsolete" not in source
    assert '"child"."parent_id" -> "parent"."id"' in source
    assert '"id": ""' in source
    assert not (tmp_path / "schema.svg").exists()


@pytest.fixture
def simple_migrations(tmp_path):
    migrations = tmp_path / "SQL 输入"
    migrations.mkdir()
    (migrations / "V1__tables.sql").write_text(
        "CREATE TABLE customers (id integer PRIMARY KEY);\n"
        "CREATE TABLE orders (id integer PRIMARY KEY, customer_id integer);\n",
        encoding="utf-8",
    )
    return migrations


def test_positional_d2_has_types_without_renderer_or_implicit_config(
    tmp_path, simple_migrations
):
    output = tmp_path / "输出 图" / "schema.d2"
    result = cli(simple_migrations, output, env=dict(os.environ, PATH=""))
    assert result.returncode == 0, result.stderr
    source = output.read_text()
    assert source.count("shape: sql_table") == 2
    assert '"id": "INT" {constraint: primary_key}' in source
    assert "theme-overrides:" in source
    assert "direction: right" in source
    assert "foreign_key" not in source
    assert not output.with_suffix(".svg").exists()
    assert str(output) in result.stdout


def test_positional_options_can_hide_types_and_add_relationships(
    tmp_path, simple_migrations
):
    config = tmp_path / "fk.yaml"
    config.write_text(
        "orders:\n  fks:\n    - [customer_id, customers, id]\n", encoding="utf-8"
    )
    output = tmp_path / "schema.d2"
    result = cli(
        simple_migrations,
        output,
        "--hide-types",
        "--fk-config",
        config,
        "--direction",
        "down",
        "--style",
        "classic",
    )
    assert result.returncode == 0, result.stderr
    source = output.read_text()
    assert '"id": "" {constraint: primary_key}' in source
    assert '"orders"."customer_id" -> "customers"."id"' in source
    assert "direction: down" in source
    assert "theme-overrides:" not in source


@pytest.mark.parametrize(
    "options",
    [
        [],
        ["INPUT"],
        ["--migrations", "INPUT"],
        ["--out", "OUTPUT"],
        ["INPUT", "--out", "OUTPUT"],
        ["INPUT", "OUTPUT", "--migrations", "INPUT"],
        ["INPUT", "OUTPUT", "--out", "OUTPUT"],
    ],
    ids=[
        "no-paths",
        "missing-output",
        "named-missing-output",
        "named-missing-input",
        "mixed-syntax",
        "duplicate-input",
        "duplicate-output",
    ],
)
def test_required_paths_and_mixed_syntax_fail_before_writing(
    tmp_path, simple_migrations, options
):
    output = tmp_path / "schema.d2"
    paths = {"INPUT": simple_migrations, "OUTPUT": output}
    result = cli(*(paths.get(option, option) for option in options))
    assert result.returncode == 2
    assert "SQL_DIR" in result.stderr and "OUTPUT" in result.stderr
    assert not output.exists()


@pytest.mark.parametrize(
    "suffix,options",
    [("png", []), ("", []), ("drawio", []), ("xml", [])],
)
def test_positional_output_rejects_unsupported_formats(
    tmp_path, simple_migrations, suffix, options
):
    output = tmp_path / (f"schema.{suffix}" if suffix else "schema")
    result = cli(simple_migrations, output, *options)
    assert result.returncode == 2
    assert not output.exists()
    assert not output.with_suffix(".d2").exists()


def test_positional_svg_failure_retains_source_and_previous_image(
    tmp_path, simple_migrations
):
    output = tmp_path / "schema.svg"
    output.write_text("old svg", encoding="utf-8")
    result = cli(simple_migrations, output, "--d2-binary", "/nonexistent/d2")
    assert result.returncode == 1
    source = output.with_suffix(".d2")
    assert source.is_file()
    assert '"id": "INT"' in source.read_text()
    assert output.read_text() == "old svg"
    assert f"D2 source retained at {source}" in result.stderr
    assert "SVG was not updated" in result.stderr


def test_help_shows_explicit_input_and_output():
    result = cli("--help")
    assert result.returncode == 0, result.stderr
    assert "SQL_DIR OUTPUT" in result.stdout
    assert "schema.svg" in result.stdout and "schema.d2" in result.stdout


def test_business_groups_are_automatic_and_can_be_overridden_without_renderer(tmp_path):
    migrations = tmp_path / "sql"
    migrations.mkdir()
    (migrations / "V1.sql").write_text(
        "\n".join(
            f"CREATE TABLE {n} (id INT PRIMARY KEY);"
            for n in ("books", "books_details", "books_files", "audit")
        )
    )
    output = tmp_path / "schema.d2"
    result = cli(migrations, output, env=dict(os.environ, PATH=""))
    assert result.returncode == 0, result.stderr
    assert 'label: "Books' in output.read_text()
    config = tmp_path / "layout.yaml"
    config.write_text(
        'groups:\n  custom:\n    tables: ["books", "books_*", "audit"]\n    label: 图书\n    color: gold\n'
    )
    result = cli(
        migrations,
        output,
        "--layout-config",
        config,
        "--grouping",
        "none",
        env=dict(os.environ, PATH=""),
    )
    assert result.returncode == 0, result.stderr
    source = output.read_text()
    assert 'label: "图书' in source and "#FCEDBD" in source
    assert source.count("shape: sql_table") == 4


@pytest.mark.parametrize(
    "payload",
    [
        "groups: [",
        "groups: {one: {tables: [absent]}}",
        "groups: {one: {tables: [customers]}, two: {tables: [customers]}}",
    ],
)
def test_invalid_layout_configuration_preserves_both_outputs(
    tmp_path, simple_migrations, payload
):
    config = tmp_path / "layout.yaml"
    config.write_text(payload)
    source, svg = tmp_path / "schema.d2", tmp_path / "schema.svg"
    source.write_text("old source")
    svg.write_text("old image")
    result = cli(
        simple_migrations, svg, "--layout-config", config, "--log-dir", tmp_path
    )
    assert result.returncode == 1
    assert "Layout config" in result.stderr
    assert source.read_text() == "old source" and svg.read_text() == "old image"


def test_clean_style_is_default_and_classic_can_be_selected(tmp_path):
    args = input_args(tmp_path)
    result = cli(*args)
    assert result.returncode == 0, result.stderr
    source = tmp_path / "schema.d2"
    assert "theme-overrides:" in source.read_text()
    result = cli(*args, "--style", "classic")
    assert result.returncode == 0, result.stderr
    assert "theme-overrides:" not in source.read_text()
    assert source.read_text().count("shape: sql_table") == 2


def test_grouping_can_be_disabled_without_changing_the_default_command(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1.sql").write_text(
        (ROOT / "tests/fixtures/related_tables.sql").read_text()
    )
    output = tmp_path / "schema.d2"
    result = cli(migrations, output)
    assert result.returncode == 0, result.stderr
    assert "_erd_group_" in output.read_text()
    result = cli(migrations, output, "--grouping", "none")
    assert result.returncode == 0, result.stderr
    assert "_erd_group_" not in output.read_text()


@pytest.mark.parametrize("positional", [False, True], ids=["named", "positional"])
@pytest.mark.parametrize(
    "options",
    [
        ["--direction", "diagonal"],
        ["--render-timeout", "0", "--render", "svg"],
        ["--force-appendix"],
        ["--render", "png"],
        ["--style", "unknown"],
        ["--grouping", "unknown"],
    ],
)
def test_invalid_d2_options_fail_before_writing(tmp_path, options, positional):
    result = cli(*input_args(tmp_path, positional=positional), *options)
    assert result.returncode == 2
    assert not (tmp_path / "schema.d2").exists()


def test_mismatched_extension_rejected(tmp_path):
    result = cli(*input_args(tmp_path, "drawio"))
    assert result.returncode == 2
    assert not (tmp_path / "schema.drawio").exists()


@pytest.mark.parametrize("positional", [False, True], ids=["named", "positional"])
def test_detected_parse_failure_cannot_overwrite_good_source(tmp_path, positional):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1.sql").write_text(
        "CREATE TABLE a (id int); CREATE TABLE secret_payload (", encoding="utf-8"
    )
    output = tmp_path / "schema.d2"
    output.write_text("old source", encoding="utf-8")
    image = output.with_suffix(".svg")
    image.write_text("old svg", encoding="utf-8")
    args = (
        [migrations, image]
        if positional
        else ["--migrations", migrations, "--out", output]
    )
    result = cli(*args, "--log-dir", tmp_path)
    assert result.returncode == 1
    assert "secret_payload" not in result.stdout + result.stderr
    assert output.read_text() == "old source"
    assert image.read_text() == "old svg"
    logs = list((tmp_path / "parse_log").glob("*.log"))
    assert len(logs) == 1
    assert "secret_payload" not in logs[0].read_text()


def test_missing_renderer_preserves_old_svg(tmp_path):
    (tmp_path / "schema.svg").write_text("old svg", encoding="utf-8")
    result = cli(
        *input_args(tmp_path), "--render", "svg", "--d2-binary", "/nonexistent/d2"
    )
    assert result.returncode == 1
    assert (tmp_path / "schema.d2").is_file()
    assert (tmp_path / "schema.svg").read_text() == "old svg"
    assert "SVG was not updated" in result.stderr


def test_unknown_fk_config_prevents_partial_diagram(tmp_path):
    config = tmp_path / "fk.yaml"
    config.write_text(
        "missing: {fks: [[id, demo_library.members, id]]}", encoding="utf-8"
    )
    result = cli(*input_args(tmp_path), "--fk-config", config)
    assert result.returncode == 1
    assert not (tmp_path / "schema.d2").exists()


def test_postgres_setup_and_static_do_generate_without_credentials_in_logs(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__setup.sql").write_text(
        "CREATE SCHEMA app;\n"
        "CREATE USER reader PASSWORD 'private;credential';\n"
        "ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT SELECT ON TABLES TO reader;\n"
        "DO $migration$ BEGIN CREATE TABLE app.items(id int PRIMARY KEY); END; $migration$;\n",
        encoding="utf-8",
    )
    output = tmp_path / "schema.d2"
    result = cli(migrations, output, "--log-dir", tmp_path)
    assert result.returncode == 0, result.stderr
    assert '"app.items"' in output.read_text()
    assert "private;credential" not in result.stdout + result.stderr
    assert not (tmp_path / "parse_log").exists()


def test_library_role_migration_preserves_surrounding_ddl(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    setup = (ROOT / "tests/fixtures/postgres_role_setup.sql").read_text()
    (migrations / "V1.sql").write_text(
        "CREATE TABLE demo_library.members(id int PRIMARY KEY);\n"
        + setup
        + "\nCREATE TABLE demo_library.loans(id int, member_id int REFERENCES demo_library.members(id));\n",
        encoding="utf-8",
    )
    output = tmp_path / "schema.d2"
    result = cli(migrations, output, "--log-dir", tmp_path)
    assert result.returncode == 0, result.stderr
    source = output.read_text()
    assert source.count("shape: sql_table") == 2
    assert '"demo_library.loans"."member_id" -> "demo_library.members"."id"' in source
    assert "demo_library_reader" not in source
    assert not (tmp_path / "parse_log").exists()


@pytest.mark.parametrize(
    "body,reason",
    [
        (
            "DO $$ BEGIN CREATE TABLE staged(id int); EXECUTE 'private_payload'; END; $$;",
            "Unsupported DO",
        ),
        (
            "DO $missing$ BEGIN RAISE NOTICE 'private_payload'; END;",
            "Unterminated SQL token",
        ),
        (
            "DO $$ BEGIN IF true THEN GRANT SELECT ON keep TO reader; "
            "ELSE EXECUTE format('DROP TABLE %I', 'private_payload'); END IF; END $$;",
            "Unsupported DO",
        ),
        (
            "DO $$ BEGIN EXECUTE format('GRANT SELECT ON keep TO %I', "
            "private_payload()); END $$;",
            "Unsupported DO",
        ),
    ],
    ids=["dynamic-do", "unclosed-dollar-quote", "hidden-ddl", "argument-call"],
)
def test_unsupported_postgres_input_preserves_both_outputs(tmp_path, body, reason):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1.sql").write_text(
        "CREATE TABLE keep(id int);\n" + body, encoding="utf-8"
    )
    source, image = tmp_path / "schema.d2", tmp_path / "schema.svg"
    source.write_text("old source", encoding="utf-8")
    image.write_text("old image", encoding="utf-8")
    result = cli(migrations, image, "--log-dir", tmp_path)
    assert result.returncode == 1
    assert source.read_text() == "old source"
    assert image.read_text() == "old image"
    assert reason in result.stderr
    assert "private_payload" not in result.stdout + result.stderr
    logs = list((tmp_path / "parse_log").glob("*.log"))
    assert len(logs) == 1
    assert reason in logs[0].read_text()
    assert "private_payload" not in logs[0].read_text()


def test_output_directory_is_not_writable_file(tmp_path):
    parent = tmp_path / "blocked"
    parent.write_text("file", encoding="utf-8")
    result = cli(*input_args(tmp_path), "--out", parent / "schema.d2")
    assert result.returncode == 1
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    "options",
    [
        ["--format", "d2"],
        ["--format", "drawio"],
        ["--layout", "elk"],
        ["--layout", "grid"],
        ["--per-row", "2"],
        ["--graphviz-prog", "dot"],
        ["--graphviz-scale", "1"],
        ["--graphviz-spacing", "100"],
    ],
)
def test_removed_backend_options_fail_without_replacing_outputs(tmp_path, options):
    source, image = tmp_path / "schema.d2", tmp_path / "schema.svg"
    source.write_text("old source")
    image.write_text("old image")
    result = cli(*input_args(tmp_path), *options)
    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr
    assert source.read_text() == "old source"
    assert image.read_text() == "old image"


def test_python_entrypoint_uses_same_d2_workflow_as_module_cli(tmp_path):
    from erd_generator import (
        ParseFailure,
        build_d2,
        get_last_parse_failures,
        load_schema_from_migrations,
        main,
    )

    arguments = input_args(tmp_path, positional=True)
    assert main(list(map(str, arguments))) == 0
    source = tmp_path / "schema.d2"
    expected = source.read_bytes()
    result = cli(*arguments)
    assert result.returncode == 0, result.stderr
    assert source.read_bytes() == expected
    assert "shape: sql_table" in source.read_text()
    assert callable(build_d2)
    assert callable(get_last_parse_failures) and callable(load_schema_from_migrations)
    assert ParseFailure(None, "", "failure").reason == "failure"
