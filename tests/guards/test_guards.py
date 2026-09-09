import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_vendor_read_only() -> None:
    manifest = ROOT / "scripts" / "vendor.sha256"
    assert manifest.is_file(), "vendor.sha256 manifest missing"
    problems: list[str] = []
    for entry in manifest.read_text(encoding="utf-8").splitlines():
        entry = entry.strip()
        if not entry:
            continue
        digest, _, rel = entry.partition("  ")
        f = ROOT / rel.strip()
        if not f.is_file():
            problems.append(f"missing: {rel}")
            continue
        actual = hashlib.sha256(f.read_bytes()).hexdigest()
        if actual != digest.strip():
            problems.append(f"changed: {rel}")
    assert not problems, f"vendor drift (I9): {problems}"
