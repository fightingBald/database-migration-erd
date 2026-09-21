"""Layout selection must improve geometry without weakening output guarantees."""

from dataclasses import replace
import logging

import pytest

from erd_generator import d2_refinement
from erd_generator.d2_renderer import D2RenderConfig, D2RenderError
from erd_generator.d2_geometry import LayoutMetrics, improves_layout
from erd_generator.schema import Column, Table


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


@pytest.fixture
def refinement(tmp_path, monkeypatch):
    source, output = tmp_path / "schema.d2", tmp_path / "schema.svg"
    source.write_text("baseline")
    output.write_text("previous SVG")
    schema = {f"t{i}": Table(f"t{i}", columns=[Column("id", "INT")]) for i in range(12)}
    calls = []

    def render(path, target, config):
        content = path.read_text()
        calls.append(content)
        target.write_text(content + " SVG")

    monkeypatch.setattr(d2_refinement, "render_d2", render)
    monkeypatch.setattr(d2_refinement, "build_d2", lambda *a, **kw: "candidate")
    monkeypatch.setattr(
        d2_refinement,
        "measure_layout",
        lambda path, *a, **kw: (
            BETTER if path.read_text().startswith("candidate") else BASE
        ),
    )
    return schema, source, output, calls


def test_publishes_matching_source_and_svg_and_removes_temporary_files(refinement):
    schema, source, output, calls = refinement
    selected = d2_refinement.render_optimized(schema, source, output)
    assert selected == "compact"
    assert calls == ["baseline", "candidate"]
    assert source.read_text() == "candidate"
    assert output.read_text() == "candidate SVG"
    assert set(source.parent.iterdir()) == {source, output}


@pytest.mark.parametrize("enabled", [False, True])
def test_candidate_preserves_requested_reference_visibility(
    refinement, monkeypatch, enabled
):
    schema, source, output, calls = refinement
    options = {}

    def candidate(*args, **kwargs):
        options.update(kwargs)
        return "candidate"

    monkeypatch.setattr(d2_refinement, "build_d2", candidate)
    d2_refinement.render_optimized(schema, source, output, show_references=enabled)
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
        return BETTER if path.read_text().startswith("candidate") else BASE

    monkeypatch.setattr(d2_refinement, "build_d2", candidate)
    monkeypatch.setattr(d2_refinement, "measure_layout", measure)
    assert (
        d2_refinement.render_optimized(schema, source, output, show_indexes=enabled)
        == "compact"
    )
    assert options == [enabled, enabled, enabled]


@pytest.mark.parametrize("failure", ["quality", "verification", "render"])
def test_bad_candidate_keeps_successful_baseline(
    refinement, monkeypatch, caplog, failure
):
    caplog.set_level(logging.INFO)
    schema, source, output, calls = refinement
    original_render = d2_refinement.render_d2
    original_measure = d2_refinement.measure_layout

    def render(path, target, config):
        if path.read_text() == "candidate" and failure == "render":
            raise D2RenderError("D2 render failed")
        return original_render(path, target, config)

    def measure(path, *a, **kw):
        if path.read_text().startswith("candidate"):
            if failure == "verification":
                raise D2RenderError("D2 layout verification failed: field endpoints")
            return replace(BASE, width=1200)
        return original_measure(path, *a, **kw)

    monkeypatch.setattr(d2_refinement, "render_d2", render)
    monkeypatch.setattr(d2_refinement, "measure_layout", measure)
    assert d2_refinement.render_optimized(schema, source, output) == "balanced"
    assert source.read_text() == "baseline"
    assert output.read_text() == "baseline SVG"
    assert "baseline" in caplog.text
    assert len(calls) <= 2
    assert set(source.parent.iterdir()) == {source, output}


def test_failed_baseline_never_replaces_existing_svg(refinement, monkeypatch):
    schema, source, output, calls = refinement

    def fail(*a, **kw):
        raise D2RenderError("D2 render failed")

    monkeypatch.setattr(d2_refinement, "render_d2", fail)
    with pytest.raises(D2RenderError):
        d2_refinement.render_optimized(schema, source, output)
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
            "measure_layout",
            lambda *a, **kw: replace(BASE, table_area=500000),
        )
    if mode == "identical":
        monkeypatch.setattr(d2_refinement, "build_d2", lambda *a, **kw: "baseline")
    if mode == "disabled":
        options["grouping"] = "none"
    if mode == "appendix":
        options["config"] = D2RenderConfig(force_appendix=True)
    assert (
        d2_refinement.render_optimized(schema, source, output, **options) == "balanced"
    )
    assert calls == ["baseline"]


def test_failed_source_publication_keeps_old_svg(refinement, monkeypatch):
    schema, source, output, calls = refinement

    def fail(*a, **kw):
        raise OSError("publication failed")

    monkeypatch.setattr(d2_refinement, "write_text_atomic", fail)
    with pytest.raises(OSError):
        d2_refinement.render_optimized(schema, source, output)
    assert source.read_text() == "baseline"
    assert output.read_text() == "previous SVG"


def test_rejects_conflicting_output_paths_before_rendering(refinement):
    schema, source, output, calls = refinement
    with pytest.raises(D2RenderError):
        d2_refinement.render_optimized(schema, source, source)
    assert calls == []


def test_unmeasurable_baseline_skips_optional_refinement(
    refinement, monkeypatch, caplog
):
    schema, source, output, calls = refinement

    def fail(*a, **kw):
        raise D2RenderError("D2 layout verification failed: unexpected SVG structure")

    monkeypatch.setattr(d2_refinement, "measure_layout", fail)
    assert d2_refinement.render_optimized(schema, source, output) == "balanced"
    assert calls == ["baseline"]
    assert output.read_text() == "baseline SVG"
    assert "baseline metrics unavailable" in caplog.text
