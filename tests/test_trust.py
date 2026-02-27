"""
Test trust scoring module
"""

import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from trust import compute_trust_score, _action_gate


def test_compute_trust_score_high_confidence():
    """Test trust score with high confidence inputs."""
    result = compute_trust_score(p=0.9, ue=0.05, ua=0.05)

    assert result["trust_score"] > 0.8
    assert result["risk"] < 0.2
    assert result["decision"] == "PASS"


def test_compute_trust_score_low_confidence():
    """Test trust score with low confidence inputs."""
    result = compute_trust_score(p=0.3, ue=0.6, ua=0.3)

    assert result["trust_score"] < 0.3
    assert result["risk"] > 0.7
    assert result["decision"] == "ESCALATE"


def test_action_gate():
    """Test action gate thresholds."""
    assert _action_gate(0.1) == "PASS"
    assert _action_gate(0.4) == "REFINE"
    assert _action_gate(0.7) == "ESCALATE"


def test_trust_score_complementarity():
    """Test that C + R = 1."""
    result = compute_trust_score(p=0.5, ue=0.2, ua=0.2)

    c = result["confidence"]
    r = result["risk"]

    assert abs((c + r) - 1.0) < 0.01
