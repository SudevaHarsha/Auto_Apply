"""Repository import map (S2).

This module is the canonical table -> owner mapping (see
``plans/autoapply-implementation.md`` §2 Ownership). The T2 ownership-guard test reads
``OWNERSHIP`` and scans each repository source to assert no component touches another's
table. Keep the mapping and the repository classes in lockstep.
"""

from __future__ import annotations

from backend.app.db.repositories.auth_repository import AuthRepository
from backend.app.db.repositories.checkpointing_repository import CheckpointingRepository
from backend.app.db.repositories.chrome_extension_repository import ChromeExtensionRepository
from backend.app.db.repositories.core_engine_repository import CoreEngineRepository
from backend.app.db.repositories.discord_repository import DiscordRepository
from backend.app.db.repositories.discovery_repository import DiscoveryRepository
from backend.app.db.repositories.llm_router_repository import LlmRouterRepository
from backend.app.db.repositories.observability_repository import ObservabilityRepository

__all__ = [
    "AuthRepository",
    "CheckpointingRepository",
    "ChromeExtensionRepository",
    "CoreEngineRepository",
    "DiscordRepository",
    "DiscoveryRepository",
    "LlmRouterRepository",
    "ObservabilityRepository",
]

# table -> owning repository class name (canonical import map, T2 ownership guard).
OWNERSHIP: dict[str, str] = {
    "users": "AuthRepository",
    "api_keys": "AuthRepository",
    "settings": "AuthRepository",
    "user_profiles": "AuthRepository",
    "profiles": "CoreEngineRepository",
    "jobs": "CoreEngineRepository",
    "applications": "CoreEngineRepository",
    "pipeline_runs": "CoreEngineRepository",
    "job_snapshots": "CoreEngineRepository",
    "llm_providers": "LlmRouterRepository",
    "provider_usage": "LlmRouterRepository",
    "rate_limit_state": "LlmRouterRepository",
    "telegram_connections": "DiscoveryRepository",
    "telegram_messages": "DiscoveryRepository",
    "discord_connections": "DiscordRepository",
    "discord_messages": "DiscordRepository",
    "evidence": "ChromeExtensionRepository",
    "audit_logs": "ObservabilityRepository",
    "error_logs": "ObservabilityRepository",
    "checkpoints": "CheckpointingRepository",
}

# Snapshots are RLS-exempt (I1) and shared; core_engine is the writer (owns them here),
# but they are intentionally readable by every component. That shared-read is not a
# violation of the ownership guard: global reads are exempted by design (see brief S2 §4).
SNAPSHOT_SHARED_READ = {"job_snapshots"}
