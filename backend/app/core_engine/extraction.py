"""Extraction orchestration (S5, D22 — copy-and-replace).

Vendor ``pdf.py`` control flow is reimplemented here: the section loop,
single-retry-on-None, abort semantics, and ``Basics``/``JSONResume`` assembly
are mirrored verbatim from ``vendor/hiring_agent/pdf.py`` (lines 45-327),
but every LLM call goes through ``route_llm_request`` (S4 router) instead of
the vendor's ``OpenAICompatibleProvider``. All helpers are local copies
(``json_utils``, ``section_transforms``, ``template_manager``,
``pymupdf_rag_impl``). The vendor tree is untouched (I9).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import uuid
from collections.abc import Callable
from typing import Any

import psycopg
import pymupdf

from backend.app.core_engine.errors import ExtractionFailedError
from backend.app.core_engine.json_utils import extract_json_from_response
from backend.app.core_engine.pymupdf_rag_impl import to_markdown
from backend.app.core_engine.resume_models import (
    AwardsSection,
    Basics,
    BasicsSection,
    EducationSection,
    JSONResume,
    ProjectsSection,
    SkillsSection,
    WorkSection,
)
from backend.app.core_engine.section_transforms import transform_parsed_data
from backend.app.core_engine.template_manager import TemplateManager
from backend.app.llm.adapters.base import ProviderAdapter
from backend.app.llm.errors import ProvidersExhaustedError
from backend.app.llm.router import route_llm_request

logger = logging.getLogger(__name__)

template_manager = TemplateManager()

SECTION_ORDER = ["basics", "work", "education", "skills", "projects", "awards"]


def _pdf_to_markdown(pdf_path: str) -> str | None:
    """Vendor ``PDFHandler.extract_text_from_pdf`` (pdf.py:45-62), copied verbatim.

    One deliberate deviation from the vendor call (``to_markdown(doc,
    pages=pages)``): ``ignore_alpha=True`` and ``ignore_graphics=True`` are
    passed so resumes that mark highlight text as invisible (``alpha=0``) or
    overlay it with vector graphics are not silently stripped from the
    markdown (decided for the Amazon/MERN live-test PDFs, see S5 report).
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    with pymupdf.open(pdf_path) as doc:
        pages = range(doc.page_count)
        resume_text = to_markdown(
            doc,
            pages=pages,
            ignore_alpha=True,
            ignore_graphics=True,
        )
        logger.debug(f"Extracted text from PDF: {len(resume_text) if resume_text else 0} characters")
        return resume_text


def _parse_section_json(response_text: str) -> dict[str, Any] | None:
    """Vendor JSON-parse block (pdf.py:109-114), copied verbatim."""
    response_text = extract_json_from_response(response_text)
    json_start = response_text.find("{")
    json_end = response_text.rfind("}")
    if json_start != -1 and json_end != -1:
        response_text = response_text[json_start : json_end + 1]
    return json.loads(response_text)


async def _call_llm_for_section(
    conn: psycopg.AsyncConnection,
    user_id: uuid.UUID,
    section_name: str,
    text_content: str,
    prompt: str,
    return_model: Any = None,
    *,
    adapter_factory: Callable[[str], ProviderAdapter] | None = None,
) -> dict | None:
    """Vendor ``PDFHandler._call_llm_for_section`` (pdf.py:64-132), transport swapped.

    ``self.provider.chat(...)`` is replaced by ``route_llm_request`` (D22):
    provider chain resolution, failover, circuit breaker, and ``provider_usage``
    auditing all live in the S4 router. Parsing + transform are copied verbatim.
    """
    logger.debug(f"🔄 Extracting {section_name} section...")

    section_system_message = template_manager.render_template("system_message", section_name_param=section_name)
    if not section_system_message:
        logger.error(f"❌ Failed to render system message template for {section_name}")
        return None

    kwargs = {}
    if return_model:
        kwargs["output_schema"] = return_model.model_json_schema()

    try:
        resp = await route_llm_request(
            conn,
            user_id=user_id,
            prompt=prompt,
            system_message=section_system_message,
            json_mode=True,
            adapter_factory=adapter_factory,
            **kwargs,
        )
    except ProvidersExhaustedError as e:
        raise ExtractionFailedError(str(e)) from e

    response_text = resp.content or ""

    try:
        parsed_data = _parse_section_json(response_text)
        logger.debug(f"✅ Successfully extracted {section_name} section")
        if parsed_data is None:
            logger.error(f"❌ Section parse returned null for {section_name}: {response_text}")
            return None
        return transform_parsed_data(parsed_data)
    except json.JSONDecodeError as e:
        logger.error(f"❌ Error parsing JSON for {section_name} section: {e}")
        logger.error(f"Raw response: {response_text}")
        return None
    except Exception as e:
        logger.error(f"❌ Error calling LLM for {section_name} section: {e}")
        return None


async def extract_basics_section(
    conn: psycopg.AsyncConnection, user_id: uuid.UUID, resume_text: str, *, adapter_factory=None
) -> dict | None:
    """Vendor ``PDFHandler.extract_basics_section`` (pdf.py:134-141), async."""
    prompt = template_manager.render_template("basics", text_content=resume_text)
    if not prompt:
        logger.error("❌ Failed to render basics template")
        return None
    return await _call_llm_for_section(
        conn, user_id, "basics", resume_text, prompt, BasicsSection, adapter_factory=adapter_factory
    )


async def extract_work_section(
    conn: psycopg.AsyncConnection, user_id: uuid.UUID, resume_text: str, *, adapter_factory=None
) -> dict | None:
    """Vendor ``PDFHandler.extract_work_section`` (pdf.py:143-148), async."""
    prompt = template_manager.render_template("work", text_content=resume_text)
    if not prompt:
        logger.error("❌ Failed to render work template")
        return None
    return await _call_llm_for_section(
        conn, user_id, "work", resume_text, prompt, WorkSection, adapter_factory=adapter_factory
    )


async def extract_education_section(
    conn: psycopg.AsyncConnection, user_id: uuid.UUID, resume_text: str, *, adapter_factory=None
) -> dict | None:
    """Vendor ``PDFHandler.extract_education_section`` (pdf.py:150-159), async."""
    prompt = template_manager.render_template("education", text_content=resume_text)
    if not prompt:
        logger.error("❌ Failed to render education template")
        return None
    return await _call_llm_for_section(
        conn, user_id, "education", resume_text, prompt, EducationSection, adapter_factory=adapter_factory
    )


async def extract_skills_section(
    conn: psycopg.AsyncConnection, user_id: uuid.UUID, resume_text: str, *, adapter_factory=None
) -> dict | None:
    """Vendor ``PDFHandler.extract_skills_section`` (pdf.py:161-168), async."""
    prompt = template_manager.render_template("skills", text_content=resume_text)
    if not prompt:
        logger.error("❌ Failed to render skills template")
        return None
    return await _call_llm_for_section(
        conn, user_id, "skills", resume_text, prompt, SkillsSection, adapter_factory=adapter_factory
    )


async def extract_projects_section(
    conn: psycopg.AsyncConnection, user_id: uuid.UUID, resume_text: str, *, adapter_factory=None
) -> dict | None:
    """Vendor ``PDFHandler.extract_projects_section`` (pdf.py:170-179), async."""
    prompt = template_manager.render_template("projects", text_content=resume_text)
    if not prompt:
        logger.error("❌ Failed to render projects template")
        return None
    return await _call_llm_for_section(
        conn, user_id, "projects", resume_text, prompt, ProjectsSection, adapter_factory=adapter_factory
    )


async def extract_awards_section(
    conn: psycopg.AsyncConnection, user_id: uuid.UUID, resume_text: str, *, adapter_factory=None
) -> dict | None:
    """Vendor ``PDFHandler.extract_awards_section`` (pdf.py:181-188), async."""
    prompt = template_manager.render_template("awards", text_content=resume_text)
    if not prompt:
        logger.error("❌ Failed to render awards template")
        return None
    return await _call_llm_for_section(
        conn, user_id, "awards", resume_text, prompt, AwardsSection, adapter_factory=adapter_factory
    )


_SECTION_HANDLERS = {
    "basics": extract_basics_section,
    "work": extract_work_section,
    "education": extract_education_section,
    "skills": extract_skills_section,
    "projects": extract_projects_section,
    "awards": extract_awards_section,
}


async def _extract_section_data(
    conn: psycopg.AsyncConnection,
    user_id: uuid.UUID,
    text_content: str,
    section_name: str,
    return_model: Any = None,
    *,
    adapter_factory: Callable[[str], ProviderAdapter] | None = None,
) -> dict | None:
    """Vendor ``PDFHandler._extract_section_data`` (pdf.py:217-234), async dispatch."""
    handler = _SECTION_HANDLERS.get(section_name)
    if handler is None:
        logger.error(f"❌ Invalid section name: {section_name}")
        logger.error(f"Valid sections: {list(_SECTION_HANDLERS.keys())}")
        return None
    return await handler(conn, user_id, text_content, adapter_factory=adapter_factory)


async def _extract_all_sections_async(
    conn: psycopg.AsyncConnection,
    user_id: uuid.UUID,
    text_content: str,
    *,
    adapter_factory: Callable[[str], ProviderAdapter] | None = None,
) -> JSONResume | None:
    """Vendor ``PDFHandler._extract_all_sections_separately`` (pdf.py:264-327), async.

    Same 6-section loop, same 13-key skeleton, same one-retry-on-None, same
    abort-on-persistent-None, same ``Basics`` cast + ``JSONResume`` assembly.
    """
    complete_resume: dict[str, Any] = {
        "basics": None,
        "work": None,
        "volunteer": None,
        "education": None,
        "awards": None,
        "certificates": None,
        "publications": None,
        "skills": None,
        "languages": None,
        "interests": None,
        "references": None,
        "projects": None,
        "meta": None,
    }

    for section_name in SECTION_ORDER:
        section_data = await _extract_section_data(
            conn, user_id, text_content, section_name, adapter_factory=adapter_factory
        )
        if section_data is None:
            logger.warning(f"🔁 Retrying {section_name} section extraction")
            section_data = await _extract_section_data(
                conn, user_id, text_content, section_name, adapter_factory=adapter_factory
            )

        if section_data:
            complete_resume.update(section_data)
            logger.debug(f"✅ Successfully extracted {section_name} section")
        elif section_data is not None:
            # Valid response with no content for this section (e.g. no awards)
            logger.warning(f"⚠️ {section_name} section empty; continuing")
        else:
            logger.error(
                f"⚠️ Failed to extract {section_name} section. "
                "Aborting extraction to prevent partial/invalid resume data."
            )
            return None

    try:
        if complete_resume.get("basics") and isinstance(complete_resume["basics"], dict):
            try:
                complete_resume["basics"] = Basics(**complete_resume["basics"])
            except Exception as e:
                logger.error(f"❌ Error creating Basics object: {e}")
                complete_resume["basics"] = None

        return JSONResume(**complete_resume)
    except Exception as e:
        logger.error(f"❌ Error creating JSONResume object: {e}")
        return None


def sha256_hex(payload: bytes) -> str:
    """Stable hex sha256 of raw PDF bytes (idempotency fingerprint, D23)."""
    return hashlib.sha256(payload).hexdigest()


async def extract_profile(
    conn: psycopg.AsyncConnection,
    *,
    user_id: uuid.UUID,
    pdf_path: str,
    adapter_factory: Callable[[str], ProviderAdapter] | None = None,
) -> JSONResume:
    """Canonical core-engine entry (D21/D22): PDF file → validated JSONResume.

    Step 1 — PDF→Markdown via the copied ``pymupdf_rag_impl`` helper, run in a
    worker thread (blocking pymupdf work off the event loop).
    Step 2 — 6 sequential section calls, one connection, one event loop.
    Step 3 — ``transform`` + Pydantic assembly into :class:`JSONResume`.

    ``adapter_factory`` is the test-only injection seam (D26): the S4
    ``mock_provider`` is threaded straight into ``route_llm_request`` so the
    offline T5 suite needs no real provider keys.
    """
    if not os.path.exists(pdf_path):
        raise ExtractionFailedError(f"pdf not found: {pdf_path}")

    text_content = await asyncio.to_thread(_pdf_to_markdown, pdf_path)
    if not text_content:
        raise ExtractionFailedError("empty text extracted from pdf")

    resume = await _extract_all_sections_async(conn, user_id, text_content, adapter_factory=adapter_factory)
    if resume is None:
        raise ExtractionFailedError("section extraction failed")
    return resume
