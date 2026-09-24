"""Fictional schema builders shared by rendering tests."""

from erd_generator.layout_config import GroupRule, LayoutConfig
from erd_generator.schema import Column, ForeignKey, Index, Table
from erd_generator.sql_parser import parse_schema_from_sql
from tests.support import FIXTURES


def table(name, fields=3):
    return Table(
        name,
        columns=[Column("id", "INT", is_primary_key=True)]
        + [Column(f"field_{i}", "TEXT") for i in range(1, fields)],
    )


def related_schema():
    schema = {}
    fixture = FIXTURES / "related_tables.sql"
    parse_schema_from_sql(fixture.read_text(), schema)
    return schema


def business_schema():
    schema = {}
    suffixes = ("root", "details", "files", "links", "contacts")
    roots = []
    for prefix in ("books", "loans", "members"):
        names = [f"demo_library.{prefix}_{suffix}" for suffix in suffixes]
        roots.append(names[0])
        for i, name in enumerate(names):
            schema[name] = table(name, 5 + i % 3)
            if i:
                schema[name].foreign_keys = [
                    ForeignKey(
                        ("field_1", "field_3"),
                        names[0],
                        ("id", "field_2"),
                        f"pair_{prefix}",
                    )
                ]
    for i, root in enumerate(roots):
        schema[root].foreign_keys = [
            ForeignKey(
                ("field_1", "field_3"),
                roots[(i + 1) % 3],
                ("id", "field_2"),
                "cross_pair",
            )
        ]
    schema[roots[0]].foreign_keys.append(ForeignKey(("field_4",), roots[0], ("id",)))
    return schema


def scenario(shape):
    if shape == "communities":
        return related_schema()
    if shape == "composite_cycles":
        return business_schema()
    names = tuple(f"demo_library.t{i:02}" for i in range(18))
    schema = {n: table(n, 3 + i % 7) for i, n in enumerate(names)}
    if shape != "isolated":
        for i, name in enumerate(names[1:], 1):
            target = names[0] if shape == "star" else names[i - 1]
            schema[name].foreign_keys = [ForeignKey(("field_1",), target, ("id",))]
    return schema


def uneven_business_schema(topology):
    """Forty fictional tables, six unequal regions, and externally linked leaves."""
    schema, rules, roots = {}, [], []
    for group, (prefix, count) in enumerate(
        zip(
            ("catalog", "dispatch", "identity", "messaging", "storage", "audit"),
            (12, 9, 7, 5, 4, 3),
            strict=True,
        )
    ):
        root = f"demo_atlas.{prefix}"
        roots.append(root)
        members = [root] + [f"{root}_item_{i:02}" for i in range(1, count)]
        rules.append(GroupRule(prefix, tuple(members)))
        for i, name in enumerate(members):
            schema[name] = Table(
                name,
                columns=[
                    Column("id", "BIGINT", is_primary_key=True),
                    Column("parent_id", "BIGINT"),
                    Column("ref_id", "BIGINT"),
                    *[Column(f"value_{j}", "TEXT") for j in range((i + group) % 7 + 2)],
                ],
            )
            if i and group != 2:
                schema[name].foreign_keys.append(
                    ForeignKey(("parent_id",), root, ("id",))
                )
            if i == 0:
                schema[name].indexes.append(
                    Index(f"ix_{prefix}_ref", ("ref_id",), column_names=("ref_id",))
                )
    for group in range(1, len(roots)):
        schema[roots[group]].foreign_keys.append(
            ForeignKey(
                ("ref_id",),
                roots[group - 1] if topology == "sparse" else roots[0],
                ("id",),
            )
        )
    for name in rules[2].tables[1:]:
        schema[name].foreign_keys.append(ForeignKey(("ref_id",), roots[0], ("id",)))
    if topology == "dense":
        for group, rule in enumerate(rules):
            for i, name in enumerate(rule.tables[1:], 1):
                schema[name].foreign_keys.append(
                    ForeignKey(("ref_id",), roots[(group + i) % 6], ("id",))
                )
    return schema, LayoutConfig(tuple(rules))
