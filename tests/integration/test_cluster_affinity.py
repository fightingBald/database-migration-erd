"""Exercise native cluster candidates, including nested packed component paths."""

import shutil
from copy import deepcopy

import pytest

from erd_generator.d2 import build_d2
from erd_generator.d2_geometry import measure_layout
from erd_generator.d2_renderer import D2RenderConfig, render_d2
from erd_generator.layout_config import GroupRule, LayoutConfig
from erd_generator.schema import Column, ForeignKey, Index, Table

pytestmark = pytest.mark.integration


def clustered_schema():
    schema, groups = {}, []
    for prefix, count in (
        ("catalog", 3),
        ("lending", 4),
        ("readers", 3),
        ("spaces", 2),
    ):
        names = tuple(f"{prefix}_{i}" for i in range(count))
        groups.append(GroupRule(prefix, names))
        for i, name in enumerate(names):
            schema[name] = Table(
                name,
                columns=[
                    Column(n, "INT") for n in ("tenant", "id", "parent_id", "ref_id")
                ],
                primary_key={"tenant", "id"},
                foreign_keys=[ForeignKey(("parent_id",), names[0], ("id",))]
                if i
                else [],
            )
        schema[names[0]].indexes.append(
            Index(f"ix_{prefix}", ("parent_id",), column_names=("parent_id",))
        )
    for a, b in (
        ("lending_0", "catalog_0"),
        ("readers_0", "lending_0"),
        ("spaces_0", "readers_0"),
        ("catalog_0", "spaces_0"),
    ):
        schema[a].foreign_keys.append(
            ForeignKey(("tenant", "ref_id"), b, ("tenant", "id"))
        )
    schema["readers_0"].foreign_keys.append(
        ForeignKey(("parent_id",), "readers_0", ("id",))
    )
    return schema, LayoutConfig(tuple(groups))


@pytest.mark.parametrize(
    "engine", ["elk", pytest.param("tala", marks=pytest.mark.tala)]
)
@pytest.mark.parametrize("mode", ["ordered", "paired", "packed"])
@pytest.mark.parametrize("direction,packed", [("right", False), ("down", True)])
def test_native_candidates_keep_regions_indexes_and_fk_field_endpoints(
    tmp_path, engine, mode, direction, packed
):
    if engine == "tala" and shutil.which("d2plugin-tala") is None:
        pytest.skip("Optional d2plugin-tala executable is not on PATH")
    schema, config = clustered_schema()
    if packed:
        schema["settings"] = Table("settings", columns=[Column("id", "INT")])
    before = deepcopy(schema)
    source = tmp_path / "schema.d2"
    source.write_text(
        build_d2(
            schema,
            layout_engine=engine,
            cluster_affinity=mode,
            layout_config=config,
            show_types=True,
            direction=direction,
            show_references=True,
            style="classic" if packed else "clean",
        )
    )
    image = source.with_suffix(".svg")
    render_d2(source, image, D2RenderConfig(layout_engine=engine))
    native = image.read_bytes()
    metrics = measure_layout(image, schema, show_types=True, layout_config=config)
    assert metrics.affinity_distance > 0
    assert image.read_bytes() == native
    assert schema == before
