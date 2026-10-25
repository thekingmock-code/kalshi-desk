"use client";

import type { DeskSnapshot } from "@/lib/desk-types";
import type { Copy } from "@/lib/i18n";

function money(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 10_000) return `$${(n / 1000).toFixed(0)}k`;
  return `$${n.toFixed(0)}`;
}

export function MeasureStrip({
  snap,
  t,
  leanUp,
  fairSide,
}: {
  snap: DeskSnapshot;
  t: Copy;
  leanUp: boolean | null;
  fairSide: number | null;
}) {
  const flow = snap.flow;
  const seal = leanUp == null ? flow.takerBuyPct : leanUp ? flow.takerBuyPct : 100 - flow.takerBuyPct;
  const closePct = fairSide == null ? null : fairSide * 100;
  const certain = closePct != null && closePct >= 80 && (snap.market ? snap.market.closeTs - Date.now() / 1000 < 180 : false);
  const marks = (snap.interval >= 60 ? snap.candles.slice(-12) : []).map((c) => {
    const upBar = c.close >= c.open;
    const agree = leanUp == null ? upBar : leanUp ? upBar : !upBar;
    return agree;
  });

  return (
    <section className="gold-card px-3 py-3 sm:px-4">
      <p className="font-mono text-[12px] leading-relaxed text-[#c5cedd]">
        <span className="text-[#8b93a7]">{t.measured}:</span> {t.atSeal}{" "}
        <span className="text-[#f3d78a]">{seal.toFixed(0)}%</span>
        {flow.trades ? ` (${flow.trades.toLocaleString()})` : ""} · {t.atClose}{" "}
        <span className="text-[#f3d78a]">{closePct == null ? "—" : `${closePct.toFixed(0)}%`}</span>{" "}
        <span className="text-[#8b93a7]">({certain ? t.nearCertain : t.modelEstimate})</span>
      </p>
      {marks.length > 0 && (
        <p className="mt-1 font-mono text-sm tracking-widest" aria-label="Recent minute agreement">
          {marks.map((ok, i) => (
            <span key={i} className={ok ? "text-emerald-400" : "text-rose-400"}>
              {ok ? "✓" : "×"}
            </span>
          ))}
        </p>
      )}
      <p className="mt-2 font-mono text-[12px] text-[#d5dbe8]">
        {money(flow.buyUsd)} {t.bought} · {flow.buyBase.toFixed(snap.asset === "BTC" ? 2 : 1)} {snap.asset} ·{" "}
        {money(flow.sellUsd)} {t.sold} · {flow.sellBase.toFixed(snap.asset === "BTC" ? 2 : 1)} {snap.asset} ·{" "}
        {flow.trades.toLocaleString()} {t.trades}
      </p>
      {flow.partial && <p className="mt-1 text-[11px] text-[#8b93a7]">{t.partialTape}</p>}
      <p className="mt-2 text-[12px] leading-relaxed text-[#8b93a7]">{t.cushionCopy}</p>
    </section>
  );
}
