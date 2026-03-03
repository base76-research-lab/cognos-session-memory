# CognOS Session Memory

mcp-name: io.github.base76-research-lab/cognos-session-memory

**Verified context injection via epistemic trust scoring for LLMs.**

Solves session fragmentation by maintaining verified, high-confidence session context between conversations.

## Problem

Large language models suffer from **session fragmentation**: each new conversation starts without verified context of previous work. This forces repeated explanations, loses decision history, and breaks long-running workflows.

Existing solutions (persistent memory systems, vector retrieval) either:
- Lack trust scores before injection → hallucinations propagate
- Don't audit which context was injected → compliance gaps
- Treat all past information equally → noise overwhelms signal

## Solution

A **plan-mode gateway** that:

1. **Extracts** structured context from 3-5 recent traces
2. **Scores** context quality via CognOS epistemic formula: `C = p · (1 − Ue − Ua)`
3. **Injects** as system prompt only if `C > threshold`
4. **Flags** for manual review if `C < threshold`
5. **Audits** every context injection with trace IDs → EU AI Act compliance

## Architecture

```
recent_traces (n=5)
    ↓
extract_context() → ContextField + coverage
    ↓
compute_trust_score(p, ue, ua) → C, R, decision
    ↓
if C > threshold:
    system_prompt ← inject
else:
    flagged_reason ← manual review
```

### Core Formula

```
C = p · (1 − Ue − Ua)
R = 1 − C

where:
  p   = prediction confidence (coverage of required fields)
  Ue  = epistemic uncertainty (divergence between traces)
  Ua  = aleatoric uncertainty (mean risk in traces)
```

### Action Gate

```
R < 0.25       → PASS      (inject without review)
0.25 ≤ R < 0.60 → REFINE   (inject with caution)
R ≥ 0.60       → ESCALATE  (flag for manual review)
```

## API

### POST /v1/plan

Extract and score context.

**Request:**
```json
{
  "n": 5,
  "trust_threshold": 0.75,
  "mode": "auto"
}
```

**Response (if injected):**
```json
{
  "status": "injected",
  "trust_score": 0.82,
  "confidence": 0.82,
  "risk": 0.18,
  "decision": "PASS",
  "context": {
    "active_project": "CognOS mHC research",
    "last_decision": "Verify P1 hypothesis",
    "open_questions": ["How does routing entropy scale?"],
    "current_output": "exp_008 complete",
    "recent_models": ["gpt-4", "claude-3", "mistral"]
  },
  "system_prompt": "## CognOS Context...",
  "trace_ids": ["uuid-1", "uuid-2", ...]
}
```

**Response (if flagged):**
```json
{
  "status": "flagged",
  "trust_score": 0.45,
  "decision": "REFINE",
  "flagged_reason": "Trust score 0.45 below threshold 0.75. Manual review recommended.",
  "trace_ids": [...]
}
```

## Modes

- **auto** (default) — inject if `trust_score ≥ threshold`, else flag
- **force** — always inject (for testing)
- **dry_run** — compute score but never inject

## Claude Code Integration

### As a /compact replacement

```bash
# In any Claude Code session:
/save
```

Claude writes a structured summary, trust-scores it, and persists it to SQLite.
Next session: automatically injected as `SESSION_CONTEXT` before your first prompt.

See [docs/COMPACT_ALTERNATIVE.md](docs/COMPACT_ALTERNATIVE.md) for a full comparison.

### As an MCP server

Add to `~/.claude/settings.json`:

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

| Tool | Description |
|------|-------------|
| `save_session(summary, project?)` | Trust-score and persist a session summary |
| `load_session(threshold?)` | Retrieve last verified context (default threshold: 0.45) |

---

## Quick Start

### Installation

```bash
git clone https://github.com/base76-research-lab/cognos-session-memory
cd cognos-session-memory
pip install -e .
```

### Run Gateway

```bash
python3 -m uvicorn --app-dir src main:app --port 8788
```

### Test /v1/plan (dry_run)

```bash
curl -X POST http://127.0.0.1:8788/v1/plan \
  -H 'Content-Type: application/json' \
  -d '{"n": 5, "mode": "dry_run"}'
```

### Test /v1/plan (auto)

```bash
curl -X POST http://127.0.0.1:8788/v1/plan \
  -H 'Content-Type: application/json' \
  -d '{"n": 5, "trust_threshold": 0.75, "mode": "auto"}'
```

## Modules

- **trust.py** — CognOS confidence formula, action gate, signal extractors
- **trace_store.py** — SQLite persistence (write/read/purge)
- **plan.py** — Context extraction, trust scoring, system prompt building
- **main.py** — FastAPI gateway + middleware
- **mcp_server.py** — MCP stdio server (`save_session`, `load_session`)

## Testing

```bash
pytest tests/ -v --cov=src
```

## Documentation

- [COMPACT_ALTERNATIVE.md](docs/COMPACT_ALTERNATIVE.md) — Why this beats `/compact`
- [PAPER.md](docs/PAPER.md) — Research paper

## Research Paper

See [docs/PAPER.md](docs/PAPER.md) — "Verified Context Injection: Epistemically Scored Session Memory for Large Language Models"

**Status:** Independent research — Base76 Research Lab, 2026
**Authors:** Björn André Wikström (Base76)

## Citation

```bibtex
@software{wikstrom2026cognos,
  author = {Wikström, Björn André},
  title = {{CognOS Session Memory}: Verified Context Injection via Epistemic Trust Scoring},
  year = {2026},
  url = {https://github.com/base76-research-lab/cognos-session-memory}
}
```

## License

MIT

## Contact

- **Author:** Björn André Wikström
- **Email:** bjorn@base76.se
- **ORCID:** 0009-0000-4015-2357
- **GitHub:** [base76-research-lab](https://github.com/base76-research-lab)
