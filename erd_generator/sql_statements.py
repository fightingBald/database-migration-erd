"""PostgreSQL statement boundaries using the project's pinned SQL tokenizer."""

from sqlglot.dialects import Dialect
from sqlglot.errors import TokenError
from sqlglot.tokens import Token, TokenType


class SQLLexError(ValueError):
    def __init__(
        self,
        line: int,
        message: str = (
            "Unterminated SQL token or invalid quoted literal; check dollar quotes, strings and comments"
        ),
    ):
        super().__init__(message)
        self.line = line


def tokenize_sql(sql: str) -> list[Token]:
    tokenizer = Dialect.get_or_raise("postgres").tokenizer()
    try:
        return tokenizer.tokenize(sql)
    except TokenError:
        # Locate the incomplete statement without exposing the tokenizer's
        # exception text, which includes source SQL and possibly credentials.
        statement_line = None
        offset = 0
        for token in tokenizer.tokens:
            if token.token_type == TokenType.SEMICOLON:
                statement_line = None
                offset = token.end + 1
            elif statement_line is None:
                statement_line = token.line
        if statement_line is None:
            offset += len(sql[offset:]) - len(sql[offset:].lstrip())
            statement_line = sql.count("\n", 0, offset) + 1
        raise SQLLexError(statement_line) from None


def split_sql_statements(sql: str) -> list[str]:
    statements = []
    start = 0
    tokens = tokenize_sql(sql)
    token_start = depth = 0
    routine = False
    for i, token in enumerate(tokens):
        if i == token_start:
            routine = routine_kind(tokens[i : i + 4]) is not None
        # SQL-language routine bodies are not necessarily quoted. Keep their
        # statements opaque just like dollar strings; CASE has its own END.
        if (routine and starts_with(tokens[i : i + 2], "BEGIN", "ATOMIC")) or (
            depth and is_word(token, "CASE")
        ):
            depth += 1
        elif depth and is_word(token, "END"):
            depth -= 1
        if token.token_type == TokenType.SEMICOLON and not depth:
            statement = sql[start : token.start].strip()
            if statement:
                statements.append(statement)
            start = token.end + 1
            token_start = i + 1
    if depth:
        raise SQLLexError(
            tokens[token_start].line,
            "Unterminated SQL routine body; expected END for BEGIN ATOMIC",
        )
    tail = sql[start:].strip()
    if tail:
        statements.append(tail)
    return statements


def is_word(token: Token, word: str) -> bool:
    return (
        token.token_type != TokenType.IDENTIFIER
        and not token.token_type.name.endswith("STRING")
        and token.text.upper() == word
    )


def starts_with(tokens: list[Token], *words: str) -> bool:
    return len(tokens) >= len(words) and all(
        is_word(token, word) for token, word in zip(tokens, words, strict=False)
    )


def routine_kind(tokens: list[Token]) -> str | None:
    if starts_with(tokens, "CREATE", "OR", "REPLACE"):
        tokens = tokens[3:]
    elif starts_with(tokens, "CREATE"):
        tokens = tokens[1:]
    else:
        return None
    return next(
        (kind for kind in ("FUNCTION", "PROCEDURE") if starts_with(tokens, kind)), None
    )
