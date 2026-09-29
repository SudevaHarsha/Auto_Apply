"""Score orchestration (D50/D52/D53/D55/D56/D57/D58 + S7-v2 C3).

``score_job`` / ``score_profile`` map 1:1 to ``POST /jobs/{id}/score`` and
``POST /profiles/{id}/analyze``:

schema-version guard (D55) → rubric from ``rubric_cache`` or ``generate_rubric``
(D49/D58) → single evaluation via the copied evaluator (D48) → normalize (D50) →
one transaction: ``jobs.score`` + ``profiles.last_scored_at`` + ``rubric_cache``
upsert + one ``rubric_evidence`` row per facet (summary block on the first, D52/I7)
+ ``job_scored`` / ``profile_scored`` audit (D53).

Call budget (D71): rubric ≤ 2 (1 generation + at most 1 targeted gate repair) +
evaluation = 1 → hard cap 3; cache-hit re-score = 1. ``_CallLimiter`` makes the
cap a hard error, not a soft skip.

S7-v2 C3: ``Deductions`` is gone (no opaque penalties) — gaps surface as
``critical_gaps`` + ``eligibility.blocked_reasons``; each facet carries the
``evidence_strength``; a ``gate_miss`` (soft-coverage accept-after-repair,
Fix 4B) rides the summary metadata so rubric quality is observable.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import psycopg

from backend.app.core_engine.errors import (
    JobNotFoundError,
    NoCurrentProfileError,
    ScoringBudgetExceededError,
    SnapshotSchemaMismatchError,
)
from backend.app.core_engine.jd_schema import CURRENT_SCHEMA_VERSION
from backend.app.core_engine.resume_models import JSONResume
from backend.app.db.context import DbContext
from backend.app.db.repositories.core_engine_repository import CoreEngineRepository
from backend.app.db.repositories.observability_repository import ObservabilityRepository

from .evaluator import ResumeEvaluator
from .injection import sanitize_resume_text
from .resume_text import convert_json_resume_to_text
from .role import RoleDefinition
from .rubric_generator import generate_rubric, persist_envelope, rebuild_role_definition, rubric_sha256
from .scoring_models import build_evaluation_model


@dataclass
class RubricFacetScore:
    """Per-category scored result (label/score/evidence)."""

    key: str
    label: str
    max: int
    score: float
    evidence: str
    evidence_strength: int = 0


@dataclass
class ScoreResult:
    """Normalized result of a scoring op (D50) plus the routed-call provenance."""

    role: RoleDefinition
    total: float
    normalized: int
    per_facet: list[RubricFacetScore] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    bonus: float = 0.0
    bonus_breakdown: str = ""
    eligible: bool = True
    blocked_reasons: list[str] = field(default_factory=list)
    critical_gaps: list[str] = field(default_factory=list)
    gate_miss: dict[str, Any] | None = None
    evaluation: dict[str, Any] = field(default_factory=dict)
    model: str = ""
    latency_ms: int = 0
    rubric_sha256: str | None = None
    injection_flagged: bool = False


class _CallLimiter:
    """D54/D71: hard routed-call counter — rubric ≤ 2 + evaluation = 1, no retries."""

    def __init__(self, cap: int):
        self.cap = cap
        self.count = 0

    def consume(self) -> None:
        if self.count >= self.cap:
            raise ScoringBudgetExceededError(
                "scoring LLM call cap reached",
                details={"calls": self.count, "cap": self.cap},
            )
        self.count += 1


def _total_math(evaluation: Any, role: RoleDefinition) -> tuple[float, float]:
    """Total math copied from vendor ``score.py:66-90`` (D50, S7-v2 C3).

    total = Σ min(score, max) + bonus, capped at max_possible =
    Σ max + bonus_max. ``Deductions`` were removed in S7-v2 (no opaque
    penalties — gaps report via ``critical_gaps``/``eligibility``). Returns
    ``(total, max_final_score)``.
    """
    total = 0.0
    max_score = 0

    if getattr(evaluation, "scores", None):
        for data in evaluation.scores.model_dump().values():
            total += min(data["score"], data["max"])
            max_score += data["max"]

    if getattr(evaluation, "bonus_points", None):
        total += evaluation.bonus_points.total

    max_final_score = float(max_score + role.bonus_max)
    return min(total, max_final_score), max_final_score


def normalize(total: float, max_final_score: float) -> int:
    """D50: scale to a 0-100 integer (round-half-to-even)."""
    return round(100 * total / max_final_score)


async def _resolve_rubric(
    db: DbContext,
    *,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    payload: dict[str, Any],
    limiter: _CallLimiter,
    adapter_factory: Callable[[str], Any] | None,
) -> tuple[RoleDefinition, str, bool]:
    """Rubric from cache (hash-verified, D58) or fresh generation (+ upsert, D49)."""
    repo = CoreEngineRepository(db)
    cached = await repo.get_rubric(job_id, snapshot_id, CURRENT_SCHEMA_VERSION)

    if cached is not None:
        computed = rubric_sha256(cached["rubric"])
        if computed == cached["rubric_sha256"]:
            return rebuild_role_definition(cached["rubric"]), computed, True

    role_def, sha = await generate_rubric(
        db.conn,
        user_id=user_id,
        job_id=job_id,
        snapshot_id=snapshot_id,
        jd_payload=payload,
        adapter_factory=adapter_factory,
        before_call=limiter.consume,
    )
    await repo.put_rubric(
        job_id=job_id,
        snapshot_id=snapshot_id,
        schema_version=CURRENT_SCHEMA_VERSION,
        rubric=persist_envelope(role_def),
        rubric_sha256=sha,
    )
    return role_def, sha, False


def _summary_block(evaluation: Any, evaluation_dict: dict[str, Any]) -> dict[str, Any]:
    return {
        "strengths": list(evaluation.key_strengths),
        "improvements": list(evaluation.areas_for_improvement),
        "bonus": evaluation.bonus_points.total,
        "bonus_breakdown": evaluation.bonus_points.breakdown,
        "eligibility": {
            "eligible": bool(evaluation.eligibility.eligible),
            "blocked_reasons": list(evaluation.eligibility.blocked_reasons),
        },
        "critical_gaps": list(evaluation.critical_gaps),
        "evaluation": evaluation_dict,
    }


async def _score(
    conn: psycopg.AsyncConnection,
    *,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    profile_id: uuid.UUID | None,
    audit_action: str,
    rubric: RoleDefinition | None = None,
    adapter_factory: Callable[[str], Any] | None = None,
) -> ScoreResult:
    """Shared rubric-generate/score/evaluate-commit orchestration (D50-D58)."""
    async with DbContext(conn, user_id).transaction() as db:
        repo = CoreEngineRepository(db)
        observability = ObservabilityRepository(db)

        job = await repo.get_job_detail(user_id, job_id)
        if job is None:
            raise JobNotFoundError(f"job {job_id} not found")
        payload = job.get("payload")
        snapshot_id = job.get("current_snapshot_id")
        if snapshot_id is None or payload is None:
            raise SnapshotSchemaMismatchError(
                f"job {job_id} has no current snapshot to score against",
                details={"job_id": str(job_id)},
            )
        meta = (payload.get("_meta") or {}) if isinstance(payload, dict) else {}
        if meta.get("schema_version") != CURRENT_SCHEMA_VERSION:
            # D55: future/unknown snapshot shapes are never scored.
            raise SnapshotSchemaMismatchError(
                "snapshot schema_version is not the current shape",
                details={
                    "schema_version": meta.get("schema_version"),
                    "current": CURRENT_SCHEMA_VERSION,
                    "job_id": str(job_id),
                },
            )

        if profile_id is not None:
            profile = await repo.get_profile(user_id, profile_id)
        else:
            profile = await repo.get_current_profile(user_id)
        if profile is None:
            raise NoCurrentProfileError(
                f"no {'profile ' + str(profile_id) if profile_id else 'current'} profile for user {user_id}",
                details={
                    "profile_id": str(profile_id) if profile_id else None,
                    "user_id": str(user_id),
                },
            )

        resume_text = convert_json_resume_to_text(JSONResume.model_validate(profile["json_resume"]))
        cleaned_text, injection_flagged = sanitize_resume_text(resume_text)

        limiter = _CallLimiter(3)
        if rubric is not None:
            role_def = rubric
            sha: str | None = None
        else:
            role_def, sha, _cache_hit = await _resolve_rubric(
                db,
                user_id=user_id,
                job_id=job_id,
                snapshot_id=snapshot_id,
                payload=payload,
                limiter=limiter,
                adapter_factory=adapter_factory,
            )

        evaluator = ResumeEvaluator(role_def, build_evaluation_model(role_def))
        evaluation = await evaluator.evaluate_resume(
            conn=conn,
            user_id=user_id,
            resume_text=cleaned_text,
            job_id=job_id,
            adapter_factory=adapter_factory,
            before_call=limiter.consume,
        )

        total, max_final_score = _total_math(evaluation, role_def)
        normalized = normalize(total, max_final_score)

        full_scores: dict[str, dict[str, Any]] = (
            evaluation.scores.model_dump() if getattr(evaluation, "scores", None) else {}
        )
        per_facet = [
            RubricFacetScore(
                key=cat.key,
                label=cat.label,
                max=cat.max,
                score=full_scores.get(cat.key, {}).get("score", 0),
                evidence=full_scores.get(cat.key, {}).get("evidence", ""),
                evidence_strength=full_scores.get(cat.key, {}).get("evidence_strength", 0),
            )
            for cat in role_def.categories
        ]

        evaluation_dict = evaluation.model_dump()
        response = evaluator.last_response
        model = (response.model if response else "") or ""
        latency_ms = response.latency_ms if response else 0
        provider = (response.provider if response else "") or ""

        summary = _summary_block(evaluation, evaluation_dict)
        profile_id_resolved = profile["id"]

        for index, cat in enumerate(role_def.categories):
            value = full_scores.get(cat.key, {})
            metadata: dict[str, Any] = {
                "job_id": str(job_id),
                "profile_id": str(profile_id_resolved),
                "snapshot_id": str(snapshot_id),
                "category_key": cat.key,
                "label": cat.label,
                "max": cat.max,
                "score": value.get("score", 0),
                "evidence": value.get("evidence", ""),
                "evidence_strength": value.get("evidence_strength", 0),
                "model": model,
                "latency_ms": latency_ms,
            }
            if role_def.gate_miss is not None and index == 0:
                # Fix 4B: soft-coverage accept-after-repair is observable.
                metadata["gate_miss"] = role_def.gate_miss
            if sha is not None:
                metadata["rubric_sha256"] = sha
            if index == 0:
                # D52/I7: each facet is one rubric_evidence row; the summary
                # block rides on the first row so scoring information is never
                # stored inside the profile JSON blob.
                metadata.update(summary)
            await repo.insert_evidence(
                user_id,
                evidence_type="rubric_evidence",
                file_url=f"internal://scoring/{job_id}/{cat.key}",
                metadata=metadata,
            )

        await repo.set_job_score(user_id, job_id, normalized)
        await repo.set_profile_last_scored(user_id, profile_id_resolved)

        # D53: one audit per scoring op (job_scored / profile_scored).
        if audit_action == "job_scored":
            await observability.insert_audit(
                action="job_scored",
                resource_type="job",
                resource_id=job_id,
                details={"score": normalized, "provider": provider, "latency_ms": latency_ms},
            )
        else:
            await observability.insert_audit(
                action="profile_scored",
                resource_type="profile",
                resource_id=profile_id_resolved,
                details={"score": normalized, "provider": provider, "latency_ms": latency_ms},
            )

        return ScoreResult(
            role=role_def,
            total=total,
            normalized=normalized,
            per_facet=per_facet,
            strengths=list(evaluation.key_strengths),
            improvements=list(evaluation.areas_for_improvement),
            bonus=evaluation.bonus_points.total,
            bonus_breakdown=evaluation.bonus_points.breakdown,
            eligible=bool(evaluation.eligibility.eligible),
            blocked_reasons=list(evaluation.eligibility.blocked_reasons),
            critical_gaps=list(evaluation.critical_gaps),
            gate_miss=role_def.gate_miss,
            evaluation=evaluation_dict,
            model=model,
            latency_ms=latency_ms,
            rubric_sha256=sha,
            injection_flagged=injection_flagged,
        )


async def score_job(
    conn: psycopg.AsyncConnection,
    *,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    profile_id: uuid.UUID | None = None,
    rubric: RoleDefinition | None = None,
    adapter_factory: Callable[[str], Any] | None = None,
) -> ScoreResult:
    """Score a job's current snapshot against the current (or given) profile."""
    return await _score(
        conn,
        user_id=user_id,
        job_id=job_id,
        profile_id=profile_id,
        audit_action="job_scored",
        rubric=rubric,
        adapter_factory=adapter_factory,
    )


async def score_profile(
    conn: psycopg.AsyncConnection,
    *,
    user_id: uuid.UUID,
    profile_id: uuid.UUID,
    job_id: uuid.UUID,
    adapter_factory: Callable[[str], Any] | None = None,
) -> ScoreResult:
    """Score the given profile against the job's current snapshot (D53)."""
    return await _score(
        conn,
        user_id=user_id,
        job_id=job_id,
        profile_id=profile_id,
        audit_action="profile_scored",
        adapter_factory=adapter_factory,
    )
