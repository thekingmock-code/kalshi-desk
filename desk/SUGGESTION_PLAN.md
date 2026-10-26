# Suggestion plan (15m desk)

Use this with the **SUGGESTION PLAN** panel on the dashboard. The page fills answers from live data every second. The desk never places orders; **WAIT** is normal when flat.

## When you are FLAT

| # | Question | Green means | If red |
|---|----------|-------------|--------|
| 1 | Is the 15m round open with enough time left? | ≥ 60s left (typical gate) | Do not enter; wait for next window |
| 2 | Is composite fresh (≤ 5s)? | Coinbase and/or Kraken in the composite | Ignore the signal until feeds refresh |
| 3 | Is chop a real move or a coin flip? | **REAL MOVE** (≥ 70) | **COIN FLIP** (< 40): skip; **MIXED**: size down or skip |
| 4 | Does lag support the side ahead of strike? | Composite − index points with the leader | Lag fights the leader — lower conviction |
| 5 | Is model edge positive on the favored side? | Edge > 0 after fee | No structural edge at the ask |
| 6 | Do all active strategy gates pass? | Every gate PASS on favored side | Fix the failing gate before manual entry |

**Plan verdict (flat):**

- All green + chop ≥ 70 → *If you trade manually:* small size on the favored side only; log chop at entry in your journal.
- Gates pass but chop mixed → Paper or skip.
- Chop coin flip → No new risk.
- Desk word stays **WAIT** (observe only) even when gates pass.

## When you are IN a trade

Ask in this order (first strong **EXIT NOW** wins):

| # | Question | Suggestion if yes |
|---|----------|-------------------|
| 1 | Loss ≥ 42% of cost? | **EXIT NOW** |
| 2 | Held bid ≥ 95¢ with > 45s left? | **EXIT NOW** (bank) |
| 3 | Still inside 75s entry grace? | **HOLD** |
| 4 | Wrong side of strike? | Consider **REVERSE** if other side ≥ 80%, ≥ 60s left, other ask ≤ 90¢; else **EXIT** if recover < 35% |
| 5 | Right side, in profit, but win prob < 55%? | **EXIT NOW** (thin cushion) |
| 6 | Strategy trail / breakeven / arb escape / hour stop? | **EXIT NOW** per active strategy sliders |

**Plan verdict (in trade):** Match the big **HOLD / REVERSE / WAIT / EXIT NOW** banner; the plan explains *why*.

## Journal habit

After any manual trade, note: asset, side, chop score at entry, and whether lag and taker flow agreed. Compare win rate when chop ≥ 70 vs chop < 40 in the journal header.

## Caveats

- Settlement is the **60s index average** before close; the model uses a driftless shortcut.
- BTC 15m edge after fees is often thin in public data — default to observe-only until your journal proves an edge.
