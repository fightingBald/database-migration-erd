"""Objects excluded from a table/FK diagram; never execute their SQL.

This scope policy is separate from the proof of neutrality used for DO blocks.
Names are exact identifier tuples: no search_path guessing or short-name matches.
"""

from dataclasses import dataclass, field
from collections import Counter
from collections.abc import Collection
import re

from sqlglot.tokens import Token, TokenType

from .sql_statements import is_word, routine_kind, starts_with

RelationName = tuple[str, ...]


def _name(tokens: list[Token], cursor: int) -> tuple[RelationName, int]:
    parts = []
    while cursor < len(tokens):
        token = tokens[cursor]
        if token.token_type == TokenType.IDENTIFIER:
            parts.append(token.text)
        elif re.fullmatch(
            r"[^\W\d][\w$]*", token.text
        ) and not token.token_type.name.endswith("STRING"):
            parts.append(token.text.lower())
        else:
            return (), cursor
        cursor += 1
        if cursor == len(tokens) or tokens[cursor].token_type != TokenType.DOT:
            return tuple(parts), cursor
        cursor += 1
    return (), cursor


def _create_view(tokens: list[Token]) -> tuple[RelationName, bool]:
    if not starts_with(tokens, "CREATE"):
        return (), False
    cursor = 1
    if starts_with(tokens[cursor:], "OR", "REPLACE"):
        cursor += 2
    if any(starts_with(tokens[cursor:], word) for word in ("TEMP", "TEMPORARY")):
        cursor += 1
    if starts_with(tokens[cursor:], "RECURSIVE"):
        cursor += 1
    materialized = starts_with(tokens[cursor:], "MATERIALIZED")
    cursor += int(materialized)
    if not starts_with(tokens[cursor:], "VIEW"):
        return (), False
    cursor += 1
    if materialized and starts_with(tokens[cursor:], "IF", "NOT", "EXISTS"):
        cursor += 3
    name, cursor = _name(tokens, cursor)
    # The query is out of scope, but a missing object/header is not a definition.
    depth = 0
    for i in range(cursor, len(tokens) - 1):
        token = tokens[i]
        if token.token_type == TokenType.L_PAREN:
            depth += 1
        elif token.token_type == TokenType.R_PAREN:
            depth -= 1
        elif depth == 0 and is_word(token, "AS"):
            return name, materialized
    return (), False


def _drop_materialized_views(tokens: list[Token]) -> list[RelationName]:
    if not starts_with(tokens, "DROP", "MATERIALIZED", "VIEW"):
        return []
    cursor = 3
    if starts_with(tokens[cursor:], "IF", "EXISTS"):
        cursor += 2
    names = []
    while cursor < len(tokens):
        name, cursor = _name(tokens, cursor)
        if not name:
            return []
        names.append(name)
        if cursor == len(tokens):
            return names
        if cursor == len(tokens) - 1 and any(
            is_word(tokens[cursor], word) for word in ("CASCADE", "RESTRICT")
        ):
            return names
        if tokens[cursor].token_type != TokenType.COMMA:
            return []
        cursor += 1
    return []


def _index_target(tokens: list[Token]) -> RelationName:
    if not starts_with(tokens, "CREATE"):
        return ()
    cursor = 1
    if starts_with(tokens[cursor:], "UNIQUE"):
        cursor += 1
    if not starts_with(tokens[cursor:], "INDEX"):
        return ()
    cursor += 1
    if starts_with(tokens[cursor:], "CONCURRENTLY"):
        cursor += 1
    if starts_with(tokens[cursor:], "IF", "NOT", "EXISTS"):
        cursor += 3
    if not starts_with(tokens[cursor:], "ON"):
        name, cursor = _name(tokens, cursor)
        if not name:
            return ()
    if not starts_with(tokens[cursor:], "ON"):
        return ()
    cursor += 1
    if starts_with(tokens[cursor:], "ONLY"):
        cursor += 1
    name, _ = _name(tokens, cursor)
    return name


@dataclass
class SQLParseContext:
    """One migration stream's exclusions; copied with staged DO changes."""

    materialized_views: set[RelationName] = field(default_factory=set)
    skipped: Counter[str] = field(default_factory=Counter)

    def skip_statement(
        self, tokens: list[Token], *, tables: Collection[str] = (), in_do: bool = False
    ) -> str | None:
        kind = routine_kind(tokens)
        if kind and any(
            is_word(token, "AS")
            and tokens[i + 1].token_type in {TokenType.STRING, TokenType.HEREDOC_STRING}
            or starts_with(tokens[i : i + 2], "BEGIN", "ATOMIC")
            for i, token in enumerate(tokens[:-1])
        ):
            return f"CREATE {kind} definition"
        if not in_do:
            for words in (("CALL",), ("DROP", "PROCEDURE"), ("CREATE", "EXTENSION")):
                if len(tokens) > len(words) and starts_with(tokens, *words):
                    return " ".join(words)
        name, materialized = _create_view(tokens)
        if name:
            # IF NOT EXISTS may find an existing table instead of a view.
            # Its real indexes must still reach the schema handler.
            if materialized and ".".join(name) not in tables:
                self.materialized_views.add(name)
            return "CREATE MATERIALIZED VIEW" if materialized else "CREATE VIEW"
        names = _drop_materialized_views(tokens)
        if names:
            self.materialized_views.difference_update(names)
            return "DROP MATERIALIZED VIEW"
        target = _index_target(tokens)
        if target in self.materialized_views and ".".join(target) not in tables:
            return "CREATE INDEX on recorded materialized view"
        return None
