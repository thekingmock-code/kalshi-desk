export type Asset = "BTC" | "SOL";

export type Candle = {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export type Flow = {
  buyUsd: number;
  sellUsd: number;
  buyBase: number;
  sellBase: number;
  trades: number;
  takerBuyPct: number;
  fromTs: number | null;
  toTs: number | null;
  partial: boolean;
};

export type MarketSnap = {
  ticker: string;
  title: string;
  strike: number;
  openTs: number;
  closeTs: number;
  yesAsk: number;
  noAsk: number;
  yesBid: number | null;
  noBid: number | null;
};

export type DeskSnapshot = {
  asset: Asset;
  asOf: number;
  spot: number | null;
  spotSource: string | null;
  index: number | null;
  indexSource: string | null;
  market: MarketSnap | null;
  candles: Candle[];
  interval: number;
  flow: Flow;
  typicalMove: number | null;
  sigmaPerSec: number | null;
  volRatio: number | null;
  fairYes: number | null;
  feeYes: number | null;
  feeNo: number | null;
  edgeYes: number | null;
  edgeNo: number | null;
  warning: string | null;
};
