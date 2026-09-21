"""Pure cross-group target labels; independent of routing and SVG rendering."""

from collections import Counter, defaultdict
from collections.abc import Iterable

from .validation import Relationship

FieldReferences = dict[tuple[str, str], str]


def field_references(
    tables: Iterable[str],
    relationships: tuple[Relationship, ...],
    groups: tuple[tuple[str, ...], ...],
) -> FieldReferences:
    """Annotate only boundaries in the original, top-level group partition.

    Keep unusual names verbatim. Conventional qualified names can omit their
    namespace only if the remaining table name is unique across the diagram.
    """
    names = {}
    for name in tables:
        parts = name.split(".")
        names[name] = (
            parts[-1]
            if len(parts) == 2 and all(part.isidentifier() for part in parts)
            else name
        )
    counts = Counter(names.values())
    names = {n: short if counts[short] == 1 else n for n, short in names.items()}
    owners = {name: i for i, members in enumerate(groups) for name in members}
    targets: dict[tuple[str, str], set[str]] = defaultdict(set)
    for fk in relationships:
        if owners[fk.table] == owners[fk.ref_table]:
            continue
        for column, remote in zip(fk.columns, fk.ref_columns, strict=True):
            targets[fk.table, column].add(f"{names[fk.ref_table]}.{remote}")
    return {key: ", ".join(sorted(values)) for key, values in sorted(targets.items())}
