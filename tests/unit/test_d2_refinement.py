"""Layout selection must improve geometry without weakening output guarantees."""

import logging
from dataclasses import replace

import pytest

from erd_generator import d2_refinement
from erd_generator.d2_geometry import (
    LayoutMetrics,
    improves_affinity,
    improves_layout,
    improves_packing,
    improves_partitioned,
)
from erd_generator.d2_renderer import D2RenderConfig, D2RenderError
from erd_generator.layout_config import GroupRule, LayoutConfig
from erd_generator.schema import Column, ForeignKey, Table

BASE = LayoutMetrics(1000, 800, 100000, 8000, 2000, 40)
BETTER = replace(BASE, width=800, total_length=7000, longest=1800)


@pytest.mark.parametrize(
    "candidate",
    [
        BASE,
        replace(BASE, width=980),
        replace(BETTER, total_length=8001),
        replace(BETTER, longest=2001),
        replace(BETTER, height=1001),
        replace(BETTER, width=300),  # Narrower area alone can produce a strip.
        replace(BETTER, crossings=43),
    ],
)
def test_rejects_ties_small_gains_and_regressions(candidate):
    assert not improves_layout(candidate, BASE)


def test_accepts_smaller_canvas_with_shorter_routes_and_bounded_crossings():
    assert improves_layout(BETTER, BASE)
    assert improves_layout(replace(BETTER, crossings=42), BASE)
    assert improves_layout(replace(BETTER, width=900, height=500), BASE)


def test_packing_allows_a_small_total_route_tradeoff_for_material_area_gain():
    baseline = replace(BASE, affinity_distance=1000)
    candidate = replace(BETTER, total_length=8160, affinity_distance=900)
    assert improves_packing(candidate, baseline)
    for changes in (
        {"width": 950},
        {"total_length": 8241},
        {"longest": 2001},
        {"crossings": 43},
        {"affinity_distance": 1001},
        {"height": 1001},
    ):
        assert not improves_packing(replace(candidate, **changes), baseline)


def test_packing_cannot_replace_an_existing_better_candidate():
    assert not improves_packing(BASE, BETTER)


def test_partitioning_requires_major_compaction_and_bounded_routing_tradeoffs():
    baseline = replace(
        BASE, width=1000, height=3000, affinity_distance=1000, crossing_points=5
    )
    candidate = replace(baseline, width=1400, height=1200, crossing_points=10)
    assert improves_partitioned(candidate, baseline, 40)
    for changes in (
        {"width": 2000},
        {"longest": 2001},
        {"total_length": 8900},
        {"crossing_points": 16},
        {"crossings": 121},
        {"affinity_distance": 1101},
    ):
        assert not improves_partitioned(replace(candidate, **changes), baseline, 40)


@pytest.mark.parametrize(
    "changes",
    [
        {"affinity_distance": 960},
        {"width": 1001},
        {"height": 801},
        {"total_length": 8001},
        {"longest": 2001},
        {"crossings": 43},
        {"width": 300, "height": 800},
    ],
)
def test_closer_clusters_cannot_hide_other_layout_regressions(changes):
    baseline = replace(BASE, affinity_distance=1000)
    candidate = replace(baseline, affinity_distance=800)
    assert not improves_affinity(replace(candidate, **changes), baseline)


def test_affinity_gain_does_not_require_shrinking_the_whole_canvas():
    baseline = replace(BASE, affinity_distance=1000)
    assert improves_affinity(replace(baseline, affinity_distance=950), baseline)
    assert not improves_affinity(BASE, BASE)


def render_export(schema, source, output, config=None, **options):
    """Exercise refinement with an explicitly requested D2 export."""
    return d2_refinement.render_optimized(
        schema, source.read_text(), output, config, source_output=source, **options
    )


@pytest.fixture
def refinement(tmp_path, monkeypatch):
    source, output = tmp_path / "schema.d2", tmp_path / "schema.svg"
    source.write_text("baseline")
    output.write_text("previous SVG")
    schema = {f"t{i}": Table(f"t{i}", columns=[Column("id", "INT")]) for i in range(12)}
    calls = []

    def render(content, config):
        calls.append(content)
        return content + " SVG"

    monkeypatch.setattr(d2_refinement, "render_source", render)
    monkeypatch.setattr(d2_refinement, "build_d2", lambda *a, **kw: "candidate")
    monkeypatch.setattr(
        d2_refinement,
        "measure_svg",
        lambda path, *a, **kw: BETTER if path.startswith("candidate") else BASE,
    )
    return schema, source, output, calls


def test_publishes_matching_source_and_svg_and_removes_temporary_files(refinement):
    schema, source, output, calls = refinement
    selected = render_export(schema, source, output)
    assert selected == "compact"
    assert calls == ["baseline", "candidate"]
    assert source.read_text() == "candidate"
    assert output.read_text() == "candidate SVG"
    assert set(source.parent.iterdir()) == {source, output}


@pytest.mark.parametrize("enabled", [False, True])
def test_candidate_preserves_requested_reference_visibility(
    refinement, monkeypatch, enabled
):
    schema, source, output, _calls = refinement
    options = {}

    def candidate(*args, **kwargs):
        options.update(kwargs)
        return "candidate"

    monkeypatch.setattr(d2_refinement, "build_d2", candidate)
    render_export(schema, source, output, show_references=enabled)
    assert options["show_references"] is enabled


@pytest.mark.parametrize("enabled", [False, True])
def test_candidate_and_verification_preserve_index_visibility(
    refinement, monkeypatch, enabled
):
    schema, source, output, _ = refinement
    options = []

    def candidate(*args, **kwargs):
        options.append(kwargs["show_indexes"])
        return "candidate"

    def measure(path, *args, **kwargs):
        options.append(kwargs["show_indexes"])
        return BETTER if path.startswith("candidate") else BASE

    monkeypatch.setattr(d2_refinement, "build_d2", candidate)
    monkeypatch.setattr(d2_refinement, "measure_svg", measure)
    assert render_export(schema, source, output, show_indexes=enabled) == "compact"
    assert options == [enabled, enabled, enabled]


@pytest.mark.parametrize("failure", ["quality", "verification", "render"])
def test_bad_candidate_keeps_successful_baseline(
    refinement, monkeypatch, caplog, failure
):
    caplog.set_level(logging.INFO)
    schema, source, output, calls = refinement
    original_render = d2_refinement.render_source
    original_measure = d2_refinement.measure_svg

    def render(path, config):
        if path == "candidate" and failure == "render":
            raise D2RenderError("D2 render failed")
        return original_render(path, config)

    def measure(path, *a, **kw):
        if path.startswith("candidate"):
            if failure == "verification":
                raise D2RenderError("D2 layout verification failed: field endpoints")
            return replace(BASE, width=1200)
        return original_measure(path, *a, **kw)

    monkeypatch.setattr(d2_refinement, "render_source", render)
    monkeypatch.setattr(d2_refinement, "measure_svg", measure)
    assert render_export(schema, source, output) == "balanced"
    assert source.read_text() == "baseline"
    assert output.read_text() == "baseline SVG"
    assert "baseline" in caplog.text
    assert len(calls) <= 2
    assert set(source.parent.iterdir()) == {source, output}


@pytest.mark.parametrize("failure", [None, "composition", "verification", "quality"])
def test_partitioning_preserves_native_source_and_falls_back_safely(
    affinity_refinement, monkeypatch, failure
):
    schema, source, output, calls, layout, metrics = affinity_refinement
    metrics["baseline"] = replace(
        metrics["baseline"],
        height=3000,
        group_sizes=tuple((f"config:g{i}", 200, 1200) for i in range(4)),
    )
    metrics["composed"] = replace(
        metrics["baseline"], width=1200, height=1200, longest=1700
    )
    monkeypatch.setattr(
        d2_refinement, "build_partitioned_d2", lambda *a, **kw: "independent"
    )

    def compose(*args, **kwargs):
        if failure == "composition":
            raise ValueError("cannot compose")
        return "composed SVG"

    monkeypatch.setattr(d2_refinement, "compose_partitions", compose)
    measure = d2_refinement.measure_svg

    def verify(image, *args, **kwargs):
        if image == "composed SVG" and failure == "verification":
            raise D2RenderError("invalid field endpoint")
        return measure(image, *args, **kwargs)

    monkeypatch.setattr(d2_refinement, "measure_svg", verify)
    if failure == "quality":
        metrics["composed"] = replace(metrics["composed"], longest=4000)
    selected = render_export(schema, source, output, layout_config=layout)
    if failure is None:
        assert selected == "partitioned"
        assert output.read_text() == "composed SVG"
        assert source.read_text() == "baseline"
        assert calls == ["baseline", "independent"]
    else:
        assert selected == "compact-paired"
        assert output.read_text() == "compact:paired SVG"
    assert set(output.parent.iterdir()) == {source, output}


def test_failed_baseline_never_replaces_existing_svg(refinement, monkeypatch):
    schema, source, output, _calls = refinement

    def fail(*a, **kw):
        raise D2RenderError("D2 render failed")

    monkeypatch.setattr(d2_refinement, "render_source", fail)
    with pytest.raises(D2RenderError):
        render_export(schema, source, output)
    assert source.read_text() == "baseline"
    assert output.read_text() == "previous SVG"
    assert set(source.parent.iterdir()) == {source, output}


@pytest.mark.parametrize(
    "mode", ["small", "dense", "identical", "disabled", "appendix"]
)
def test_skips_unnecessary_second_render(refinement, monkeypatch, mode):
    schema, source, output, calls = refinement
    options = {}
    if mode == "small":
        schema = dict(list(schema.items())[:3])
    if mode == "dense":
        monkeypatch.setattr(
            d2_refinement,
            "measure_svg",
            lambda *a, **kw: replace(BASE, table_area=500000),
        )
    if mode == "identical":
        monkeypatch.setattr(d2_refinement, "build_d2", lambda *a, **kw: "baseline")
    if mode == "disabled":
        options["grouping"] = "none"
    if mode == "appendix":
        options["config"] = D2RenderConfig(force_appendix=True)
    assert render_export(schema, source, output, **options) == "balanced"
    assert calls == ["baseline"]


def test_failed_source_publication_keeps_old_svg(refinement, monkeypatch):
    schema, source, output, _calls = refinement

    def fail(*a, **kw):
        raise OSError("publication failed")

    monkeypatch.setattr(d2_refinement, "write_text_atomic", fail)
    with pytest.raises(OSError):
        render_export(schema, source, output)
    assert source.read_text() == "baseline"
    assert output.read_text() == "previous SVG"


def test_rejects_conflicting_output_paths_before_rendering(refinement):
    schema, source, _output, calls = refinement
    with pytest.raises(D2RenderError):
        render_export(schema, source, source)
    assert calls == []


def test_unmeasurable_baseline_skips_optional_refinement(
    refinement, monkeypatch, caplog
):
    schema, source, output, calls = refinement

    def fail(*a, **kw):
        raise D2RenderError("D2 layout verification failed: unexpected SVG structure")

    monkeypatch.setattr(d2_refinement, "measure_svg", fail)
    assert render_export(schema, source, output) == "balanced"
    assert calls == ["baseline"]
    assert output.read_text() == "baseline SVG"
    assert "baseline metrics unavailable" in caplog.text


def test_tala_skips_refinement_without_cross_cluster_links(refinement, monkeypatch):
    schema, source, output, calls = refinement

    def unexpected(*args, **kwargs):
        pytest.fail("ELK refinement must not run for TALA")

    monkeypatch.setattr(d2_refinement, "measure_svg", unexpected)
    monkeypatch.setattr(d2_refinement, "build_d2", unexpected)
    selected = render_export(
        schema, source, output, D2RenderConfig(layout_engine="tala")
    )
    assert calls == ["baseline"]
    assert source.read_text() == "baseline" and output.read_text() == "baseline SVG"
    assert selected == "balanced"


@pytest.fixture
def affinity_refinement(refinement, monkeypatch):
    schema, source, output, calls = refinement
    config = LayoutConfig(
        tuple(
            GroupRule(f"g{i}", tuple(f"t{j}" for j in range(i * 3, i * 3 + 3)))
            for i in range(4)
        )
    )
    for a, b in ((0, 3), (3, 6), (6, 9)):
        schema[f"t{a}"].foreign_keys.append(ForeignKey(("id",), f"t{b}", ("id",)))
    metrics = {
        "baseline": replace(BASE, affinity_distance=1000),
        "compact:none": replace(BETTER, affinity_distance=1100),
        "compact:ordered": replace(
            BETTER, width=790, total_length=6900, affinity_distance=900
        ),
        "compact:paired": replace(
            BETTER, width=780, total_length=6800, affinity_distance=800
        ),
        "balanced:ordered": replace(
            BETTER, width=790, total_length=6900, affinity_distance=900
        ),
        "balanced:paired": replace(
            BETTER, width=780, total_length=6800, affinity_distance=800
        ),
    }
    monkeypatch.setattr(
        d2_refinement,
        "build_d2",
        lambda *a, **kw: (
            f"{kw.get('layout_strategy', 'balanced')}:{kw.get('cluster_affinity', 'none')}"
        ),
    )
    monkeypatch.setattr(
        d2_refinement,
        "measure_svg",
        lambda path, *a, **kw: metrics[path.removesuffix(" SVG")],
    )
    return schema, source, output, calls, config, metrics


@pytest.mark.parametrize("engine", ["elk", "tala"])
def test_selects_closer_clusters_with_bounded_native_renders(
    affinity_refinement, engine
):
    schema, source, output, calls, layout, _ = affinity_refinement
    selected = render_export(
        schema,
        source,
        output,
        D2RenderConfig(layout_engine=engine),
        layout_config=layout,
    )
    expected = "compact:paired" if engine == "elk" else "balanced:paired"
    assert source.read_text() == expected
    assert output.read_text() == expected + " SVG"
    assert selected == expected.replace(":", "-")
    assert len(calls) == (4 if engine == "elk" else 3)
    assert set(source.parent.iterdir()) == {source, output}


@pytest.mark.parametrize("regression", ["area", "distance", "longest", "crossings"])
def test_affinity_compares_against_existing_compact_winner(
    affinity_refinement, regression
):
    schema, source, output, _, layout, metrics = affinity_refinement
    reference = metrics["compact:none"]
    changes = dict(
        area={"width": 900},
        distance={"affinity_distance": 1050},
        longest={"longest": 1900},
        crossings={"crossings": 43},
    )[regression]
    for name in ("compact:ordered", "compact:paired"):
        metrics[name] = replace(
            reference,
            affinity_distance=800,
            **{k: v for k, v in changes.items() if k != "affinity_distance"},
        )
        if regression == "distance":
            metrics[name] = replace(metrics[name], **changes)
    assert render_export(schema, source, output, layout_config=layout) == "compact"
    assert output.read_text() == "compact:none SVG"


def test_candidate_tolerances_cannot_accumulate(affinity_refinement):
    schema, source, output, _, layout, metrics = affinity_refinement
    metrics["compact:ordered"] = replace(metrics["compact:ordered"], crossings=42)
    metrics["compact:paired"] = replace(metrics["compact:paired"], crossings=44)
    assert (
        render_export(schema, source, output, layout_config=layout) == "compact-ordered"
    )
    assert output.read_text() == "compact:ordered SVG"


def test_packing_cannot_accumulate_crossings_from_affinity(affinity_refinement):
    schema, source, output, _, layout, metrics = affinity_refinement
    sizes = (("config:g0", 400, 600), ("config:g1", 300, 500), ("config:g2", 200, 300))
    previous = replace(metrics["compact:paired"], crossings=42, group_sizes=sizes)
    metrics["compact:paired"] = previous
    metrics["compact:packed"] = replace(previous, width=600, crossings=44)
    assert (
        render_export(schema, source, output, layout_config=layout) == "compact-paired"
    )
    assert output.read_text() == "compact:paired SVG"


@pytest.mark.parametrize("outcome", ["better", "worse", "render", "verification"])
def test_measured_packing_uses_previous_winner_and_keeps_it_on_failure(
    affinity_refinement, monkeypatch, outcome
):
    schema, source, output, calls, layout, metrics = affinity_refinement
    sizes = (("config:g0", 400, 600), ("config:g1", 300, 500), ("config:g2", 200, 300))
    previous = replace(metrics["compact:paired"], group_sizes=sizes)
    metrics["compact:paired"] = previous
    metrics["compact:packed"] = replace(
        previous, width=600 if outcome != "worse" else 900
    )
    build, render, measure = (
        d2_refinement.build_d2,
        d2_refinement.render_source,
        d2_refinement.measure_svg,
    )

    def candidate(*args, **kwargs):
        if kwargs.get("cluster_affinity") == "packed":
            assert kwargs["cluster_sizes"] == {key: (w, h) for key, w, h in sizes}
        return build(*args, **kwargs)

    def maybe_render(path, *args, **kwargs):
        if outcome == "render" and path == "compact:packed":
            raise D2RenderError("candidate failure")
        return render(path, *args, **kwargs)

    def maybe_measure(path, *args, **kwargs):
        if outcome == "verification" and path == "compact:packed SVG":
            raise D2RenderError("D2 layout verification failed: field endpoints")
        return measure(path, *args, **kwargs)

    monkeypatch.setattr(d2_refinement, "build_d2", candidate)
    monkeypatch.setattr(d2_refinement, "render_source", maybe_render)
    monkeypatch.setattr(d2_refinement, "measure_svg", maybe_measure)
    selected = render_export(schema, source, output, layout_config=layout)
    expected = "compact:packed" if outcome == "better" else "compact:paired"
    assert source.read_text() == expected
    assert output.read_text() == expected + " SVG"
    assert selected == expected.replace(":", "-")
    assert len(calls) <= 5
    assert set(source.parent.iterdir()) == {source, output}


@pytest.mark.parametrize("failure", ["render", "verification"])
def test_failed_affinity_candidate_keeps_previous_winner(
    affinity_refinement, monkeypatch, failure
):
    schema, source, output, _, layout, _ = affinity_refinement
    name = "render_source" if failure == "render" else "measure_svg"
    original = getattr(d2_refinement, name)

    def fail(path, *args, **kwargs):
        if path.startswith("compact:paired"):
            raise D2RenderError("candidate failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(d2_refinement, name, fail)
    assert (
        render_export(schema, source, output, layout_config=layout) == "compact-ordered"
    )
    assert output.read_text() == "compact:ordered SVG"


def test_identical_affinity_sources_are_rendered_only_once(
    affinity_refinement, monkeypatch
):
    schema, source, output, calls, layout, _ = affinity_refinement
    monkeypatch.setattr(d2_refinement, "build_d2", lambda *a, **kw: "compact:ordered")
    render_export(schema, source, output, layout_config=layout)
    assert calls == ["baseline", "compact:ordered"]


@pytest.mark.parametrize("disabled", ["small", "grouping", "appendix", "one_pair"])
def test_skips_affinity_when_not_applicable(affinity_refinement, disabled):
    schema, source, output, calls, layout, _ = affinity_refinement
    config = D2RenderConfig(layout_engine="tala", force_appendix=disabled == "appendix")
    if disabled == "small":
        schema = {n: t for n, t in schema.items() if n != "t11"}
        layout = LayoutConfig(
            tuple(
                replace(g, tables=tuple(n for n in g.tables if n in schema))
                for g in layout.groups
            )
        )
    if disabled == "one_pair":
        schema["t3"].foreign_keys.clear()
        schema["t6"].foreign_keys.clear()
    assert (
        render_export(
            schema,
            source,
            output,
            config,
            layout_config=layout,
            grouping="none" if disabled == "grouping" else "auto",
        )
        == "balanced"
    )
    assert calls == ["baseline"]
