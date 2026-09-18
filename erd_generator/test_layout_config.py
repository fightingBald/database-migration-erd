import pytest

from erd_generator.layout_config import GroupRule, LayoutConfig, load_layout_config


def test_load_minimal_and_styled_groups(tmp_path):
    path = tmp_path / "layout.yaml"
    path.write_text(
        'groups:\n  books:\n    tables: ["demo_library.books", "demo_library.books_*"]\n  loans:\n    tables: ["demo_library.loans_*"]\n    label: 借阅记录\n    color: gold\n'
    )
    assert load_layout_config(path) == LayoutConfig(
        (
            GroupRule("books", ("demo_library.books", "demo_library.books_*")),
            GroupRule("loans", ("demo_library.loans_*",), "借阅记录", "gold"),
        )
    )


@pytest.mark.parametrize(
    "text",
    [
        "",
        "[]",
        "groups: []",
        "groups: {}",
        "groups: {books: []}",
        "groups: {books: {tables: []}}",
        "groups: {books: {tables: books_*}}",
        "groups: {books: {tables: [null]}}",
        "groups: {books: {tables: ['']}}",
        "groups: {books: {tables: ['x'], color: ultraviolet}}",
        "groups: {books: {tables: ['x'], label: 123}}",
        "groups: {books: {tables: ['x'], unknown: secret}}",
        "groups: {books: {tables: ['x']}}\nunknown: secret",
        "groups: {books: {tables: ['x'], tables: ['y']}}",
        "groups: {books: {tables: ['x']}, books: {tables: ['y']}}",
        "groups: {1: {tables: ['x']}}",
        "groups: {books: {tables: [",
        "groups: {books: {tables: ['x'], <<: {color: blue}}}",
    ],
)
def test_rejects_invalid_yaml_contract_without_echoing_payload(tmp_path, text):
    path = tmp_path / "layout.yaml"
    path.write_text(text)
    with pytest.raises(ValueError, match="Layout config") as error:
        load_layout_config(path)
    assert "secret" not in str(error.value)


def test_missing_or_invalid_utf8_configuration_has_context(tmp_path):
    path = tmp_path / "layout.yaml"
    for payload in (None, b"\xff"):
        if payload is not None:
            path.write_bytes(payload)
        with pytest.raises(ValueError, match="Layout config.*layout.yaml"):
            load_layout_config(path)


def test_python_configuration_contract_is_checked():
    with pytest.raises(ValueError, match="Layout config"):
        GroupRule("a", (), color="blue")
    with pytest.raises(ValueError, match="Layout config"):
        GroupRule("a", ("t",), color="invalid")
    with pytest.raises(ValueError, match="Layout config"):
        LayoutConfig((GroupRule("a", ("t",)), GroupRule("a", ("u",))))
