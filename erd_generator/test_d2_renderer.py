import subprocess
from pathlib import Path

import pytest

from erd_generator.d2_renderer import D2RenderConfig, D2RenderError, render_d2

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
        Path(argv[-1]).write_text(content, encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_success_uses_elk_argument_array_and_atomic_output(monkeypatch, paths):
    source, output = paths
    monkeypatch.setenv("D2_LAYOUT", "dagre")
    monkeypatch.setenv("D2_WATCH", "true")
    calls = fake_d2(monkeypatch)
    render_d2(source, output, D2RenderConfig(force_appendix=True))
    argv, kwargs = calls[-1]
    assert argv[argv.index("--layout") + 1] == "elk"
    assert str(source.resolve()) in argv
    assert argv[-1] != str(output)
    assert "--force-appendix=true" in argv
    assert "D2_LAYOUT" not in kwargs["env"]
    assert "D2_WATCH" not in kwargs["env"]
    assert kwargs["timeout"] > 0
    assert not kwargs.get("shell", False)
    assert output.read_text() == SVG
    assert set(output.parent.iterdir()) == {source, output}


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


@pytest.mark.parametrize("content", ["", "not XML", "<html/>"])
def test_invalid_svg_cannot_replace_existing_artifact(monkeypatch, paths, content):
    fake_d2(monkeypatch, content=content)
    with pytest.raises(D2RenderError, match="SVG"):
        render_d2(*paths)
    assert paths[1].read_text() == "old svg"


def test_missing_executable_has_actionable_error(monkeypatch, paths):
    def missing(*args, **kwargs):
        raise FileNotFoundError("missing")

    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(D2RenderError, match="executable"):
        render_d2(*paths)


@pytest.mark.parametrize(
    "version,elk,message",
    [("0.6.0", "elk (bundled):", "version"), ("0.7.1", "dagre", "ELK")],
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
