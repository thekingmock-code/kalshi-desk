"""Per-side gate checks — delegates to gates_eval."""
from __future__ import annotations

from desk.engine.gates_eval import GateContext, all_pass, evaluate_side, gate_edge_value, net_edge, net_edge_entry
from desk.engine.tunable import merge_params


def gate_sides(
    strategy: dict,
    *,
    asset: str,
    secs_left: float | None,
    yes_bid: float | None,
    yes_ask: float | None,
    no_bid: float | None,
    no_ask: float | None,
    p_up: float | None,
    buy_pct: float | None,
    momentum: int | None,
    vol_ratio: float | None,
    now: float,
    fee_fn,
    already_entered_hour: bool = False,
    params: dict | None = None,
    sigma_t: float | None = None,
    ref: float | None = None,
    strike: float | None = None,
    dual_feed_ok: bool = False,
    feed_detail: str = "",
    composite_pct_move_3s: float | None = None,
    kalshi_mid_move_3s: float | None = None,
    btc_momentum: int | None = None,
    sol_confirm_secs: float | None = None,
    index_ok: bool = False,
    lag: float | None = None,
    momentum_30: int | None = None,
    momentum_60: int | None = None,
    signal_hold_secs: float | None = None,
    edge_basis: str = "net",
    ignore_edge_gates: bool = False,
    skip_divergence: bool = False,
    is_weekend: bool = False,
    composite: float | None = None,
    index_price: float | None = None,
    coinbase_age: float | None = None,
    kraken_age: float | None = None,
    feed_freshness_enabled: bool = False,
    feed_max_age_secs: float = 2.0,
    momentum_gate_enabled: bool = True,
) -> dict[str, list[dict]]:
    del already_entered_hour
    p = params or merge_params(strategy.get("id", "gates_15m"), asset, strategy.get("params"))
    yes_mid = None if yes_bid is None or yes_ask is None else (yes_bid + yes_ask) / 2
    no_mid = None if no_bid is None or no_ask is None else (no_bid + no_ask) / 2

    def one(side: str, bid, ask, prob, flow, mom) -> list[dict]:
        spread = None if ask is None or bid is None else ask - bid
        edge = net_edge(prob, ask, spread, fee_fn)
        edge_ent = net_edge_entry(prob, ask, fee_fn)
        g_edge = gate_edge_value(edge_basis, edge, edge_ent)
        ctx = GateContext(
            asset=asset,
            side=side,
            secs_left=secs_left,
            bid=bid,
            ask=ask,
            prob=prob,
            flow_pct=flow,
            momentum=mom,
            vol_ratio=vol_ratio,
            sigma_t=sigma_t,
            ref=ref,
            strike=strike,
            dual_feed_ok=dual_feed_ok,
            feed_detail=feed_detail,
            p_up=p_up,
            yes_mid=yes_mid,
            no_mid=no_mid,
            net_edge=edge,
            net_edge_entry=edge_ent,
            gate_edge=g_edge,
            composite_pct_move_3s=composite_pct_move_3s,
            kalshi_mid_move_3s=kalshi_mid_move_3s,
            btc_momentum=btc_momentum,
            sol_confirm_secs=sol_confirm_secs,
            params=p,
            index_ok=index_ok,
            lag=lag,
            momentum_30=momentum_30,
            momentum_60=momentum_60,
            signal_hold_secs=signal_hold_secs,
            is_weekend=is_weekend,
            composite=composite,
            index_price=index_price,
            coinbase_age=coinbase_age,
            kraken_age=kraken_age,
            feed_freshness_enabled=feed_freshness_enabled,
            feed_max_age_secs=feed_max_age_secs,
            momentum_gate_enabled=momentum_gate_enabled,
        )
        return evaluate_side(
            strategy=strategy,
            ctx_base=ctx,
            fee_fn=fee_fn,
            ignore_edge_gates=ignore_edge_gates,
            skip_divergence=skip_divergence,
        )

    return {
        "UP": one("UP", yes_bid, yes_ask, p_up, buy_pct, momentum),
        "DOWN": one(
            "DOWN",
            no_bid,
            no_ask,
            None if p_up is None else 1 - p_up,
            None if buy_pct is None else 100 - buy_pct,
            None if momentum is None else -momentum,
        ),
    }


__all__ = ["all_pass", "gate_sides", "net_edge"]
