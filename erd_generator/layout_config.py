"""Explicit business-layout overrides; file I/O stays outside pure planning."""

from dataclasses import dataclass
from pathlib import Path

from .d2_styles import GROUP_PALETTES


def _text(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and not any(ord(c) < 32 and c not in "\n\r\t" for c in value)
    )


@dataclass(frozen=True)
class GroupRule:
    key: str
    tables: tuple[str, ...]
    label: str | None = None
    color: str | None = None

    def __post_init__(self) -> None:
        if not _text(self.key):
            raise ValueError("Layout config: group key must be nonempty text")
        if (
            not isinstance(self.tables, tuple)
            or not self.tables
            or not all(map(_text, self.tables))
        ):
            raise ValueError(
                "Layout config: tables must be a nonempty tuple of selectors"
            )
        if self.label is not None and not _text(self.label):
            raise ValueError("Layout config: label must be nonempty text")
        if self.color is not None and (
            not isinstance(self.color, str) or self.color not in GROUP_PALETTES
        ):
            raise ValueError(
                "Layout config: color must name an available group palette"
            )


@dataclass(frozen=True)
class LayoutConfig:
    groups: tuple[GroupRule, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.groups, tuple) or not all(
            isinstance(g, GroupRule) for g in self.groups
        ):
            raise ValueError(
                "Layout config: groups must be a tuple of GroupRule objects"
            )
        if len({g.key for g in self.groups}) != len(self.groups):
            raise ValueError("Layout config: duplicate group key")


def load_layout_config(path: str | Path) -> LayoutConfig:
    import yaml

    class UniqueLoader(yaml.SafeLoader):
        def construct_mapping(self, node, deep=False):
            seen = set()
            for key_node, _ in node.value:
                if key_node.tag == "tag:yaml.org,2002:merge":
                    raise yaml.constructor.ConstructorError(
                        None, None, "merge keys are unsupported", key_node.start_mark
                    )
                key = self.construct_object(key_node, deep=deep)
                if not isinstance(key, str) or key in seen:
                    raise yaml.constructor.ConstructorError(
                        None, None, "non-text or duplicate key", key_node.start_mark
                    )
                seen.add(key)
            return super().construct_mapping(node, deep=deep)

    source = Path(path).expanduser()
    try:
        raw = yaml.load(source.read_text(encoding="utf-8"), Loader=UniqueLoader)
    except (OSError, UnicodeError) as exc:
        raise ValueError(
            f"Layout config: {source}: cannot read UTF-8 configuration ({type(exc).__name__})"
        ) from exc
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        raise ValueError(f"Layout config: {source}: invalid YAML{where}") from exc
    if not isinstance(raw, dict) or set(raw) != {"groups"}:
        raise ValueError(f"Layout config: {source}: expected only a groups mapping")
    groups = raw["groups"]
    if not isinstance(groups, dict) or not groups:
        raise ValueError(f"Layout config: {source}: groups must be a nonempty mapping")
    rules = []
    for key, value in sorted(groups.items()):
        if not isinstance(value, dict) or set(value) - {"tables", "label", "color"}:
            raise ValueError(
                f"Layout config: {source}: expected tables and optional label/color in each group"
            )
        selectors = value.get("tables")
        if not isinstance(selectors, list):
            raise ValueError(f"Layout config: {source}: tables must be a nonempty list")
        if any(
            field in value and not _text(value[field]) for field in ("label", "color")
        ):
            raise ValueError(
                f"Layout config: {source}: label/color must be nonempty text"
            )
        rules.append(
            GroupRule(key, tuple(selectors), value.get("label"), value.get("color"))
        )
    return LayoutConfig(tuple(rules))
