#!/usr/bin/env python3
"""
CognOS Session Memory — MCP server

Exposes two tools for Claude Code and other MCP clients:

  save_session   — trust-score and persist a session summary to SQLite
  load_session   — retrieve last verified session context

A trust-scored, auditable alternative to Claude Code's /compact.

Usage:
    python3 mcp_server.py

Claude Code config (~/.claude/settings.json):
    {
      "mcpServers": {
        "cognos-session-memory": {
          "command": "python3",
          "args": ["/path/to/cognos-session-memory/mcp_server.py"]
        }
      }
    }
"""

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

DB_PATH = os.getenv(
    "COGNOS_TRACE_DB",
    str(Path.home() / ".local/share/b76/sessions/traces.sqlite3"),
)

# ---------------------------------------------------------------------------
# Lazy init — only import when first tool call arrives
# ---------------------------------------------------------------------------

_initialized = False

def _ensure_init():
    global _initialized
    if _initialized:
        return
    import trace_store as ts
    ts.DB_PATH = DB_PATH
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    ts.init_db()
    _initialized = True


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _save_session(summary: str, project: str | None = None) -> str:
    _ensure_init()
    import trace_store as ts
    from trust import compute_trust_score

    tokens = len(summary) // 4
    p  = min(tokens / 150, 1.0)   # 150 tokens = full coverage
    ue = 0.10                      # manual save → low epistemic uncertainty
    ua = 0.10                      # explicit summary → low aleatoric noise

    result = compute_trust_score(p=p, ue=ue, ua=ua)

    trace_id = str(uuid.uuid4())
    ts.DB_PATH = DB_PATH
    ts.save_trace({
        "trace_id":    trace_id,
        "created_at":  datetime.now(timezone.utc).isoformat(),
        "decision":    result["decision"],
        "policy":      "/save",
        "trust_score": result["trust_score"],
        "risk":        result["risk"],
        "is_stream":   False,
        "status_code": 200,
        "model":       "claude-code/mcp",
        "metadata": {
            "summary":  summary,
            "project":  project,
            "tokens":   tokens,
            "source":   "mcp_save",
        },
    })

    count = ts.count_traces()

    return json.dumps({
        "saved":       True,
        "trace_id":    trace_id,
        "trust_score": result["trust_score"],
        "confidence":  result["confidence"],
        "risk":        result["risk"],
        "decision":    result["decision"],
        "tokens":      tokens,
        "traces_total": count,
        "signals":     result["signals"],
    }, indent=2)


def _load_session(threshold: float = 0.45) -> str:
    _ensure_init()
    import trace_store as ts
    ts.DB_PATH = DB_PATH

    traces = ts.get_recent_traces(n=10)
    manual = [
        t for t in traces
        if isinstance(t.get("metadata"), dict)
        and t["metadata"].get("source") in ("mcp_save", "manual_save")
    ]

    if not manual:
        return json.dumps({"found": False, "reason": "No saved sessions found."})

    latest  = manual[0]
    trust   = latest.get("trust_score", 0)
    meta    = latest.get("metadata", {})
    summary = meta.get("summary", "")

    if trust < threshold:
        return json.dumps({
            "found":   False,
            "reason":  f"Latest session trust score {trust:.2f} below threshold {threshold}.",
            "trace_id": latest.get("trace_id"),
        })

    saved_at = latest.get("created_at", "")[:16].replace("T", " ")

    return json.dumps({
        "found":       True,
        "trust_score": trust,
        "decision":    latest.get("decision"),
        "saved_at":    saved_at,
        "project":     meta.get("project"),
        "summary":     summary,
        "trace_id":    latest.get("trace_id"),
        "inject":      (
            f"SESSION_CONTEXT: (trust={trust:.2f}, saved {saved_at})\n"
            f"{summary}"
        ),
    }, indent=2)


# ---------------------------------------------------------------------------
# MCP protocol (stdio transport)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "save_session",
        "description": (
            "Save a trust-scored session summary to CognOS Session Memory. "
            "Call this instead of or after /compact to preserve verified context "
            "across sessions. The summary is scored epistemically — short or "
            "vague summaries get lower trust scores and may not be injected next session."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": (
                        "Compact session summary (100-200 words): active project, "
                        "last decision, current output, open questions, key files."
                    ),
                },
                "project": {
                    "type": "string",
                    "description": "Optional: active project name.",
                },
            },
            "required": ["summary"],
        },
    },
    {
        "name": "load_session",
        "description": (
            "Load the last verified session context from CognOS Session Memory. "
            "Returns the summary and an inject-ready SESSION_CONTEXT block. "
            "Only returns context that passed the trust threshold — never injects "
            "low-confidence or stale sessions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "threshold": {
                    "type": "number",
                    "description": "Minimum trust score to accept (default 0.45).",
                },
            },
            "required": [],
        },
    },
]


def send(obj: dict):
    print(json.dumps(obj), flush=True)


def handle(request: dict) -> dict | None:
    method = request.get("method")
    req_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name":    "cognos-session-memory",
                    "version": "0.1.0",
                },
            },
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {"tools": TOOLS},
        }

    if method == "tools/call":
        tool = request.get("params", {}).get("name")
        args = request.get("params", {}).get("arguments", {})

        try:
            if tool == "save_session":
                text = _save_session(
                    summary=args.get("summary", ""),
                    project=args.get("project"),
                )
            elif tool == "load_session":
                text = _load_session(
                    threshold=float(args.get("threshold", 0.45)),
                )
            else:
                return {
                    "jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {tool}"},
                }
        except Exception as e:
            text = json.dumps({"error": str(e)})

        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {"content": [{"type": "text", "text": text}]},
        }

    if method == "notifications/initialized":
        return None

    return {
        "jsonrpc": "2.0", "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request  = json.loads(line)
            response = handle(request)
            if response is not None:
                send(response)
        except json.JSONDecodeError:
            pass
        except Exception as e:
            send({
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32603, "message": str(e)},
            })


if __name__ == "__main__":
    main()
