# CognOS Session Memory — A Better /compact

> *Claude Code's `/compact` compresses your conversation. It doesn't remember what mattered.*

---

## The Problem with /compact

Claude Code's built-in `/compact` command summarizes the conversation when the context window fills up. It works — but it has three structural weaknesses:

**1. No trust scoring**
The summary is generated without any verification of what information was reliable. Speculative comments, failed attempts, and confident errors are all treated equally.

**2. No audit trail**
There is no record of what was summarized, when, or why. For regulated use cases (EU AI Act, safety-critical systems), this is a compliance gap.

**3. Session boundary = memory loss**
When you start a new session, `/compact` output is gone. Each new conversation begins cold, with no verified context of what was decided, built, or blocked.

---

## What CognOS Session Memory Does Instead

```
/compact  →  summary lost at session boundary
/save     →  trust-scored, stored in SQLite, injected next session
```

### The Formula

```
C = p · (1 − Ue − Ua)

p   = summary coverage (length/quality proxy)
Ue  = epistemic uncertainty (fixed low for manual saves: 0.10)
Ua  = aleatoric uncertainty (fixed low for explicit summaries: 0.10)
```

A 150-token summary scores C ≈ 0.72 (PASS).
A 30-token summary scores C ≈ 0.14 — not injected. Forces quality.

### Action Gate

```
C > 0.45   → inject as SESSION_CONTEXT next session
C < 0.45   → block injection, flag for review
```

---

## Comparison

| | Claude /compact | CognOS /save |
|---|---|---|
| Summarizes conversation | ✓ | ✓ |
| Trust-scores the summary | ✗ | ✓ |
| Persists across sessions | ✗ | ✓ |
| Injected next session | ✗ | ✓ |
| Audit trail (trace ID) | ✗ | ✓ |
| Blocks low-quality summaries | ✗ | ✓ |
| EU AI Act audit-ready | ✗ | ✓ |
| Works offline (local SQLite) | ✓ | ✓ |

---

## Usage

### Via Claude Code slash command

```
/save
```

Claude writes a structured summary, trust-scores it, and saves it to SQLite.
Next session: automatically injected as `SESSION_CONTEXT`.

### Via MCP tool

```json
{
  "mcpServers": {
    "cognos-session-memory": {
      "command": "python3",
      "args": ["/path/to/cognos-session-memory/mcp_server.py"]
    }
  }
}
```

Tools exposed:
- `save_session(summary, project?)` — save and score
- `load_session(threshold?)` — retrieve last verified context

### Via API

```bash
# Start gateway
python3 -m uvicorn --app-dir src main:app --port 8788

# Save (via trace middleware — trust scoring happens automatically)
# Load
curl -X POST http://127.0.0.1:8788/v1/plan \
  -H 'Content-Type: application/json' \
  -d '{"n": 5, "trust_threshold": 0.45, "mode": "auto"}'
```

---

## Design Philosophy

> *Verification before injection. Trust as a gate, not a label.*

CognOS Session Memory treats session context the same way the trust engine treats any AI output: it is not trusted by default. A summary must earn its injection by passing a minimum confidence threshold.

This is not a UX improvement over `/compact`. It is an architectural one.

---

*Base76 Research Lab · Björn André Wikström · 2026*
*ORCID: 0009-0000-4015-2357*
