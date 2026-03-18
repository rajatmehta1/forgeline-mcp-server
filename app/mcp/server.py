"""
Blanket MCP Server — Production FastMCP server.

Exposes MCP tools for prompt-time policy injection.
Connect this to Claude Code or Cursor via streamable-http transport.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import FastMCP

from app.utils.config import get_settings
from app.utils.db import init_pool, close_pool, fetch_all
from app.utils.auth import authenticate
from app.model.models import (
    AuthContext,
    EventType,
    PolicyCategory,
    PolicyContext,
    PolicySeverity,
)
from app.mcp.policies import (
    build_injection_text,
    get_all_org_policies,
    get_policies_for_project,
    get_template_policies,
    match_policies,
)
from app.mcp.enforcement import log_enforcement, resolve_project_id

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger("blanket.server")

# ---------------------------------------------------------------------------
# FastMCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="blanket",
    instructions=(
        "Blanket is an AI code governance server. "
        "Call `get_policies` at the START of every code generation task "
        "to retrieve the coding policies that must be followed. "
        "Apply all returned policies to the code you generate."
    ),
)

# ---------------------------------------------------------------------------
# Lifespan — pool init/teardown
# ---------------------------------------------------------------------------

_original_run = None  # patched in __main__


async def _startup() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    try:
        await init_pool(settings)
    except Exception as e:
        logger.warning("Database connection failed (tools will still load): %s", e)
    logger.info("Blanket MCP server started (transport=%s)", settings.transport)


async def _shutdown() -> None:
    await close_pool()
    logger.info("Blanket MCP server stopped")


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

async def _resolve_auth(api_key: str | None) -> AuthContext:
    """Authenticate or raise."""
    settings = get_settings()

    if not settings.require_auth:
        # Dev mode: return a dummy context
        return AuthContext(
            org_id=UUID("00000000-0000-0000-0000-000000000001"),
            api_key_id=UUID("00000000-0000-0000-0000-000000000000"),
            org_name="dev-mode",
            org_plan="enterprise",
        )

    if not api_key:
        raise ValueError(
            "API key is required. Pass your Blanket API key as the `api_key` parameter."
        )

    auth = await authenticate(api_key)
    if auth is None:
        raise ValueError("Invalid or inactive API key.")
    return auth


# ---------------------------------------------------------------------------
# Approximate token counting (avoid heavy deps)
# ---------------------------------------------------------------------------

def _approx_tokens(text: str) -> int:
    """Rough token count: ~4 chars per token for English."""
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_policies(
    api_key: str | None = None,
    project: str | None = None,
    language: str | None = None,
    framework: str | None = None,
    categories: list[str] | None = None,
    severities: list[str] | None = None,
    tags: list[str] | None = None,
    source_tool: str | None = None,
) -> str:
    """
    Retrieve coding policies that MUST be followed when generating code.

    Call this tool at the START of every code generation task.
    The returned text contains governance rules your organization
    has defined — apply all of them to the code you produce.

    Args:
        api_key:     Your Blanket API key for authentication.
        project:     Project slug to scope policies (e.g. "backend-api").
                     If omitted, returns all org-level policies.
        language:    Programming language context (e.g. "python", "typescript").
                     Filters to language-specific policies.
        framework:   Framework context (e.g. "fastapi", "nextjs").
                     Filters to framework-specific policies.
        categories:  Filter by category: security, quality, compliance,
                     architecture, custom.
        severities:  Filter by severity: error, warning, info.
        tags:        Filter by policy tags (any match).
        source_tool: Identify calling tool: "claude_code", "cursor", "api".
    """
    t0 = time.monotonic()
    settings = get_settings()

    auth = await _resolve_auth(api_key)

    # Build the matching context
    ctx = PolicyContext(
        project_slug=project,
        language=language,
        framework=framework,
        categories=[PolicyCategory(c) for c in categories] if categories else None,
        severities=[PolicySeverity(s) for s in severities] if severities else None,
        tags=tags,
    )

    # Fetch policies
    if project:
        raw_policies = await get_policies_for_project(auth.org_id, project)
    else:
        raw_policies = await get_all_org_policies(auth.org_id)

    # Match and filter
    matched = match_policies(
        raw_policies, ctx, max_count=settings.max_policies_per_injection
    )

    # Build injection text
    injection_text = build_injection_text(matched)

    # Determine event type
    if matched:
        event_type = EventType.POLICY_INJECTION
    elif raw_policies:
        event_type = EventType.POLICY_SKIPPED
    else:
        event_type = EventType.NO_MATCH

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    # Resolve project_id for logging
    project_id = None
    if project:
        project_id = await resolve_project_id(auth.org_id, project)

    # Log enforcement (async, non-blocking on failure)
    await log_enforcement(
        org_id=auth.org_id,
        project_id=project_id,
        api_key_id=auth.api_key_id,
        event_type=event_type,
        source_tool=source_tool or "unknown",
        language=language,
        framework=framework,
        policies_applied=matched,
        prompt_token_count=None,
        enriched_token_count=_approx_tokens(injection_text) if injection_text else None,
        processing_ms=elapsed_ms,
    )

    if not injection_text:
        return (
            "No matching policies found for this context. "
            "Proceed with standard coding practices."
        )

    return injection_text


@mcp.tool()
async def list_projects(
    api_key: str | None = None,
) -> str:
    """
    List all active projects in the organization.
    Use this to discover available project slugs for get_policies.

    Args:
        api_key: Your Blanket API key for authentication.
    """
    auth = await _resolve_auth(api_key)

    rows = await fetch_all(
        """
        SELECT slug, name, language, framework,
               (SELECT COUNT(*) FROM project_policies pp
                WHERE pp.project_id = p.id AND pp.is_enabled = true) AS policy_count
        FROM projects p
        WHERE org_id = $1 AND is_active = true
        ORDER BY name
        """,
        auth.org_id,
    )

    if not rows:
        return "No active projects found. Create a project in the Blanket dashboard first."

    lines = ["Active projects:\n"]
    for r in rows:
        lang_fw = ""
        if r["language"]:
            lang_fw = f" ({r['language']}"
            if r["framework"]:
                lang_fw += f"/{r['framework']}"
            lang_fw += ")"
        lines.append(
            f"  • {r['slug']} — {r['name']}{lang_fw} [{r['policy_count']} policies]"
        )

    return "\n".join(lines)


@mcp.tool()
async def list_available_policies(
    api_key: str | None = None,
    project: str | None = None,
) -> str:
    """
    List all available policies (name, category, severity, description).
    Useful for understanding what governance rules exist.

    Args:
        api_key: Your Blanket API key for authentication.
        project: Optional project slug to show only policies assigned to that project.
    """
    auth = await _resolve_auth(api_key)

    if project:
        policies = await get_policies_for_project(auth.org_id, project)
        header = f"Policies enabled for project '{project}':"
    else:
        policies = await get_all_org_policies(auth.org_id)
        header = "All organization policies:"

    if not policies:
        return "No policies found."

    lines = [header, ""]
    for p in policies:
        severity_icon = {"error": "🔴", "warning": "🟡", "info": "🔵"}.get(
            p.severity.value, "⚪"
        )
        lines.append(f"  {severity_icon} [{p.category.value}] {p.name}")
        if p.description:
            lines.append(f"     {p.description}")
        if p.tags:
            lines.append(f"     Tags: {', '.join(p.tags)}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
async def get_policy_templates() -> str:
    """
    List the built-in Blanket policy templates.
    These are ready-made policies you can assign to your projects.
    No authentication required.
    """
    templates = await get_template_policies()

    if not templates:
        return "No templates available."

    lines = ["Blanket built-in policy templates:\n"]
    for t in templates:
        severity_icon = {"error": "🔴", "warning": "🟡", "info": "🔵"}.get(
            t.severity.value, "⚪"
        )
        lines.append(f"  {severity_icon} {t.name} ({t.slug})")
        lines.append(f"     Category: {t.category.value} | Severity: {t.severity.value}")
        if t.description:
            lines.append(f"     {t.description}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MCP Resources
# ---------------------------------------------------------------------------

@mcp.resource("blanket://health")
async def health_check() -> str:
    """Health check — verifies database connectivity."""
    try:
        from app.utils.db import fetch_one

        row = await fetch_one("SELECT 1 AS ok")
        return "healthy" if row and row["ok"] == 1 else "unhealthy: query failed"
    except Exception as e:
        return f"unhealthy: {e}"


@mcp.resource("blanket://info")
async def server_info() -> str:
    """Server metadata and version info."""
    return (
        "Blanket MCP Server v1.0.0\n"
        "AI Code Governance Platform\n"
        "https://blanket.com\n\n"
        "Tools:\n"
        "  • get_policies — Retrieve policies for code generation (primary tool)\n"
        "  • list_projects — List active projects\n"
        "  • list_available_policies — List all policies with details\n"
        "  • get_policy_templates — List built-in templates\n"
    )
