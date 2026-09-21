"""Exercise the optional TALA plugin through native D2 SVG rendering."""

from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from erd_generator.d2 import build_d2
from erd_generator.d2_geometry import measure_layout
from erd_generator.d2_renderer import D2RenderConfig, render_d2
from erd_generator.layout_config import GroupRule, LayoutConfig
from erd_generator.schema import Column, ForeignKey, Table
from erd_generator.sql_parser import load_schema_result, parse_schema_from_sql
from erd_generator.validation import preview_schema

pytestmark = [pytest.mark.integration, pytest.mark.tala]
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def require_tala():
    if shutil.which("d2plugin-tala") is None:
        pytest.skip("Optional d2plugin-tala executable is not on PATH")


@pytest.mark.parametrize("direction", ["right", "left", "up", "down"])
def test_grouped_indexes_composite_keys_and_self_references(tmp_path, direction):
    schema = {}
    parse_schema_from_sql(
        "CREATE TABLE library.books(tenant INT, id INT, title TEXT, PRIMARY KEY(tenant,id));"
        "CREATE INDEX ix_title ON library.books(lower(title));"
        "CREATE TABLE library.members(id INT PRIMARY KEY, parent_id INT REFERENCES library.members(id));"
        "CREATE TABLE library.loans(tenant INT, book_id INT, member_id INT REFERENCES library.members(id), returned DATE, "
        "FOREIGN KEY(tenant,book_id) REFERENCES library.books(tenant,id));"
        "CREATE INDEX ix_open ON library.loans(book_id) WHERE returned IS NULL;"
        "CREATE TABLE library.tags(id INT PRIMARY KEY);",
        schema,
    )
    config = LayoutConfig(
        (
            GroupRule("catalog", ("library.books", "library.tags")),
            GroupRule("lending", ("library.loans",)),
            GroupRule("people", ("library.members",)),
        )
    )
    source = tmp_path / "schema.d2"
    source.write_text(
        build_d2(
            schema,
            layout_engine="tala",
            direction=direction,
            show_types=True,
            layout_config=config,
            show_references=True,
        )
    )
    image = source.with_suffix(".svg")
    render_d2(source, image, D2RenderConfig(layout_engine="tala"))
    # Check actual table membership, FK row endpoints, types, footers and overlap.
    measure_layout(image, schema, show_types=True, layout_config=config)
    root = ET.parse(image).getroot()
    assert "FK → books.id" in "".join(root.itertext())


@pytest.mark.parametrize("connected", [True, False])
def test_forty_tables_in_six_unequal_automatic_groups(tmp_path, connected):
    schema = {}
    roots = []
    suffixes = (
        "records",
        "details",
        "notes",
        "tags",
        "links",
        "files",
        "history",
        "settings",
        "events",
    )
    for prefix, count in zip(
        ("books", "loans", "members", "events", "fees", "rooms"), (9, 8, 7, 6, 5, 5)
    ):
        parent = f"{prefix}_records"
        roots.append(parent)
        for i in range(count):
            name = f"{prefix}_{suffixes[i]}"
            schema[name] = Table(
                name,
                columns=[Column("id", "INT"), Column("parent_id", "INT")],
                primary_key={"id"},
                foreign_keys=[ForeignKey(("parent_id",), parent, ("id",))]
                if connected and i
                else [],
            )
    if connected:
        for root in roots[1:]:
            schema[root].foreign_keys.append(
                ForeignKey(("parent_id",), roots[0], ("id",))
            )
    source = tmp_path / "schema.d2"
    source.write_text(build_d2(schema, layout_engine="tala", show_types=True))
    assert source.read_text().count("label.near: top-left") == 6
    image = source.with_suffix(".svg")
    render_d2(source, image, D2RenderConfig(layout_engine="tala"))
    measure_layout(image, schema, show_types=True)


def test_cli_partial_preview_uses_tala_and_preserves_formal_outputs(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1.sql").write_text(
        "CREATE TABLE books(id INT PRIMARY KEY);"
        "CREATE TABLE loans(book_id INT REFERENCES books(id), ghost_id INT REFERENCES missing(id));"
        "CREATE INDEX ix_book ON loans(book_id);"
    )
    source, image = tmp_path / "schema.d2", tmp_path / "schema.svg"
    source.write_text("old source")
    image.write_text("old image")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "erd_generator",
            str(migrations),
            str(image),
            "--layout",
            "tala",
            "--log-dir",
            str(tmp_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1, result.stderr
    assert source.read_text() == "old source" and image.read_text() == "old image"
    partial = tmp_path / "schema.partial.svg"
    assert "layout-engine: tala" in partial.with_suffix(".d2").read_text()
    root = ET.parse(partial).getroot()
    assert any(
        "INCOMPLETE" in "".join(e.itertext())
        for e in root.iter("{http://www.w3.org/2000/svg}text")
    )
    schema, omitted = preview_schema(load_schema_result(str(migrations)).schema)
    assert len(omitted) == 1
    measure_layout(partial, schema, show_types=True)
