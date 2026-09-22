import itertools
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path

import pytest

from erd_generator.d2 import build_d2
from erd_generator.d2_geometry import measure_layout
from erd_generator.d2_indexes import index_footer
from erd_generator.d2_renderer import D2RenderConfig, D2RenderError, render_d2
from erd_generator.layout_config import GroupRule, LayoutConfig
from erd_generator.schema import Column, ForeignKey, Index, Table
from erd_generator.sql_parser import load_schema_result

pytestmark = pytest.mark.integration
NS = "{http://www.w3.org/2000/svg}"
HTML_NS = "{http://www.w3.org/1999/xhtml}"


def visible_text(root):
    nodes = list(root.iter(NS + "text"))
    nodes += root.findall(f".//{HTML_NS}span[@data-erd-index-line='true']")
    return "".join("".join(node.itertext()) for node in nodes)


@pytest.mark.parametrize(
    "engine", ["elk", pytest.param("tala", marks=pytest.mark.tala)]
)
@pytest.mark.parametrize("direction", ["right", "left", "up", "down"])
def test_index_captions_follow_actual_table_left_edges(tmp_path, engine, direction):
    if engine == "tala" and shutil.which("d2plugin-tala") is None:
        pytest.skip("Optional d2plugin-tala executable is not on PATH")
    schema = {}
    for name, index_name in (
        ("nodes", "idx_library_invitation_permissions_member_id"),
        ("demo_library.invitation_archive", "ix_created"),
        ('quoted."档案"', "idx_" + "W" * 55),
    ):
        schema[name] = Table(
            name,
            columns=[Column("id", "UUID"), Column("parent_id", "UUID")],
            primary_key={"id"},
            foreign_keys=[ForeignKey(("parent_id",), name, ("id",))],
            indexes=[Index(index_name, ("parent_id",))],
        )
    source = tmp_path / "captions.d2"
    source.write_text(
        build_d2(schema, show_types=True, direction=direction, layout_engine=engine)
    )
    output = source.with_suffix(".svg")
    render_d2(source, output, D2RenderConfig(layout_engine=engine))
    measure_layout(output, schema, show_types=True)
    root = ET.parse(output).getroot()
    headers = {
        group.find(NS + "text").text: group.find(f"{NS}rect[@class='class_header']")
        for group in root.iter(NS + "g")
        if group.find(f"{NS}rect[@class='class_header']") is not None
    }
    for table in schema.values():
        footer = next(
            label
            for label in root.iter(NS + "foreignObject")
            if table.indexes[0].name in "".join(label.itertext())
        )
        lines = footer.findall(f".//{HTML_NS}span[@data-erd-index-line='true']")
        assert any(table.indexes[0].name in "".join(line.itertext()) for line in lines)
        header = headers[table.name]
        assert float(footer.get("x")) == pytest.approx(float(header.get("x")), abs=0.01)
        assert float(footer.get("width")) <= float(header.get("width"))


@pytest.mark.parametrize("hidden", [False, True])
def test_cli_index_visibility_and_source_only_output(tmp_path, hidden):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1.sql").write_text(
        "CREATE TABLE books(id INT PRIMARY KEY, title TEXT); CREATE INDEX ix_title ON books(title);"
    )
    output = tmp_path / "schema.svg"
    arguments = [str(migrations), str(output), *(["--hide-indexes"] if hidden else [])]
    result = subprocess.run(
        [sys.executable, "-m", "erd_generator", *arguments],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert set(tmp_path.iterdir()) == {migrations, output}
    visible = visible_text(ET.parse(output).getroot())
    assert ("INDEX ix_title" in visible) is not hidden
    schema = load_schema_result(str(migrations)).schema
    measure_layout(output, schema, show_types=True, show_indexes=not hidden)
    # D2 source is available only when it is explicitly requested.
    arguments[1] = str(output.with_suffix(".d2"))
    result = subprocess.run(
        [sys.executable, "-m", "erd_generator", *arguments],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    source = output.with_suffix(".d2").read_text()
    assert ("label.near: bottom-left" in source) is not hidden
    assert "Index ix_title" in source
    assert source == build_d2(schema, show_types=True, show_indexes=not hidden)


@pytest.mark.parametrize("direction", ["right", "left", "up", "down"])
@pytest.mark.parametrize("style", ["clean", "classic"])
def test_visible_indexes_preserve_grouping_and_field_endpoints(
    tmp_path, direction, style
):
    schema = {
        "library.books": Table(
            "library.books",
            columns=[
                Column("tenant", "INT"),
                Column("id", "INT"),
                Column("title", "TEXT"),
            ],
            primary_key={"tenant", "id"},
            indexes=[
                Index("ux_title", ("tenant", "title"), unique=True),
                Index("ix_search", ("lower(title)",), method="btree"),
            ],
        ),
        "library.loans": Table(
            "library.loans",
            columns=[
                Column("tenant", "INT"),
                Column("book_id", "INT"),
                Column("returned", "DATE"),
            ],
            foreign_keys=[
                ForeignKey(
                    ("tenant", "book_id"), "library.books", ("tenant", "id"), "fk_book"
                )
            ],
            indexes=[Index("ix_open", ("book_id",), where="returned IS NULL")],
        ),
        "library.tags": Table("library.tags", columns=[Column("id", "INT")]),
    }
    config = LayoutConfig(
        (
            GroupRule("catalog", ("library.books", "library.tags")),
            GroupRule("lending", ("library.loans",)),
        )
    )
    before = deepcopy(schema)
    path = tmp_path / "indexed.d2"
    path.write_text(
        build_d2(
            schema,
            show_types=True,
            direction=direction,
            style=style,
            layout_config=config,
            show_references=True,
        )
    )
    output = path.with_suffix(".svg")
    render_d2(path, output)
    # Includes table membership, column types, overlap, groups and actual FK ports.
    measure_layout(output, schema, show_types=True, layout_config=config)
    root = ET.parse(output).getroot()
    visible = visible_text(root)
    assert all(name in visible for name in ("ux_title", "ix_search", "ix_open"))
    assert "lower(title)" in visible and "returned IS NULL" in visible
    assert "FK → books.id" in visible
    assert schema == before


def test_long_quoted_index_footer_self_loop_and_corrupt_footer_detection(tmp_path):
    name = 'demo.${literal}."quoted"\\档案'
    index = "idx_" + "long_" * 20 + '${literal}_"quoted"|</div>'
    table = Table(
        name,
        columns=[Column("id", "INT"), Column("parent", "INT"), Column("title", "TEXT")],
        primary_key={"id"},
        foreign_keys=[ForeignKey(("parent",), name, ("id",))],
        indexes=[Index(index, ("lower(title)",), where="title <> 'a  b < c'")],
    )
    schema = {name: table}
    source = tmp_path / "literal.d2"
    source.write_text(build_d2(schema, show_types=True))
    output = source.with_suffix(".svg")
    render_d2(source, output)
    measure_layout(output, schema, show_types=True)
    tree = ET.parse(output)
    footer = next(
        e
        for e in tree.getroot().iter(NS + "foreignObject")
        if "INDEX idx_" in "".join(e.itertext())
    )
    spans = footer.findall(f".//{HTML_NS}span[@data-erd-index-line='true']")
    assert "".join("".join(s.itertext()) for s in spans) == "".join(
        index_footer(table, show_types=True).splitlines()
    )
    assert len(spans) >= 2
    original = output.read_bytes()
    # Actual SVG edits here are deliberately invalid test inputs, never output fixes.
    footer.set("y", "0")
    tree.write(output)
    with pytest.raises(D2RenderError, match="index footer"):
        measure_layout(output, schema, show_types=True)
    output.write_bytes(original)
    tree = ET.parse(output)
    footer = tree.find(f".//{NS}foreignObject")
    footer.set("x", str(float(footer.get("x")) - 11))
    tree.write(output)
    with pytest.raises(D2RenderError, match="index footer"):
        measure_layout(output, schema, show_types=True)
    output.write_bytes(original)
    tree = ET.parse(output)
    content = tree.find(f".//{HTML_NS}div[@data-erd-index-footer='true']")
    content.set(
        "style", content.get("style").replace("text-align:left", "text-align:center")
    )
    tree.write(output)
    with pytest.raises(D2RenderError, match="index footer"):
        measure_layout(output, schema, show_types=True)
    output.write_bytes(original)
    table.indexes[0].where = "title IS NULL"
    with pytest.raises(D2RenderError, match="index footer"):
        measure_layout(output, schema, show_types=True)


@pytest.mark.parametrize("connected", [True, False])
def test_forty_indexed_tables_in_six_unequal_automatic_groups(tmp_path, connected):
    schema = {}
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
        "limits",
    )
    roots = []
    for prefix, size in zip(
        ("books", "loans", "members", "fees", "staff", "rooms"),
        (10, 8, 7, 6, 5, 4),
        strict=True,
    ):
        root = f"{prefix}_{suffixes[0]}"
        roots.append(root)
        for i in range(size):
            name = f"{prefix}_{suffixes[i]}"
            schema[name] = Table(
                name,
                columns=[
                    Column("id", "BIGINT"),
                    Column("owner", "BIGINT"),
                    Column("status", "TEXT"),
                ],
                primary_key={"id"},
                foreign_keys=[ForeignKey(("owner",), root, ("id",))]
                if i and connected
                else [],
                indexes=[
                    Index(f"ix_{name}_status", ("status",), where="status = 'open'")
                ],
            )
    if connected:
        for left, right in itertools.pairwise(roots):
            schema[right].foreign_keys.append(ForeignKey(("owner",), left, ("id",)))
    for strategy in ("balanced", "compact"):
        source = tmp_path / f"{strategy}.d2"
        source.write_text(
            build_d2(
                schema, show_types=True, layout_strategy=strategy, show_references=True
            )
        )
        assert source.read_text().count("label.near: top-left") == 6
        output = source.with_suffix(".svg")
        render_d2(source, output)
        measure_layout(output, schema, show_types=True)
