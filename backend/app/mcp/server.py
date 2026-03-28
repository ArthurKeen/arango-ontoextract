"""AOE Development-time MCP server.

Starts via stdio transport so Cursor can connect and give Claude
live access to the ArangoDB instance for schema introspection,
AQL queries, and document sampling.

Usage:
    python -m app.mcp.server
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from app.mcp.tools.introspection import register_introspection_tools

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

mcp = FastMCP(
    "aoe-dev",
    instructions=(
        "AOE development-time MCP server. "
        "Provides tools to introspect the ArangoDB database: "
        "list collections, run read-only AQL queries, and sample documents."
    ),
)

register_introspection_tools(mcp)


if __name__ == "__main__":
    log.info("Starting AOE dev-time MCP server (stdio)")
    mcp.run(transport="stdio")
