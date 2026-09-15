"""Recognize wholly ERD-neutral DO bodies without evaluating PL/pgSQL."""

import re

from sqlglot.tokens import Token, TokenType

from .postgres_commands import harmless_do_statement, neutral_command
from .sql_statements import SQLLexError, is_word, starts_with, tokenize_sql

_STRINGS = {TokenType.STRING, TokenType.HEREDOC_STRING}
_FORMAT_SLOT = re.compile(r"%(?:([1-9][0-9]*)\$)?([IL])|%%")


def _unqualify_catalog(tokens: list[Token]) -> list[Token]:
    if len(tokens) >= 3 and is_word(tokens[0], "PG_CATALOG"):
        if tokens[1].token_type == TokenType.DOT:
            return tokens[2:]
    return tokens


def _safe_argument(tokens: list[Token]) -> bool:
    if len(tokens) == 1:
        return tokens[0].token_type in _STRINGS or any(
            is_word(tokens[0], name)
            for name in ("CURRENT_USER", "CURRENT_ROLE", "SESSION_USER")
        )
    tokens = _unqualify_catalog(tokens)
    return (
        len(tokens) == 3
        and any(
            is_word(tokens[0], name) for name in ("CURRENT_DATABASE", "CURRENT_SCHEMA")
        )
        and tokens[1].token_type == TokenType.L_PAREN
        and tokens[2].token_type == TokenType.R_PAREN
    )


def _safe_condition(tokens: list[Token]) -> bool:
    """Only boolean constants or a simple role-catalog existence check."""
    if starts_with(tokens, "NOT"):
        tokens = tokens[1:]
    if len(tokens) == 1:
        return is_word(tokens[0], "TRUE") or is_word(tokens[0], "FALSE")
    if not (
        len(tokens) >= 3
        and starts_with(tokens, "EXISTS")
        and tokens[1].token_type == TokenType.L_PAREN
        and tokens[-1].token_type == TokenType.R_PAREN
    ):
        return False
    query = tokens[2:-1]
    if not starts_with(query, "SELECT"):
        return False
    from_index = next(
        (i for i, token in enumerate(query) if is_word(token, "FROM")), -1
    )
    if from_index not in {1, 2}:
        return False
    tail = _unqualify_catalog(query[from_index + 1 :])
    if len(tail) != 5:
        return False
    column = next(
        (
            column
            for catalog, column in (
                ("PG_ROLES", "ROLNAME"),
                ("PG_AUTHID", "ROLNAME"),
                ("PG_USER", "USENAME"),
            )
            if is_word(tail[0], catalog)
        ),
        None,
    )
    return (
        column is not None
        and (
            from_index == 1
            or query[1].token_type == TokenType.STAR
            or query[1].token_type == TokenType.NUMBER
            and query[1].text == "1"
            or is_word(query[1], column)
        )
        and is_word(tail[1], "WHERE")
        and is_word(tail[2], column)
        and tail[3].token_type == TokenType.EQ
        and _safe_argument(tail[4:])
    )


def _neutral_commands(tokens: list[Token]) -> bool:
    """Check every command, including those after a semicolon in a template."""
    commands: list[list[Token]] = [[]]
    for token in tokens:
        if token.token_type == TokenType.SEMICOLON:
            commands.append([])
        else:
            commands[-1].append(token)
    return any(commands) and all(
        neutral_command(command) for command in commands if command
    )


def _neutral_template(template: str, argument_count: int) -> bool:
    # Represent arguments as quoted tokens, never as SQL text. Every slot must
    # occupy a complete token outside existing strings, identifiers and comments.
    rendered = ""
    slots = []
    cursor = next_argument = 0
    while cursor < len(template):
        percent = template.find("%", cursor)
        if percent < 0:
            rendered += template[cursor:]
            break
        rendered += template[cursor:percent]
        match = _FORMAT_SLOT.match(template, percent)
        if match is None:
            return False
        cursor = match.end()
        if match.group() == "%%":
            rendered += "%"
            continue
        position, kind = match.groups()
        index = int(position) - 1 if position else next_argument
        if index >= argument_count:
            return False
        next_argument = index + 1
        # Adjacent unquoted text could merge with an identifier when PostgreSQL
        # decides that quote_ident need not add quotes.
        neighbors = (
            template[max(0, percent - 1) : percent] + template[cursor : cursor + 1]
        )
        if any(char.isalnum() or char in "_$\"'" for char in neighbors):
            return False
        quote = '"' if kind == "I" else "'"
        value = f"{quote}__erd_argument_{len(slots)}__{quote}"
        token_type = TokenType.IDENTIFIER if kind == "I" else TokenType.STRING
        slots.append((len(rendered), len(rendered) + len(value) - 1, token_type))
        rendered += value
    tokens = tokenize_sql(rendered)
    spans = {(token.start, token.end, token.token_type) for token in tokens}
    return all(slot in spans for slot in slots) and _neutral_commands(tokens)


def _neutral_execute(argument_sql: str) -> bool:
    # sqlglot sometimes treats EXECUTE's whole argument as an opaque STRING.
    # Retokenize the original suffix to distinguish a literal from an expression.
    tokens = tokenize_sql(argument_sql)
    if len(tokens) == 1 and tokens[0].token_type in _STRINGS:
        return _neutral_commands(tokenize_sql(tokens[0].text))
    tokens = _unqualify_catalog(tokens)
    if not (
        len(tokens) >= 4
        and starts_with(tokens, "FORMAT")
        and tokens[1].token_type == TokenType.L_PAREN
        and tokens[2].token_type in _STRINGS
        and tokens[-1].token_type == TokenType.R_PAREN
    ):
        return False
    arguments: list[list[Token]] = []
    for token in tokens[3:-1]:
        if token.token_type == TokenType.COMMA:
            arguments.append([])
        elif arguments:
            arguments[-1].append(token)
        else:
            return False
    # Even unused format arguments are evaluated by PostgreSQL.
    return all(_safe_argument(arg) for arg in arguments) and _neutral_template(
        tokens[2].text, len(arguments)
    )


def neutral_do_body(sql: str) -> bool:
    """All branches must be neutral; unknown constructs fail this allowlist.

    The caller retains its existing static-DDL path and error/atomicity policy.
    A body mixing conditional setup and structural DDL does not qualify here.
    """
    try:
        return _neutral_body(tokenize_sql(sql), sql)
    except SQLLexError:
        return False


def _neutral_body(tokens: list[Token], sql: str) -> bool:
    # Each frame records whether ELSE has already appeared. No branch is chosen
    # and nesting uses an explicit stack rather than recursive evaluation.
    branches: list[bool] = []
    cursor = 0
    while cursor < len(tokens):
        token = tokens[cursor]
        if any(is_word(token, word) for word in ("IF", "ELSIF", "ELSEIF")):
            if is_word(token, "IF"):
                branches.append(False)
            elif not branches or branches[-1]:
                return False
            end = cursor + 1
            while end < len(tokens) and not is_word(tokens[end], "THEN"):
                end += 1
            if end == len(tokens) or not _safe_condition(tokens[cursor + 1 : end]):
                return False
            cursor = end + 1
        elif is_word(token, "ELSE"):
            if not branches or branches[-1]:
                return False
            branches[-1] = True
            cursor += 1
        elif is_word(token, "END"):
            if not (
                branches
                and starts_with(tokens[cursor:], "END", "IF")
                and cursor + 2 < len(tokens)
                and tokens[cursor + 2].token_type == TokenType.SEMICOLON
            ):
                return False
            branches.pop()
            cursor += 3
        else:
            end = cursor
            while end < len(tokens) and tokens[end].token_type != TokenType.SEMICOLON:
                end += 1
            if end == len(tokens):
                return False
            command = tokens[cursor:end]
            if not (
                neutral_command(command)
                or harmless_do_statement(command)
                or is_word(token, "EXECUTE")
                and _neutral_execute(sql[token.end + 1 : tokens[end].start])
            ):
                return False
            cursor = end + 1
    return bool(tokens) and not branches
