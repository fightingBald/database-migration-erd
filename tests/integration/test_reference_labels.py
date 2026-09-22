"""Validate native reference text at real FK rows, including reversed routing."""

import xml.etree.ElementTree as ET

import pytest

from erd_generator.d2 import build_d2
from erd_generator.d2_geometry import measure_layout
from erd_generator.d2_renderer import render_d2
from erd_generator.layout_config import GroupRule, LayoutConfig
from erd_generator.schema import Column, ForeignKey, Table
from tests.support.schemas import business_schema
from tests.support.svg import NS, assert_fk_arrows, assert_named_regions, table_boxes

pytestmark = pytest.mark.integration


def field_markers(root):
    result = {}
    for group in root.iter(NS + "g"):
        if not any(
            "class_header" in r.get("class", "") for r in group.findall(NS + "rect")
        ):
            continue
        texts = group.findall(NS + "text")
        name = "".join(texts[0].itertext())
        for field, marker in zip(texts[1::3], texts[3::3], strict=True):
            result[name, "".join(field.itertext())] = marker
    return result


@pytest.mark.parametrize("direction", ["right", "left", "up", "down"])
@pytest.mark.parametrize(
    "style,types,strategy", [("clean", True, "balanced"), ("classic", False, "compact")]
)
def test_cross_group_composite_labels_stay_at_source_rows(
    tmp_path, direction, style, types, strategy
):
    schema = business_schema()
    source = tmp_path / "schema.d2"
    source.write_text(
        build_d2(
            schema,
            show_types=types,
            show_references=True,
            style=style,
            direction=direction,
            layout_strategy=strategy,
        )
    )
    image = source.with_suffix(".svg")
    render_d2(source, image)
    root = ET.parse(image).getroot()
    measure_layout(image, schema, show_types=types)
    assert_fk_arrows(schema, root)
    assert_named_regions(root, schema)
    boxes, markers = table_boxes(root), field_markers(root)
    expected = {}
    for domain, remote in (
        ("books", "loans"),
        ("loans", "members"),
        ("members", "books"),
    ):
        table = f"demo_library.{domain}_root"
        for field, key in (("field_1", "id"), ("field_3", "field_2")):
            expected[table, field] = f"FK → {remote}_root.{key}"
    found = {
        key: "".join(marker.itertext())
        for key, marker in markers.items()
        if "FK →" in "".join(marker.itertext())
    }
    assert found == expected
    for name, field in expected:
        box, marker = boxes[name], markers[name, field]
        row = next(i for i, col in enumerate(schema[name].columns) if col.name == field)
        assert box["x"] < float(marker.get("x")) < box["x"] + box["width"]
        top = box["y"] + (row + 1) * box["header"]
        assert top < float(marker.get("y")) < top + box["header"]


def test_long_and_unusual_reference_names_render_without_losing_keys(tmp_path):
    field = 'key.${literal}"\\值'
    schema = {
        "entry": Table(
            "entry",
            columns=[Column("ref", "INT")],
            primary_key={"ref"},
            foreign_keys=[
                ForeignKey(("ref",), n, (field,))
                for n in ("alpha.destination", "beta.destination")
            ],
        ),
        **{
            name: Table(name, columns=[Column(field, "INT")])
            for name in ("alpha.destination", "beta.destination")
        },
    }
    config = LayoutConfig(
        tuple(GroupRule(str(i), (name,)) for i, name in enumerate(schema))
    )
    source = tmp_path / "schema.d2"
    source.write_text(
        build_d2(schema, show_types=True, show_references=True, layout_config=config)
    )
    image = source.with_suffix(".svg")
    render_d2(source, image)
    root = ET.parse(image).getroot()
    measure_layout(image, schema, show_types=True, layout_config=config)
    assert_fk_arrows(schema, root)
    marker = field_markers(root)["entry", "ref"]
    assert (
        "".join(marker.itertext())
        == f"PK, FK → alpha.destination.{field}, beta.destination.{field}"
    )
