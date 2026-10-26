# 15m suggestion plan (use beside the desk)

Keep this open on paper, Notes, or a second screen while you watch the dashboard. Map each answer to what you see on the desk (tabs, trade card, chop meter, gates, big suggestion).

The desk is **observe-only** — it will say **WAIT** when flat even if gates pass. This plan is for **your** decisions if you trade manually on Kalshi.

---

## A. Before every round (30 seconds)

| Question | Look at | If yes | If no |
|----------|---------|--------|-------|
| Is there an open 15m market with **≥ 60s** left? | Tab timer | Continue | **Skip** — wait for next window |
| Is **composite age ≤ 5s** (both feeds if possible)? | Trade card · composite line | Trust spot | **Skip** — stale data |
| Is **Kalshi index** showing (not blank)? | Index line | Use lag | Lag unknown — treat chop lag as neutral |
| Am I in **observe-only** mode on purpose? | Banner / your rule | No size until journal proves edge | — |

**Suggestion:** Default **no trade** on BTC until your journal shows positive net P&L over 20+ logged decisions.

---

## B. Flat — should I even consider entering?

Work top to bottom. **Any “stop” row → WAIT.**

| # | Question | Dashboard signal | Stop → WAIT | Go deeper → |
|---|----------|------------------|-------------|-------------|
| 1 | **Chop ≥ 70** (REAL MOVE)? | Chop meter label | **COIN FLIP** (< 40) | Mixed (40–69): half size max |
| 2 | **Favored side** has **positive edge** after fees? | Reasons under WAIT · edge line | Edge ≤ 0 | Note UP vs DOWN |
| 3 | **All gates PASS** on that side? | Strategy · UP/YES or DOWN/NO column | Any FAIL | Match active strategy tab |
| 4 | **Taker buy %** supports that side? | Trade card · taker buy | Flow against you (< 58% for 15m Gates) | — |
| 5 | **Momentum** same sign as favored side? | Momentum line | Against or flat | — |
| 6 | **Lag** (composite − index) points with **leader vs strike**? | Lag + strike vs composite | Lag fights leader | Skip if index missing |
| 7 | **Ask ≤ price cap** for strategy? | Gates · price cap | Above cap | — |
| 8 | **Vol ratio ≤ 2×** baseline (15m Gates)? | Vol vs baseline | Hot vol | Widen pad mentally for arb |

**Suggestions (flat):**

- All pass + chop ≥ 70 + edge ≥ **2¢** → *Highest tier watchlist* — still **WAIT** on desk; you may paper or tiny manual size **once per round**.
- Gates pass but chop mixed → **Paper only** or skip.
- Chop coin flip → **No entry**.
- Sub-25¢ scanner strategy → **Log only**, never size up because gates passed.

---

## C. In a trade — what should I do?

Use the **big suggestion** first. Then this checklist confirms it.

| Priority | Question | Typical desk read | Suggestion |
|----------|----------|-------------------|------------|
| 1 | Loss ≥ **42%** of cost? | P&L red, EXIT NOW | **Exit** at bid |
| 2 | Held bid ≥ **95¢** and **> 45s** left? | EXIT NOW · bank | **Exit** — don’t be greedy |
| 3 | **< 75s** since entry? | HOLD · grace | **Hold** — no flip |
| 4 | **WRONG** vs strike? | Red RIGHT/WRONG banner | See 4a / 4b |
| 4a | Other side ≥ **80%**, ≥ **60s** left, other ask ≤ **90¢**? | REVERSE (blue) | **Consider reverse** manually |
| 4b | Recover prob **< 35%**? | EXIT NOW | **Exit** |
| 5 | **RIGHT**, in profit, but held-side prob **< 55%**? | EXIT NOW · thin cushion | **Take profit** |
| 6 | Strategy trail / breakeven / arb escape / hour stop? | Extra reason line | **Exit** per strategy tab |

**Suggestions (in trade):**

- Green P&L + HOLD + chop was ≥ 70 at entry → let it work unless rule 2 or 5 fires.
- WRONG + REVERSE → only reverse if you accept double fees and size limits; else exit.
- RIGHT banner but chop at entry was < 40 → treat as lucky; **exit** on first profit rule.

---

## D. Per asset (quick bias)

| Asset | Extra question | Suggestion |
|-------|----------------|------------|
| **BTC** | Is edge ≥ 2¢ *after* fee on a **≤ 65¢** ask? | If not, **WAIT** — public data says BTC 15m edge is thin |
| **BNB** | Single-feed flag on composite? | Require **chop ≥ 70** and all gates; else skip |
| **SOL** | Using **SOL 15m** strategy tab? | Band **35–55¢**, ≥ **120s** left, trend + momentum both required |

---

## E. After the round (journal)

| Question | Suggestion |
|----------|------------|
| Did I log **chop at entry**? | Required — compare win rate chop ≥ 70 vs < 40 in journal header |
| Was I **RIGHT/WRONG** vs settlement line? | Tag manual notes; desk auto-settle is for open positions only |
| Did I break my size rule? | If yes, next round **observe only** |

---

## F. One-line decision tree

```
FLAT → chop < 40? → WAIT
     → chop ok but gates fail? → WAIT
     → gates pass + chop ≥ 70 + edge > 0? → optional tiny manual / paper
IN TRADE → match EXIT / REVERSE / HOLD banner
         → when unsure, exit if WRONG or loss ≥ 42%
```

---

## G. Questions to ask yourself (not on screen)

1. **Am I trading because of FOMO or because gates + chop aligned?**
2. **Would I take this trade if the desk were offline?**
3. **Is this my first trade this hour** (1h strategy = one entry per UTC hour)?
4. **Did I revoke and rotate API keys** if they ever leaked into chat?

Copy/edit this file for your own rules. Thresholds match `desk/config.yaml`.
