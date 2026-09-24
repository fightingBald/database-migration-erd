import xml.etree.ElementTree as ET

import pytest

from erd_generator.d2_index_svg import align_index_captions

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 200">
<style><![CDATA[.shape > .child { fill: red; }]]></style>
<g class="wrapper"><g class="shape"><rect x="0" y="0" width="400" height="160"/></g>
<g><foreignObject x="5" y="110" width="80" height="18"><div xmlns="http://www.w3.org/1999/xhtml"
data-erd-index-footer="true" data-erd-index-table="books"><span>INDEX ix_id (id)</span></div></foreignObject></g></g>
<g><rect class="shape" x="115" y="16" width="160" height="72"/>
<rect class="class_header" x="115" y="16" width="160" height="36"/><text>books</text></g>
<path class="connection" d="M 300 50 L 275 50"/>
<text>TALA evaluation watermark</text></svg>"""
NS = "{http://www.w3.org/2000/svg}"


def test_alignment_changes_only_caption_x_preserving_native_geometry_and_content():
    aligned = align_index_captions(SVG)
    before, after = ET.fromstring(SVG), ET.fromstring(aligned)
    footer = after.find(f".//{NS}foreignObject")
    assert footer.get("x") == "115.000000"
    footer.set("x", "5")
    assert ET.tostring(before) == ET.tostring(after)
    assert "<![CDATA[.shape > .child { fill: red; }]]>" in aligned
    assert align_index_captions(aligned) == aligned


def test_no_index_captions_leave_svg_bytes_unchanged():
    svg = SVG.replace('data-erd-index-footer="true"', "")
    assert align_index_captions(svg) == svg


@pytest.mark.parametrize(
    "original,replacement",
    [
        ('data-erd-index-table="books"', 'data-erd-index-table="missing"'),
        ('y="110"', 'y="50"'),
        ('width="80"', 'width="200"'),
        ('height="160"', 'height="120"'),
        ('x="115"', 'x="nan"'),
    ],
)
def test_invalid_captions_fail_before_publication(original, replacement):
    with pytest.raises(ValueError, match="index footer"):
        align_index_captions(SVG.replace(original, replacement))
