"""Conservative name families plus relationship communities; never change Schema."""

import re
from collections import defaultdict
from dataclasses import dataclass
from fnmatch import fnmatchcase

from .d2_grouping import group_tables
from .d2_layout import connected_components
from .layout_config import LayoutConfig
from .schema import Schema
from .validation import Relationship

MIN_FAMILY_SIZE = 3
TECHNICAL_PREFIXES = {"t", "tb", "tbl", "table"}


@dataclass(frozen=True)
class BusinessGroup:
    key: str
    tables: tuple[str, ...]
    label: str = ""
    color: str | None = None


def _overrides(schema: Schema, config: LayoutConfig) -> list[BusinessGroup]:
    groups = []
    claimed = set()
    for rule in sorted(config.groups, key=lambda g: g.key):
        members = set()
        for index, selector in enumerate(rule.tables, 1):
            matches = (
                {selector}
                if selector in schema
                else {n for n in schema if fnmatchcase(n, selector)}
            )
            if not matches:
                raise ValueError(
                    f"Layout config: group {rule.key!r}, selector {index} matches no tables"
                )
            members.update(matches)
        if members & claimed:
            raise ValueError(
                f"Layout config: group {rule.key!r}: a table belongs to more than one group"
            )
        claimed.update(members)
        groups.append(
            BusinessGroup(
                f"config:{rule.key}",
                tuple(sorted(members)),
                rule.label or rule.key,
                rule.color,
            )
        )
    return groups


def _name_groups(
    schema: Schema, relationships: tuple[Relationship, ...]
) -> list[BusinessGroup]:
    namespaces = defaultdict(dict)
    for name in sorted(schema):
        namespace, _, base = name.rpartition(".")
        tokens = tuple(base.casefold().split("_"))
        # Unusual quoted names remain valid SQL/D2 but are weak naming evidence.
        if all(token and token.isalnum() for token in tokens):
            namespaces[namespace][name] = tokens
    neighbors = defaultdict(set)
    for fk in relationships:
        if fk.table != fk.ref_table:
            neighbors[fk.table].add(fk.ref_table)
            neighbors[fk.ref_table].add(fk.table)
    result = []
    for namespace, names in sorted(namespaces.items()):
        prefixes = defaultdict(set)
        for name, tokens in names.items():
            for end in range(1, len(tokens) + 1):
                prefixes[tokens[:end]].add(name)
        candidates = {}
        for prefix, members in prefixes.items():
            if len(members) < MIN_FAMILY_SIZE or prefix[-1] in TECHNICAL_PREFIXES:
                continue
            tails = {
                names[n][len(prefix)] for n in members if len(names[n]) > len(prefix)
            }
            meaningful = {
                t for t in tails if not t.isdigit() and not re.fullmatch(r"v\d+", t)
            }
            has_root = any(names[n] == prefix for n in members)
            if not meaningful or (not has_root and len(meaningful) < 2):
                continue
            candidates[prefix] = members
        claimed = set()
        for prefix, members in sorted(
            candidates.items(), key=lambda item: (len(item[0]), item[0])
        ):
            if members & claimed:
                continue
            # Prefer meaningful subfamilies to a rootless wrapper. This decision
            # uses its own subtree, so unrelated additions cannot merge groups.
            children = {
                p[len(prefix)]
                for p in candidates
                if len(p) > len(prefix) and p[: len(prefix)] == prefix
            }
            if len(children) >= 2 and not any(names[n] == prefix for n in members):
                continue
            internal = sum(len(neighbors[n] & members) for n in members) // 2
            degree = max((len(neighbors[n]) for n in members), default=0)
            outside = [
                (n, other)
                for n in members
                for other in neighbors[n] - members
                if len(neighbors[other]) < max(6, 2 * degree)
            ]
            if (
                len(outside) > 2 * internal
                and len({other for _, other in outside}) >= 3
            ):
                continue
            words = prefix
            while words and words[0] in TECHNICAL_PREFIXES:
                words = words[1:]
            label = " ".join(words).capitalize()
            if namespace:
                label += f" · {namespace}"
            key = f"name:{namespace}:{'_'.join(prefix)}"
            result.append(BusinessGroup(key, tuple(sorted(members)), label))
            claimed.update(members)
    return result


def plan_groups(
    schema: Schema,
    relationships: tuple[Relationship, ...],
    *,
    automatic: bool = True,
    config: LayoutConfig | None = None,
) -> tuple[BusinessGroup, ...]:
    """Partition every table once; explicit membership takes precedence."""
    groups = _overrides(schema, config or LayoutConfig())
    claimed = {n for g in groups for n in g.tables}
    if automatic:
        remaining = {n: t for n, t in schema.items() if n not in claimed}
        groups.extend(_name_groups(remaining, relationships))
        claimed = {n for g in groups for n in g.tables}
    remaining = {n: t for n, t in schema.items() if n not in claimed}
    edges = tuple(
        f for f in relationships if f.table in remaining and f.ref_table in remaining
    )
    for component in connected_components(remaining, edges):
        communities = (
            group_tables(component.tables, component.relationships)
            if automatic
            else (component.tables,)
        )
        groups.extend(
            BusinessGroup(f"relations:{names[0]}", names) for names in communities
        )
    return tuple(sorted(groups, key=lambda g: (g.tables, g.key)))
