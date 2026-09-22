"""Exercise business groups through pinned D2, including actual SVG field ports."""

import itertools
import xml.etree.ElementTree as ET
from copy import deepcopy

import pytest

from erd_generator.d2 import build_d2
from erd_generator.d2_renderer import render_d2
from erd_generator.layout_config import GroupRule, LayoutConfig
from erd_generator.schema import ForeignKey
from tests.support.schemas import business_schema, related_schema, table
from tests.support.svg import (
    arrow_routes,
    assert_compact,
    assert_fk_arrows,
    assert_named_regions,
    assert_no_overlaps,
    region_boxes,
    table_boxes,
)

pytestmark = pytest.mark.integration


def render(schema, directory, **options):
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "schema.d2"
    source.write_text(build_d2(schema, show_types=True, **options), encoding="utf-8")
    render_d2(source, source.with_suffix(".svg"))
    root = ET.parse(source.with_suffix(".svg")).getroot()
    boxes = table_boxes(root)
    assert set(boxes) == set(schema)
    assert_no_overlaps(boxes)
    assert_fk_arrows(schema, root)
    return root


@pytest.mark.parametrize("direction", ["right", "down"])
def test_auto_business_regions_pack_isolated_tables_without_stretching_rows(
    tmp_path, direction
):
    suffixes = ("details", "files", "links", "contacts", "history", "settings")
    schema = {
        f"demo_library.{prefix}_{suffix}": table(
            f"demo_library.{prefix}_{suffix}", 2 + i % 4
        )
        for prefix in ("books", "loans", "members", "branches")
        for i, suffix in enumerate(suffixes)
    }
    root = render(schema, tmp_path, direction=direction)
    assert_compact(root, table_boxes(root))
    assert_named_regions(root, schema)
    for name, box in table_boxes(root).items():
        assert box["header"] == 36
        assert box["height"] == 36 * (len(schema[name].columns) + 1)


@pytest.mark.parametrize("style", ["clean", "classic"])
@pytest.mark.parametrize("direction", ["right", "left", "up", "down"])
def test_cross_domain_composite_cycles_self_refs_and_colours_keep_row_ports(
    tmp_path, style, direction
):
    schema = business_schema()
    root = render(schema, tmp_path, style=style, direction=direction)
    assert_named_regions(root, schema)
    assert len(arrow_routes(root)) == 31


def test_explicit_group_can_span_disconnected_components_and_quoted_names(tmp_path):
    names = (
        'demo_library.${literal}."quoted"\\路径',
        "style",
        "width",
        "_erd_group_0",
        "other",
        "孤立表",
    )
    schema = {n: table(n, i + 3) for i, n in enumerate(names)}
    schema[names[0]].foreign_keys = [ForeignKey(("field_1",), "style", ("id",))]
    schema["width"].foreign_keys = [ForeignKey(("field_1",), "other", ("id",))]
    config = LayoutConfig(
        (
            GroupRule(
                "one", (names[0], "width", "孤立表"), "借阅 / ${literal}", "gold"
            ),
            GroupRule("two", ("style", "other"), "引用", "green"),
        )
    )
    root = render(schema, tmp_path, layout_config=config)
    assert_named_regions(root, schema, config)


@pytest.mark.parametrize("bridges", [True, False])
def test_shared_hub_does_not_force_forty_tables_into_one_long_strip(tmp_path, bridges):
    schema = related_schema()
    schema["identity"] = table("identity")
    for name, value in schema.items():
        if name == "identity":
            continue
        if not bridges:
            value.foreign_keys = [
                fk for fk in value.foreign_keys if fk.columns != ("other_id",)
            ]
        value.foreign_keys.append(ForeignKey(("id",), "identity", ("id",)))
    root = render(schema, tmp_path)
    assert_compact(root, table_boxes(root))
    lengths = [
        sum(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in itertools.pairwise(route))
        for route in arrow_routes(root)
    ]
    assert max(lengths) < 4800


def test_multiple_shared_hubs_and_uneven_business_group_sizes_keep_all_fields(tmp_path):
    schema = business_schema()
    for name in ("identity", "tenant"):
        schema[name] = table(name, 4)
    for name, value in list(schema.items()):
        if name not in {"identity", "tenant"}:
            value.foreign_keys.extend(
                ForeignKey(("field_2",), hub, ("id",)) for hub in ("identity", "tenant")
            )
    schema["identity"].foreign_keys = [ForeignKey(("field_1",), "tenant", ("id",))]
    for index in range(7):
        name = f"demo_library.books_extension_{index}"
        schema[name] = table(name, 4 + index)
        schema[name].foreign_keys = [
            ForeignKey(("field_1",), "demo_library.books_root", ("id",))
        ]
    before = deepcopy(schema)
    root = render(schema, tmp_path)
    assert_named_regions(root, schema)
    assert schema == before


def test_same_named_families_in_two_schemas_are_distinct_and_output_is_repeatable(
    tmp_path,
):
    schema = {
        f"{ns}.图书_{suffix}": table(f"{ns}.图书_{suffix}")
        for ns in ("live", "archive")
        for suffix in ("详情", "文件", "链接")
    }
    first = render(schema, tmp_path / "first")
    assert_named_regions(first, schema)
    second = render(dict(reversed(list(schema.items()))), tmp_path / "second")
    assert table_boxes(first) == table_boxes(second)
    assert region_boxes(first) == region_boxes(second)
    assert (tmp_path / "first/schema.d2").read_bytes() == (
        tmp_path / "second/schema.d2"
    ).read_bytes()


def test_one_hundred_tables_remain_partitioned_by_business_family(tmp_path):
    schema = {
        f"demo_library.{prefix}_{suffix}": table(
            f"demo_library.{prefix}_{suffix}", 2 + i % 5
        )
        for prefix in ("books", "loans", "members", "branches", "events")
        for i, suffix in enumerate(
            [
                f"{kind}_{n}"
                for kind in ("files", "links", "details", "history")
                for n in range(5)
            ]
        )
    }
    root = render(schema, tmp_path)
    assert_named_regions(root, schema)
    assert_compact(root, table_boxes(root))


@pytest.mark.parametrize("direction", ["right", "down"])
@pytest.mark.parametrize("style", ["clean", "classic"])
def test_large_business_regions_keep_inner_clusters_and_cross_region_ports(
    tmp_path, direction, style
):
    schema = related_schema()
    first = tuple(n for n in schema if int(n[-2:]) % 4 < 2)
    second = tuple(n for n in schema if n not in first)
    config = LayoutConfig(
        (GroupRule("first", first, "First"), GroupRule("second", second, "Second"))
    )
    root = render(
        schema, tmp_path, layout_config=config, direction=direction, style=style
    )
    assert_named_regions(root, schema, config)
    boxes = table_boxes(root)
    domains = {}
    for i in range(4):
        members = [box for n, box in boxes.items() if int(n[-2:]) % 4 == i]
        x, y = min(b["x"] for b in members), min(b["y"] for b in members)
        domains[i] = {
            "x": x,
            "y": y,
            "width": max(b["x"] + b["width"] for b in members) - x,
            "height": max(b["y"] + b["height"] for b in members) - y,
        }
    assert_no_overlaps(domains)
