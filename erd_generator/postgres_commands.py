"""Bounded PostgreSQL command policy; no Schema or renderer dependencies."""

from dataclasses import dataclass

from sqlglot import exp
from sqlglot.tokens import Token, TokenType

from .sql_statements import is_word, starts_with, tokenize_sql


def _is_name(token: Token) -> bool:
    return token.token_type in {TokenType.VAR, TokenType.IDENTIFIER}


def _empty_schema(tokens: list[Token]) -> bool:
    remaining = tokens[2:]
    if starts_with(remaining, "IF", "NOT", "EXISTS"):
        remaining = remaining[3:]
    if remaining and not starts_with(remaining, "AUTHORIZATION"):
        if not _is_name(remaining[0]):
            return False
        remaining = remaining[1:]
        if not remaining:
            return True
    return (
        len(remaining) == 2
        and starts_with(remaining, "AUTHORIZATION")
        and (
            _is_name(remaining[1])
            or any(
                is_word(remaining[1], word)
                for word in ("CURRENT_USER", "CURRENT_ROLE", "SESSION_USER")
            )
        )
    )


def neutral_command(tokens: list[Token]) -> str | None:
    """Recognize commands whose own operation does not change ERD structure.

    This is an impact allowlist, not a complete PostgreSQL syntax validator.
    In particular, CREATE SCHEMA must not contain any embedded object DDL.
    """
    if (
        any(starts_with(tokens, word) for word in ("GRANT", "REVOKE"))
        and len(tokens) >= 4
        and any(is_word(t, "TO") or is_word(t, "FROM") for t in tokens[1:])
    ):
        return tokens[0].text.upper()
    if starts_with(tokens, "ALTER", "DEFAULT", "PRIVILEGES") and any(
        is_word(t, "GRANT") or is_word(t, "REVOKE") for t in tokens[3:]
    ):
        return "ALTER DEFAULT PRIVILEGES"
    if (
        any(starts_with(tokens, "CREATE", kind) for kind in ("ROLE", "USER"))
        and len(tokens) >= 3
        and _is_name(tokens[2])
        and not is_word(tokens[2], "MAPPING")
        and not any(
            is_word(t, word)
            for t in tokens[3:]
            for word in ("CREATE", "ALTER", "DROP", "DO", "CALL", "EXECUTE")
        )
    ):
        return "CREATE ROLE/USER"
    if starts_with(tokens, "CREATE", "SCHEMA") and _empty_schema(tokens):
        return "CREATE SCHEMA"
    return None


def routine_definition(statement: exp.Expression) -> str | None:
    if not isinstance(statement, exp.Create):
        return None
    kind = (statement.args.get("kind") or "").upper()
    body = statement.args.get("expression")
    if kind in {"FUNCTION", "PROCEDURE"} and (
        isinstance(body, exp.Heredoc)
        or (isinstance(body, exp.Literal) and body.is_string)
    ):
        return f"CREATE {kind} definition"
    return None


def harmless_do_statement(tokens: list[Token]) -> bool:
    if len(tokens) == 1 and starts_with(tokens, "NULL"):
        return True
    return (
        len(tokens) == 3
        and starts_with(tokens, "RAISE")
        and any(
            is_word(tokens[1], level)
            for level in ("NOTICE", "INFO", "DEBUG", "LOG", "WARNING")
        )
        and tokens[2].token_type in {TokenType.STRING, TokenType.HEREDOC_STRING}
    )


@dataclass(frozen=True)
class DoBody:
    sql: str
    line_offset: int


class UnsupportedDoError(ValueError):
    pass


DO_STATEMENT_ERROR = (
    "Unsupported DO statement: expected static table/index DDL or a provably "
    "ERD-neutral setup block; unknown conditions, loops, calls and dynamic SQL "
    "are not evaluated (see dev_guide.md)"
)


def extract_do_body(sql: str, tokens: list[Token]) -> DoBody:
    """Extract only a dollar-quoted, unlabeled PL/pgSQL BEGIN ... END block."""
    code_start = tokens[0].end + 1
    remaining = tokenize_sql(sql[code_start:])
    language_prefix = starts_with(remaining, "LANGUAGE")
    if language_prefix:
        if len(remaining) < 3 or not is_word(remaining[1], "PLPGSQL"):
            raise UnsupportedDoError(
                "Unsupported DO language: only plpgsql is supported"
            )
        remaining = remaining[2:]
    if not remaining or remaining[0].token_type != TokenType.HEREDOC_STRING:
        raise UnsupportedDoError(
            "Unsupported DO body: use a dollar-quoted plpgsql block"
        )
    literal = remaining[0]
    suffix = remaining[1:]
    if suffix and (
        language_prefix
        or len(suffix) != 2
        or not starts_with(suffix, "LANGUAGE", "PLPGSQL")
    ):
        raise UnsupportedDoError("Unsupported DO language or trailing syntax")
    body_tokens = tokenize_sql(literal.text)
    if body_tokens and body_tokens[-1].token_type == TokenType.SEMICOLON:
        body_tokens = body_tokens[:-1]
    if (
        len(body_tokens) < 2
        or not starts_with(body_tokens, "BEGIN")
        or not is_word(body_tokens[-1], "END")
    ):
        raise UnsupportedDoError(
            "Unsupported DO block: expected an unlabeled BEGIN ... END without DECLARE"
        )
    if len(body_tokens) > 2 and body_tokens[-2].token_type != TokenType.SEMICOLON:
        raise UnsupportedDoError(
            "Unsupported DO syntax: each statement needs a semicolon"
        )
    literal_start = code_start + literal.start
    delimiter_length = sql.index("$", literal_start + 1) - literal_start + 1
    inner_start = literal_start + delimiter_length + body_tokens[0].end + 1
    inner_end = literal_start + delimiter_length + body_tokens[-1].start
    return DoBody(sql[inner_start:inner_end], sql.count("\n", 0, inner_start))
