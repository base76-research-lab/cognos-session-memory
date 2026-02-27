"""
Plan Engine Module

Extracts verified context from recent traces and computes trust score.
If trust_score > threshold, injects as system prompt.
If trust_score < threshold, flags for manual review.

Core workflow:
    1. Fetch recent traces (n=5 by default)
    2. Extract structured context (project, decision, questions, etc.)
    3. Compute trust score via trust.compute_trust_score()
    4. Return injected system prompt or flagged context
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from trace_store import get_recent_traces
from trust import compute_trust_score

router = APIRouter()


# ── Request/Response Models ────────────────────────────────────────────────────


class PlanRequest(BaseModel):
    """Request to plan route."""
    n: int = 5                  # number of traces to fetch
    trust_threshold: float = 0.75
    mode: str = "auto"          # auto | force | dry_run


class ContextField(BaseModel):
    """Extracted context structure."""
    active_project: str | None = None
    last_decision: str | None = None
    open_questions: list[str] = []
    current_output: str | None = None
    recent_models: list[str] = []


class PlanResponse(BaseModel):
    """Response from plan route."""
    status: str                 # injected | flagged | empty
    trust_score: float
    confidence: float
    risk: float
    decision: str               # PASS | REFINE | ESCALATE
    context: ContextField
    system_prompt: str | None = None
    flagged_reason: str | None = None
    trace_ids: list[str] = []
    generated_at: str


# ── Context Extraction ─────────────────────────────────────────────────────────


def extract_context(traces: list[dict[str, Any]]) -> tuple[ContextField, float]:
    """
    Extract structured context from traces.
    Returns (ContextField, coverage_score).

    coverage = fraction of required fields that were filled.
    """
    required_fields = ["active_project", "last_decision", "current_output"]
    filled = 0

    projects: list[str] = []
    decisions: list[str] = []
    questions: list[str] = []
    outputs: list[str] = []
    models: list[str] = []

    for trace in traces:
        meta = trace.get("metadata", {})

        if model := trace.get("model"):
            models.append(model)

        # Try to extract structured data from metadata
        if project := meta.get("active_project"):
            projects.append(project)
            filled += 1

        if decision := meta.get("last_decision"):
            decisions.append(decision)
            filled += 1

        if output := meta.get("current_output"):
            outputs.append(output)
            filled += 1

        if qs := meta.get("open_questions", []):
            questions.extend(qs)

    # Fallback: if metadata lacks structure, count partial coverage
    total_possible = len(required_fields) * len(traces) if traces else 1
    coverage = min(filled / total_possible, 1.0) if total_possible > 0 else 0.0

    context = ContextField(
        active_project=projects[-1] if projects else None,
        last_decision=decisions[-1] if decisions else None,
        open_questions=list(dict.fromkeys(questions))[:5],  # dedup, max 5
        current_output=outputs[-1] if outputs else None,
        recent_models=list(dict.fromkeys(models))[:3],
    )

    return context, coverage


def compute_context_signals(
    traces: list[dict[str, Any]],
    coverage: float,
) -> tuple[float, float, float]:
    """
    Compute (p, ue, ua) for context trust score.

    p  = coverage (fraction of schema filled)
    ue = divergence between traces (epistemic)
    ua = mean risk in traces (aleatoric proxy)
    """
    if not traces:
        return 0.0, 1.0, 1.0

    risks = [float(t.get("risk", 0.5)) for t in traces]
    trust_scores = [float(t.get("trust_score", 0.5)) for t in traces]

    # Ua: mean risk from traces
    ua = sum(risks) / len(risks)

    # Ue: spread in trust_scores (divergence proxy)
    if len(trust_scores) > 1:
        mean_ts = sum(trust_scores) / len(trust_scores)
        variance = sum((s - mean_ts) ** 2 for s in trust_scores) / len(trust_scores)
        ue = min(variance * 4, 1.0)  # normalize
    else:
        ue = 0.2  # single trace → moderate epistemic uncertainty

    p = coverage

    return p, ue, ua


def build_system_prompt(context: ContextField, trust_score: float) -> str:
    """Build system prompt from extracted context."""
    lines = [
        "## CognOS Context — Session Initialization",
        f"Trust Score: {trust_score:.2f}",
        "",
    ]

    if context.active_project:
        lines.append(f"**Active project:** {context.active_project}")
    if context.last_decision:
        lines.append(f"**Last decision:** {context.last_decision}")
    if context.current_output:
        lines.append(f"**Current output:** {context.current_output}")
    if context.open_questions:
        lines.append("**Open questions:**")
        for q in context.open_questions:
            lines.append(f"  - {q}")
    if context.recent_models:
        lines.append(f"**Recent models:** {', '.join(context.recent_models)}")

    lines += [
        "",
        "_Context injected by CognOS Plan Engine. Treat as verified but not exhaustive._",
    ]

    return "\n".join(lines)


# ── Route ──────────────────────────────────────────────────────────────────────


@router.post("/v1/plan", response_model=PlanResponse)
async def plan(req: PlanRequest) -> PlanResponse:
    """
    Plan-mode route: fetch recent traces, extract context,
    compute trust score, and return system prompt or flagged context.
    """
    traces = get_recent_traces(n=req.n)

    if not traces:
        return PlanResponse(
            status="empty",
            trust_score=0.0,
            confidence=0.0,
            risk=1.0,
            decision="ESCALATE",
            context=ContextField(),
            flagged_reason="No traces found. Start a session to build context.",
            trace_ids=[],
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    trace_ids = [t["trace_id"] for t in traces if "trace_id" in t]
    context, coverage = extract_context(traces)
    p, ue, ua = compute_context_signals(traces, coverage)
    result = compute_trust_score(p=p, ue=ue, ua=ua)

    trust_score = result["trust_score"]
    confidence = result["confidence"]
    risk = result["risk"]
    decision = result["decision"]

    # dry_run: compute but do not inject
    if req.mode == "dry_run":
        return PlanResponse(
            status="flagged",
            trust_score=trust_score,
            confidence=confidence,
            risk=risk,
            decision=decision,
            context=context,
            flagged_reason="dry_run mode — no injection performed",
            trace_ids=trace_ids,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    # force: inject regardless of score
    if req.mode == "force" or trust_score >= req.trust_threshold:
        prompt = build_system_prompt(context, trust_score)
        return PlanResponse(
            status="injected",
            trust_score=trust_score,
            confidence=confidence,
            risk=risk,
            decision=decision,
            context=context,
            system_prompt=prompt,
            trace_ids=trace_ids,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    # below threshold → flag
    return PlanResponse(
        status="flagged",
        trust_score=trust_score,
        confidence=confidence,
        risk=risk,
        decision=decision,
        context=context,
        flagged_reason=f"Trust score {trust_score:.2f} below threshold {req.trust_threshold}. Manual review recommended.",
        trace_ids=trace_ids,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
