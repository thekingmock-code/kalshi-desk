"""Chop vs Real log-only gate (paper). Never blocks entries."""
from __future__ import annotations

from desk.engine.gate_utils import gate_check

CHOP_LOG_LABEL = "Chop (log)"


def secs_left_bucket(secs_left: float | None) -> str:
    if secs_left is None:
        return "unknown"
    if secs_left > 600:
        return "early"
    if secs_left >= 300:
        return "mid"
    return "late"


def chop_log_score_for_basis(
    *,
    original: float | None,
    adjusted: float | None,
    basis: str,
) -> tuple[float | None, str]:
    use = (basis or "original").lower()
    if use == "adjusted" and adjusted is not None:
        return adjusted, "adjusted"
    if original is not None:
        return original, "original"
    return adjusted, "adjusted" if adjusted is not None else "original"


def chop_log_detail(
    *,
    original: float | None,
    adjusted: float | None,
    threshold: float,
) -> str:
    if original is None and adjusted is None:
        return f"chop — vs {threshold:.0f}"
    o = "—" if original is None else f"{original:.0f}"
    if adjusted is not None and adjusted != original:
        return f"chop {o} (adj {adjusted:.0f}) vs {threshold:.0f}"
    return f"chop {o} vs {threshold:.0f}"


def chop_log_would_block(score: float | None, threshold: float) -> bool:
    if score is None:
        return False
    return score < threshold


def chop_log_gate(
    *,
    original: float | None,
    adjusted: float | None,
    threshold: float,
    basis: str,
) -> dict:
    score, basis_used = chop_log_score_for_basis(original=original, adjusted=adjusted, basis=basis)
    would_block = chop_log_would_block(score, threshold)
    detail = chop_log_detail(original=original, adjusted=adjusted, threshold=threshold)
    status = "log_would_block" if would_block else "log_ok"
    return gate_check(
        CHOP_LOG_LABEL,
        ok=True,
        detail=detail,
        status=status,
        counts=False,
        hardness="log",
        value=score,
        threshold=threshold,
        tag="L",
        chop_log_basis=basis_used,
        chop_log_would_block=would_block,
    )


def candidate_log_fields(
    *,
    original: float | None,
    adjusted: float | None,
    threshold: float,
    basis: str,
    secs_left: float | None,
) -> dict:
    score, basis_used = chop_log_score_for_basis(original=original, adjusted=adjusted, basis=basis)
    return {
        "chop_log_score": score,
        "chop_log_threshold": threshold,
        "chop_log_basis": basis_used,
        "chop_log_would_block": chop_log_would_block(score, threshold),
        "chop_log_secs_left_bucket": secs_left_bucket(secs_left),
    }
