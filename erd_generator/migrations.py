"""Select forward migration SQL without changing source text or line numbers."""

import re

from .sql_statements import SQLLexError, split_sql_statements, tokenize_sql


_DIRECTION = re.compile(
    r"^[ \t]*--[ \t]*\+(migrate|goose)[ \t]+(Up|Down)"
    r"(?:[ \t]+notransaction)?[ \t]*\r?$",
    re.MULTILINE | re.IGNORECASE,
)


def up_migration_sql(sql: str) -> str:
    """Keep plain SQL or one Up section; Down SQL is never tokenized.

    Only candidate directive lines need a lexical check. Reuse the PostgreSQL
    splitter so strings, nested comments and unquoted routine bodies obey the
    same boundaries as schema parsing. A slice preserves diagnostic line numbers.
    """
    framework = None
    for match in _DIRECTION.finditer(sql):
        prefix = sql[: match.start()]
        try:
            split_sql_statements(prefix)
        except SQLLexError:
            # A marker inside a literal/comment/body is ordinary SQL content.
            # Any actual lexical error is still reported by the schema parser.
            continue
        line = sql.count("\n", 0, match.start()) + 1
        kind, direction = (part.lower() for part in match.groups())
        if framework is None:
            if direction != "up":
                raise SQLLexError(line, "Migration Down has no preceding Up section")
            if tokenize_sql(prefix):
                raise SQLLexError(line, "Migration SQL appears before the Up section")
            framework = kind
        elif kind != framework:
            raise SQLLexError(line, "Migration mixes sql-migrate and goose directions")
        elif direction == "up":
            raise SQLLexError(line, "Migration contains more than one Up section")
        else:
            return prefix
    return sql
