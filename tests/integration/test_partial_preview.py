from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from erd_generator.d2_geometry import measure_layout
from erd_generator.sql_parser import load_schema_result
from erd_generator.validation import preview_schema

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]
NS = "{http://www.w3.org/2000/svg}"


@pytest.mark.parametrize("direction,style", [("right", "clean"), ("down", "classic")])
def test_partial_svg_has_visible_notice_real_field_ports_and_no_formal_updates(
    tmp_path, direction, style
):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1.sql").write_text(
        "CREATE TABLE parent(id int PRIMARY KEY);"
        "CREATE TABLE child(id int, parent_id int REFERENCES parent(id), ghost_id int REFERENCES missing(id));"
        "CREATE INDEX ix_parent ON child(parent_id);"
        "CREATE TABLE _erd_partial_notice(id int);"
        "DO $$BEGIN CREATE TABLE rolled_back(id int); CALL unsupported(); END;$$;"
    )
    source, image = tmp_path / "schema.d2", tmp_path / "schema.svg"
    source.write_text("old source")
    image.write_text("old image")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "erd_generator",
            str(migrations),
            str(image),
            "--log-dir",
            str(tmp_path),
            "--direction",
            direction,
            "--style",
            style,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1, result.stderr
    assert image.read_text() == "old image" and source.read_text() == "old source"
    partial = tmp_path / "schema.partial.svg"
    root = ET.parse(partial).getroot()
    notices = [
        e for e in root.iter(NS + "text") if "INCOMPLETE" in "".join(e.itertext())
    ]
    assert len(notices) == 1
    assert "Structure not fully verified" in "".join(notices[0].itertext())
    assert notices[0].get("fill") == "#92400E"
    assert "font-size:26px" in notices[0].get("style")
    schema, omissions = preview_schema(load_schema_result(str(migrations)).schema)
    assert len(schema) == 3 and len(omissions) == 1
    measure_layout(partial, schema, show_types=True)
    assert "rolled_back" not in partial.with_suffix(".d2").read_text()
    assert "_erd_partial_notice_:" in partial.with_suffix(".d2").read_text()
    assert "Relationship omitted" in result.stderr and "Unsupported DO" in result.stderr
