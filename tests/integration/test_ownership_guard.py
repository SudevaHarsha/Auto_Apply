"""T2 ownership guard: no repository may touch a table it does not own (implementation §2).

Semantics:
- The ``OWNERSHIP`` map in ``backend/app/db/repositories/__init__.py`` is canonical.
- The union of every repository's ``owns`` set must equal ``OWNERSHIP`` (no undeclared /
  orphan / duplicated tables) and each class must declare exactly the tables the map assigns.
- No table name may be *used in code* (string literals and comments stripped) by any
  repository other than its owner. ``job_snapshots`` is exempt from the "no cross-repo
  reads" rule because it is a shared, RLS-exempt cache (I1/I4) — core_engine owns/writes it,
  but any component may read it.
"""

from __future__ import annotations

import re
from pathlib import Path

from backend.app.db.repositories import OWNERSHIP, SNAPSHOT_SHARED_READ

REPO_DIR = Path(__file__).resolve().parents[2] / "backend" / "app" / "db" / "repositories"

_CLASS_FILE = {
    "AuthRepository": "auth_repository.py",
    "CoreEngineRepository": "core_engine_repository.py",
    "LlmRouterRepository": "llm_router_repository.py",
    "DiscoveryRepository": "discovery_repository.py",
    "DiscordRepository": "discord_repository.py",
    "ChromeExtensionRepository": "chrome_extension_repository.py",
    "ObservabilityRepository": "observability_repository.py",
    "CheckpointingRepository": "checkpointing_repository.py",
}

_OWNS_RE = re.compile(r"owns\s*=\s*frozenset\(\s*\{(.*?)\}\s*\)", re.S)
_TRIPLE_RE = re.compile(r'("""(?s:.*?)"""|\'\'\'(?s:.*?)\'\'\')')
_COMMENT_RE = re.compile(r"#[^\n]*")
_STRING_RE = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'')
_WORD_RE = re.compile(r"\b_\w+\b")  # unused by design: skipped tables


def _repo_sources() -> dict[str, str]:
    return {name: (REPO_DIR / f).read_text(encoding="utf-8") for name, f in _CLASS_FILE.items()}


def _owned_tables(source: str) -> set[str]:
    m = _OWNS_RE.search(source)
    assert m, "repository must declare an `owns` frozenset"
    body = m.group(1).replace("\n", " ")
    return {t.strip().strip('"') for t in body.split(",") if t.strip()}


def _code_only(source: str) -> str:
    """Strip strings, docstrings, and comments so only real code remains."""
    s = _TRIPLE_RE.sub(" ", source)
    s = _COMMENT_RE.sub(" ", s)
    s = _STRING_RE.sub(" ", s)
    return s


def test_ownership_map_is_complete_and_consistent() -> None:
    sources = _repo_sources()
    declared: set[str] = set()
    for _name, src in sources.items():
        declared |= _owned_tables(src)
    assert declared == set(OWNERSHIP), (
        f"ownership drift: repo-declared={sorted(declared)} vs map={sorted(OWNERSHIP)}"
    )
    for owner, src in sources.items():
        assigned = {t for t, o in OWNERSHIP.items() if o == owner}
        assert _owned_tables(src) == assigned, (
            f"{owner}: owns {sorted(_owned_tables(src))} != map {sorted(assigned)}"
        )


def test_owner_classes_are_unique_and_cover_the_map() -> None:
    owners = set(OWNERSHIP.values())
    assert owners == set(_CLASS_FILE), (
        f"owners in map ({sorted(owners)}) != repo classes ({sorted(_CLASS_FILE)})"
    )


def test_no_table_used_outside_its_owner() -> None:
    sources = _repo_sources()
    for table in sorted(OWNERSHIP):
        if table in SNAPSHOT_SHARED_READ:
            continue  # shared cache: writable by core_engine, readable by all (I1/I4)
        owner = OWNERSHIP[table]
        needle = re.compile(rf"\b{re.escape(table)}\b")
        for other_name, other_src in sources.items():
            if other_name == owner:
                continue
            assert not needle.search(_code_only(other_src)), (
                f"{other_name} uses {table!r} in code but {owner} owns it"
            )