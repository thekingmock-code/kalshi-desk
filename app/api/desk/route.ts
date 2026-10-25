import { NextRequest, NextResponse } from "next/server";
import { getDesk } from "@/lib/desk-data";
import type { Asset } from "@/lib/desk-types";

export const dynamic = "force-dynamic";

const INTERVALS = new Set([15, 30, 45, 60, 180, 300]);

export async function GET(req: NextRequest) {
  const assetParam = req.nextUrl.searchParams.get("asset") ?? "BTC";
  const interval = Number(req.nextUrl.searchParams.get("interval") ?? "60");
  if (assetParam !== "BTC" && assetParam !== "SOL") {
    return NextResponse.json({ error: "asset must be BTC or SOL" }, { status: 400 });
  }
  if (!INTERVALS.has(interval)) {
    return NextResponse.json({ error: "unsupported interval" }, { status: 400 });
  }
  try {
    const data = await getDesk(assetParam as Asset, interval);
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : "desk fetch failed";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
