param([string]$Target = "test")

$ErrorActionPreference = "Stop"

switch ($Target) {
    "lint" { & ruff check .; & mypy backend }
    "test" { & python -m pytest tests/units }
    "dev-up" { & docker compose -f infra/docker-compose.dev.yml up -d }
    "dev-down" { & docker compose -f infra/docker-compose.dev.yml down }
    "test-integration" {
        & docker compose -f infra/docker-compose.dev.yml up -d db
        & python -m pytest tests/integration
        & docker compose -f infra/docker-compose.dev.yml down
    }
    "test-e2e" { & python -m pytest tests/e2e }
    "parity" { & python -m pytest tests/parity }
    default { Write-Error "Unknown target: $Target" }
}