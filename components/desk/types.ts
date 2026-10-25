export type JournalEntry = {
  id: string;
  ts: number;
  asset: "BTC" | "SOL";
  ticker: string;
  side: "UP" | "DOWN";
  ask: number;
  contracts: number;
  spot: number;
  strike: number;
  fair: number;
  edge: number;
  note: string;
  closed: boolean;
  exitAsk?: number;
  pnl: number;
};
