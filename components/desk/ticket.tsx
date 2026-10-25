"use client";

import { useEffect, useState } from "react";
import type { DeskSnapshot } from "@/lib/desk-types";
import type { Copy } from "@/lib/i18n";

function px(asset: string, n: number): string {
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: asset === "BTC" ? 2 : 4,
  });
}

function cents(p: number): string {
  const c = p * 100;
  return Number.isInteger(Math.round(c * 10) / 10) && Math.abs(c - Math.round(c)) < 0.05
    ? `${Math.round(c)}¢`
    : `${c.toFixed(1)}¢`;
}

export function Ticket({
  snap,
  t,
  asset,
  onAsset,
  upPrice,
  downPrice,
  spot,
  strike,
  onSide,
  onForce,
  notice,
}: {
  snap: DeskSnapshot;
  t: Copy;
  asset: "BTC" | "SOL";
  onAsset: (a: "BTC" | "SOL") => void;
  upPrice: number | null;
  downPrice: number | null;
  spot: number | null;
  strike: number | null;
  onSide: (side: "UP" | "DOWN") => void;
  onForce: (() => void) | null;
  notice: string | null;
}) {
  const market = snap.market;
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(id);
  }, []);
  const secs = market ? Math.max(0, Math.floor(market.closeTs - now / 1000)) : 0;
  const mm = String(Math.floor(secs / 60)).padStart(2, "0");
  const ss = String(secs % 60).padStart(2, "0");
  const target = market
    ? new Intl.DateTimeFormat("en-US", {
        timeZone: "America/New_York",
        hour: "numeric",
        minute: "2-digit",
      }).format(new Date(market.closeTs * 1000))
    : "—";
  const delta = spot != null && strike != null ? spot - strike : null;
  const closes = snap.candles.slice(-40).map((c) => c.close);
  const min = Math.min(...closes, spot ?? Infinity);
  const max = Math.max(...closes, spot ?? -Infinity);
  const span = max - min || 1;
  const pts = closes.map((c, i) => {
    const x = (i / Math.max(closes.length - 1, 1)) * 100;
    const y = 36 - ((c - min) / span) * 32;
    return `${x},${y}`;
  });

  return (
    <section className="gold-card px-3 py-3 sm:px-4">
      <div className="flex items-center gap-2">
        <span className="grid size-8 place-items-center rounded-full bg-[#f7931a] text-sm font-bold text-black">
          {asset === "BTC" ? "₿" : "◎"}
        </span>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h2 className="text-base font-semibold text-white">
              {asset} 15 min
            </h2>
            <span className="rounded-md bg-white/10 px-1.5 py-0.5 font-mono text-xs text-[#d5dbe8]">
              {market ? `${mm}:${ss}` : "--:--"}
            </span>
          </div>
          <p className="truncate text-[11px] text-[#8b93a7]">{market?.ticker ?? t.noMarket}</p>
        </div>
        <div className="ml-auto flex rounded-full bg-black/40 p-0.5 text-xs">
          {(["BTC", "SOL"] as const).map((a) => (
            <button
              key={a}
              type="button"
              className={`rounded-full px-2.5 py-1 ${asset === a ? "bg-[#e8c547] text-black" : "text-[#8b93a7]"}`}
              onClick={() => onAsset(a)}
            >
              {a}
            </button>
          ))}
        </div>
      </div>

      {market && spot != null && strike != null ? (
        <div className="mt-3 grid grid-cols-2 gap-3">
          <div>
            <p className="text-[11px] text-[#8b93a7]">
              {target} {t.target}
            </p>
            <p className="font-mono text-xl text-white sm:text-2xl">{px(asset, strike)}</p>
          </div>
          <div>
            <p className="text-[11px] text-[#8b93a7]">
              {t.now}{" "}
              <span className={delta != null && delta >= 0 ? "text-emerald-300" : "text-rose-300"}>
                {delta == null ? "" : `${delta >= 0 ? "▲" : "▼"} ${px(asset, Math.abs(delta))}`}
              </span>
            </p>
            <p className="font-mono text-xl text-white sm:text-2xl">{px(asset, spot)}</p>
          </div>
        </div>
      ) : (
        <p className="mt-3 text-sm text-[#8b93a7]">{t.noMarket}</p>
      )}

      {pts.length > 1 && (
        <svg viewBox="0 0 100 40" className="mt-2 h-16 w-full" role="img" aria-label="Recent path">
          <defs>
            <linearGradient id="spark" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#e8c547" stopOpacity="0.7" />
              <stop offset="100%" stopColor="#e8c547" stopOpacity="0" />
            </linearGradient>
          </defs>
          <polygon points={`0,40 ${pts.join(" ")} 100,40`} fill="url(#spark)" />
          <polyline points={pts.join(" ")} fill="none" stroke="#e8c547" strokeWidth="1.4" />
        </svg>
      )}

      <div className="mt-3 grid grid-cols-2 gap-2">
        <button
          type="button"
          disabled={upPrice == null}
          onClick={() => onSide("UP")}
          className="rounded-xl bg-[#1f8f5f] py-3 text-white shadow-inner transition hover:bg-[#26a56d] disabled:opacity-40"
        >
          <span className="block text-lg font-semibold">
            {t.upWord} {upPrice == null ? "—" : cents(upPrice)}
          </span>
          <span className="font-mono text-xs text-emerald-100/80">
            {upPrice && upPrice > 0 ? `${(1 / upPrice).toFixed(2)}x` : ""}
          </span>
        </button>
        <button
          type="button"
          disabled={downPrice == null}
          onClick={() => onSide("DOWN")}
          className="rounded-xl bg-[#e11d48] py-3 text-white shadow-inner transition hover:bg-[#f43f5e] disabled:opacity-40"
        >
          <span className="block text-lg font-semibold">
            {t.downWord} {downPrice == null ? "—" : cents(downPrice)}
          </span>
          <span className="font-mono text-xs text-rose-100/80">
            {downPrice && downPrice > 0 ? `${(1 / downPrice).toFixed(2)}x` : ""}
          </span>
        </button>
      </div>
      {notice && <p className="mt-2 text-center text-xs text-[#f3d78a]">{notice}</p>}
      {onForce && (
        <button type="button" className="mt-2 w-full text-center text-xs text-[#e8c547] underline" onClick={onForce}>
          {t.journalAnyway}
        </button>
      )}
      <p className="mt-3 text-center text-[10px] tracking-[0.25em] text-[#8b93a7]">◆ {t.paper}</p>
    </section>
  );
}
