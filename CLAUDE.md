# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**forgeline-mcp-server** (codename "Blanket") is a Python MCP (Model Context Protocol) server that injects organization-defined coding policies into LLM prompts used by AI code editors (Claude Code, Cursor, etc.). The server reads policies from a database, evaluates them against the current coding context (language, framework, file patterns), and returns the matching policy text for prompt enrichment.

## Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server (local dev, no auth)
BLANKET_REQUIRE_AUTH=false python -m blanket_mcp

# Run the server (with auth)
python -m blanket_mcp

# Apply database schema to a local PostgreSQL
psql $BLANKET_DATABASE_URL -f db/schema.txt
```

No test infrastructure is configured yet. No linter or formatter is set up.

## Environment Variables

All prefixed with `BLANKET_`. Key settings in `.env`:

- `BLANKET_DATABASE_URL` — PostgreSQL connection string (required)
- `BLANKET_REQUIRE_AUTH` — set `false` for local dev (skips API key validation)
- `BLANKET_TRANSPORT` — `streamable-http` (default), `stdio`, or `sse`
- `BLANKET_PORT` — default `8000`
- `BLANKET_MAX_POLICIES` — cap on policies per injection (default 20)

## Architecture

The system has 5 planned components (only #1 and #2 live in this repo):

1. **FastMCP Server** (this repo) — reads policies from DB, logs enforcement events
2. **Policy Engine** (this repo) — evaluates policy rules against request context (language, framework, tags)
3. **PostgreSQL/Neon Database** — schema in `db/schema.txt`
4. **FastAPI Gateway** — CRUD REST API for all entities (not yet built)
5. **Web Dashboard** — UI for managing organizations, projects, and policies (not yet built)

### Code Layout

- `app/mcp/server.py` — FastMCP server instance, MCP tool definitions (`get_policies`, `list_projects`, `list_available_policies`, `get_policy_templates`), lifespan hooks, auth resolution
- `app/mcp/policies.py` — Policy fetching (by project or org), matching/filtering engine, injection text builder
- `app/mcp/enforcement.py` — Fire-and-forget enforcement logging to `enforcement_log` table
- `app/model/models.py` — Pydantic models and enums: `Policy`, `PolicyContext`, `AuthContext`, `PolicyCategory`, `PolicySeverity`, `EventType`
- `app/utils/config.py` — `Settings` dataclass loaded from env vars via `get_settings()` (cached)
- `app/utils/auth.py` — API key authentication: SHA-256 hash lookup against `api_keys` table
- `app/utils/db.py` — asyncpg connection pool with `fetch_all`, `fetch_one`, `execute` helpers

### Request Flow

1. MCP client calls `get_policies` with optional filters (project, language, framework, categories, severities, tags)
2. `_resolve_auth` validates the API key (or returns dev-mode context if auth disabled)
3. Policies fetched from DB via `get_policies_for_project` or `get_all_org_policies`
4. `match_policies` filters by language/framework/category/severity/tags, caps at `max_policies_per_injection`
5. `build_injection_text` assembles structured prompt text with severity markers
6. `log_enforcement` writes to `enforcement_log` (fire-and-forget, never fails the request)

### Known Import Inconsistency

Some modules (`policies.py`, `enforcement.py`, `db.py`) import from `blanket_mcp.*` while others (`server.py`, `auth.py`) import from `app.*`. This needs to be unified before the server can actually run.

## Database

- PostgreSQL (Neon-compatible) with extensions: `pgcrypto`, `citext`, `pg_vector`
- Full schema: `db/schema.txt` — ERD visualization: `docs/db/erd.html`
- Core tables: `organizations`, `users`, `api_keys`, `projects`, `policies`, `project_policies`, `enforcement_log`
- Multi-tenant via `org_id` on all tables; UUID primary keys throughout
- Policies have category (`security`/`quality`/`compliance`/`architecture`/`custom`), severity (`error`/`warning`/`info`), and language/framework targeting arrays
- 5 seed policy templates are inserted by the schema
- `enforcement_log` tracks every MCP request with event type, source tool, applied policy IDs, and token counts (never stores full prompts)
- DB access uses raw asyncpg (not SQLAlchemy ORM) with parameterized queries (`$1`, `$2`, etc.)

## Current State

Pre-alpha. The database schema is complete and the MCP server code is written but has import path inconsistencies that prevent it from running. `main.py` at root is a PyCharm placeholder. No tests, no CI, no Docker setup yet.
