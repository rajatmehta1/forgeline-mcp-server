"""
Blanket MCP Server — Entry point.

Usage:
    # Streamable HTTP (production, connect from Claude Code / Cursor)
    python -m blanket_mcp

    # Stdio (for local dev / piped connections)
    BLANKET_TRANSPORT=stdio python -m blanket_mcp
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from app.utils.config import get_settings
from app.mcp.server import mcp, _startup, _shutdown

logger = logging.getLogger("blanket.main")

def main() -> None:
    settings = get_settings()

    # Configure logging early
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )

    logger.info("Starting Blanket MCP Server v1.0.0")
    logger.info("Transport: %s | Host: %s | Port: %d", settings.transport, settings.host, settings.port)

    if settings.transport == "stdio":
        _run_stdio()
    else:
        _run_http(settings)


def _run_http(settings) -> None:
    """Run with streamable-http transport (production mode)."""
    import uvicorn
    from contextlib import asynccontextmanager
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    # Health endpoint at /health (outside MCP)
    async def health_endpoint(request: Request) -> JSONResponse:
        try:
            from app.utils.db import fetch_one
            row = await fetch_one("SELECT 1 AS ok")
            ok = row and row["ok"] == 1
        except Exception:
            ok = False
        status = 200 if ok else 503
        return JSONResponse({"status": "healthy" if ok else "unhealthy"}, status_code=status)

    # Get the MCP Starlette app (has its own lifespan for session manager)
    mcp_app = mcp.streamable_http_app()

    # Inject our startup/shutdown into the MCP app's existing lifespan
    _original_lifespan = mcp_app.router.lifespan_context

    @asynccontextmanager
    async def combined_lifespan(app):
        await _startup()
        async with _original_lifespan(app) as value:
            yield value
        await _shutdown()

    mcp_app.router.lifespan_context = combined_lifespan

    # Add health route and CORS to the MCP app directly
    mcp_app.routes.insert(0, Route("/health", health_endpoint, methods=["GET"]))

    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware
    mcp_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    uvicorn.run(
        mcp_app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        access_log=True,
        timeout_keep_alive=30,
    )


def _run_stdio() -> None:
    """Run with stdio transport (dev / local pipe mode)."""

    async def _run():
        await _startup()
        try:
            await mcp.run_stdio_async()
        finally:
            await _shutdown()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
