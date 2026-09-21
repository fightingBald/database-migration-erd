"""Pure D2 SQL-table source generation with ELK and component packing."""

from collections.abc import Callable
from hashlib import sha256

from .d2_emit import container_lines, diagram_lines, relationship_lines, table_path
from .d2_emit import quote_d2 as quote_d2
from .d2_business import BusinessGroup, plan_groups
from .d2_grouping import centered_ranks, group_tables
from .d2_layout import Component, estimate_size, plan_layout, table_ranks
from .d2_references import FieldReferences, field_references
from .d2_styles import CLEAN_CONFIG, GRID_GAP, STYLES, GroupPalette, group_palette
from .layout_config import LayoutConfig
from .schema import Schema
from .validation import Relationship, validate_schema


def _packed_lines(
    columns: tuple[tuple[Component, ...], ...],
    emit: Callable[[Component], list[str]],
    direction: str,
) -> list[str]:
    if sum(map(len, columns)) == 1:
        return emit(columns[0][0])
    lines = [
        "grid-rows: 1",
        f"grid-columns: {len(columns)}",
        f"grid-gap: {GRID_GAP}",
        "",
    ]
    for column_index, column in enumerate(columns):
        body = [
            f"grid-rows: {len(column)}",
            "grid-columns: 1",
            "horizontal-gap: 0",
            f"vertical-gap: {GRID_GAP}",
        ]
        for index, component in enumerate(column):
            body.extend(
                container_lines(
                    f"_erd_component_{index}",
                    [f"direction: {direction}", *emit(component)],
                )
            )
        lines.extend(container_lines(f"_erd_column_{column_index}", body))
    return lines


def _component_lines(
    schema: Schema,
    component: Component,
    groups: tuple[BusinessGroup, ...],
    *,
    show_types: bool,
    show_indexes: bool,
    style: str,
    direction: str,
    automatic: bool,
    compact: bool = False,
    metadata: tuple[Relationship, ...] | None = None,
    inherited_palette: GroupPalette | None = None,
    references: FieldReferences | None = None,
) -> tuple[list[str], dict[str, str]]:
    members = set(component.tables)
    metadata = component.relationships if metadata is None else metadata
    groups = tuple(g for g in groups if g.tables[0] in members)
    if len(groups) == 1 and not groups[0].label:
        ranks = (
            table_ranks(
                component,
                schema,
                show_types,
                direction,
                center=not compact,
                show_indexes=show_indexes,
            )
            if inherited_palette and automatic
            else None
        )
        return diagram_lines(
            {n: schema[n] for n in members},
            component.relationships,
            show_types=show_types,
            show_indexes=show_indexes,
            style=style,
            metadata=metadata,
            palette=inherited_palette,
            ranks=ranks,
            references=references,
        ), {n: table_path(schema[n], show_indexes) for n in members}
    keys = {
        g.key: f"_erd_group_{sha256(g.key.encode()).hexdigest()[:16]}"
        if g.label
        else f"_erd_group_{i}"
        for i, g in enumerate(groups)
    }
    owners = {n: keys[g.key] for g in groups for n in g.tables}
    internal: dict[str, list[Relationship]] = {key: [] for key in keys.values()}
    external = []
    for fk in component.relationships:
        if owners[fk.table] == owners[fk.ref_table]:
            internal[owners[fk.table]].append(fk)
        else:
            external.append(fk)
    # Include ancestor-level edges: a nested subcommunity with an external
    # field reference must also remain outside grid cells.
    linked = {
        owners[n]
        for f in metadata
        for n, other in ((f.table, f.ref_table), (f.ref_table, f.table))
        if n in owners and owners.get(other) != owners[n]
    }
    weights = {}
    lines = []
    paths = {}
    for group in groups:
        key = keys[group.key]
        edges = tuple(internal[key])
        tables = {n: schema[n] for n in group.tables}
        palette = (
            group_palette(group.key, group.color) if group.label else inherited_palette
        )

        def emit(part: Component) -> tuple[list[str], dict[str, str]]:
            if group.label:
                # One business level plus one inferred community level. Child
                # groups have no business label, so this recursion is bounded.
                communities = (
                    group_tables(part.tables, part.relationships)
                    if automatic and not compact
                    else (part.tables,)
                )
                return _component_lines(
                    schema,
                    part,
                    tuple(
                        BusinessGroup(f"relations:{names[0]}", names)
                        for names in communities
                    ),
                    show_types=show_types,
                    show_indexes=show_indexes,
                    style=style,
                    direction=direction,
                    automatic=automatic,
                    compact=compact,
                    metadata=metadata,
                    inherited_palette=palette,
                    references=references,
                )
            ranks = (
                table_ranks(
                    part,
                    schema,
                    show_types,
                    direction,
                    center=not compact,
                    show_indexes=show_indexes,
                )
                if automatic
                else None
            )
            return diagram_lines(
                {n: schema[n] for n in part.tables},
                part.relationships,
                show_types=show_types,
                show_indexes=show_indexes,
                style=style,
                palette=palette,
                metadata=metadata,
                ranks=ranks,
                references=references,
            ), {n: table_path(schema[n], show_indexes) for n in part.tables}

        region = Component(group.tables, edges)
        # Grid boundaries are safe only when no external FK enters a cell.
        # A business group with external edges must remain a native ELK region,
        # including any of its tables which have no internal relationship.
        if key in linked:
            body, local_paths = emit(region)
            paths.update({n: f"{key}.{path}" for n, path in local_paths.items()})
        else:
            # No ancestor can reference these packed cells. Their paths need
            # not escape this region; every FK is emitted inside its own cell.
            body = _packed_lines(
                plan_layout(
                    tables,
                    edges,
                    show_types=show_types,
                    direction=direction,
                    show_indexes=show_indexes,
                ),
                lambda part: emit(part)[0],
                direction,
            )
        size = estimate_size(
            region, schema, show_types, direction, show_indexes=show_indexes
        )
        weights[key] = size[1 if direction in {"right", "left"} else 0]
        lines.extend(
            container_lines(
                key, body, label=group.label, palette=palette if group.label else None
            )
        )
    ranks = (
        centered_ranks(
            tuple(sorted(internal)),
            tuple((owners[f.table], owners[f.ref_table]) for f in external),
            hubs=tuple(keys[g.key] for g in groups if len(g.tables) == 1),
            weights=weights,
        )
        if automatic
        else None
    )
    lines.extend(
        relationship_lines(
            tuple(external),
            style=style,
            paths=paths,
            ranks={name: ranks[owner] for name, owner in owners.items()}
            if ranks
            else None,
        )
    )
    return lines, paths


def build_d2(
    schema: Schema,
    *,
    show_types: bool = False,
    direction: str = "right",
    style: str = "clean",
    grouping: str = "auto",
    layout_config: LayoutConfig | None = None,
    layout_strategy: str = "balanced",
    show_references: bool = False,
    show_indexes: bool = True,
) -> str:
    if direction not in {"up", "down", "left", "right"}:
        raise ValueError("D2 direction must be up, down, left or right")
    if style not in STYLES:
        raise ValueError("D2 style must be clean or classic")
    if grouping not in {"auto", "none"}:
        raise ValueError("D2 grouping must be auto or none")
    if layout_strategy not in {"balanced", "compact"}:
        raise ValueError("D2 layout strategy must be balanced or compact")
    if layout_config is not None and not isinstance(layout_config, LayoutConfig):
        raise ValueError("Layout config: expected a LayoutConfig object")
    result = validate_schema(schema)
    if result.errors:
        raise ValueError("Schema validation failed: " + "; ".join(result.errors))
    groups = plan_groups(
        schema, result.relationships, automatic=grouping == "auto", config=layout_config
    )
    references = (
        field_references(schema, result.relationships, tuple(g.tables for g in groups))
        if show_references
        else None
    )
    lines = [
        "# Generated from migrations; edit SQL or FK configuration, then regenerate.",
        "vars: {",
        "  d2-config: {",
        "    layout-engine: elk",
        *(CLEAN_CONFIG if style == "clean" else ()),
        "  }",
        "}",
        f"direction: {direction}",
        "",
    ]
    columns = plan_layout(
        schema,
        result.relationships,
        show_types=show_types,
        show_indexes=show_indexes,
        direction=direction,
        keep_together=tuple(g.tables for g in groups if g.label),
    )
    lines.extend(
        _packed_lines(
            columns,
            lambda component: _component_lines(
                schema,
                component,
                groups,
                show_types=show_types,
                show_indexes=show_indexes,
                style=style,
                direction=direction,
                automatic=grouping == "auto",
                compact=layout_strategy == "compact",
                references=references,
            )[0],
            direction,
        )
    )
    return "\n".join(lines).rstrip() + "\n"
