#!/usr/bin/env python3
"""Protocol-level readiness check for a staged or installed Noesis release."""

import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED_TOOLS = {
    "propose_capture",
    "commit_capture",
    "start_review",
    "submit_attempt",
    "resolve_learning_issue",
    "update_learning_state",
    "recall_context",
    "get_progress",
}


async def check(command: str, args: list[str]) -> None:
    parameters = StdioServerParameters(command=command, args=args, env=dict(os.environ))
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            names = {tool.name for tool in (await session.list_tools()).tools}
            if names != EXPECTED_TOOLS:
                raise RuntimeError(f"unexpected MCP tools: {sorted(names)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(f"usage: {sys.argv[0]} COMMAND [ARG ...]")
    asyncio.run(check(sys.argv[1], sys.argv[2:]))
