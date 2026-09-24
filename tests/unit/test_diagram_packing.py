"""Measured rectangles, independent of SQL semantics and rendering."""

from erd_generator.diagram_packing import pack_rectangles


def test_unequal_rectangles_are_complete_non_overlapping_and_deterministic():
    sizes = {"a": (600, 450), "b": (900, 700), "c": (350, 800), "d": (500, 300)}
    packed = pack_rectangles(sizes, {("a", "b"): 8, ("c", "d"): 2})
    assert set(packed) == set(sizes)
    assert packed == pack_rectangles(
        dict(reversed(list(sizes.items()))), {("a", "b"): 8, ("c", "d"): 2}
    )
    for key, box in packed.items():
        assert (box.width, box.height) == sizes[key]
        for other, region in packed.items():
            if key != other:
                assert (
                    box.right <= region.x
                    or region.right <= box.x
                    or box.bottom <= region.y
                    or region.bottom <= box.y
                )


def test_no_rectangles_needs_no_placement():
    assert pack_rectangles({}, {}) == {}
