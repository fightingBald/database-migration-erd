import os
import subprocess
import sys

import pytest

from tests.support import FIXTURES, ROOT


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


def test_explicit_d2_output_does_not_start_renderer(tmp_path):
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


@pytest.mark.parametrize("existing_source", [False, True])
def test_svg_failure_cleans_temporary_source_and_preserves_existing_files(
    tmp_path, simple_migrations, existing_source
):
    output = tmp_path / "schema.svg"
    output.write_text("old svg", encoding="utf-8")
    source = output.with_suffix(".d2")
    if existing_source:
        source.write_text("user-maintained source")
    before = set(tmp_path.iterdir())
    result = cli(simple_migrations, output, "--d2-binary", "/nonexistent/d2")
    assert result.returncode == 1
    assert set(tmp_path.iterdir()) == before
    if existing_source:
        assert source.read_text() == "user-maintained source"
    else:
        assert not source.exists()
    assert output.read_text() == "old svg"
    assert "source retained" not in result.stderr
    assert "SVG was not updated" in result.stderr


@pytest.mark.parametrize("positional", [False, True], ids=["named", "positional"])
@pytest.mark.parametrize("existing_source", [False, True])
def test_svg_output_passes_source_in_memory_without_creating_workspace(
    tmp_path, simple_migrations, monkeypatch, capsys, positional, existing_source
):
    from erd_generator.cli import main

    output = tmp_path / "输出 图" / "schema.SVG"
    output.parent.mkdir()
    companion = output.with_suffix(".d2")
    if existing_source:
        companion.write_text("user-maintained source")
    sources = []

    def render(schema, source, image, config, **options):
        assert isinstance(source, str)
        assert "shape: sql_table" in source
        assert options["source_output"] is None
        assert set(output.parent.iterdir()) == (
            {companion} if existing_source else set()
        )
        assert set(schema) == {"customers", "orders"}
        image.write_text("rendered SVG")
        sources.append(source)

    monkeypatch.setattr("erd_generator.d2_refinement.render_optimized", render)
    arguments = (
        [simple_migrations, output]
        if positional
        else ["--migrations", simple_migrations, "--out", output]
    )
    assert main(list(map(str, arguments))) == 0
    assert output.read_text() == "rendered SVG"
    assert sources
    assert set(output.parent.iterdir()) == (
        {output, companion} if existing_source else {output}
    )
    if existing_source:
        assert companion.read_text() == "user-maintained source"
    captured = capsys.readouterr()
    assert str(output) in captured.out
    assert ".d2" not in captured.out


def test_help_shows_explicit_input_and_output():
    result = cli("--help")
    assert result.returncode == 0, result.stderr
    assert "SQL_DIR OUTPUT" in result.stdout
    assert "schema.svg" in result.stdout and "schema.d2" in result.stdout


@pytest.mark.parametrize(
    "render", [False, True], ids=["source-only", "missing-renderer"]
)
def test_cross_group_reference_option_reaches_generated_source(tmp_path, render):
    arguments = input_args(tmp_path, suffix="d2", positional=True)
    config = tmp_path / "layout.yaml"
    config.write_text(
        "groups:\n  parents:\n    tables: [parent]\n  children:\n    tables: [child]\n"
    )
    output = tmp_path / "schema.svg"
    if render:
        output.write_text("previous SVG")
        arguments += ["--render", "svg", "--d2-binary", "/nonexistent/d2"]
    result = cli(
        *arguments,
        "--layout-config",
        config,
        "--show-references",
        env=dict(os.environ, PATH=""),
    )
    assert result.returncode == (1 if render else 0), result.stderr
    assert (
        '"parent_id": "BIGINT" {constraint: "FK → parent.id"}'
        in (tmp_path / "schema.d2").read_text()
    )
    if render:
        assert output.read_text() == "previous SVG"


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
    (migrations / "V1.sql").write_text((FIXTURES / "related_tables.sql").read_text())
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


def test_unknown_fk_config_preserves_formal_output_and_writes_preview(tmp_path):
    config = tmp_path / "fk.yaml"
    config.write_text(
        "missing: {fks: [[id, demo_library.members, id]]}", encoding="utf-8"
    )
    result = cli(*input_args(tmp_path), "--fk-config", config)
    assert result.returncode == 1
    assert not (tmp_path / "schema.d2").exists()
    assert "INCOMPLETE" in (tmp_path / "schema.partial.d2").read_text()


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
    setup = (FIXTURES / "postgres_role_setup.sql").read_text()
    (migrations / "V1.sql").write_text(
        "-- +migrate Up\nCREATE TABLE demo_library.members(id int PRIMARY KEY);\n"
        + setup.removeprefix("-- +migrate Up\n")
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
    result = cli(
        migrations, image, "--log-dir", tmp_path, "--d2-binary", "/nonexistent/d2"
    )
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


@pytest.mark.parametrize("engine", ["grid", "dagre"])
def test_unsupported_layout_does_not_replace_outputs(tmp_path, engine):
    source, image = tmp_path / "schema.d2", tmp_path / "schema.svg"
    source.write_text("old source")
    image.write_text("old image")
    result = cli(*input_args(tmp_path), "--layout", engine)
    assert result.returncode == 2
    assert "invalid choice" in result.stderr
    assert source.read_text() == "old source" and image.read_text() == "old image"


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


def test_excluded_postgres_objects_allow_codegen_but_unknown_index_still_blocks_it(
    tmp_path,
):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__tables.sql").write_text(
        "CREATE TABLE library.books(id int PRIMARY KEY);"
        "CREATE TABLE library.loans(id int, book_id int REFERENCES library.books(id));"
    )
    (migrations / "V2__objects.sql").write_text(
        "CREATE VIEW library.available AS SELECT id FROM library.books;"
        "CREATE MATERIALIZED VIEW library.summary WITH (fillfactor=90) AS SELECT id FROM library.books WITH NO DATA;"
        "CREATE OR REPLACE PROCEDURE library.refresh(n int = 1) LANGUAGE plpgsql "
        "AS $body$BEGIN CREATE TABLE never_run(id int); RAISE NOTICE 'private_payload'; END;$body$;"
        "CALL library.refresh(); DROP PROCEDURE library.refresh(integer);"
        "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
    )
    (migrations / "V3__indexes.sql").write_text(
        "CREATE UNIQUE INDEX ix_summary ON library.summary(id);"
        "DROP MATERIALIZED VIEW library.summary;"
    )
    output = tmp_path / "schema.d2"
    result = cli(migrations, output, "--log-dir", tmp_path)
    assert result.returncode == 0, result.stderr
    source = output.read_text()
    assert source.count("shape: sql_table") == 2
    assert '"library.loans"."book_id" -> "library.books"."id"' in source
    assert "summary" not in source and "never_run" not in source
    assert "private_payload" not in result.stdout + result.stderr
    (migrations / "V4__typo.sql").write_text(
        "CREATE INDEX ix_typo ON library.bokos(id);"
    )
    result = cli(migrations, output, "--log-dir", tmp_path)
    assert result.returncode == 1
    assert "Index references unknown table 'library.bokos'" in result.stderr
    assert output.read_text() == source


@pytest.mark.parametrize("framework", ["migrate", "goose"])
def test_codegen_generates_forward_schema_with_mixed_migration_inputs(
    tmp_path, framework
):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001.sql").write_text("CREATE TABLE books(id int PRIMARY KEY);")
    (migrations / "002.sql").write_text(
        f"-- +{framework} up\n"
        "CREATE TABLE loans(id int, book_id int REFERENCES books(id));\n"
        f"-- +{framework} down\nDROP TABLE loans;"
    )
    (migrations / "003.up.sql").write_text(
        "ALTER TABLE loans ADD COLUMN returned_at date;"
    )
    (migrations / "003.down.sql").write_text(
        "CREATE INDEX should_not_run ON unknown_table(id);"
    )
    output = tmp_path / "schema.d2"
    result = cli(migrations, output, "--log-dir", tmp_path)
    assert result.returncode == 0, result.stderr
    source = output.read_text()
    assert source.count("shape: sql_table") == 2
    assert '"loans"."book_id" -> "books"."id"' in source
    assert "returned_at" in source and "INCOMPLETE" not in source
    assert "Down migration file=1" in result.stderr
    assert "Down migration section=1" in result.stderr
    assert not (tmp_path / "schema.partial.d2").exists()


def test_codegen_rejects_ambiguous_directions_without_replacing_formal_output(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001.sql").write_text("CREATE TABLE books(id int);")
    (migrations / "002.sql").write_text(
        "-- +migrate Up\nCREATE TABLE untrusted(id int);\n-- +migrate Up\n"
    )
    output = tmp_path / "schema.d2"
    output.write_text("last verified diagram")
    result = cli(migrations, output, "--log-dir", tmp_path)
    assert result.returncode == 1
    assert output.read_text() == "last verified diagram"
    assert "002.sql:3" in result.stderr and "more than one Up" in result.stderr
    preview = (tmp_path / "schema.partial.d2").read_text()
    assert "INCOMPLETE" in preview and "untrusted" not in preview


@pytest.mark.parametrize("engine", ["elk", "tala"])
def test_layout_option_works_for_source_only_without_plugin(tmp_path, engine):
    result = cli(*input_args(tmp_path, positional=True), "--layout", engine)
    assert result.returncode == 0, result.stderr
    source = (tmp_path / "schema.d2").read_text()
    assert f"layout-engine: {engine}" in source
    assert '"child"."parent_id" -> "parent"."id"' in source


def test_partial_source_preserves_requested_tala_layout(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001.sql").write_text(
        "CREATE TABLE books(id int); CREATE INDEX ix ON missing(id);"
    )
    result = cli(
        migrations, tmp_path / "schema.d2", "--layout", "tala", "--log-dir", tmp_path
    )
    assert result.returncode == 1
    source = (tmp_path / "schema.partial.d2").read_text()
    assert "layout-engine: tala" in source and "INCOMPLETE" in source
