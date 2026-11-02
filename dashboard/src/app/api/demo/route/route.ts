import { NextResponse } from "next/server";

export async function POST(request: Request) {
  const hub = process.env.HUB_INTERNAL_HTTP_URL ?? process.env.NEXT_PUBLIC_HUB_HTTP_URL;
  if (!hub) return NextResponse.json({ path: null }, { status: 503 });
  try {
    const response = await fetch(`${hub}/demo/route`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: await request.text(), signal: AbortSignal.timeout(15000),
    });
    return NextResponse.json(await response.json(), { status: response.status });
  } catch {
    return NextResponse.json({ path: null }, { status: 502 });
  }
}
