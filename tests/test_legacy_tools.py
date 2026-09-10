import subprocess
import sys
from pathlib import Path

import yaml

from erd_generator.cli import main

ROOT = Path(__file__).resolve().parents[1]


def test_drawio_extraction_and_comparator_remain_usable(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1.sql").write_text(
        (ROOT / "tests/fixtures/simple.sql").read_text(), encoding="utf-8"
    )
    diagram = tmp_path / "schema.drawio"
    assert (
        main(["--migrations", str(migrations), "--out", str(diagram), "--show-types"])
        == 0
    )
    edges = subprocess.run(
        [sys.executable, str(ROOT / "parse_drawio_edges.py"), str(diagram)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert edges.returncode == 0, edges.stderr
    data = yaml.safe_load(edges.stdout)
    assert sum(len(t["fks"]) for t in data.values()) == 1
    report = subprocess.run(
        [
            sys.executable,
            str(ROOT / "compare_drawio_to_migrations.py"),
            str(migrations),
            str(diagram),
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert report.returncode == 0, report.stderr
    assert report.stdout.count("(none)") == 8


def test_graphviz_option_retains_documented_grid_fallback(tmp_path):
    # An unavailable Graphviz program is an explicit legacy-only fallback.
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1.sql").write_text("CREATE TABLE a (id int);", encoding="utf-8")
    assert (
        main(
            [
                "--migrations",
                str(migrations),
                "--out",
                str(tmp_path / "schema.drawio"),
                "--layout",
                "graphviz",
                "--graphviz-prog",
                "nonexistent_graphviz",
            ]
        )
        == 0
    )
