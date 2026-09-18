from copy import deepcopy

import pytest

from erd_generator.d2_business import plan_groups
from erd_generator.d2_styles import group_palette
from erd_generator.layout_config import GroupRule, LayoutConfig
from erd_generator.schema import Column, ForeignKey, Table
from erd_generator.validation import validate_schema


def tables(*names):
    return {
        n: Table(n, columns=[Column("id", "INT"), Column("parent_id", "INT")])
        for n in names
    }


def planned(schema, **kwargs):
    return plan_groups(schema, validate_schema(schema).relationships, **kwargs)


def named(groups):
    return {g.label: set(g.tables) for g in groups if g.label}


def test_recognizes_families_without_foreign_keys_or_configuration():
    schema = tables(
        *(
            f"demo_library.{prefix}_{suffix}"
            for prefix in ("books", "loans", "members")
            for suffix in ("details", "files", "links")
        )
    )
    groups = planned(schema)
    assert named(groups) == {
        f"{p.title()} · demo_library": {
            f"demo_library.{p}_{s}" for s in ("details", "files", "links")
        }
        for p in ("books", "loans", "members")
    }
    assert sorted(n for g in groups for n in g.tables) == sorted(schema)
    assert len({group_palette(g.key).header for g in groups}) == 3


def test_root_and_deep_family_use_word_boundaries_not_substrings():
    schema = tables(
        "demo_library.books",
        "demo_library.books_details",
        "demo_library.books_details_files",
        "demo_library.bookshelf_log",
        "demo_library.loans_books_files",
        "demo_library.loans_books_links",
        "demo_library.loans_books_details",
    )
    groups = named(planned(schema))
    assert groups["Books · demo_library"] == {
        "demo_library.books",
        "demo_library.books_details",
        "demo_library.books_details_files",
    }
    assert groups["Loans books · demo_library"] == {
        "demo_library.loans_books_files",
        "demo_library.loans_books_links",
        "demo_library.loans_books_details",
    }
    assert all(
        "demo_library.bookshelf_log" not in members for members in groups.values()
    )


def test_common_technical_prefix_does_not_merge_unrelated_domains():
    schema = tables(
        *(
            f"demo_library.tbl_{p}_{s}"
            for p in ("books", "events")
            for s in ("accounts", "details", "files")
        )
    )
    assert set(named(planned(schema))) == {
        "Books · demo_library",
        "Events · demo_library",
    }
    numeric = tables(*(f"demo_library.table_{i:02}" for i in range(40)))
    assert not named(planned(numeric))


def test_namespace_and_unicode_are_preserved():
    schema = tables(
        *(
            f"{ns}.图书_{suffix}"
            for ns in ("one", "two")
            for suffix in ("详情", "文件", "链接")
        )
    )
    groups = planned(schema)
    assert set(named(groups)) == {"图书 · one", "图书 · two"}
    assert len({g.key for g in groups}) == 2


def test_discriminating_fk_evidence_can_reject_misleading_names():
    schema = tables(
        *(
            f"{p}_{s}"
            for p in ("books", "events")
            for s in ("accounts", "details", "files")
        )
    )
    for suffix in ("accounts", "details", "files"):
        schema[f"books_{suffix}"].foreign_keys.append(
            ForeignKey(("parent_id",), f"events_{suffix}", ("id",))
        )
    assert not named(planned(schema))
    assert all(len(g.tables) == 2 for g in planned(schema))


def test_common_hub_does_not_destroy_clear_named_domains():
    schema = tables(
        "identity",
        *(
            f"{p}_{s}"
            for p in ("books", "events", "catalog")
            for s in ("accounts", "details", "files")
        ),
    )
    for name, table in schema.items():
        if name != "identity":
            table.foreign_keys.append(ForeignKey(("parent_id",), "identity", ("id",)))
    groups = planned(schema)
    assert set(named(groups)) == {"Books", "Events", "Catalog"}
    assert next(g for g in groups if "identity" in g.tables).tables == ("identity",)


def test_explicit_override_wins_and_unmatched_tables_are_still_inferred():
    schema = tables(
        *(
            f"{p}_{s}"
            for p in ("books", "events")
            for s in ("accounts", "details", "files")
        )
    )
    config = LayoutConfig(
        (GroupRule("custom", ("books_*",), "Book collection", "gold"),)
    )
    groups = planned(schema, config=config)
    assert set(named(groups)) == {"Book collection", "Events"}
    assert next(g for g in groups if g.label == "Book collection").color == "gold"
    assert set(named(planned(schema, config=config, automatic=False))) == {
        "Book collection"
    }
    assert not named(planned(schema, automatic=False))


def test_named_group_identity_palette_and_input_are_stable():
    schema = tables(
        "demo_library.books", "demo_library.books_details", "demo_library.books_files"
    )
    before = deepcopy(schema)
    group = next(g for g in planned(schema) if g.label)
    reverse = dict(reversed(list(schema.items())))
    assert planned(reverse) == planned(schema)
    reverse["demo_library.unrelated"] = Table("demo_library.unrelated")
    after = next(g for g in planned(reverse) if "demo_library.books" in g.tables)
    assert (after.key, after.label, group_palette(after.key)) == (
        group.key,
        group.label,
        group_palette(group.key),
    )
    assert schema == before


def test_unrelated_tables_do_not_turn_a_common_wrapper_into_one_large_group():
    schema = tables(
        *(
            f"app_{p}_{s}"
            for p in ("books", "events")
            for s in ("accounts", "details", "files")
        )
    )
    before = {g.key: g.tables for g in planned(schema) if g.label}
    assert len(before) == 2
    schema.update(tables("unrelated_one", "unrelated_two"))
    assert {g.key: g.tables for g in planned(schema) if g.label} == before


@pytest.mark.parametrize("count", [0, 1, 2, 100])
def test_uninformative_names_are_not_given_business_meaning(count):
    schema = tables(*(f"t{i:03}" for i in range(count)))
    groups = planned(schema)
    assert not named(groups)
    assert sorted(n for g in groups for n in g.tables) == sorted(schema)


@pytest.mark.parametrize(
    "rules,reason",
    [
        (
            (GroupRule("a", ("books_*",)), GroupRule("b", ("books_files",))),
            "more than one",
        ),
        ((GroupRule("a", ("absent_*",)),), "matches no tables"),
    ],
)
def test_bad_overrides_fail_before_partial_grouping(rules, reason):
    with pytest.raises(ValueError, match=reason):
        planned(tables("books_files", "books_details"), config=LayoutConfig(rules))


def test_exact_override_precedes_glob_interpretation_and_keeps_case():
    schema = tables("demo_library.Item[1]", "demo_library.Item1", "demo_library.item1")
    config = LayoutConfig((GroupRule("literal", ("demo_library.Item[1]",)),))
    group = next(g for g in planned(schema, config=config) if g.label)
    assert group.tables == ("demo_library.Item[1]",)
    with pytest.raises(ValueError, match="matches no tables"):
        planned(schema, config=LayoutConfig((GroupRule("wrong_case", ("APP.Item1",)),)))


def test_duplicate_and_self_foreign_keys_do_not_change_family_confidence():
    schema = tables(
        "books_accounts",
        "books_details",
        "books_files",
        "events_accounts",
        "events_details",
        "events_files",
    )
    for p in ("books", "events"):
        for suffix in ("details", "files"):
            schema[f"{p}_{suffix}"].foreign_keys = [
                ForeignKey(("parent_id",), f"{p}_accounts", ("id",))
            ]
    before = planned(schema)
    for name, table in schema.items():
        table.foreign_keys *= 3
        table.foreign_keys += [ForeignKey(("id",), name, ("id",))]
    assert planned(schema) == before
