import pytest

from erd_generator.fk_config import apply_foreign_key_config, load_foreign_key_config
from erd_generator.schema import Column, Table


def load(tmp_path, body):
    path = tmp_path / "fks.yaml"
    path.write_text(body, encoding="utf-8")
    failures = []
    entries, source = load_foreign_key_config(str(path), failures)
    return entries, source, failures


@pytest.mark.parametrize(
    "body",
    [
        "a: {fks: 42}",
        "a: {fks: [[x]]}",
        "a: {fks: [[[], b, id]]}",
        "a: {fks: [[x, b, [id, other]]]}",
        "a: {fks: [false]}",
        "a: {fks: [[x, b, id, unexpected]]}",
        "42: {fks: []}",
        "a: {fks: [['', b, id]]}",
        "a: 1",
        "a: {fks: [[x, '', id]]}",
        "[not, a, mapping]",
        "a: [unterminated",
    ],
)
def test_invalid_config_entries_collect_errors(tmp_path, body):
    entries, _, failures = load(tmp_path, body)
    assert not entries
    assert failures


def test_strict_lookup_rejects_ambiguous_or_wrong_qualified_table(tmp_path):
    schema = {
        name: Table(name, columns=[Column("id")]) for name in ("one.a", "two.a", "b")
    }
    for table_name in ("a", "missing.a"):
        entries, source, failures = load(
            tmp_path, f"{table_name}: {{fks: [[id, b, id]]}}"
        )
        apply_foreign_key_config(
            schema, entries, config_source=source, failures=failures, strict=True
        )
        assert failures
        assert not any(t.foreign_keys for t in schema.values())


def test_strict_lookup_rejects_unknown_target_or_column(tmp_path):
    schema = {name: Table(name, columns=[Column("id")]) for name in ("a", "b")}
    for fk in ("id, missing, id", "absent, b, id", "id, b, absent"):
        entries, source, failures = load(tmp_path, f"a: {{fks: [[{fk}]]}}")
        apply_foreign_key_config(
            schema, entries, config_source=source, failures=failures, strict=True
        )
        assert failures
        assert not schema["a"].foreign_keys


def test_valid_config_deduplicates_and_accepts_unambiguous_suffix(tmp_path):
    schema = {
        name: Table(name, columns=[Column("id")]) for name in ("public.a", "public.b")
    }
    entries, source, failures = load(tmp_path, "a: {fks: [[id, b, id], [id, b, id]]}")
    apply_foreign_key_config(
        schema, entries, config_source=source, failures=failures, strict=True
    )
    assert not failures
    assert len(schema["public.a"].foreign_keys) == 1
    assert schema["public.a"].foreign_keys[0].ref_table == "public.b"


def test_explicit_empty_mapping_reference_columns_are_invalid(tmp_path):
    entries, _, failures = load(
        tmp_path, "a: {fks: [{columns: [id], table: b, ref_columns: []}]}"
    )
    assert not entries
    assert failures
