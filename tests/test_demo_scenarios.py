"""Business outcomes for the executable demos, independent of layout snapshots."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from erd_generator.d2 import build_d2
from erd_generator.fk_config import apply_foreign_key_config, load_foreign_key_config
from erd_generator.sql_parser import load_schema_result
from erd_generator.validation import validate_schema

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def load_demo(name):
    directory = EXAMPLES / name
    result = load_schema_result(directory / "migrations")
    config = directory / "fks.yaml"
    if config.exists():
        entries, source = load_foreign_key_config(str(config), result.failures)
        apply_foreign_key_config(
            result.schema,
            entries,
            config_source=source,
            failures=result.failures,
            strict=True,
        )
    assert not result.failures
    validation = validate_schema(result.schema)
    assert not validation.errors
    return result.schema, validation.relationships


def endpoints(relations):
    return {(fk.table, fk.columns, fk.ref_table, fk.ref_columns) for fk in relations}


def test_tenant_orders_preserve_composite_pairs_and_actor_roles():
    schema, relations = load_demo("tenant_orders")
    assert set(schema) == {
        "accounts.tenants",
        "accounts.users",
        "accounts.roles",
        "accounts.user_roles",
        "catalog.categories",
        "catalog.products",
        "sales.orders",
        "sales.order_items",
        "billing.payments",
    }
    expected = {
        (table, ("tenant_id",), "accounts.tenants", ("id",))
        for table in (
            "accounts.users",
            "accounts.roles",
            "catalog.categories",
            "sales.orders",
        )
    }
    for table, local, target in [
        ("accounts.users", "manager_id", "accounts.users"),
        ("accounts.user_roles", "user_id", "accounts.users"),
        ("accounts.user_roles", "role_id", "accounts.roles"),
        ("catalog.categories", "parent_id", "catalog.categories"),
        ("catalog.products", "category_id", "catalog.categories"),
        ("sales.orders", "created_by", "accounts.users"),
        ("sales.orders", "approved_by", "accounts.users"),
        ("sales.orders", "assigned_to", "accounts.users"),
        ("sales.order_items", "order_id", "sales.orders"),
        ("sales.order_items", "product_id", "catalog.products"),
        ("billing.payments", "order_id", "sales.orders"),
    ]:
        expected.add((table, ("tenant_id", local), target, ("tenant_id", "id")))
    assert endpoints(relations) == expected
    assert len(relations) == 15
    assert sum(len(fk.columns) for fk in relations) == 26
    assert schema["sales.order_items"].primary_key == {
        "tenant_id",
        "order_id",
        "line_no",
    }
    assert schema["accounts.users"].get_column("manager_id").nullable
    source = build_d2(schema, show_types=True)
    assert '"fk_order_product [1/2]"' in source
    assert '"fk_order_product [2/2]"' in source
    assert "manager_id → id" in source
    # Composite/partial uniqueness must not mark each participating column unique.
    products = source.split('"catalog.products": {', 1)[1].split("\n}", 1)[0]
    assert '"sku": "TEXT"\n' in products
    assert "uq_product_sku" in products


def test_release_evolution_removes_retired_objects_and_retargets_references():
    schema, relations = load_demo("release_evolution")
    assert {
        name: [c.name for c in table.columns] for name, table in schema.items()
    } == {
        "app.customers": ["customer_id", "email", "display_name", "metadata"],
        "app.orders": ["id", "customer_id", "total_amount", "lifecycle_state"],
        "app.order_lines": ["id", "order_id", "quantity", "unit_price"],
        "audit.events": ["id", "customer_id", "event_type"],
    }
    assert endpoints(relations) == {
        ("app.orders", ("customer_id",), "app.customers", ("customer_id",)),
        ("app.order_lines", ("order_id",), "app.orders", ("id",)),
        ("audit.events", ("customer_id",), "app.customers", ("customer_id",)),
    }
    assert schema["app.customers"].primary_key == {"customer_id"}
    assert not schema["app.orders"].get_column("lifecycle_state").nullable
    assert schema["app.orders"].get_column("lifecycle_state").data_type == "VARCHAR(24)"
    assert schema["app.orders"].get_column("total_amount").data_type == "DECIMAL(16, 2)"
    assert {index.name for t in schema.values() for index in t.indexes} == {
        "uq_customer_email",
        "ix_customer_lower_email",
        "ix_orders_state",
        "uq_active_order",
    }
    assert "fk_order_legacy" not in schema["app.orders"].constraint_types
    assert "uq_legacy_code" not in schema["app.customers"].constraint_types


def test_logical_relationships_resolve_same_named_tables_and_deduplicate_sources():
    schema, relations = load_demo("logical_relationships")
    assert set(schema) == {
        "auth.users",
        "crm.users",
        "crm.accounts",
        "support.tickets",
        "integration.sync_jobs",
        "ops.outbox",
    }
    expected = [
        ("crm.accounts", "owner_id", "crm.users"),
        ("crm.accounts", "parent_id", "crm.accounts"),
        ("crm.users", "account_ref", "crm.accounts"),
        ("crm.users", "external_auth_id", "auth.users"),
        ("support.tickets", "reporter_id", "crm.users"),
        ("support.tickets", "assignee_id", "auth.users"),
        ("support.tickets", "account_id", "crm.accounts"),
        ("integration.sync_jobs", "ticket_id", "support.tickets"),
        ("integration.sync_jobs", "triggered_by", "auth.users"),
        ("integration.sync_jobs", "previous_job_id", "integration.sync_jobs"),
    ]
    assert endpoints(relations) == {
        (table, (column,), target, ("id",)) for table, column, target in expected
    }
    assert sum(len(t.foreign_keys) for t in schema.values()) == 10
    assert not schema["ops.outbox"].foreign_keys
    assert '"ops.outbox": {' in build_d2(schema)


def test_readability_handles_real_sql_identifiers_and_empty_table():
    schema, relations = load_demo("readability")
    assert set(schema) == {
        "报表.客户资料",
        "报表.monthly_customer_reconciliation_details",
        "报表.processing_attempts",
        "报表.empty_extension_point",
    }
    assert [c.name for c in schema["报表.客户资料"].columns] == [
        "客户编号",
        "客户名称",
        "shape",
        "a.b",
        "${reference}",
        "path\\segment",
        'quoted"label',
    ]
    assert len(relations) == 3
    assert not schema["报表.empty_extension_point"].columns
    source = build_d2(schema, show_types=True)
    assert '"\\${reference}": "TEXT"' in source
    assert '"path\\\\segment": "TEXT"' in source
    assert '"quoted\\"label": "TEXT"' in source
    assert "previous.attempt → id" in source


@pytest.mark.parametrize("direction", ["right", "left", "up", "down"])
def test_demo_cli_direction_and_type_options(tmp_path, direction):
    output = tmp_path / "schema.d2"
    command = [
        sys.executable,
        "-m",
        "erd_generator",
        "--migrations",
        str(EXAMPLES / "tenant_orders/migrations"),
        "--out",
        str(output),
        "--direction",
        direction,
    ]
    result = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stderr
    assert f"direction: {direction}\n" in output.read_text()
    assert '"sku": ""' in output.read_text()
    result = subprocess.run(
        [*command, "--show-types"], cwd=ROOT, capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stderr
    assert '"sku": "TEXT"' in output.read_text()
    assert not output.with_suffix(".svg").exists()


@pytest.mark.parametrize(
    "case_id",
    [
        "ambiguous_table",
        "stale_fk_column",
        "implicit_composite",
        "malformed_sql",
        "invalid_layout",
        "missing_renderer",
    ],
)
def test_failure_demos_preserve_last_good_artifacts(tmp_path, case_id):
    catalog = json.loads((EXAMPLES / "scenarios.json").read_text())
    case = next(c for c in catalog["failure"] if c["id"] == case_id)
    source, svg = tmp_path / "schema.d2", tmp_path / "schema.svg"
    source.write_text("previous good source", encoding="utf-8")
    svg.write_text("previous good image", encoding="utf-8")
    command = [
        sys.executable,
        "-m",
        "erd_generator",
        "--migrations",
        str(ROOT / case["migrations"]),
        "--out",
        str(source),
        "--log-dir",
        str(tmp_path),
        "--render",
        "svg",
    ]
    if case.get("fk_config"):
        command.extend(["--fk-config", str(ROOT / case["fk_config"])])
    result = subprocess.run(
        [*command, *case.get("args", [])],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == case["exit_code"], result.stderr
    assert case["error"] in result.stderr
    assert "Traceback" not in result.stderr
    assert svg.read_text() == "previous good image"
    if case["id"] == "missing_renderer":
        assert "shape: sql_table" in source.read_text()
        assert "SVG was not updated" in result.stderr
    else:
        assert source.read_text() == "previous good source"
