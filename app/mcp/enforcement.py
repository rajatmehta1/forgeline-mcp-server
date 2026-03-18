"""Blanket MCP Server — Enforcement logging."""

from __future__ import annotations

import logging
from uuid import UUID

from app.utils.db import execute
from app.model.models import EventType, Policy

logger = logging.getLogger("blanket.enforcement")


async def log_enforcement(
    org_id: UUID,
    project_id: UUID | None,
    api_key_id: UUID | None,
    event_type: EventType,
    source_tool: str | None,
    language: str | None,
    framework: str | None,
    policies_applied: list[Policy],
    prompt_token_count: int | None,
    enriched_token_count: int | None,
    processing_ms: int,
) -> None:
    """
    Insert an enforcement log entry. Fire-and-forget — failures
    are logged but never propagate to the caller.
    """
    try:
        policy_ids = [str(p.id) for p in policies_applied]

        await execute(
            """
            INSERT INTO enforcement_log (
                org_id, project_id, api_key_id,
                event_type, source_tool, language, framework,
                policies_applied, policies_count,
                prompt_token_count, enriched_token_count,
                processing_ms
            ) VALUES (
                $1, $2, $3,
                $4, $5, $6, $7,
                $8::uuid[], $9,
                $10, $11,
                $12
            )
            """,
            org_id,
            project_id,
            api_key_id,
            event_type.value,
            source_tool,
            language,
            framework,
            policy_ids,
            len(policies_applied),
            prompt_token_count,
            enriched_token_count,
            processing_ms,
        )
        logger.info(
            "Enforcement logged: type=%s policies=%d ms=%d",
            event_type.value,
            len(policies_applied),
            processing_ms,
        )
    except Exception:
        logger.error("Failed to log enforcement event", exc_info=True)


async def resolve_project_id(org_id: UUID, project_slug: str) -> UUID | None:
    """Look up a project ID from org + slug."""
    from app.utils.db import fetch_one

    row = await fetch_one(
        "SELECT id FROM projects WHERE org_id = $1 AND slug = $2 AND is_active = true",
        org_id,
        project_slug,
    )
    return row["id"] if row else None
