"""Verify real field semantics before considering a rendered layout candidate."""

import pytest

from erd_generator.d2_geometry import measure_layout
from erd_generator.d2_renderer import D2RenderError
from erd_generator.schema import Column, ForeignKey, Table


SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 200">
<g><rect class="shape" x="20" y="20" width="100" height="108"/>
<rect class="class_header" x="20" y="20" width="100" height="36"/>
<text>a</text><text>id</text><text>INT</text><text>PK</text>
<text>b_id</text><text>INT</text><text>FK</text></g>
<g><rect class="shape" x="220" y="40" width="100" height="72"/>
<rect class="class_header" x="220" y="40" width="100" height="36"/>
<text>b</text><text>id</text><text>INT</text><text>PK</text></g>
<path class="connection" d="M 120 110 L 180 110 L 180 94 L 215 94" marker-end="url(#arrow)"/>
</svg>"""


@pytest.fixture
def diagram(tmp_path):
    schema = {
        "a": Table(
            "a",
            columns=[Column("id", "INT"), Column("b_id", "INT")],
            foreign_keys=[ForeignKey(("b_id",), "b", ("id",))],
        ),
        "b": Table("b", columns=[Column("id", "INT")]),
    }
    path = tmp_path / "schema.svg"
    path.write_text(SVG)
    return path, schema


def test_measures_verified_tables_and_directed_field_routes(diagram):
    metrics = measure_layout(*diagram, show_types=True)
    assert (metrics.width, metrics.height, metrics.table_area) == (400, 200, 18000)
    assert metrics.total_length == metrics.longest == 111
    assert metrics.crossings == 0


@pytest.mark.parametrize(
    "before,after",
    [
        ('marker-end="url(#arrow)"', 'marker-start="url(#arrow)"'),
        ("M 120 110", "M 120 74"),
        ("<text>b_id</text>", "<text>wrong</text>"),
        ("<text>INT</text>", "<text>TEXT</text>"),
        ('x="220"', 'x="80"'),
        ('viewBox="0 0 400 200"', 'viewBox="0 0 nan 200"'),
        ('viewBox="0 0 400 200"', 'viewBox="0 0 0 200"'),
        ('viewBox="0 0 400 200"', 'viewBox="0 0 200 100"'),
        ('class="connection"', 'class="missing"'),
    ],
)
def test_invalid_candidate_is_rejected_without_echoing_schema(diagram, before, after):
    path, schema = diagram
    path.write_text(SVG.replace(before, after))
    with pytest.raises(D2RenderError, match="layout verification failed") as error:
        measure_layout(path, schema, show_types=True)
    assert "b_id" not in str(error.value)


def test_hidden_types_are_still_checked(diagram):
    path, schema = diagram
    path.write_text(SVG.replace("<text>INT</text>", "<text/>"))
    assert measure_layout(path, schema, show_types=False).longest == 111


def test_multiple_constraints_cannot_reuse_one_matching_arrow(diagram):
    path, schema = diagram
    schema["a"].foreign_keys.append(ForeignKey(("id",), "b", ("id",)))
    path.write_text(
        SVG.replace(
            "</svg>",
            '<path class="connection" d="M 120 110 L 215 94" marker-end="url(#arrow)"/></svg>',
        )
    )
    with pytest.raises(D2RenderError, match="field endpoints"):
        measure_layout(path, schema, show_types=True)
