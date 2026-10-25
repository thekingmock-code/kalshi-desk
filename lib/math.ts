import type { Candle } from "./desk-types";

export function erf(x: number): number {
  const sign = x < 0 ? -1 : 1;
  const a = Math.abs(x);
  const p = 0.3275911;
  const t = 1 / (1 + p * a);
  const y =
    1 -
    ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t +
      0.254829592) *
      t *
      Math.exp(-a * a);
  return sign * y;
}

export function normCdf(x: number): number {
  return 0.5 * (1 + erf(x / Math.SQRT2));
}

export function kalshiFee(price: number): number {
  return 0.07 * price * (1 - price);
}

/** P(spot at close > strike) under a driftless lognormal. */
export function fairProbAbove(
  spot: number,
  strike: number,
  secsLeft: number,
  sigmaPerSec: number,
): { prob: number; sigmaT: number } {
  const sigmaT = Math.max(sigmaPerSec * Math.sqrt(Math.max(secsLeft, 1)), 1e-6);
  const d2 = (Math.log(spot / strike) - 0.5 * sigmaT * sigmaT) / sigmaT;
  return { prob: normCdf(d2), sigmaT };
}

export function median(values: number[]): number | null {
  if (!values.length) return null;
  const s = [...values].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

export function stdev(values: number[]): number | null {
  if (values.length < 2) return null;
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  const v = values.reduce((a, r) => a + (r - mean) ** 2, 0) / (values.length - 1);
  return Math.sqrt(v);
}

/** One-minute log-return volatility, scaled to per-second. */
export function sigmaPerSecFromMinuteCloses(closes: number[]): number | null {
  const rets: number[] = [];
  for (let i = 1; i < closes.length; i++) {
    if (closes[i - 1] > 0 && closes[i] > 0) rets.push(Math.log(closes[i] / closes[i - 1]));
  }
  const perMin = stdev(rets);
  if (perMin == null) return null;
  return perMin / Math.sqrt(60);
}

export function ema(values: number[], period: number): number[] {
  const k = 2 / (period + 1);
  const out: number[] = [];
  let prev = values[0] ?? 0;
  values.forEach((v, i) => {
    prev = i === 0 ? v : v * k + prev * (1 - k);
    out.push(prev);
  });
  return out;
}

export function bollinger(values: number[], period = 20, mult = 2) {
  const mid: (number | null)[] = [];
  const upper: (number | null)[] = [];
  const lower: (number | null)[] = [];
  for (let i = 0; i < values.length; i++) {
    if (i < period - 1) {
      mid.push(null);
      upper.push(null);
      lower.push(null);
      continue;
    }
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += values[j];
    const m = sum / period;
    let ss = 0;
    for (let j = i - period + 1; j <= i; j++) ss += (values[j] - m) ** 2;
    const sd = Math.sqrt(ss / period);
    mid.push(m);
    upper.push(m + mult * sd);
    lower.push(m - mult * sd);
  }
  return { mid, upper, lower };
}

export function vwapFrom(candles: Candle[], resetTs: number | null): (number | null)[] {
  let pv = 0;
  let vol = 0;
  let started = resetTs == null;
  return candles.map((c) => {
    if (!started) {
      if (c.time >= resetTs!) started = true;
      else return null;
    }
    const typical = (c.high + c.low + c.close) / 3;
    const w = c.volume > 0 ? c.volume : 1;
    pv += typical * w;
    vol += w;
    return pv / vol;
  });
}

export function detectPattern(candles: Candle[]): {
  key: "bullEngulf" | "bearEngulf" | "none";
  bias: "up" | "down" | "flat";
} {
  if (candles.length < 2) return { key: "none", bias: "flat" };
  const a = candles[candles.length - 2];
  const b = candles[candles.length - 1];
  const aBear = a.close < a.open;
  const bBull = b.close > b.open;
  const aHi = Math.max(a.open, a.close);
  const aLo = Math.min(a.open, a.close);
  const bHi = Math.max(b.open, b.close);
  const bLo = Math.min(b.open, b.close);
  if (aBear && bBull && bHi >= aHi && bLo <= aLo) return { key: "bullEngulf", bias: "up" };
  if (!aBear && !bBull && b.close < b.open && bHi >= aHi && bLo <= aLo) {
    return { key: "bearEngulf", bias: "down" };
  }
  return { key: "none", bias: "flat" };
}
