import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from erd_generator.d2 import build_d2
from erd_generator.d2_renderer import D2RenderConfig, D2_VERSION, render_d2
from erd_generator.schema import Column, ForeignKey, Table
from erd_generator.sql_parser import parse_schema_from_sql

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]
NS = "{http://www.w3.org/2000/svg}"


@pytest.fixture(scope="module", autouse=True)
def require_pinned_d2():
    result = subprocess.run(
        ["d2", "--version"], capture_output=True, text=True, check=True, timeout=10
    )
    assert result.stdout.strip() == D2_VERSION, (
        "Install the pinned D2; rendering tests must not be silently skipped"
    )


def test_golden_source_matches_and_compiles(tmp_path):
    schema = {}
    parse_schema_from_sql((ROOT / "tests/fixtures/simple.sql").read_text(), schema)
    source = build_d2(schema, show_types=True)
    assert source == (ROOT / "tests/fixtures/simple.d2").read_text()
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
    assert "public.users" in ["".join(e.itertext()) for e in root.iter(NS + "text")]
    assert any("manager_id" in (e.text or "") for e in root.iter(NS + "title"))


def test_sample_cli_uses_elk_even_if_environment_requests_dagre(tmp_path):
    env = dict(os.environ, D2_LAYOUT="dagre", D2_WATCH="true")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "erd_generator",
            "--migrations",
            str(ROOT / "db/migration"),
            "--out",
            str(tmp_path / "schema.d2"),
            "--fk-config",
            str(ROOT / "sample_fk_config.yaml"),
            "--show-types",
            "--render",
            "svg",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "layout=elk" in result.stderr
    root = ET.parse(tmp_path / "schema.svg").getroot()
    texts = ["".join(e.itertext()) for e in root.iter(NS + "text")]
    assert {t for t in texts if t.startswith("public.")} == {
        "public.users",
        "public.purchase_orders",
        "public.products",
        "public.order_items",
        "public.roles",
    }
    assert not {"last_login", "order_label"}.intersection(texts)


def test_literals_and_reserved_keys_survive_real_compilation(tmp_path):
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
    source.write_text(build_d2({table_name: table}), encoding="utf-8")
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
