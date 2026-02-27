"""
Trust Score Calculation Module

Core CognOS confidence formula:
    C = p · (1 − Ue − Ua)
    R = 1 − C

Where:
    p   = prediction confidence (coverage / softmax)
    Ue  = epistemic uncertainty (divergence / variance)
    Ua  = aleatoric uncertainty (output entropy / irreducible noise)
"""

from __future__ import annotations

import math
from typing import Any


def compute_trust_score(
    p: float,
    ue: float,
    ua: float,
) -> dict[str, Any]:
    """
    Compute CognOS confidence, risk, and action decision.

    Args:
        p:  prediction confidence [0, 1]
        ue: epistemic uncertainty [0, 1]
        ua: aleatoric uncertainty [0, 1]

    Returns:
        dict with trust_score, confidence, risk, decision, signals
    """
    p = _clamp(p)
    ue = _clamp(ue)
    ua = _clamp(ua)

    # Prevent Ue + Ua > 1 (mathematically invalid)
    total_uncertainty = min(ue + ua, 1.0)

    C = p * (1.0 - total_uncertainty)
    R = 1.0 - C

    return {
        "confidence": _round(C),
        "risk": _round(R),
        "trust_score": _round(C),
        "decision": _action_gate(R),
        "signals": {
            "p": _round(p),
            "ue": _round(ue),
            "ua": _round(ua),
            "total_uncertainty": _round(total_uncertainty),
        },
    }


# ── Action Gate ───────────────────────────────────────────────────────────────
#   R < τ1          → PASS
#   τ1 ≤ R < τ2    → REFINE
#   R ≥ τ2          → ESCALATE

TAU_1 = 0.25  # under → PASS
TAU_2 = 0.60  # under → REFINE, over → ESCALATE


def _action_gate(risk: float) -> str:
    """Determine action based on risk threshold."""
    if risk < TAU_1:
        return "PASS"
    if risk < TAU_2:
        return "REFINE"
    return "ESCALATE"


# ── Signal Extractors ──────────────────────────────────────────────────────────


def epistemic_uncertainty_from_divergence(
    hidden_states: list[list[float]],
) -> float:
    """
    Ue from inter-stream divergence.

    D = (1/N) · Σ ||hi − h̄||²

    Normalized to [0, 1] via tanh scaling.
    """
    if not hidden_states or len(hidden_states) < 2:
        return 0.2

    n = len(hidden_states)
    dim = len(hidden_states[0])

    mean = [
        sum(h[i] for h in hidden_states) / n
        for i in range(dim)
    ]

    divergence = sum(
        sum((h[i] - mean[i]) ** 2 for i in range(dim))
        for h in hidden_states
    ) / n

    # Normalize: tanh gives soft [0,1] mapping
    return _round(math.tanh(divergence))


def aleatoric_uncertainty_from_entropy(
    probs: list[float],
) -> float:
    """
    Ua from output distribution Shannon entropy.

    H = −Σ p·log(p)

    Normalized against maximal entropy for given vocab size.
    """
    if not probs:
        return 0.5

    probs = [max(p, 1e-12) for p in probs]
    total = sum(probs)
    probs = [p / total for p in probs]

    H = -sum(p * math.log(p) for p in probs)
    H_max = math.log(len(probs)) if len(probs) > 1 else 1.0

    return _round(H / H_max if H_max > 0 else 0.0)


def prediction_confidence_from_softmax(
    logits: list[float],
) -> float:
    """
    p from softmax top-1 confidence.
    """
    if not logits:
        return 0.5

    max_l = max(logits)
    exps = [math.exp(l - max_l) for l in logits]
    total = sum(exps)
    probs = [e / total for e in exps]

    return _round(max(probs))


# ── Routing Integrity Check ────────────────────────────────────────────────────
#   RoutingIntegrity = (P_refine > P_min) ∧ (Coverage_refine > ε)

P_MIN = 0.60
EPS_COV = 0.10


def routing_integrity(
    refine_precision: float,
    coverage: float,
) -> dict[str, Any]:
    """
    Verify that refine-routing is meaningful.
    System must not CONTINUE without approved integrity.
    """
    precision_ok = refine_precision > P_MIN
    coverage_ok = coverage > EPS_COV
    valid = precision_ok and coverage_ok

    return {
        "valid": valid,
        "precision_ok": precision_ok,
        "coverage_ok": coverage_ok,
        "refine_precision": _round(refine_precision),
        "coverage": _round(coverage),
        "p_min": P_MIN,
        "eps_coverage": EPS_COV,
        "verdict": "CONTINUE" if valid else "HALT",
    }


# ── CW-gain (Condition-Weighted Performance Metric) ───────────────────────────


def cw_gain(
    correct_improvements: int,
    errors_introduced: int,
    n_total: int,
) -> dict[str, Any]:
    """
    CW = (correct_improvements − errors_introduced) / N

    Measures net utility of refine step.
    """
    if n_total == 0:
        return {"cw": 0.0, "delta_cw": 0.0}

    cw = (correct_improvements - errors_introduced) / n_total

    return {
        "cw": _round(cw),
        "correct_improvements": correct_improvements,
        "errors_introduced": errors_introduced,
        "n_total": n_total,
    }


# ── Helpers ────────────────────────────────────────────────────────────────────


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp value to [lo, hi]."""
    return max(lo, min(hi, float(v)))


def _round(v: float, decimals: int = 4) -> float:
    """Round to N decimals."""
    return round(float(v), decimals)
