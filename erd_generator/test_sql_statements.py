import pytest

from erd_generator.sql_parser import _split_sql_statements


@pytest.mark.parametrize(
    "statement",
    [
        "DO $$BEGIN NULL; RAISE NOTICE 'a;b'; END;$$",
        "DO $migration$BEGIN RAISE NOTICE $$a;b$$; END;$migration$",
        "DO $Case$BEGIN RAISE NOTICE 'unmatched quote'; END;$Case$",
        "CREATE TABLE a (message text DEFAULT $$semi; 'quote /* text */$$)",
        "CREATE TABLE a (message text DEFAULT $text$a;b$text$)",
        r"SELECT E'escaped\';semicolon'",
        "CREATE TABLE dollar$name (id int)",
        'CREATE TABLE "订单" ("备注" text DEFAULT $$内容;文字$$)',
        "/* outer; /* inner; */ still a comment; */ CREATE TABLE a (id int)",
        "-- $$ is only a comment;\nCREATE TABLE a (id int)",
    ],
)
def test_semicolons_in_literals_and_comments_do_not_split_statements(statement):
    following = "CREATE TABLE following (id int)"
    assert _split_sql_statements(f"{statement};\n{following};") == [
        statement,
        following,
    ]


@pytest.mark.parametrize(
    "sql",
    [
        "DO $$BEGIN NULL; END;",
        "DO $Tag$BEGIN NULL; END;$tag$;",
        "CREATE TABLE a (message text DEFAULT 'missing)",
        "/* missing closing comment",
    ],
)
def test_unterminated_tokens_are_rejected(sql):
    with pytest.raises(ValueError, match="Unterminated SQL token"):
        _split_sql_statements(sql)


def test_empty_statements_and_end_of_file():
    assert _split_sql_statements(" ; ; CREATE TABLE a (id int); ; SELECT 1") == [
        "CREATE TABLE a (id int)",
        "SELECT 1",
    ]
