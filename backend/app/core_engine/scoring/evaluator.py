"""Resume evaluator (copied from ``vendor/hiring_agent/evaluator.py:18-86``, D47/D48).

Evaluation logic and strict JSON validation copied; the sync ``provider.chat``
transport is replaced by ``await route_llm_request(...)`` (D48) so the router owns
provider failover, breaker, usage and audit. Evaluation is single-shot (D54): a
refused/malformed response raises ``ScoringFailedError`` and is never re-called;
only the rubric-cache decision ever affects call count.

S8 — evidence pointers: the resume is rendered into the prompt as an indexed
line listing (``r[i]``), and per-category ``evidence`` is written as 1-3
``r[i]`` pointers instead of retyped resume text. The short ``r[i]`` label
(S10) cuts the billed input tokens of the index prefixes vs ``resume[i]``
while resolution is identical. Pointers are resolved back to the literal
resume lines here, server-side, before the strict model validation; an
out-of-range pointer fails the evaluation like any malformed output (never
leaks a raw pointer into persisted evidence).
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from typing import Any

import psycopg
from pydantic import BaseModel

from backend.app.core_engine.errors import ScoringFailedError
from backend.app.core_engine.json_utils import extract_json_from_response
from backend.app.core_engine.template_manager import TemplateManager
from backend.app.llm.limits import count_prompt_tokens, estimate_eval_cap
from backend.app.llm.router import LLMResponse, route_llm_request

from .role import RoleDefinition

_EVIDENCE_POINTER_RE = re.compile(r"^r(\d+)$")

# S9: low, deterministic sampling so the same rubric+resume scores consistently
# (providers otherwise default to ~1.0 and groq flipped a bonus 3 vs 10 across
# identical inputs). Exported so the eval corpus test asserts the same value.
EVAL_TEMPERATURE = 0.3


def _build_indexed_resume(resume_text: str) -> tuple[list[str], str]:
    """Return ``(lines, listing)`` where each non-empty resume line gets a
    short ``r[i]`` index for evidence pointers (S8/S10). Resolution reuses the
    exact same ``lines`` list, so indexes are never ambiguous with blank lines.
    """
    lines = [line for line in resume_text.split("\n") if line.strip()]
    listing = "\n".join(f"r{i} {line}" for i, line in enumerate(lines))
    return lines, listing


def _resolve_evidence_pointers(evidence: str, resume_lines: list[str]) -> str:
    """Resolve ``r[i]`` tokens in an evidence string to the literal resume
    line; every other token is kept verbatim. An out-of-range ``r[i]``
    raises ``ValueError`` so the caller can fail the evaluation loudly.
    """
    out: list[str] = []
    for token in evidence.split():
        match = _EVIDENCE_POINTER_RE.match(token)
        if match:
            index = int(match.group(1))
            if index >= len(resume_lines):
                raise ValueError(token)
            out.append(resume_lines[index])
        else:
            out.append(token)
    return " ".join(out)


class ResumeEvaluator:
    """Evaluates a resume against a generated rubric (D47/D48)."""

    def __init__(self, role: RoleDefinition, evaluation_model: type[BaseModel]):
        """Initialize the resume evaluator with a role definition and model.

        Args:
            role: The generated role definition (RoleDefinition).
            evaluation_model: Strict ``EvaluationData`` model class.
        """
        if role is None:
            raise ValueError("role cannot be empty")

        self.role = role
        self.evaluation_model = evaluation_model
        self.template_manager = TemplateManager()
        self._last_resume_text: str | None = None
        self._resume_lines: list[str] | None = None
        self.last_response: LLMResponse | None = None

    def _load_evaluation_prompt(self, resume_text: str) -> str:
        """Render the criteria template with the indexed resume listing (S8)."""
        resume_lines, listing = _build_indexed_resume(resume_text)
        self._resume_lines = resume_lines
        return self.template_manager.render_string(self.role.criteria, text_content=listing)

    async def evaluate_resume(
        self,
        *,
        conn: psycopg.AsyncConnection,
        user_id: uuid.UUID,
        resume_text: str,
        job_id: uuid.UUID,
        adapter_factory: Callable[[str], Any] | None = None,
        before_call: Callable[[], None] | None = None,
    ) -> Any:
        """Score the resume text against the rubric: exactly 1 routed call (D54).

        ``before_call`` is the scorer's call-counter hook. Returns the strict
        ``EvaluationData`` instance; on provider failure or malformed output
        raises ``ScoringFailedError``.

        Note: the generated criteria template is *re-rendered* with the resume
        text here (vendor ``render_string`` contract). ``sanitize_resume_text``
        (D57) has already stripped the prompt-injection denylist by this point.
        """
        self._last_resume_text = resume_text

        if before_call is not None:
            before_call()

        try:
            full_prompt = self._load_evaluation_prompt(resume_text)
            system_message = self.template_manager.render_string(self.role.system_message)
            max_output_tokens = estimate_eval_cap(resume_tokens=count_prompt_tokens(resume_text))
            response = await route_llm_request(
                conn,
                user_id=user_id,
                prompt=full_prompt,
                system_message=system_message,
                json_mode=True,
                output_schema=self.evaluation_model.model_json_schema(),
                max_output_tokens=max_output_tokens,
                temperature=EVAL_TEMPERATURE,
                job_id=job_id,
                step="scoring",
                adapter_factory=adapter_factory,
            )
        except Exception as exc:
            raise ScoringFailedError(
                "evaluation exhausted every configured provider",
                details={"cause": type(exc).__name__},
            ) from exc

        self.last_response = response

        if response.truncated:
            raise ScoringFailedError(
                "evaluation output hit its max_output_tokens ceiling",
                details={
                    "cause": "output_truncated",
                    "max_output_tokens": max_output_tokens,
                    "completion_tokens": response.completion_tokens,
                    "content_prefix": (response.content or "")[:200],
                },
            )

        try:
            response_text = extract_json_from_response(response.content or "")
            evaluation_dict = json.loads(response_text)
        except Exception as exc:
            raise ScoringFailedError(
                "evaluation returned a refused or malformed response",
                details={"cause": type(exc).__name__, "content_prefix": (response.content or "")[:200]},
            ) from exc

        resume_lines = self._resume_lines or []
        for key, score_entry in (evaluation_dict.get("scores") or {}).items():
            if not isinstance(score_entry, dict) or not isinstance(score_entry.get("evidence"), str):
                continue
            try:
                score_entry["evidence"] = _resolve_evidence_pointers(score_entry["evidence"], resume_lines)
            except ValueError as exc:
                raise ScoringFailedError(
                    "evaluation returned an unresolvable evidence pointer",
                    details={"category": key, "pointer": str(exc)},
                ) from exc

        try:
            evaluation_data = self.evaluation_model(**evaluation_dict)
        except Exception as exc:
            raise ScoringFailedError(
                "evaluation returned a refused or malformed response",
                details={"cause": type(exc).__name__, "content_prefix": (response.content or "")[:200]},
            ) from exc

        return evaluation_data
