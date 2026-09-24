import subprocess
import tempfile
from pathlib import Path

import pytest

from erd_generator.d2_renderer import (
    D2RenderConfig,
    D2RenderError,
    render_d2,
    render_source,
)

SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text>x</text></svg>'
)


@pytest.fixture
def paths(tmp_path):
    source = tmp_path / "schema with spaces.d2"
    source.write_text("x -> y\n", encoding="utf-8")
    output = tmp_path / "schema with spaces.svg"
    output.write_text("old svg", encoding="utf-8")
    return source, output


def fake_d2(
    monkeypatch, *, version="0.7.1", elk="elk (bundled):", content=SVG, error=None
):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[1] == "--version":
            return subprocess.CompletedProcess(argv, 0, version, "")
        if argv[1] == "layout":
            return subprocess.CompletedProcess(argv, 0, elk, "")
        if error:
            raise error
        return subprocess.CompletedProcess(argv, 0, content, "")

    monkeypatch.setattr(subprocess, "run", run)
    return calls


@pytest.mark.parametrize("version", ["0.7.1", "v0.7.1"])
def test_success_uses_elk_argument_array_and_atomic_output(monkeypatch, paths, version):
    source, output = paths
    monkeypatch.setenv("D2_LAYOUT", "dagre")
    monkeypatch.setenv("D2_WATCH", "true")
    calls = fake_d2(monkeypatch, version=version)
    render_d2(source, output, D2RenderConfig(force_appendix=True))
    argv, kwargs = calls[-1]
    assert argv[argv.index("--layout") + 1] == "elk"
    assert argv[-2:] == ["-", "-"]
    assert kwargs["input"] == source.read_text()
    assert "--force-appendix=true" in argv
    assert "D2_LAYOUT" not in kwargs["env"]
    assert "D2_WATCH" not in kwargs["env"]
    assert kwargs["timeout"] > 0
    assert not kwargs.get("shell", False)
    assert output.read_text() == SVG
    assert set(output.parent.iterdir()) == {source, output}


def test_in_memory_render_never_creates_intermediate_files(monkeypatch, tmp_path):
    calls = fake_d2(monkeypatch)

    def unexpected(*args, **kwargs):
        pytest.fail("Rendering source must not create temporary files or directories")

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", unexpected)
    monkeypatch.setattr(tempfile, "TemporaryDirectory", unexpected)
    assert render_source("node -> other\n") == SVG
    assert calls[-1][0][-2:] == ["-", "-"]
    assert calls[-1][1]["input"] == "node -> other\n"
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "error",
    [
        subprocess.TimeoutExpired(["d2"], 1),
        subprocess.CalledProcessError(1, ["d2"], stderr="secret SQL payload"),
    ],
)
def test_failed_render_preserves_previous_svg_and_source(monkeypatch, paths, error):
    source, output = paths
    fake_d2(monkeypatch, error=error)
    with pytest.raises(D2RenderError) as raised:
        render_d2(source, output)
    assert "secret SQL payload" not in str(raised.value)
    assert output.read_text() == "old svg"
    assert source.read_text() == "x -> y\n"
    assert set(output.parent.iterdir()) == {source, output}


def test_final_atomic_replace_failure_keeps_old_svg_and_removes_staging(
    monkeypatch, paths
):
    source, output = paths
    fake_d2(monkeypatch)

    def fail(*args, **kwargs):
        raise OSError("publication failed")

    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(D2RenderError, match="SVG output failed"):
        render_d2(source, output)
    assert output.read_text() == "old svg"
    assert set(output.parent.iterdir()) == {source, output}


@pytest.mark.parametrize("content", ["", "not XML", "<html/>"])
def test_invalid_svg_cannot_replace_existing_artifact(monkeypatch, paths, content):
    fake_d2(monkeypatch, content=content)
    with pytest.raises(D2RenderError, match="SVG"):
        render_d2(*paths)
    assert paths[1].read_text() == "old svg"


def test_caption_alignment_failure_preserves_previous_artifact(monkeypatch, paths):
    fake_d2(monkeypatch)

    def invalid_caption(svg):
        raise ValueError("index footer bounds")

    monkeypatch.setattr(
        "erd_generator.d2_renderer.align_index_captions", invalid_caption
    )
    with pytest.raises(D2RenderError, match="index footer alignment"):
        render_d2(*paths)
    assert paths[1].read_text() == "old svg"
    assert set(paths[0].parent.iterdir()) == set(paths)


def test_missing_executable_has_actionable_error(monkeypatch, paths):
    def missing(*args, **kwargs):
        raise FileNotFoundError("missing")

    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(D2RenderError, match="executable"):
        render_d2(*paths)


@pytest.mark.parametrize(
    "version,elk,message",
    [
        ("0.6.0", "elk (bundled):", "version"),
        ("v0.6.0", "elk (bundled):", "version"),
        ("v0.7.10", "elk (bundled):", "version"),
        ("v0.7.1-dev", "elk (bundled):", "version"),
        ("vv0.7.1", "elk (bundled):", "version"),
        ("0.7.1", "dagre", "ELK"),
    ],
)
def test_preflight_rejects_incompatible_engine(
    monkeypatch, paths, version, elk, message
):
    calls = fake_d2(monkeypatch, version=version, elk=elk)
    with pytest.raises(D2RenderError, match=message):
        render_d2(*paths)
    assert all("--layout" not in argv for argv, _ in calls)


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_timeout(timeout):
    with pytest.raises(ValueError, match="timeout"):
        D2RenderConfig(timeout=timeout)


def test_tala_uses_plugin_and_isolated_flags_preserving_license_environment(
    monkeypatch, paths, caplog
):
    monkeypatch.setenv("D2_LAYOUT", "elk")
    monkeypatch.setenv("ELK_NODE_NODE", "999")
    monkeypatch.setenv("TALA_SEEDS", "999")
    monkeypatch.setenv("TSTRUCT_TOKEN", "test-license-not-a-real-token")
    calls = fake_d2(monkeypatch, elk="tala (/tmp/d2plugin-tala):")
    render_d2(*paths, D2RenderConfig(layout_engine="tala"))
    assert calls[1][0] == ["d2", "layout", "tala"]
    argv, kwargs = calls[-1]
    assert argv[argv.index("--layout") + 1] == "tala"
    assert not any(arg.startswith("--elk-") for arg in argv)
    assert "TALA_SEEDS" not in kwargs["env"]
    assert "ELK_NODE_NODE" not in kwargs["env"]
    assert kwargs["env"]["TSTRUCT_TOKEN"] == "test-license-not-a-real-token"
    assert "test-license-not-a-real-token" not in caplog.text
    assert paths[1].read_text() == SVG


def test_missing_tala_plugin_has_actionable_error_without_fallback(monkeypatch, paths):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[1] == "--version":
            return subprocess.CompletedProcess(argv, 0, "0.7.1", "")
        raise subprocess.CalledProcessError(1, argv, stderr="private payload")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(D2RenderError, match="d2plugin-tala") as error:
        render_d2(*paths, D2RenderConfig(layout_engine="tala"))
    assert "private payload" not in str(error.value)
    assert calls[-1] == ["d2", "layout", "tala"]
    assert paths[1].read_text() == "old svg"
    assert set(paths[0].parent.iterdir()) == set(paths)


def test_tala_failure_does_not_publish_or_leak_renderer_payload(monkeypatch, paths):
    fake_d2(
        monkeypatch,
        elk="tala (/tmp/d2plugin-tala):",
        error=subprocess.CalledProcessError(1, ["d2"], stderr="private payload"),
    )
    with pytest.raises(D2RenderError) as error:
        render_d2(*paths, D2RenderConfig(layout_engine="tala"))
    assert "private payload" not in str(error.value)
    assert paths[1].read_text() == "old svg"
    assert set(paths[0].parent.iterdir()) == set(paths)


def test_invalid_render_layout_is_rejected():
    with pytest.raises(ValueError, match="layout engine"):
        D2RenderConfig(layout_engine="dagre")
