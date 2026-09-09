import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run(args: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def test_harness_collects() -> None:
    suites = ["units", "integration", "e2e", "guards", "parity"]
    for suite in suites:
        assert (ROOT / "tests" / suite).is_dir(), f"missing suite {suite}"
    result = _run([sys.executable, "-m", "pytest", "--collect-only", "-q"])
    assert result.returncode == 0, result.stderr


def test_ci_stages_defined() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for stage in ("lint", "unit", "integration", "parity"):
        assert stage in ci, f"CI missing stage {stage}"


def test_lint_target() -> None:
    result = _run([sys.executable, "-m", "ruff", "check", "."])
    assert result.returncode == 0, result.stdout
    result = _run([sys.executable, "-m", "mypy", "backend"])
    assert result.returncode == 0, result.stdout


def test_infra_compose_valid() -> None:
    assert shutil.which("docker"), "docker not installed"
    dev = ROOT / "infra" / "docker-compose.dev.yml"
    result = _run(["docker", "compose", "-f", str(dev), "config", "-q"])
    assert result.returncode == 0, result.stderr
    out = _run(["docker", "compose", "-f", str(dev), "config"]).stdout
    assert "api:" in out and "db:" in out
