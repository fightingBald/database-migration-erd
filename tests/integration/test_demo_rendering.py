"""Execute the same demo command used in a team presentation."""

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]
NS = "{http://www.w3.org/2000/svg}"


def test_complete_demo_gallery_and_expected_failures(tmp_path):
    result = subprocess.run(
        [sys.executable, "scripts/run_demos.py", "--output", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / "report.json").read_text())
    assert len(report) == 10
    assert all(case["passed"] for case in report)
    catalog = json.loads((ROOT / "examples/scenarios.json").read_text())
    for case in catalog["success"]:
        path = tmp_path / case["id"] / "schema.svg"
        svg = ET.parse(path).getroot()
        assert svg.tag == NS + "svg"
        texts = {"".join(e.itertext()) for e in svg.iter(NS + "text")}
        assert set(case["tables"]).issubset(texts)
        assert set(case.get("labels", [])).issubset(texts)
        assert not set(case.get("absent_labels", [])).intersection(texts)
    assert "expected failure" in (tmp_path / "index.html").read_text()
    assert "原有 SVG 保留" in (tmp_path / "index.html").read_text()


def test_demo_returns_failure_when_renderer_is_unavailable(tmp_path):
    previous = tmp_path / "release_evolution/schema.svg"
    previous.parent.mkdir()
    previous.write_text("previous SVG", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_demos.py",
            "--output",
            str(tmp_path),
            "--case",
            "release_evolution",
            "--d2-binary",
            "/nonexistent/demo-renderer",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 1
    report = json.loads((tmp_path / "report.json").read_text())
    assert len(report) == 1 and not report[0]["passed"]
    assert previous.read_text() == "previous SVG"
    assert (
        'href="release_evolution/schema.svg"'
        not in (tmp_path / "index.html").read_text()
    )
