import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def cli(*args, legacy=False):
    entry = (
        [str(ROOT / "gen_drawio_erd_table.py")] if legacy else ["-m", "erd_generator"]
    )
    return subprocess.run(
        [sys.executable, *entry, *map(str, args)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )


def sample_args(tmp_path, suffix="d2"):
    return [
        "--migrations",
        ROOT / "db/migration",
        "--out",
        tmp_path / f"schema.{suffix}",
        "--fk-config",
        ROOT / "sample_fk_config.yaml",
        "--log-dir",
        tmp_path,
    ]


def test_default_entrypoint_generates_d2_without_starting_renderer(tmp_path):
    result = cli(*sample_args(tmp_path), "--d2-binary", "/nonexistent/d2")
    # A renderer-only flag must not be silently ignored in source-only mode.
    assert result.returncode == 2
    result = cli(*sample_args(tmp_path))
    assert result.returncode == 0, result.stderr
    source = (tmp_path / "schema.d2").read_text()
    assert "layout-engine: elk" in source
    assert source.count("shape: sql_table") == 5
    assert "temp_audit" not in source
    assert not (tmp_path / "schema.svg").exists()


def test_clean_style_is_default_and_classic_can_be_selected(tmp_path):
    args = sample_args(tmp_path)
    result = cli(*args)
    assert result.returncode == 0, result.stderr
    source = tmp_path / "schema.d2"
    assert "theme-overrides:" in source.read_text()
    result = cli(*args, "--style", "classic")
    assert result.returncode == 0, result.stderr
    assert "theme-overrides:" not in source.read_text()
    assert source.read_text().count("shape: sql_table") == 5


@pytest.mark.parametrize("style", ["clean", "classic"])
def test_d2_style_is_rejected_for_drawio(tmp_path, style):
    result = cli(
        *sample_args(tmp_path, "drawio"), "--format", "drawio", "--style", style
    )
    assert result.returncode == 2
    assert not (tmp_path / "schema.drawio").exists()


def test_d2_path_does_not_import_drawio_dependencies(tmp_path):
    program = """
import importlib.abc, runpy, sys
class BlockLegacy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'networkx', 'pydot'} or fullname in {'erd_generator.drawio', 'erd_generator.layout'}:
            raise ImportError('legacy dependency imported: ' + fullname)
sys.meta_path.insert(0, BlockLegacy())
runpy.run_module('erd_generator', run_name='__main__')
"""
    result = subprocess.run(
        [sys.executable, "-c", program, *map(str, sample_args(tmp_path))],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "options",
    [
        ["--layout", "grid"],
        ["--per-row", "0"],
        ["--graphviz-scale", "1"],
        ["--direction", "diagonal"],
        ["--render-timeout", "0", "--render", "svg"],
        ["--force-appendix"],
        ["--render", "png"],
        ["--style", "unknown"],
    ],
)
def test_invalid_d2_options_fail_before_writing(tmp_path, options):
    result = cli(*sample_args(tmp_path), *options)
    assert result.returncode == 2
    assert not (tmp_path / "schema.d2").exists()


def test_mismatched_extension_rejected(tmp_path):
    result = cli(*sample_args(tmp_path, "drawio"))
    assert result.returncode == 2
    assert not (tmp_path / "schema.drawio").exists()


def test_legacy_and_explicit_drawio_generate_same_document(tmp_path):
    args = sample_args(tmp_path, "drawio")
    result = cli(*args, "--show-types", legacy=True)
    assert result.returncode == 0, result.stderr
    expected = ET.parse(tmp_path / "schema.drawio").getroot()
    assert expected.tag == "mxfile"
    expected_bytes = (tmp_path / "schema.drawio").read_bytes()
    result = cli(*args, "--format", "drawio", "--show-types")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "schema.drawio").read_bytes() == expected_bytes


def test_invalid_drawio_layout_rejected(tmp_path):
    result = cli(
        *sample_args(tmp_path, "drawio"), "--format", "drawio", "--layout", "elk"
    )
    assert result.returncode == 2


def test_detected_parse_failure_cannot_overwrite_good_source(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1.sql").write_text(
        "CREATE TABLE a (id int); CREATE TABLE secret_payload (", encoding="utf-8"
    )
    output = tmp_path / "schema.d2"
    output.write_text("old source", encoding="utf-8")
    result = cli("--migrations", migrations, "--out", output, "--log-dir", tmp_path)
    assert result.returncode == 1
    assert "secret_payload" not in result.stdout + result.stderr
    assert output.read_text() == "old source"
    logs = list((tmp_path / "parse_log").glob("*.log"))
    assert len(logs) == 1
    assert "secret_payload" not in logs[0].read_text()


def test_missing_renderer_preserves_old_svg(tmp_path):
    (tmp_path / "schema.svg").write_text("old svg", encoding="utf-8")
    result = cli(
        *sample_args(tmp_path), "--render", "svg", "--d2-binary", "/nonexistent/d2"
    )
    assert result.returncode == 1
    assert (tmp_path / "schema.d2").is_file()
    assert (tmp_path / "schema.svg").read_text() == "old svg"
    assert "SVG was not updated" in result.stderr


def test_unknown_fk_config_prevents_partial_diagram(tmp_path):
    config = tmp_path / "fk.yaml"
    config.write_text("missing: {fks: [[id, public.users, id]]}", encoding="utf-8")
    result = cli(*sample_args(tmp_path), "--fk-config", config)
    assert result.returncode == 1
    assert not (tmp_path / "schema.d2").exists()


def test_output_directory_is_not_writable_file(tmp_path):
    parent = tmp_path / "blocked"
    parent.write_text("file", encoding="utf-8")
    result = cli(*sample_args(tmp_path), "--out", parent / "schema.d2")
    assert result.returncode == 1
    assert "Traceback" not in result.stderr


def test_legacy_python_api_imports_remain_available():
    from erd_generator import (
        ParseFailure,
        build_drawio,
        get_last_parse_failures,
        load_schema_from_migrations,
        main,
    )

    assert callable(main) and callable(build_drawio)
    assert callable(get_last_parse_failures) and callable(load_schema_from_migrations)
    assert ParseFailure(None, "", "failure").reason == "failure"
