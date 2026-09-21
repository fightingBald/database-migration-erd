from copy import deepcopy

import pytest

from erd_generator.d2 import build_d2
from erd_generator.d2_indexes import FOOTER_LINE_WIDTH, footer_markup, index_footer
from erd_generator.d2_layout import Component, estimate_size
from erd_generator.schema import Column, ForeignKey, Index, Table


def indexed_schema():
    return {
        "library.books": Table(
            "library.books",
            columns=[Column("id", "INT"), Column("title", "TEXT")],
            primary_key={"id"},
            indexes=[
                Index("ix_title", ("lower(title)",), method="btree"),
                Index("ux_title", ("title",), unique=True),
            ],
        ),
        "library.loans": Table(
            "library.loans",
            columns=[Column("id", "INT"), Column("book_id", "INT")],
            foreign_keys=[ForeignKey(("book_id",), "library.books", ("id",))],
        ),
    }


def test_indexes_are_visible_below_their_table_without_changing_schema():
    schema = indexed_schema()
    before = deepcopy(schema)
    source = build_d2(schema, show_types=True)
    assert source.count("label.near: bottom-left") == 1
    assert "style.font-size: 12" in source
    assert "text-align:left" in source
    assert "INDEX ix_title" in source and "UNIQUE ux_title" in source
    assert "USING btree" in source and "lower(title)" in source
    assert source.count("shape: sql_table") == 2
    assert schema == before
    schema["library.books"].indexes.reverse()
    assert build_d2(schema, show_types=True) == source


def test_hiding_index_footers_retains_tooltips_and_original_field_paths():
    source = build_d2(indexed_schema(), show_indexes=False)
    assert "label.near: bottom-left" not in source
    assert "Index ix_title using btree" in source
    assert '"library.loans"."book_id" -> "library.books"."id"' in source


@pytest.mark.parametrize("direction", ["right", "down"])
def test_packing_accounts_for_index_footers(direction):
    schema = indexed_schema()
    component = Component(("library.books",), ())
    shown = estimate_size(component, schema, True, direction)
    hidden = estimate_size(component, schema, True, direction, show_indexes=False)
    assert shown[0] >= hidden[0]
    assert shown[1] > hidden[1]


def test_tables_without_indexes_keep_the_existing_source_and_size():
    schema = {"empty": Table("empty"), "plain": Table("plain", [Column("id")])}
    assert build_d2(schema) == build_d2(schema, show_indexes=False)


def test_wrapping_preserves_long_identifiers_expressions_and_literal_whitespace():
    name = "idx_" + "long_" * 30 + '${literal}_"quoted"'
    expression = "lower(title)"
    predicate = "title <> 'two  spaces < value'"
    table = Table("books", indexes=[Index(name, (expression,), where=predicate)])
    footer = index_footer(table)
    assert max(map(len, footer.splitlines())) <= FOOTER_LINE_WIDTH
    assert (
        "".join(footer.splitlines()) == f"INDEX {name} ({expression}) WHERE {predicate}"
    )


@pytest.mark.parametrize("field", ["name", "where"])
def test_index_metadata_cannot_inject_d2_or_xml_controls(field):
    table = Table("books", columns=[Column("id")], indexes=[Index("ix", ("id",))])
    setattr(table.indexes[0], field, "invalid\x00value")
    with pytest.raises(ValueError, match="control"):
        build_d2({table.name: table})


def test_rich_footer_escapes_html_and_d2_block_syntax_without_losing_text():
    import xml.etree.ElementTree as ET

    text = "INDEX </div><img src=\"x\"/> ${literal} |\\ 'quoted'\nWHERE title = 'two  spaces'"
    markup = footer_markup(text)
    assert "${" not in markup and "|" not in markup
    root = ET.fromstring(markup)
    assert {e.tag for e in root.iter()} == {"div", "span", "br"}
    assert "".join(root.itertext()) == "".join(text.splitlines())
    assert "text-align:left" in root.get("style")
    assert "white-space:pre" in root.get("style")
