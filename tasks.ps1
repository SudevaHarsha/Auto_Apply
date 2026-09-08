param([string]$Target = "test")

# PowerShell 5.1 turns ANY native stderr write into a terminating NativeCommandError
# under "Stop" (e.g. `docker compose up -d` on an already-running container prints
# "Container ... Running" to stderr and aborts the whole script). We run in "Continue"
# and fail hard explicitly via Invoke-Check, which is the robust pattern for wrapping
# native binaries. Real (cmdlet/PS) errors still halt via the check helpers.
$ErrorActionPreference = "Continue"

# Run a native command and throw if it exits non-zero.
function Invoke-Check {
    param(
        [scriptblock]$Command,
        [string]$What = "command"
    )
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "FAILED: $What (exit $LASTEXITCODE)"
    }
}

function Load-Env {
    param([string]$File = ".env")
    $envFile = Join-Path (Get-Location) $File
    if (Test-Path $envFile) {
        Get-Content $envFile | ForEach-Object {
            $line = $_.Trim()
            if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
                $kv = $line.Split('=', 2)
                Set-Item -Path ("env:" + $kv[0]) -Value $kv[1]
            }
        }
    }
}

function Load-TestEnv {
    if (Test-Path (Join-Path (Get-Location) ".env.test")) {
        Load-Env -File ".env.test"
    } else {
        Load-Env -File ".env.test.example"
    }
}

# Dev env by default; test targets call Load-TestEnv (overrides URLs to :5435).
Load-Env

# Prefer the project venv when present (global `python` may be a bare shim).
$script:Py = "python"
if (Test-Path (Join-Path $PSScriptRoot ".venv\Scripts\python.exe")) {
    $script:Py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
}

function Wait-Db {
    param(
        [string]$ComposeFile = "infra/docker-compose.dev.yml",
        [string]$Service = "db"
    )
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        & docker compose -f $ComposeFile exec -T $Service pg_isready -U autoapply 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { Write-Error "$Service did not become ready" }
}

function Run-Parity {
    param(
        [string]$ComposeFile,
        [string]$DbService
    )
    Set-Item -Path env:PARITY_COMPOSE -Value $ComposeFile
    Set-Item -Path env:PARITY_DB_SERVICE -Value $DbService
    Invoke-Check { & $Py tests/parity/schema_parity.py } -What "schema parity"
    Invoke-Check { & $Py -m pytest tests/parity } -What "parity pytest"
}

# Point an existing DB URL at a different database on the same host (same creds).
function New-DbUrl {
    param([string]$BaseUrl, [string]$Db)
    return $BaseUrl.Substring(0, $BaseUrl.LastIndexOf('/') + 1) + $Db
}

switch ($Target) {
    "lint" {
        Invoke-Check { & $Py -m ruff check . } -What "ruff lint"
        Invoke-Check { & $Py -m mypy backend } -What "mypy type check"
    }
    "test" { Invoke-Check { & $Py -m pytest tests/units } -What "unit tests" }
    "dev-up" { & docker compose -f infra/docker-compose.dev.yml up -d }
    "dev-down" { & docker compose -f infra/docker-compose.dev.yml down }
    "db-reset" {
        & docker compose -f infra/docker-compose.dev.yml down -v
        & docker compose -f infra/docker-compose.dev.yml up -d db
        Wait-Db
    }
    "migrate" { Invoke-Check { & $Py db/run_migrations.py } -What "migrate dev" }
    "parity" {
        Load-TestEnv
        Set-Item -Path env:PARITY_COMPOSE -Value "infra/docker-compose.test.yml"
        Set-Item -Path env:PARITY_DB_SERVICE -Value "db_test"
        & docker compose -f infra/docker-compose.test.yml up -d db_test
        Wait-Db -ComposeFile "infra/docker-compose.test.yml" -Service "db_test"
        Invoke-Check { & $Py db/per_run_db.py ensure-baseline } -What "ensure test baseline"
        Run-Parity -ComposeFile "infra/docker-compose.test.yml" -DbService "db_test"
    }
    "parity-dev" {
        Set-Item -Path env:PARITY_COMPOSE -Value "infra/docker-compose.dev.yml"
        Set-Item -Path env:PARITY_DB_SERVICE -Value "db"
        & docker compose -f infra/docker-compose.dev.yml up -d db
        Wait-Db
        Run-Parity -ComposeFile "infra/docker-compose.dev.yml" -DbService "db"
    }
    "test-integration" {
        Load-TestEnv
        Set-Item -Path env:PARITY_COMPOSE -Value "infra/docker-compose.test.yml"
        Set-Item -Path env:PARITY_DB_SERVICE -Value "db_test"
        # Option 1 (enterprise pattern): the persistent stack + baseline stay up; the suite
        # runs against a DISPOSABLE per-run clone and never touches the baseline (which
        # stays clean/inspectable). Still swap stderr-safe, so `up -d` on an already-running
        # container is a no-op rather than a NativeCommandError.
        & docker compose -f infra/docker-compose.test.yml up -d db_test
        Wait-Db -ComposeFile "infra/docker-compose.test.yml" -Service "db_test"
        Invoke-Check { & $Py db/per_run_db.py ensure-baseline } -What "ensure test baseline"
        $clone = Invoke-Check { & $Py db/per_run_db.py create } -What "create test clone"
        $clone = $clone.Trim()
        # DATABASE_URL (app_user, RLS subject) and MIGRATE_DATABASE_URL (autoapply admin)
        # must BOTH point at the clone. Mixing creds (e.g. running tests as the superuser)
        # would bypass RLS and make the isolation matrix fail.
        Set-Item -Path env:MIGRATE_DATABASE_URL -Value (New-DbUrl $env:MIGRATE_DATABASE_URL $clone)
        Set-Item -Path env:DATABASE_URL -Value (New-DbUrl $env:DATABASE_URL $clone)
        try {
            Invoke-Check { & $Py -m pytest tests/integration } -What "integration tests"
        } finally {
            & $Py db/per_run_db.py cleanup
        }
    }
    "test-e2e" { & $Py -m pytest tests/e2e }
    "test-env-up" {
        Load-TestEnv
        Set-Item -Path env:PARITY_COMPOSE -Value "infra/docker-compose.test.yml"
        Set-Item -Path env:PARITY_DB_SERVICE -Value "db_test"
        & docker compose -f infra/docker-compose.test.yml up -d
        Wait-Db -ComposeFile "infra/docker-compose.test.yml" -Service "db_test"
        Invoke-Check { & $Py db/per_run_db.py ensure-baseline } -What "ensure test baseline"
    }
    "test-env-reset" {
        Load-TestEnv
        Set-Item -Path env:PARITY_COMPOSE -Value "infra/docker-compose.test.yml"
        Set-Item -Path env:PARITY_DB_SERVICE -Value "db_test"
        & docker compose -f infra/docker-compose.test.yml down -v
        & docker compose -f infra/docker-compose.test.yml up -d
        Wait-Db -ComposeFile "infra/docker-compose.test.yml" -Service "db_test"
        Invoke-Check { & $Py db/per_run_db.py ensure-baseline } -What "ensure test baseline"
    }
    "test-env-down" { Load-TestEnv; & docker compose -f infra/docker-compose.test.yml down }
    default { Write-Error "Unknown target: $Target" }
}