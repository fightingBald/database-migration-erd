"""Shared test paths and assertion registration; never imported by runtime code."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"

pytest.register_assert_rewrite("tests.support.svg")
