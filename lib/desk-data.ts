import crypto from "crypto";
import fs from "fs";
import type { Asset, Candle, DeskSnapshot, Flow, MarketSnap } from "./desk-types";
import {
  fairProbAbove,
  kalshiFee,
  median,
  sigmaPerSecFromMinuteCloses,
  stdev,
} from "./math";

const KALSHI_BASE =
  process.env.KALSHI_API_BASE ?? "https://api.elections.kalshi.com/trade-api/v2";

const SERIES: Record<Asset, string> = { BTC: "KXBTC15M", SOL: "KXSOL15M" };
const PRODUCT: Record<Asset, string> = { BTC: "BTC-USD", SOL: "SOL-USD" };
const KRAKEN: Record<Asset, string> = { BTC: "XBTUSD", SOL: "SOLUSD" };
const CFB: Record<Asset, string> = { BTC: "BRTI", SOL: "SOLUSD_RTI" };

const UA = "xvantage-desk/1.0";

type CacheEntry = { at: number; data: DeskSnapshot };
const cache = new Map<string, CacheEntry>();

async function getJson(url: string, headers?: Record<string, string>): Promise<unknown> {
  const res = await fetch(url, {
    headers: { Accept: "application/json", "User-Agent": UA, ...headers },
    cache: "no-store",
    signal: AbortSignal.timeout(8000),
  });
  if (!res.ok) throw new Error(`${res.status} ${url}`);
  return res.json();
}

function num(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

function priceField(m: Record<string, unknown>, key: string): number | null {
  const dollars = num(m[`${key}_dollars`]);
  if (dollars != null) return dollars;
  const cents = num(m[key]);
  return cents == null ? null : cents / 100;
}

function parseCandles(raw: unknown): Candle[] {
  if (!Array.isArray(raw)) return [];
  const out: Candle[] = [];
  for (const row of raw) {
    if (!Array.isArray(row) || row.length < 6) continue;
    const time = Number(row[0]);
    const low = Number(row[1]);
    const high = Number(row[2]);
    const open = Number(row[3]);
    const close = Number(row[4]);
    const volume = Number(row[5]);
    if ([time, low, high, open, close].some((n) => !Number.isFinite(n))) continue;
    out.push({ time, open, high, low, close, volume: Number.isFinite(volume) ? volume : 0 });
  }
  out.sort((a, b) => a.time - b.time);
  return out;
}

function aggregate(candles: Candle[], seconds: number): Candle[] {
  if (seconds <= 60) return candles;
  const groups = new Map<number, Candle>();
  for (const c of candles) {
    const t = Math.floor(c.time / seconds) * seconds;
    const g = groups.get(t);
    if (!g) groups.set(t, { ...c, time: t });
    else {
      g.high = Math.max(g.high, c.high);
      g.low = Math.min(g.low, c.low);
      g.close = c.close;
      g.volume += c.volume;
    }
  }
  return [...groups.values()].sort((a, b) => a.time - b.time);
}

type Print = { id: number; time: number; price: number; size: number; takerBuy: boolean };

async function fetchTrades(product: string, pages: number): Promise<Print[]> {
  const all: Print[] = [];
  let after: string | undefined;
  for (let i = 0; i < pages; i++) {
    const url = new URL(`https://api.exchange.coinbase.com/products/${product}/trades`);
    url.searchParams.set("limit", "1000");
    if (after) url.searchParams.set("after", after);
    const batch = (await getJson(url.toString())) as Array<Record<string, string>>;
    if (!Array.isArray(batch) || !batch.length) break;
    for (const t of batch) {
      const id = Number(t.trade_id);
      const price = Number(t.price);
      const size = Number(t.size);
      const time = Date.parse(t.time) / 1000;
      if (!Number.isFinite(id) || !Number.isFinite(price) || !Number.isFinite(time)) continue;
      // Coinbase `side` is the maker. A maker sell is a taker buy.
      all.push({ id, time, price, size: Number.isFinite(size) ? size : 0, takerBuy: t.side === "sell" });
    }
    after = String(batch[batch.length - 1].trade_id);
    if (batch.length < 1000) break;
  }
  return all;
}

function bucketTrades(prints: Print[], seconds: number): Candle[] {
  const map = new Map<number, Candle>();
  const sorted = [...prints].sort((a, b) => a.time - b.time);
  for (const p of sorted) {
    const t = Math.floor(p.time / seconds) * seconds;
    const c = map.get(t);
    if (!c) {
      map.set(t, { time: t, open: p.price, high: p.price, low: p.price, close: p.price, volume: p.size });
    } else {
      c.high = Math.max(c.high, p.price);
      c.low = Math.min(c.low, p.price);
      c.close = p.price;
      c.volume += p.size;
    }
  }
  return [...map.values()].sort((a, b) => a.time - b.time);
}

function flowFrom(prints: Print[], openTs: number | null): Flow {
  const windowed = openTs == null ? prints : prints.filter((p) => p.time >= openTs - 1);
  let buyUsd = 0;
  let sellUsd = 0;
  let buyBase = 0;
  let sellBase = 0;
  let fromTs: number | null = null;
  let toTs: number | null = null;
  for (const p of windowed) {
    const usd = p.price * p.size;
    if (p.takerBuy) {
      buyUsd += usd;
      buyBase += p.size;
    } else {
      sellUsd += usd;
      sellBase += p.size;
    }
    fromTs = fromTs == null ? p.time : Math.min(fromTs, p.time);
    toTs = toTs == null ? p.time : Math.max(toTs, p.time);
  }
  const total = buyUsd + sellUsd;
  const partial = openTs != null && fromTs != null && fromTs > openTs + 20;
  return {
    buyUsd,
    sellUsd,
    buyBase,
    sellBase,
    trades: windowed.length,
    takerBuyPct: total > 0 ? (buyUsd / total) * 100 : 50,
    fromTs,
    toTs,
    partial,
  };
}

async function fetchMarket(asset: Asset): Promise<MarketSnap | null> {
  const url = `${KALSHI_BASE}/markets?series_ticker=${SERIES[asset]}&status=open&limit=20`;
  const body = (await getJson(url)) as { markets?: Array<Record<string, unknown>> };
  const now = Date.now() / 1000;
  const parsed: MarketSnap[] = [];
  for (const m of body.markets ?? []) {
    const strike = num(m.floor_strike) ?? num(m.cap_strike);
    const close = typeof m.close_time === "string" ? Date.parse(m.close_time) / 1000 : NaN;
    const open = typeof m.open_time === "string" ? Date.parse(m.open_time) / 1000 : NaN;
    const yesAsk = priceField(m, "yes_ask");
    const noAsk = priceField(m, "no_ask");
    if (strike == null || !Number.isFinite(close) || yesAsk == null || noAsk == null) continue;
    parsed.push({
      ticker: String(m.ticker),
      title: String(m.title ?? ""),
      strike,
      openTs: Number.isFinite(open) ? open : close - 15 * 60,
      closeTs: close,
      yesAsk,
      noAsk,
      yesBid: priceField(m, "yes_bid"),
      noBid: priceField(m, "no_bid"),
    });
  }
  const live = parsed.filter((m) => m.openTs <= now && m.closeTs > now + 1);
  const pool = live.length ? live : parsed.filter((m) => m.closeTs > now + 1);
  pool.sort((a, b) => a.closeTs - b.closeTs);
  return pool[0] ?? null;
}

async function fetchCoinbaseLast(product: string): Promise<number | null> {
  const body = (await getJson(
    `https://api.exchange.coinbase.com/products/${product}/ticker`,
  )) as { price?: string };
  return num(body.price);
}

async function fetchKrakenLast(pair: string): Promise<number | null> {
  const body = (await getJson(
    `https://api.kraken.com/0/public/Ticker?pair=${pair}`,
  )) as { result?: Record<string, { c?: string[] }> };
  const row = Object.values(body.result ?? {})[0];
  return num(row?.c?.[0]);
}

function loadPem(): string | null {
  const inline = process.env.KALSHI_PRIVATE_KEY?.replace(/\\n/g, "\n");
  if (inline?.includes("PRIVATE KEY")) return inline;
  const path = process.env.KALSHI_PRIVATE_KEY_PATH;
  if (!path) return null;
  try {
    return fs.readFileSync(path, "utf8");
  } catch {
    return null;
  }
}

async function fetchCfb(indexId: string): Promise<number | null> {
  const keyId = process.env.KALSHI_ACCESS_KEY || process.env.KALSHI_API_KEY_ID;
  const pem = loadPem();
  if (!keyId || !pem) return null;
  const path = "/trade-api/v2/cfbenchmarks/values";
  const timestamp = String(Date.now());
  const message = `${timestamp}GET${path}`;
  const signature = crypto
    .sign("sha256", Buffer.from(message), {
      key: pem,
      padding: crypto.constants.RSA_PKCS1_PSS_PADDING,
      saltLength: crypto.constants.RSA_PSS_SALTLEN_DIGEST,
    })
    .toString("base64");
  const body = (await getJson(`${KALSHI_BASE}/cfbenchmarks/values?id=${indexId}`, {
    "KALSHI-ACCESS-KEY": keyId,
    "KALSHI-ACCESS-SIGNATURE": signature,
    "KALSHI-ACCESS-TIMESTAMP": timestamp,
  })) as { data?: { payload?: unknown } };
  const payload = body.data?.payload;
  const row = Array.isArray(payload) ? payload[payload.length - 1] : payload;
  if (!row || typeof row !== "object") return null;
  return num((row as { value?: unknown }).value);
}

async function build(asset: Asset, interval: number): Promise<DeskSnapshot> {
  const product = PRODUCT[asset];
  const [marketR, candlesR, cbR, kxR, tradesR, indexR] = await Promise.allSettled([
    fetchMarket(asset),
    getJson(`https://api.exchange.coinbase.com/products/${product}/candles?granularity=60`),
    fetchCoinbaseLast(product),
    fetchKrakenLast(KRAKEN[asset]),
    fetchTrades(product, interval < 60 ? 2 : 2),
    fetchCfb(CFB[asset]),
  ]);

  const warnings: string[] = [];
  const market = marketR.status === "fulfilled" ? marketR.value : null;
  if (marketR.status === "rejected") warnings.push("Kalshi market request failed");

  const minute = candlesR.status === "fulfilled" ? parseCandles(candlesR.value) : [];
  if (!minute.length) warnings.push("Coinbase candles unavailable");

  const prints = tradesR.status === "fulfilled" ? tradesR.value : [];
  if (!prints.length) warnings.push("Coinbase trade tape unavailable");

  const spots = [
    cbR.status === "fulfilled" ? cbR.value : null,
    kxR.status === "fulfilled" ? kxR.value : null,
  ].filter((n): n is number => n != null && n > 0);
  const spot = spots.length ? spots.reduce((a, b) => a + b, 0) / spots.length : null;
  const spotSource =
    spots.length === 2 ? "Coinbase + Kraken" : cbR.status === "fulfilled" && cbR.value ? "Coinbase" : kxR.status === "fulfilled" && kxR.value ? "Kraken" : null;

  const index = indexR.status === "fulfilled" ? indexR.value : null;

  let candles: Candle[] = [];
  if (interval < 60 && prints.length) candles = bucketTrades(prints, interval).slice(-120);
  else if (minute.length) candles = aggregate(minute, interval).slice(-150);
  if (!candles.length && minute.length) candles = minute.slice(-150);

  const closes = minute.map((c) => c.close);
  const moves: number[] = [];
  const rets: number[] = [];
  for (let i = 1; i < minute.length; i++) {
    moves.push(Math.abs(minute[i].close - minute[i - 1].close));
    if (minute[i - 1].close > 0) rets.push(Math.log(minute[i].close / minute[i - 1].close));
  }
  const typicalMove = median(moves.slice(-60));
  const sigmaPerSec = sigmaPerSecFromMinuteCloses(closes);
  const recent = stdev(rets.slice(-15));
  const base = stdev(rets.slice(-90));
  const volRatio = recent != null && base != null && base > 0 ? recent / base : null;

  const flow = flowFrom(prints, market?.openTs ?? null);
  const now = Date.now() / 1000;
  const mark = index ?? spot;
  let fairYes: number | null = null;
  let feeYes: number | null = null;
  let feeNo: number | null = null;
  let edgeYes: number | null = null;
  let edgeNo: number | null = null;
  if (mark && market && sigmaPerSec && mark > 0 && market.strike > 0) {
    const secs = Math.max(market.closeTs - now, 1);
    fairYes = fairProbAbove(mark, market.strike, secs, sigmaPerSec).prob;
    feeYes = kalshiFee(market.yesAsk);
    feeNo = kalshiFee(market.noAsk);
    edgeYes = fairYes - market.yesAsk - feeYes;
    edgeNo = 1 - fairYes - market.noAsk - feeNo;
  }

  return {
    asset,
    asOf: Date.now(),
    spot,
    spotSource,
    index,
    indexSource: index != null ? CFB[asset] : null,
    market,
    candles,
    interval,
    flow,
    typicalMove,
    sigmaPerSec,
    volRatio,
    fairYes,
    feeYes,
    feeNo,
    edgeYes,
    edgeNo,
    warning: warnings.length ? warnings.join(" · ") : null,
  };
}

export async function getDesk(asset: Asset, interval: number): Promise<DeskSnapshot> {
  const key = `${asset}:${interval}`;
  const hit = cache.get(key);
  if (hit && Date.now() - hit.at < 1500) return hit.data;
  const data = await build(asset, interval);
  cache.set(key, { at: Date.now(), data });
  return data;
}
