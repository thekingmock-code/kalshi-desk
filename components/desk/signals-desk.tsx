"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Menu } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import type { Asset, DeskSnapshot } from "@/lib/desk-types";
import { fairProbAbove, kalshiFee } from "@/lib/math";
import { copy, type Lang } from "@/lib/i18n";
import { MeasureStrip } from "./measure-strip";
import { DEFAULT_TOGGLES, MentorChart, type Toggles } from "./mentor-chart";
import { StrategyLab, type ExitState, type Field, type GateState } from "./strategy-lab";
import { Ticket } from "./ticket";
import type { JournalEntry } from "./types";

const EMPTY_FLOW = {
  buyUsd: 0,
  sellUsd: 0,
  buyBase: 0,
  sellBase: 0,
  trades: 0,
  takerBuyPct: 50,
  fromTs: null,
  toTs: null,
  partial: false,
};

function blank(text = ""): Field {
  return { text, linked: true };
}

function parseField(field: Field, live: number | null): number | null {
  if (field.linked) return live;
  const n = Number(field.text);
  return Number.isFinite(n) ? n : live;
}

function fmt(n: number | null, digits = 2): string {
  if (n == null || !Number.isFinite(n)) return "";
  return n.toFixed(digits);
}

export function SignalsDesk() {
  const [lang, setLang] = useState<Lang>("en");
  const [asset, setAsset] = useState<Asset>("BTC");
  const [interval, setInterval] = useState(60);
  const [snap, setSnap] = useState<DeskSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [menu, setMenu] = useState(false);
  const [toggles, setToggles] = useState<Toggles>(DEFAULT_TOGGLES);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingSide, setPendingSide] = useState<"UP" | "DOWN" | null>(null);
  const [fields, setFields] = useState<Record<string, Field>>({
    contracts: { text: "10", linked: false },
    strike: blank(),
    spot: blank(),
    index: blank(),
    move: blank(),
    up: blank(),
    down: blank(),
    taker: blank(),
    vol: blank(),
  });
  const [gates, setGates] = useState<GateState>({
    edge: true,
    edgeCents: 5,
    cushion: false,
    cushionMult: 1,
    momentum: false,
  });
  const [exits, setExits] = useState<ExitState>({ tp: 8, sl: 8, flatten: 120 });
  const [journal, setJournal] = useState<JournalEntry[]>([]);
  const [ready, setReady] = useState(false);

  const t = copy(lang);

  useEffect(() => {
    try {
      const raw = localStorage.getItem("xvantage-journal");
      if (raw) setJournal(JSON.parse(raw) as JournalEntry[]);
      const g = localStorage.getItem("xvantage-gates");
      if (g) setGates(JSON.parse(g) as GateState);
      const e = localStorage.getItem("xvantage-exits");
      if (e) setExits(JSON.parse(e) as ExitState);
      const l = localStorage.getItem("xvantage-lang");
      if (l === "es" || l === "en") setLang(l);
    } catch {
      /* ignore broken local storage */
    }
    setReady(true);
  }, []);

  useEffect(() => {
    if (!ready) return;
    localStorage.setItem("xvantage-journal", JSON.stringify(journal));
    localStorage.setItem("xvantage-gates", JSON.stringify(gates));
    localStorage.setItem("xvantage-exits", JSON.stringify(exits));
    localStorage.setItem("xvantage-lang", lang);
  }, [journal, gates, exits, lang, ready]);

  const load = useCallback(async () => {
    try {
      const res = await fetch(`/api/desk?asset=${asset}&interval=${interval}`, { cache: "no-store" });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error || t.failed);
      setSnap(body as DeskSnapshot);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : t.failed);
    } finally {
      setLoading(false);
    }
  }, [asset, interval, t.failed]);

  useEffect(() => {
    setLoading(true);
    void load();
    const id = window.setInterval(() => {
      void load();
    }, 2000);
    return () => window.clearInterval(id);
  }, [load]);

  useEffect(() => {
    if (!snap) return;
    setFields((prev) => {
      const next = { ...prev };
      const live: Record<string, string> = {
        strike: fmt(snap.market?.strike ?? null, 2),
        spot: fmt(snap.spot, snap.asset === "BTC" ? 2 : 4),
        index: fmt(snap.index, snap.asset === "BTC" ? 2 : 4),
        move: fmt(snap.typicalMove, snap.asset === "BTC" ? 2 : 4),
        up: snap.market ? fmt(snap.market.yesAsk * 100, 1) : "",
        down: snap.market ? fmt(snap.market.noAsk * 100, 1) : "",
        taker: fmt(snap.flow.takerBuyPct, 1),
        vol: fmt(snap.volRatio, 2),
      };
      for (const [k, text] of Object.entries(live)) {
        if (next[k]?.linked) next[k] = { text, linked: true };
      }
      return next;
    });
  }, [snap]);

  const view = useMemo(() => {
    const strike = parseField(fields.strike, snap?.market?.strike ?? null);
    const spot = parseField(fields.spot, snap?.spot ?? null);
    const index = parseField(fields.index, snap?.index ?? null);
    const move = parseField(fields.move, snap?.typicalMove ?? null);
    const upCents = parseField(fields.up, snap?.market ? snap.market.yesAsk * 100 : null);
    const downCents = parseField(fields.down, snap?.market ? snap.market.noAsk * 100 : null);
    const taker = parseField(fields.taker, snap?.flow.takerBuyPct ?? null);
    const contracts = Math.max(1, Math.round(parseField(fields.contracts, 10) ?? 10));
    const mark = index ?? spot;
    const secsLeft = snap?.market ? Math.max(snap.market.closeTs - Date.now() / 1000, 1) : null;
    const fairYes =
      mark && strike && snap?.sigmaPerSec && secsLeft
        ? fairProbAbove(mark, strike, secsLeft, snap.sigmaPerSec).prob
        : (snap?.fairYes ?? null);
    const up = upCents == null ? null : upCents / 100;
    const down = downCents == null ? null : downCents / 100;
    let edgeYes = snap?.edgeYes ?? null;
    let edgeNo = snap?.edgeNo ?? null;
    if (fairYes != null && up != null) edgeYes = fairYes - up - kalshiFee(up);
    if (fairYes != null && down != null) edgeNo = 1 - fairYes - down - kalshiFee(down);
    const leanUp = fairYes == null ? null : fairYes >= 0.5;
    const fairSide = fairYes == null ? null : leanUp ? fairYes : 1 - fairYes;
    const edge = leanUp ? edgeYes : edgeNo;
    const edgeDollars = edge == null ? null : edge * contracts;
    const strength =
      fairSide == null ? "—" : fairSide >= 0.65 && (edge ?? 0) >= 0.03 ? t.strong : fairSide >= 0.55 ? t.lean : t.coinFlip;
    return {
      strike,
      spot,
      index,
      move,
      taker,
      contracts,
      up,
      down,
      fairYes,
      edgeYes,
      edgeNo,
      leanUp,
      fairSide,
      edgeDollars,
      strength,
      mark,
    };
  }, [fields, snap, t]);

  function setField(key: string, text: string) {
    setFields((prev) => ({ ...prev, [key]: { text, linked: false } }));
  }

  function resetLive() {
    setFields((prev) => {
      const next = { ...prev };
      for (const key of Object.keys(next)) {
        if (key === "contracts") continue;
        next[key] = { ...next[key], linked: true };
      }
      return next;
    });
  }

  function gateFails(side: "UP" | "DOWN"): string[] {
    const fails: string[] = [];
    const ask = side === "UP" ? view.up : view.down;
    const fair = view.fairYes == null ? null : side === "UP" ? view.fairYes : 1 - view.fairYes;
    const edge = side === "UP" ? view.edgeYes : view.edgeNo;
    if (gates.edge && (edge == null || edge * 100 < gates.edgeCents)) {
      fails.push(`${t.gateEdge}: ${edge == null ? "—" : (edge * 100).toFixed(1)}¢`);
    }
    if (gates.cushion && view.spot != null && view.strike != null && view.move) {
      const dir = side === "UP" ? view.spot - view.strike : view.strike - view.spot;
      const mult = dir / view.move;
      if (mult < gates.cushionMult) fails.push(`${t.gateCushion}: ${mult.toFixed(2)}×`);
    }
    if (gates.momentum && view.taker != null) {
      if (side === "UP" && view.taker < 50) fails.push(`${t.gateMom}: ${view.taker.toFixed(0)}%`);
      if (side === "DOWN" && view.taker > 50) fails.push(`${t.gateMom}: ${view.taker.toFixed(0)}%`);
    }
    void ask;
    void fair;
    return fails;
  }

  function journalSide(side: "UP" | "DOWN", force = false) {
    if (!snap?.market || view.up == null || view.down == null || view.spot == null || view.strike == null || view.fairYes == null) {
      setNotice(t.noMarket);
      return;
    }
    const fails = gateFails(side);
    if (fails.length && !force) {
      setPendingSide(side);
      setNotice(`${t.blocked}: ${fails.join(" · ")}`);
      return;
    }
    setPendingSide(null);
    const ask = side === "UP" ? view.up : view.down;
    const fair = side === "UP" ? view.fairYes : 1 - view.fairYes;
    const edge = fair - ask - kalshiFee(ask);
    const entry: JournalEntry = {
      id: crypto.randomUUID(),
      ts: Date.now(),
      asset,
      ticker: snap.market.ticker,
      side,
      ask,
      contracts: view.contracts,
      spot: view.mark ?? view.spot,
      strike: view.strike,
      fair,
      edge,
      note: fails.length ? fails.join(" · ") : "",
      closed: false,
      pnl: 0,
    };
    setJournal((rows) => [entry, ...rows].slice(0, 40));
    setNotice(`${t.logged} · ${side} ${(ask * 100).toFixed(1)}¢`);
  }

  function flatten(id: string) {
    setJournal((rows) =>
      rows.map((row) => {
        if (row.id !== id || row.closed) return row;
        const mark = row.side === "UP" ? (snap?.market?.yesBid ?? view.up) : (snap?.market?.noBid ?? view.down);
        const exitAsk = mark ?? row.ask;
        const pnl = (exitAsk - row.ask) * row.contracts;
        return { ...row, closed: true, exitAsk, pnl };
      }),
    );
  }

  const openNotes = journal.filter((j) => !j.closed && j.asset === asset);
  const exitNote = openNotes
    .map((j) => {
      const mark = j.side === "UP" ? snap?.market?.yesBid : snap?.market?.noBid;
      if (mark == null || snap?.market == null) return null;
      const cents = (mark - j.ask) * 100;
      const secs = snap.market.closeTs - Date.now() / 1000;
      if (cents >= exits.tp || cents <= -exits.sl || secs <= exits.flatten) return `${t.exitHit}: ${j.side} ${cents.toFixed(1)}¢`;
      return null;
    })
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="desk-bg min-h-dvh text-[#e8edf5]">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-3 px-3 py-3 pb-52 sm:px-4 sm:py-5 xl:pb-5">
        <header className="flex items-center gap-3">
          <div className="flex items-end gap-2">
            <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden>
              <rect x="2" y="10" width="3" height="8" fill="#3ddc97" />
              <rect x="8" y="4" width="3" height="14" fill="#e8c547" />
              <rect x="14" y="7" width="3" height="11" fill="#ff5d73" />
            </svg>
            <div>
              <p className="text-[11px] tracking-[0.22em] text-[#e8c547]">XVANTAGE // {t.signals}</p>
            </div>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <div className="flex rounded-full bg-black/40 p-0.5 text-xs">
              {(["en", "es"] as const).map((code) => (
                <button
                  key={code}
                  type="button"
                  className={`rounded-full px-2 py-1 uppercase ${lang === code ? "bg-[#e8c547] text-black" : "text-[#8b93a7]"}`}
                  onClick={() => setLang(code)}
                >
                  {code}
                </button>
              ))}
            </div>
            <Button variant="ghost" size="icon" className="text-[#e8c547]" onClick={() => setMenu(true)} aria-label="Menu">
              <Menu />
            </Button>
          </div>
        </header>

        {loading && !snap ? (
          <div className="gold-card grid h-48 place-items-center text-sm text-[#8b93a7]">{t.loading}</div>
        ) : error && !snap ? (
          <div className="gold-card space-y-3 px-4 py-8 text-center">
            <p className="text-rose-300">{t.failed}</p>
            <p className="text-xs text-[#8b93a7]">{error}</p>
            <Button onClick={() => void load()}>{t.retry}</Button>
          </div>
        ) : (
          <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_22rem]">
            <div className="contents xl:flex xl:flex-col xl:gap-3">
              {snap && (
                <MeasureStrip snap={snap} t={t} leanUp={view.leanUp} fairSide={view.fairSide} />
              )}
              <MentorChart
                snap={snap}
                interval={interval}
                onInterval={setInterval}
                toggles={toggles}
                onToggle={(k) => setToggles((prev) => ({ ...prev, [k]: !prev[k] }))}
                t={t}
                leanUp={view.leanUp}
                fairSide={view.fairSide}
                edgeDollars={view.edgeDollars}
                contracts={view.contracts}
                strength={view.strength}
              />
              {snap && (
                <div className="hidden xl:block">
                  <Ticket
                    snap={{ ...snap, flow: snap.flow ?? EMPTY_FLOW }}
                    t={t}
                    asset={asset}
                    onAsset={setAsset}
                    upPrice={view.up}
                    downPrice={view.down}
                    spot={view.spot}
                    strike={view.strike}
                    onSide={(side) => journalSide(side, false)}
                    onForce={pendingSide ? () => journalSide(pendingSide, true) : null}
                    notice={[notice, exitNote].filter(Boolean).join(" · ") || null}
                  />
                </div>
              )}
            </div>
            <StrategyLab
              t={t}
              fields={fields}
              setField={setField}
              gates={gates}
              setGates={setGates}
              exits={exits}
              setExits={setExits}
              journal={journal}
              onFlatten={flatten}
              onReset={resetLive}
              asset={asset}
            />
          </div>
        )}
        {snap?.warning && <p className="text-center text-[11px] text-amber-200/80">{snap.warning}</p>}
      </div>
      {snap && (
        <div className="fixed inset-x-0 bottom-0 z-40 xl:hidden">
          <Ticket
            variant="dock"
            snap={{ ...snap, flow: snap.flow ?? EMPTY_FLOW }}
            t={t}
            asset={asset}
            onAsset={setAsset}
            upPrice={view.up}
            downPrice={view.down}
            spot={view.spot}
            strike={view.strike}
            onSide={(side) => journalSide(side, false)}
            onForce={pendingSide ? () => journalSide(pendingSide, true) : null}
            notice={[notice, exitNote].filter(Boolean).join(" · ") || null}
          />
        </div>
      )}

      <Sheet open={menu} onOpenChange={setMenu}>
        <SheetContent side="right" className="border-[#e8c547]/30 bg-[#0c1018] text-[#e8edf5]">
          <SheetHeader>
            <SheetTitle className="text-[#f3d78a]">{t.menuAbout}</SheetTitle>
            <SheetDescription className="text-[#9aa3b5]">{t.menuBody}</SheetDescription>
          </SheetHeader>
          <div className="space-y-3 px-4 text-sm text-[#c5cedd]">
            <p>{t.disclaimer}</p>
            <p className="text-xs text-[#8b93a7]">{t.indexHint}</p>
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
}
