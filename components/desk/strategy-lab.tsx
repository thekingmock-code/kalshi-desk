"use client";

import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import type { Copy } from "@/lib/i18n";
import type { JournalEntry } from "./types";

export type Field = { text: string; linked: boolean };

export type GateState = {
  edge: boolean;
  edgeCents: number;
  cushion: boolean;
  cushionMult: number;
  momentum: boolean;
};

export type ExitState = { tp: number; sl: number; flatten: number };

function Row({
  label,
  field,
  onChange,
  suffix,
  liveTag,
  editedTag,
}: {
  label: string;
  field: Field;
  onChange: (text: string) => void;
  suffix?: string;
  liveTag: string;
  editedTag: string;
}) {
  return (
    <label className="block">
      <span className="flex items-baseline justify-between text-[11px] text-[#8b93a7]">
        {label}
        <span className={field.linked ? "text-emerald-400/80" : "text-[#e8c547]"}>{field.linked ? liveTag : editedTag}</span>
      </span>
      <span className="mt-1 flex items-center gap-1">
        <Input
          value={field.text}
          inputMode="decimal"
          onChange={(e) => onChange(e.target.value)}
          className="h-8 border-white/10 bg-black/30 font-mono text-[#f3f6fb]"
        />
        {suffix && <span className="text-xs text-[#8b93a7]">{suffix}</span>}
      </span>
    </label>
  );
}

export function StrategyLab({
  t,
  fields,
  setField,
  gates,
  setGates,
  exits,
  setExits,
  journal,
  onFlatten,
  onReset,
  asset,
}: {
  t: Copy;
  fields: Record<string, Field>;
  setField: (key: string, text: string) => void;
  gates: GateState;
  setGates: (g: GateState) => void;
  exits: ExitState;
  setExits: (e: ExitState) => void;
  journal: JournalEntry[];
  onFlatten: (id: string) => void;
  onReset: () => void;
  asset: string;
}) {
  return (
    <aside className="gold-card h-fit space-y-4 px-3 py-3 sm:px-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-[13px] font-semibold tracking-wide text-[#f3d78a]">{t.lab}</h2>
        <button type="button" className="text-[11px] text-[#8b93a7] underline-offset-2 hover:underline" onClick={onReset}>
          {t.resetLive}
        </button>
      </div>

      <section className="space-y-2">
        <h3 className="text-xs tracking-wide text-white/80">{t.current}</h3>
        <Row label={t.contracts} field={fields.contracts} onChange={(v) => setField("contracts", v)} liveTag={t.linked} editedTag={t.edited} />
        <Row label={t.strike} field={fields.strike} onChange={(v) => setField("strike", v)} suffix="$" liveTag={t.linked} editedTag={t.edited} />
        <Row label={t.spot} field={fields.spot} onChange={(v) => setField("spot", v)} suffix="$" liveTag={t.linked} editedTag={t.edited} />
        <Row label={t.index} field={fields.index} onChange={(v) => setField("index", v)} suffix="$" liveTag={t.linked} editedTag={t.edited} />
        <p className="text-[10px] leading-snug text-[#8b93a7]">{t.indexHint}</p>
        <Row label={t.move} field={fields.move} onChange={(v) => setField("move", v)} suffix="$" liveTag={t.linked} editedTag={t.edited} />
        <div className="grid grid-cols-2 gap-2">
          <Row label={t.upPx} field={fields.up} onChange={(v) => setField("up", v)} suffix="¢" liveTag={t.linked} editedTag={t.edited} />
          <Row label={t.downPx} field={fields.down} onChange={(v) => setField("down", v)} suffix="¢" liveTag={t.linked} editedTag={t.edited} />
        </div>
      </section>

      <section className="space-y-2">
        <h3 className="text-xs tracking-wide text-white/80">{t.momentum}</h3>
        <Row label={t.taker} field={fields.taker} onChange={(v) => setField("taker", v)} suffix="%" liveTag={t.linked} editedTag={t.edited} />
        <Row label={t.vol} field={fields.vol} onChange={(v) => setField("vol", v)} suffix="×" liveTag={t.linked} editedTag={t.edited} />
      </section>

      <section className="space-y-2">
        <h3 className="text-xs tracking-wide text-white/80">{t.tune}</h3>
        <h3 className="text-[11px] text-[#8b93a7]">{t.gates}</h3>
        <label className="flex items-center gap-2 text-xs text-[#d5dbe8]">
          <Checkbox checked={gates.edge} onCheckedChange={(v) => setGates({ ...gates, edge: v === true })} />
          <span className="flex-1">{t.gateEdge}</span>
          <Input
            value={String(gates.edgeCents)}
            onChange={(e) => setGates({ ...gates, edgeCents: Number(e.target.value) || 0 })}
            className="h-7 w-16 border-white/10 bg-black/30 font-mono"
          />
        </label>
        <label className="flex items-center gap-2 text-xs text-[#d5dbe8]">
          <Checkbox checked={gates.cushion} onCheckedChange={(v) => setGates({ ...gates, cushion: v === true })} />
          <span className="flex-1">{t.gateCushion}</span>
          <Input
            value={String(gates.cushionMult)}
            onChange={(e) => setGates({ ...gates, cushionMult: Number(e.target.value) || 0 })}
            className="h-7 w-16 border-white/10 bg-black/30 font-mono"
          />
        </label>
        <label className="flex items-center gap-2 text-xs text-[#d5dbe8]">
          <Checkbox checked={gates.momentum} onCheckedChange={(v) => setGates({ ...gates, momentum: v === true })} />
          {t.gateMom}
        </label>
      </section>

      <section className="space-y-2">
        <h3 className="text-xs tracking-wide text-white/80">{t.exits}</h3>
        <div className="grid grid-cols-3 gap-2">
          <label className="text-[10px] text-[#8b93a7]">
            {t.tp}
            <Input value={String(exits.tp)} onChange={(e) => setExits({ ...exits, tp: Number(e.target.value) || 0 })} className="mt-1 h-7 border-white/10 bg-black/30 font-mono" />
          </label>
          <label className="text-[10px] text-[#8b93a7]">
            {t.sl}
            <Input value={String(exits.sl)} onChange={(e) => setExits({ ...exits, sl: Number(e.target.value) || 0 })} className="mt-1 h-7 border-white/10 bg-black/30 font-mono" />
          </label>
          <label className="text-[10px] text-[#8b93a7]">
            {t.flatten}
            <Input value={String(exits.flatten)} onChange={(e) => setExits({ ...exits, flatten: Number(e.target.value) || 0 })} className="mt-1 h-7 border-white/10 bg-black/30 font-mono" />
          </label>
        </div>
      </section>

      <section>
        <h3 className="text-xs tracking-wide text-white/80">{t.journal}</h3>
        {journal.length === 0 ? (
          <p className="mt-2 text-[11px] leading-relaxed text-[#8b93a7]">{t.emptyJournal}</p>
        ) : (
          <ul className="mt-2 max-h-64 space-y-2 overflow-auto pr-1">
            {journal.map((j) => (
              <li key={j.id} className="rounded-lg border border-white/10 bg-black/25 px-2 py-2 text-[11px]">
                <div className="flex items-center justify-between gap-2">
                  <span className={j.side === "UP" ? "text-emerald-300" : "text-rose-300"}>
                    {j.asset} {j.side} · {(j.ask * 100).toFixed(1)}¢ × {j.contracts}
                  </span>
                  <span className="font-mono text-[#8b93a7]">{new Date(j.ts).toLocaleTimeString()}</span>
                </div>
                <p className="mt-1 text-[#9aa3b5]">
                  edge {(j.edge * 100).toFixed(1)}¢ · {j.ticker}
                </p>
                {j.closed ? (
                  <p className={`mt-1 font-mono ${j.pnl >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                    pnl {j.pnl >= 0 ? "+" : ""}${j.pnl.toFixed(2)}
                  </p>
                ) : (
                  <button type="button" className="mt-1 text-[#e8c547] underline" onClick={() => onFlatten(j.id)}>
                    {t.flattenBtn}
                  </button>
                )}
                {j.note && <p className="mt-1 text-[#8b93a7]">{j.note}</p>}
              </li>
            ))}
          </ul>
        )}
        <p className="mt-3 text-[10px] leading-relaxed text-[#6f788a]">{t.disclaimer}</p>
        <p className="sr-only">{asset}</p>
      </section>
    </aside>
  );
}
