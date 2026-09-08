from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_parity_seed() -> None:
    assert (ROOT / "scripts" / "vendor.sha256").is_file()
    for rel in ("infra/docker-compose.dev.yml", "infra/docker-compose.yml"):
        assert (ROOT / rel).is_file(), rel