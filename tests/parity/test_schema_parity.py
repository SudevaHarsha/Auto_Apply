import os

import psycopg
import pytest

from tests.parity import schema_parity

DEFAULT_MIGRATE_URL = schema_parity.DEFAULT_MIGRATE_URL


def _db_reachable() -> bool:
    url = os.getenv("MIGRATE_DATABASE_URL") or DEFAULT_MIGRATE_URL
    try:
        with psycopg.connect(url, connect_timeout=3):
            return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def parity() -> dict:
    if not _db_reachable():
        pytest.skip("postgres not reachable (run tasks.ps1 -Target parity)")
    return schema_parity.compare()


def test_parity_passes(parity: dict) -> None:
    assert parity["ok"], "\n".join(parity["problems"])

def test_golden_dump_committed() -> None:
    assert schema_parity.GOLDEN.is_file()

def test_docs_anchor_available() -> None:
    assert schema_parity.DOCS_SCHEMA.is_file()