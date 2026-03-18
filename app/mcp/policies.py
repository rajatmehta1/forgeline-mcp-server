"""Blanket MCP Server — Policy matching engine."""

from __future__ import annotations

import logging
from uuid import UUID

from app.utils.db import fetch_all
from app.model.models import Policy, PolicyCategory, PolicyContext, PolicySeverity

logger = logging.getLogger("blanket.policies")


async def get_policies_for_project(
    org_id: UUID,
    project_slug: str,
) -> list[Policy]:
    """
    Fetch all active, enabled policies for a specific project.
    Joins through project_policies to get only what's toggled on.
    """
    rows = await fetch_all(
        """
        SELECT
            pol.id, pol.name, pol.slug, pol.description,
            pol.category, pol.severity, pol.prompt_injection_text,
            pol.tags, pol.applies_to_languages, pol.applies_to_frameworks,
            pol.is_template
        FROM policies pol
        JOIN project_policies pp ON pp.policy_id = pol.id
        JOIN projects prj ON prj.id = pp.project_id
        WHERE prj.org_id = $1
          AND prj.slug = $2
          AND prj.is_active = true
          AND pp.is_enabled = true
          AND pol.is_active = true
        ORDER BY
            CASE pol.severity
                WHEN 'error'   THEN 0
                WHEN 'warning' THEN 1
                WHEN 'info'    THEN 2
            END,
            pol.name
        """,
        org_id,
        project_slug,
    )
    return [_row_to_policy(r) for r in rows]


async def get_all_org_policies(org_id: UUID) -> list[Policy]:
    """Fetch all active policies for an org (no project filter)."""
    rows = await fetch_all(
        """
        SELECT
            id, name, slug, description, category, severity,
            prompt_injection_text, tags,
            applies_to_languages, applies_to_frameworks, is_template
        FROM policies
        WHERE org_id = $1 AND is_active = true
        ORDER BY category, severity, name
        """,
        org_id,
    )
    return [_row_to_policy(r) for r in rows]


async def get_template_policies() -> list[Policy]:
    """Fetch all Blanket-provided template policies."""
    rows = await fetch_all(
        """
        SELECT
            id, name, slug, description, category, severity,
            prompt_injection_text, tags,
            applies_to_languages, applies_to_frameworks, is_template
        FROM policies
        WHERE is_template = true AND is_active = true
        ORDER BY category, severity, name
        """,
    )
    return [_row_to_policy(r) for r in rows]


def match_policies(
    policies: list[Policy],
    ctx: PolicyContext,
    max_count: int = 20,
) -> list[Policy]:
    """
    Filter policies based on language, framework, category, severity, and tags.
    Returns the best-matching subset, capped at max_count.
    """
    matched: list[Policy] = []

    for pol in policies:
        # Language filter: if the policy specifies languages, the context must match
        if pol.applies_to_languages and ctx.language:
            if ctx.language.lower() not in [
                lang.lower() for lang in pol.applies_to_languages
            ]:
                continue
        elif pol.applies_to_languages and not ctx.language:
            # Policy requires a specific language but context has none — skip
            continue

        # Framework filter: same logic
        if pol.applies_to_frameworks and ctx.framework:
            if ctx.framework.lower() not in [
                fw.lower() for fw in pol.applies_to_frameworks
            ]:
                continue
        elif pol.applies_to_frameworks and not ctx.framework:
            continue

        # Category filter (if caller requested specific categories)
        if ctx.categories and pol.category not in ctx.categories:
            continue

        # Severity filter
        if ctx.severities and pol.severity not in ctx.severities:
            continue

        # Tag filter (any overlap = match)
        if ctx.tags:
            policy_tags_lower = {t.lower() for t in pol.tags}
            ctx_tags_lower = {t.lower() for t in ctx.tags}
            if not policy_tags_lower & ctx_tags_lower:
                continue

        matched.append(pol)

        if len(matched) >= max_count:
            break

    logger.info(
        "Policy match: %d/%d policies matched (lang=%s, fw=%s)",
        len(matched),
        len(policies),
        ctx.language,
        ctx.framework,
    )
    return matched


def build_injection_text(policies: list[Policy]) -> str:
    """
    Assemble the final prompt injection text from matched policies.
    Structured with clear delimiters so the LLM can parse them.
    """
    if not policies:
        return ""

    sections: list[str] = []
    sections.append("=" * 60)
    sections.append("BLANKET CODE GOVERNANCE POLICIES")
    sections.append(
        "The following policies MUST be followed when generating code."
    )
    sections.append("=" * 60)

    for i, pol in enumerate(policies, 1):
        severity_marker = {
            PolicySeverity.ERROR: "🔴 MUST",
            PolicySeverity.WARNING: "🟡 SHOULD",
            PolicySeverity.INFO: "🔵 RECOMMENDED",
        }.get(pol.severity, "⚪")

        sections.append("")
        sections.append(f"--- Policy {i}/{len(policies)}: {pol.name} [{severity_marker}] ---")
        if pol.description:
            sections.append(pol.description)
        sections.append("")
        sections.append(pol.prompt_injection_text)

    sections.append("")
    sections.append("=" * 60)
    sections.append("END OF BLANKET POLICIES")
    sections.append("=" * 60)

    return "\n".join(sections)


def _row_to_policy(row) -> Policy:
    """Convert a database row to a Policy model."""
    return Policy(
        id=row["id"],
        name=row["name"],
        slug=row["slug"],
        description=row["description"],
        category=PolicyCategory(row["category"]),
        severity=PolicySeverity(row["severity"]),
        prompt_injection_text=row["prompt_injection_text"],
        tags=list(row["tags"]) if row["tags"] else [],
        applies_to_languages=list(row["applies_to_languages"])
        if row["applies_to_languages"]
        else [],
        applies_to_frameworks=list(row["applies_to_frameworks"])
        if row["applies_to_frameworks"]
        else [],
        is_template=row["is_template"],
    )
