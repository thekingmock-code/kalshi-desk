"""Per-side gate checks — delegates to gates_eval."""
from __future__ import annotations

from desk.engine.gates_eval import GateContext, all_pass, evaluate_side, net_edge
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
) -> dict[str, list[dict]]:
    del now, already_entered_hour
    p = params or merge_params(strategy.get("id", "gates_15m"), asset, strategy.get("params"))
    yes_mid = None if yes_bid is None or yes_ask is None else (yes_bid + yes_ask) / 2
    no_mid = None if no_bid is None or no_ask is None else (no_bid + no_ask) / 2

    def one(side: str, bid, ask, prob, flow, mom) -> list[dict]:
        spread = None if ask is None or bid is None else ask - bid
        edge = net_edge(prob, ask, spread, fee_fn)
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
        )
        return evaluate_side(strategy=strategy, ctx_base=ctx, fee_fn=fee_fn)

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
