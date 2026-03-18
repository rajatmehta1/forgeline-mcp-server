"""Blanket MCP Server — API key authentication."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from app.utils.db import fetch_one, execute
from app.model.models import AuthContext

logger = logging.getLogger("blanket.auth")


def hash_api_key(raw_key: str) -> str:
    """SHA-256 hash of the raw API key."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def extract_prefix(raw_key: str) -> str:
    """First 8 characters for display."""
    return raw_key[:8] if len(raw_key) >= 8 else raw_key


async def authenticate(api_key: str) -> AuthContext | None:
    """
    Validate an API key and return the resolved auth context.
    Returns None if the key is invalid or inactive.
    """
    key_hash = hash_api_key(api_key)

    row = await fetch_one(
        """
        SELECT
            ak.id       AS api_key_id,
            ak.org_id,
            o.name      AS org_name,
            o.plan      AS org_plan
        FROM api_keys ak
        JOIN organizations o ON o.id = ak.org_id
        WHERE ak.key_hash = $1
          AND ak.is_active = true
        """,
        key_hash,
    )

    if row is None:
        logger.warning("Authentication failed for key hash: %s…", key_hash[:12])
        return None

    # Update last_used_at (fire-and-forget, don't block the request)
    try:
        await execute(
            "UPDATE api_keys SET last_used_at = $1 WHERE id = $2",
            datetime.now(timezone.utc),
            row["api_key_id"],
        )
    except Exception:
        logger.debug("Failed to update last_used_at", exc_info=True)

    logger.info(
        "Authenticated: org=%s plan=%s", row["org_name"], row["org_plan"]
    )

    return AuthContext(
        org_id=row["org_id"],
        api_key_id=row["api_key_id"],
        org_name=row["org_name"],
        org_plan=row["org_plan"],
    )
