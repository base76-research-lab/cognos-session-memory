#!/usr/bin/env python3
"""
CognOS Session Memory MCP Server

Exposes trust scoring and session trace storage as MCP tools.
Self-contained — no running FastAPI instance required.

Core formula: C = p · (1 − Ue − Ua)
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mcp.server import Server
from mcp.types import Tool, TextContent, CallToolResult

server = Server("cognos-session-memory")

TOOLS = [
    Tool(
        name="compute_trust_score",
        description=(
            "Compute CognOS epistemic trust score using C = p · (1 − Ue − Ua). "
            "Returns confidence, risk, and action decision (PASS / REFINE / ESCALATE)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "p":  {"type": "number", "description": "Prediction confidence [0, 1]"},
                "ue": {"type": "number", "description": "Epistemic uncertainty [0, 1]"},
                "ua": {"type": "number", "description": "Aleatoric uncertainty [0, 1]"},
            },
            "required": ["p", "ue", "ua"],
        },
    ),
    Tool(
        name="get_recent_traces",
        description="Retrieve the N most recent session traces from the SQLite store.",
        inputSchema={
            "type": "object",
            "properties": {
                "n": {"type": "integer", "description": "Number of traces to return (1–50, default 5)"},
            },
        },
    ),
    Tool(
        name="get_trace",
        description="Retrieve a single session trace by its trace ID.",
        inputSchema={
            "type": "object",
            "properties": {
                "trace_id": {"type": "string", "description": "The trace UUID"},
            },
            "required": ["trace_id"],
        },
    ),
    Tool(
        name="count_traces",
        description="Return the total number of traces stored in the session database.",
        inputSchema={"type": "object", "properties": {}},
    ),
]


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> CallToolResult:
    try:
        if name == "compute_trust_score":
            from trust import compute_trust_score
            result = compute_trust_score(
                p=float(arguments["p"]),
                ue=float(arguments["ue"]),
                ua=float(arguments["ua"]),
            )
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result, indent=2))],
                is_error=False,
            )

        elif name == "get_recent_traces":
            from trace_store import init_db, get_recent_traces
            init_db()
            n = int(arguments.get("n", 5))
            traces = get_recent_traces(n)
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=json.dumps({"count": len(traces), "traces": traces}, indent=2),
                )],
                is_error=False,
            )

        elif name == "get_trace":
            from trace_store import init_db, get_trace
            init_db()
            trace = get_trace(arguments["trace_id"])
            if trace is None:
                return CallToolResult(
                    content=[TextContent(
                        type="text",
                        text=json.dumps({"error": f"Trace '{arguments['trace_id']}' not found."}),
                    )],
                    is_error=True,
                )
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(trace, indent=2))],
                is_error=False,
            )

        elif name == "count_traces":
            from trace_store import init_db, count_traces
            init_db()
            n = count_traces()
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps({"total_traces": n}))],
                is_error=False,
            )

        return CallToolResult(
            content=[TextContent(type="text", text=f"Unknown tool: {name}")],
            is_error=True,
        )

    except Exception as e:
        return CallToolResult(
            content=[TextContent(type="text", text=f"Error: {e}")],
            is_error=True,
        )


async def main():
    from mcp.server.stdio import stdio_server
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
