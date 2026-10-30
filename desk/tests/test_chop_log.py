from desk.engine.chop_log import (
    CHOP_LOG_LABEL,
    candidate_log_fields,
    chop_log_detail,
    chop_log_gate,
    secs_left_bucket,
)
from desk.engine.gate_utils import all_active_pass


def test_chop_log_gate_ok():
    g = chop_log_gate(original=82, adjusted=61, threshold=30, basis="original")
    assert g["label"] == CHOP_LOG_LABEL
    assert g["status"] == "log_ok"
    assert g["counts"] is False
    assert g["tag"] == "L"
    assert "82" in g["detail"]


def test_chop_log_gate_would_block():
    g = chop_log_gate(original=20, adjusted=None, threshold=30, basis="original")
    assert g["status"] == "log_would_block"
    assert g["chop_log_would_block"] is True


def test_log_gate_does_not_affect_passing_count():
    g = chop_log_gate(original=10, adjusted=None, threshold=30, basis="original")
    checks = [{"label": "Edge", "ok": True, "status": "pass", "counts": True}, g]
    assert all_active_pass(checks)


def test_detail_shows_adjusted_when_present():
    assert "adj 61" in chop_log_detail(original=82, adjusted=61, threshold=30)


def test_candidate_log_fields():
    f = candidate_log_fields(
        original=25,
        adjusted=None,
        threshold=30,
        basis="original",
        secs_left=650,
    )
    assert f["chop_log_would_block"] is True
    assert f["chop_log_secs_left_bucket"] == "early"
