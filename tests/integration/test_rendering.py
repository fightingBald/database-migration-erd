import os
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from erd_generator.d2 import build_d2
from erd_generator.d2_geometry import measure_layout
from erd_generator.d2_renderer import D2_VERSION, D2RenderConfig, render_d2
from erd_generator.schema import Column, ForeignKey, Table
from erd_generator.sql_parser import load_schema_result, parse_schema_from_sql
from tests.support import ROOT

pytestmark = pytest.mark.integration
NS = "{http://www.w3.org/2000/svg}"


@pytest.fixture(scope="module", autouse=True)
def require_pinned_d2():
    result = subprocess.run(
        ["d2", "--version"], capture_output=True, text=True, check=True, timeout=10
    )
    assert result.stdout.strip().removeprefix("v") == D2_VERSION, (
        "Install the pinned D2; rendering tests must not be silently skipped"
    )


@pytest.mark.parametrize("style", ["classic", "clean"])
def test_self_reference_compiles_with_metadata_and_style(tmp_path, style):
    schema = {}
    parse_schema_from_sql(
        "CREATE TABLE node (id INT PRIMARY KEY, parent_id INT REFERENCES node(id));",
        schema,
    )
    source = build_d2(schema, show_types=True, style=style)
    assert '"node"."parent_id" -> "node"."id"' in source
    path = tmp_path / "simple.d2"
    path.write_text(source, encoding="utf-8")
    subprocess.run(
        ["d2", "validate", str(path)],
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    )
    render_d2(path, tmp_path / "simple.svg")
    root = ET.parse(tmp_path / "simple.svg").getroot()
    assert "node" in ["".join(e.itertext()) for e in root.iter(NS + "text")]
    assert any("parent_id" in (e.text or "") for e in root.iter(NS + "title"))
    if style == "clean":
        # Check native SVG colors so a renderer silently ignoring the source
        # palette cannot pass just because the D2 text contains style settings.
        headers = [
            e for e in root.iter(NS + "rect") if "class_header" in e.get("class", "")
        ]
        assert headers and all(e.get("fill") == "#DFE9F5" for e in headers)
        texts = {"".join(e.itertext()): e for e in root.iter(NS + "text")}
        assert texts["id"].get("fill") == "#334155"
        assert texts["PK"].get("fill") == "#0F766E"
        connections = [
            e
            for e in root.iter(NS + "path")
            if "connection" in e.get("class", "").split()
        ]
        assert connections and all(e.get("stroke") == "#64748B" for e in connections)


@pytest.mark.parametrize("syntax", ["named", "positional", "positional-uppercase"])
def test_cli_uses_elk_even_if_environment_requests_dagre(tmp_path, syntax):
    env = dict(os.environ, D2_LAYOUT="dagre", D2_WATCH="true")
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1.sql").write_text(
        "CREATE TABLE parent (id BIGSERIAL PRIMARY KEY);\n"
        "CREATE TABLE child (id BIGSERIAL PRIMARY KEY, parent_id BIGINT, obsolete INT);\n"
    )
    (migrations / "V2.sql").write_text("ALTER TABLE child DROP COLUMN obsolete;\n")
    config = tmp_path / "fk.yaml"
    config.write_text("child:\n  fks:\n    - [parent_id, parent, id]\n")
    output = tmp_path / (
        "schema.SVG" if syntax == "positional-uppercase" else "schema.svg"
    )
    arguments = (
        [
            "--migrations",
            str(migrations),
            "--out",
            str(tmp_path / "schema.d2"),
            "--show-types",
            "--render",
            "svg",
        ]
        if syntax == "named"
        else [str(migrations), str(output)]
    )
    if syntax != "positional":
        arguments.extend(["--fk-config", str(config)])
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "erd_generator",
            *arguments,
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "layout=elk" in result.stderr
    source = tmp_path / "schema.d2"
    assert str(output) in result.stdout
    expected_files = {output, migrations, config}
    if syntax == "named":
        assert str(source) in result.stdout
        assert '"id": "BIGSERIAL" {constraint: primary_key}' in source.read_text()
        assert "foreign_key" in source.read_text()
        expected_files.add(source)
    else:
        assert not source.exists()
        assert ".d2" not in result.stdout
    assert set(tmp_path.iterdir()) == expected_files
    root = ET.parse(output).getroot()
    texts = ["".join(e.itertext()) for e in root.iter(NS + "text")]
    assert "BIGSERIAL" in texts
    assert ("FK" in texts) == (syntax != "positional")
    assert {"parent", "child", "parent_id"}.issubset(texts)
    assert "obsolete" not in texts


@pytest.mark.parametrize("style", ["classic", "clean"])
def test_literals_and_reserved_keys_survive_real_compilation(tmp_path, style):
    table_name = 'public.${literal}."quoted"\\路径'
    names = [
        "shape",
        "style",
        "tooltip",
        "constraint",
        "vars",
        "a.b",
        'a"b',
        "${unknown}",
        "back\\slash",
        "列名",
    ]
    table = Table(
        table_name,
        columns=[Column(name, "numeric(12, 2)") for name in names],
        primary_key={"shape"},
        foreign_keys=[ForeignKey(("a.b",), table_name, ("shape",))],
    )
    source = tmp_path / "literal.d2"
    source.write_text(build_d2({table_name: table}, style=style), encoding="utf-8")
    render_d2(source, tmp_path / "literal.svg", D2RenderConfig(force_appendix=True))
    root = ET.parse(tmp_path / "literal.svg").getroot()
    texts = ["".join(e.itertext()) for e in root.iter(NS + "text")]
    assert table_name in texts
    assert set(names).issubset(texts)


def test_composite_and_cyclic_relations_compile(tmp_path):
    parent = Table(
        "parent", columns=[Column("tenant"), Column("id")], primary_key={"tenant", "id"}
    )
    child = Table(
        "child",
        columns=[Column("tenant"), Column("id")],
        foreign_keys=[
            ForeignKey(("tenant", "id"), "parent", ("tenant", "id"), "fk_parent")
        ],
    )
    parent.foreign_keys.append(ForeignKey(("id",), "child", ("id",)))
    source = tmp_path / "composite.d2"
    source.write_text(
        build_d2({"parent": parent, "child": child, "empty": Table("empty")}),
        encoding="utf-8",
    )
    render_d2(source, tmp_path / "composite.svg")
    texts = [
        "".join(e.itertext())
        for e in ET.parse(tmp_path / "composite.svg").getroot().iter(NS + "text")
    ]
    assert "fk_parent [1/2]" in texts and "fk_parent [2/2]" in texts


def test_postgres_do_migration_renders_real_svg(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1.sql").write_text(
        "CREATE SCHEMA app;\n"
        "CREATE ROLE reader NOLOGIN;\n"
        "ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT SELECT ON TABLES TO reader;\n"
        "DO $ddl$\nBEGIN\n"
        "CREATE TABLE app.parent(id int PRIMARY KEY);\n"
        "CREATE TABLE app.child(id int PRIMARY KEY, parent_id int REFERENCES app.parent(id));\n"
        "END;\n$ddl$;\n"
        "CREATE FUNCTION never_called() RETURNS void LANGUAGE plpgsql AS $$BEGIN DROP TABLE app.parent; END;$$;\n",
        encoding="utf-8",
    )
    output = tmp_path / "schema.svg"
    result = subprocess.run(
        [sys.executable, "-m", "erd_generator", str(migrations), str(output)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert set(tmp_path.iterdir()) == {migrations, output}
    schema = load_schema_result(str(migrations)).schema
    assert set(schema) == {"app.parent", "app.child"}
    assert schema["app.child"].foreign_keys == [
        ForeignKey(("parent_id",), "app.parent", ("id",))
    ]
    measure_layout(output, schema, show_types=True)
    texts = {
        "".join(e.itertext()) for e in ET.parse(output).getroot().iter(NS + "text")
    }
    assert {"app.parent", "app.child", "parent_id", "PK", "FK"}.issubset(texts)
    assert "layout=elk" in result.stderr


def test_library_role_migration_renders_real_svg(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1.sql").write_text(
        "-- +migrate Up\nCREATE SCHEMA demo_library;\n"
        "CREATE TABLE demo_library.members(id int PRIMARY KEY);\n"
        "CREATE TABLE demo_library.loans(id int, member_id int REFERENCES demo_library.members(id));\n"
        + (ROOT / "tests/fixtures/postgres_role_setup.sql")
        .read_text()
        .removeprefix("-- +migrate Up\n"),
        encoding="utf-8",
    )
    output = tmp_path / "schema.svg"
    result = subprocess.run(
        [sys.executable, "-m", "erd_generator", str(migrations), str(output)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert set(tmp_path.iterdir()) == {migrations, output}
    schema = load_schema_result(str(migrations)).schema
    assert set(schema) == {"demo_library.members", "demo_library.loans"}
    assert schema["demo_library.loans"].foreign_keys == [
        ForeignKey(("member_id",), "demo_library.members", ("id",))
    ]
    measure_layout(output, schema, show_types=True)
    texts = {
        "".join(element.itertext())
        for element in ET.parse(output).getroot().iter(NS + "text")
    }
    assert {
        "demo_library.members",
        "demo_library.loans",
        "member_id",
        "PK",
        "FK",
    }.issubset(texts)
    assert "demo_library_reader" not in texts
    assert "layout=elk" in result.stderr
