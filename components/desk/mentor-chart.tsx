"use client";

import { useEffect, useRef } from "react";
import type { IChartApi, ISeriesApi, ISeriesMarkersPluginApi, SeriesType, Time, UTCTimestamp } from "lightweight-charts";
import type { DeskSnapshot } from "@/lib/desk-types";
import type { Copy } from "@/lib/i18n";
import { bollinger, detectPattern, ema, vwapFrom } from "@/lib/math";

export type Toggles = {
  ema: boolean;
  bands: boolean;
  vwap: boolean;
  levels: boolean;
  cone: boolean;
  markers: boolean;
  labels: boolean;
  lane: boolean;
};

export const DEFAULT_TOGGLES: Toggles = {
  ema: true,
  bands: true,
  vwap: true,
  levels: true,
  cone: true,
  markers: true,
  labels: true,
  lane: true,
};

const INTERVALS: { secs: number; label: string }[] = [
  { secs: 15, label: "15s" },
  { secs: 30, label: "30s" },
  { secs: 45, label: "45s" },
  { secs: 60, label: "1m" },
  { secs: 180, label: "3m" },
  { secs: 300, label: "5m" },
];

type SeriesBag = {
  chart: IChartApi;
  candles: ISeriesApi<"Candlestick", Time>;
  emaF: ISeriesApi<"Line", Time>;
  emaS: ISeriesApi<"Line", Time>;
  upper: ISeriesApi<"Line", Time>;
  lower: ISeriesApi<"Line", Time>;
  vwap: ISeriesApi<"Line", Time>;
  coneU: ISeriesApi<"Line", Time>;
  coneL: ISeriesApi<"Line", Time>;
  lane: ISeriesApi<"Line", Time>;
  osc: ISeriesApi<"Line", Time>;
  markers: ISeriesMarkersPluginApi<Time>;
};

function utc(t: number): UTCTimestamp {
  return t as UTCTimestamp;
}

function formatEt(time: Time): string {
  const sec = typeof time === "number" ? time : 0;
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(sec * 1000));
}

export function MentorChart({
  snap,
  interval,
  onInterval,
  toggles,
  onToggle,
  t,
  leanUp,
  fairSide,
  edgeDollars,
  contracts,
  strength,
}: {
  snap: DeskSnapshot | null;
  interval: number;
  onInterval: (n: number) => void;
  toggles: Toggles;
  onToggle: (k: keyof Toggles) => void;
  t: Copy;
  leanUp: boolean | null;
  fairSide: number | null;
  edgeDollars: number | null;
  contracts: number;
  strength: string;
}) {
  const host = useRef<HTMLDivElement>(null);
  const bag = useRef<SeriesBag | null>(null);
  const propsRef = useRef({ snap, toggles, interval });
  propsRef.current = { snap, toggles, interval };

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let dead = false;
    let chart: IChartApi | null = null;

    (async () => {
      const lc = await import("lightweight-charts");
      if (dead || !host.current) return;
      chart = lc.createChart(host.current, {
        autoSize: true,
        layout: {
          background: { type: lc.ColorType.Solid, color: "transparent" },
          textColor: "#8b93a7",
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          fontSize: 11,
        },
        grid: {
          vertLines: { color: "rgba(255,255,255,0.04)" },
          horzLines: { color: "rgba(255,255,255,0.05)" },
        },
        rightPriceScale: { borderColor: "rgba(232,197,71,0.15)" },
        localization: {
          timeFormatter: (time: Time) => formatEt(time),
        },
        timeScale: {
          borderColor: "rgba(232,197,71,0.15)",
          timeVisible: true,
          secondsVisible: false,
          rightOffset: 4,
          tickMarkFormatter: (time: Time) => formatEt(time),
        },
        crosshair: { mode: lc.CrosshairMode.Normal },
        handleScroll: {
          mouseWheel: true,
          pressedMouseMove: true,
          horzTouchDrag: true,
          vertTouchDrag: false,
        },
        handleScale: {
          mouseWheel: true,
          pinch: true,
          axisPressedMouseMove: true,
        },
      });
      const candles = chart.addSeries(lc.CandlestickSeries, {
        upColor: "#3ddc97",
        downColor: "#ff5d73",
        borderUpColor: "#3ddc97",
        borderDownColor: "#ff5d73",
        wickUpColor: "#9ff0cb",
        wickDownColor: "#ff9aab",
      });
      const line = (color: string, width: 1 | 2 | 3 | 4 = 2) =>
        chart!.addSeries(lc.LineSeries, {
          color,
          lineWidth: width,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
      const emaF = line("#c084fc", 2);
      const emaS = line("#7dd3fc", 2);
      const upper = line("rgba(56,189,248,0.55)", 1);
      const lower = line("rgba(56,189,248,0.55)", 1);
      const vwap = line("#e8c547", 2);
      const coneU = line("rgba(232,197,71,0.45)", 1);
      const coneL = line("rgba(232,197,71,0.45)", 1);
      const lane = line("rgba(61,220,151,0.85)", 1);
      const osc = chart.addSeries(
        lc.LineSeries,
        {
          color: "#e8c547",
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
        },
        1,
      );
      chart.panes()[1]?.setStretchFactor(0.18);
      const markers = lc.createSeriesMarkers(candles, []);
      bag.current = { chart, candles, emaF, emaS, upper, lower, vwap, coneU, coneL, lane, osc, markers };
      draw();
    })();

    return () => {
      dead = true;
      chart?.remove();
      bag.current = null;
    };
  }, []);

  useEffect(() => {
    draw();
  }, [snap, toggles, interval]);

  function draw() {
    const api = bag.current;
    const { snap: data, toggles: tg, interval: iv } = propsRef.current;
    if (!api || !data) return;
    const candles = data.candles;
    api.chart.applyOptions({ timeScale: { secondsVisible: iv < 60 } });
    api.candles.setData(
      candles.map((c) => ({
        time: utc(c.time),
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      })),
    );
    const closes = candles.map((c) => c.close);
    const fast = ema(closes, 8);
    const slow = ema(closes, 21);
    const bands = bollinger(closes, 20, 2);
    const vw = vwapFrom(candles, data.market?.openTs ?? null);
    const toLine = (arr: (number | null)[]) =>
      candles.flatMap((c, i) => (arr[i] == null ? [] : [{ time: utc(c.time), value: arr[i] as number }]));

    api.emaF.applyOptions({ visible: tg.ema });
    api.emaS.applyOptions({ visible: tg.ema });
    api.emaF.setData(tg.ema ? toLine(fast) : []);
    api.emaS.setData(tg.ema ? toLine(slow) : []);
    api.upper.applyOptions({ visible: tg.bands });
    api.lower.applyOptions({ visible: tg.bands });
    api.upper.setData(tg.bands ? toLine(bands.upper) : []);
    api.lower.setData(tg.bands ? toLine(bands.lower) : []);
    api.vwap.applyOptions({ visible: tg.vwap });
    api.vwap.setData(tg.vwap ? toLine(vw) : []);
    api.lane.applyOptions({ visible: tg.lane });
    api.lane.setData(tg.lane ? candles.map((c, i) => ({ time: utc(c.time), value: closes[i] })) : []);

    const last = candles[candles.length - 1];
    if (tg.cone && last && data.sigmaPerSec) {
      const coneU: { time: UTCTimestamp; value: number }[] = [];
      const coneL: { time: UTCTimestamp; value: number }[] = [];
      for (let i = 0; i <= 8; i++) {
        const dt = i * Math.max(iv, 15);
        const sig = data.sigmaPerSec * Math.sqrt(Math.max(dt, 1));
        coneU.push({ time: utc(last.time + dt), value: last.close * Math.exp(sig) });
        coneL.push({ time: utc(last.time + dt), value: last.close * Math.exp(-sig) });
      }
      api.coneU.setData(coneU);
      api.coneL.setData(coneL);
    } else {
      api.coneU.setData([]);
      api.coneL.setData([]);
    }

    api.candles.applyOptions({
      lastValueVisible: tg.labels,
      priceLineVisible: tg.labels,
    });

    const priceLines = (api.candles as ISeriesApi<SeriesType, Time> & {
      __lines?: { id: unknown }[];
    });
    // Price lines are recreated below via a stable list stored on the series object.
    const prev = (api.candles as unknown as { __pl?: ReturnType<ISeriesApi<"Candlestick">["createPriceLine"]>[] }).__pl ?? [];
    for (const line of prev) api.candles.removePriceLine(line);
    const next: ReturnType<ISeriesApi<"Candlestick">["createPriceLine"]>[] = [];
    if (tg.levels && data.market) {
      next.push(
        api.candles.createPriceLine({
          price: data.market.strike,
          color: "#e8c547",
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: true,
          title: "strike",
        }),
      );
      const openBar = candles.find((c) => c.time >= data.market!.openTs);
      if (openBar) {
        next.push(
          api.candles.createPriceLine({
            price: openBar.open,
            color: "rgba(255,255,255,0.35)",
            lineWidth: 1,
            lineStyle: 2,
            axisLabelVisible: false,
            title: "open",
          }),
        );
      }
    }
    (api.candles as unknown as { __pl?: typeof next }).__pl = next;
    void priceLines;

    const marks: {
      time: UTCTimestamp;
      position: "aboveBar" | "belowBar";
      color: string;
      shape: "circle";
    }[] = [];
    if (tg.markers) {
      for (let i = 1; i < fast.length; i++) {
        const prevDiff = fast[i - 1] - slow[i - 1];
        const diff = fast[i] - slow[i];
        if (prevDiff <= 0 && diff > 0) {
          marks.push({ time: utc(candles[i].time), position: "belowBar", color: "#3ddc97", shape: "circle" });
        } else if (prevDiff >= 0 && diff < 0) {
          marks.push({ time: utc(candles[i].time), position: "aboveBar", color: "#ff5d73", shape: "circle" });
        }
      }
    }
    api.markers.setMarkers(marks.slice(-14));

    const oscData = candles.flatMap((c, i) => {
      if (!fast[i]) return [];
      return [{ time: utc(c.time), value: ((closes[i] - fast[i]) / closes[i]) * 100 }];
    });
    api.osc.setData(oscData);
  }

  function zoom(dir: number) {
    const chart = bag.current?.chart;
    if (!chart) return;
    const range = chart.timeScale().getVisibleLogicalRange();
    if (!range) return;
    const span = range.to - range.from;
    const next = Math.max(12, span * (dir > 0 ? 0.72 : 1.35));
    const mid = (range.from + range.to) / 2;
    chart.timeScale().setVisibleLogicalRange({ from: mid - next / 2, to: mid + next / 2 });
  }

  const candles = snap?.candles ?? [];
  const pattern = detectPattern(candles);
  const patternLabel = pattern.key === "bullEngulf" ? t.bullEngulf : pattern.key === "bearEngulf" ? t.bearEngulf : t.noPattern;
  const closes = candles.map((c) => c.close);
  const fast = ema(closes, 8);
  const slow = ema(closes, 21);
  const vw = vwapFrom(candles, snap?.market?.openTs ?? null);
  const last = closes.length - 1;
  const trendUp = last >= 0 && fast[last] >= slow[last];
  const above = last >= 0 && vw[last] != null && closes[last] >= (vw[last] as number);
  const confirms = leanUp == null ? true : trendUp === leanUp;
  const mentor = !confirms ? t.mentorMixed : trendUp ? t.mentorUp : t.mentorDown;
  const pct = fairSide == null ? null : Math.round(fairSide * 100);
  const other = pct == null ? null : 100 - pct;

  return (
    <section className="gold-card overflow-hidden">
      <header className="flex items-start justify-between gap-3 border-b border-[rgba(232,197,71,0.18)] px-3 py-3 sm:px-4">
        <div className="min-w-0">
          <h2 className="font-heading text-[13px] leading-tight font-semibold tracking-wide text-[#f3d78a] sm:text-sm">
            <span className="mr-1" aria-hidden>♛</span>
            {t.mentorTitle}
          </h2>
        </div>
        <p className="hidden max-w-[14rem] text-right text-[10px] leading-snug text-[#8b93a7] sm:block">{t.mentorSub}</p>
      </header>

      <div className="flex flex-wrap items-center gap-2 px-3 pt-3 sm:px-4">
        <span className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${leanUp ? "bg-emerald-400/15 text-emerald-300" : "bg-rose-400/15 text-rose-300"}`}>
          {leanUp == null ? "—" : `${t.roundLeans} ${leanUp ? t.up : t.down}`}
          {edgeDollars != null && (
            <>
              {" "}
              {edgeDollars >= 0 ? "+" : "−"}${Math.abs(edgeDollars).toFixed(2)} {t.modelEdge}
            </>
          )}
          {" · "}
          {strength}
          {pct != null ? ` · ${pct}%` : ""} ({t.onContracts} {contracts} {t.contracts}
          {snap?.flow.trades ? ` · n=${snap.flow.trades.toLocaleString()}` : ""})
        </span>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-1.5 px-3 sm:px-4">
        <button type="button" className="chip" onClick={() => zoom(-1)} aria-label="Zoom out">−</button>
        <button type="button" className="chip" onClick={() => zoom(1)} aria-label="Zoom in">+</button>
        <button type="button" className="chip" onClick={() => bag.current?.chart.timeScale().fitContent()} aria-label="Reset zoom">⟳</button>
        <span className="ml-1 text-[11px] text-[#8b93a7]">
          {candles.length} {t.candles} · {t.zoomHint}
        </span>
        <div className="ml-auto flex flex-wrap gap-1">
          {INTERVALS.map((it) => (
            <button
              key={it.secs}
              type="button"
              className={`chip ${interval === it.secs ? "chip-on" : ""}`}
              onClick={() => onInterval(it.secs)}
            >
              {it.label}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-2 flex flex-wrap gap-1 px-3 sm:px-4">
        {(Object.keys(DEFAULT_TOGGLES) as (keyof Toggles)[]).map((key) => (
          <button
            key={key}
            type="button"
            className={`chip ${toggles[key] ? "chip-gold" : ""}`}
            onClick={() => onToggle(key)}
            aria-pressed={toggles[key]}
          >
            {key}
          </button>
        ))}
      </div>

      <div className="relative mx-2 mt-2 h-[260px] sm:mx-3 sm:h-[340px]">
        <div ref={host} className="absolute inset-0" />
        {!candles.length && (
          <div className="pointer-events-none absolute inset-0 grid place-items-center text-sm text-[#8b93a7]">
            {t.waitingChart}
          </div>
        )}
      </div>

      <footer className="space-y-2 px-3 py-3 sm:px-4">
        <div className="flex items-center gap-3">
          <span className="text-sm text-[#d7deea]">{patternLabel}</span>
          <div className="flex h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-white/5" aria-hidden>
            <div className="h-full bg-emerald-400" style={{ width: `${pct ?? 50}%` }} />
            <div className="h-full bg-rose-400" style={{ width: `${other ?? 50}%` }} />
          </div>
          <span className="font-mono text-xs text-emerald-300">{pct ?? "—"}%</span>
          <span className="font-mono text-xs text-rose-300">{other ?? "—"}%</span>
        </div>
        <p className="text-[12px] leading-relaxed text-[#9aa3b5]">
          <span className="text-[#e8c547]">♛ </span>
          {mentor}
          {last >= 0 && vw[last] != null ? ` · ${above ? t.aboveVwap : t.belowVwap}` : ""}
        </p>
      </footer>
    </section>
  );
}
