from desk.engine.model import fee_dollars
from desk.engine.paper import contracts_for_max_usd, paper_entry_contracts


def test_contracts_for_20_usd_at_50c_ask():
    c = contracts_for_max_usd(20.0, 0.50, 0.07)
    cost = c * 0.50 + fee_dollars(c, 0.50, 0.07)
    assert cost <= 20.0 + 1e-6
    assert c >= 30


def test_paper_entry_contracts_from_config():
    cfg = {"paper": {"max_trade_usd": 20, "contracts": 99}}
    assert paper_entry_contracts(cfg, 0.45, 0.07) == contracts_for_max_usd(20.0, 0.45, 0.07)
