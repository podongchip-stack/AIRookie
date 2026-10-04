import { NextResponse } from "next/server";

// 시연 통제 콘솔(/control)이 가짜 환자(통화 요약)를 hub POST /voice/summary로 보낼 때 쓰는
// 서버측 프록시(2026-10-04). 브라우저에서 hub로 직접 JSON POST하면 CORS preflight에 막혀서
// Next 서버가 대신 전달한다 — 최종 목적지는 hub뿐이므로 "dashboard는 hub와만 통신" 원칙은
// 유지된다. 시연 전용이며, 실제 운영에선 이 경로 대신 voice 인스턴스가 직접 hub로 보낸다.
export async function POST(request: Request) {
  const hub = process.env.NEXT_PUBLIC_HUB_HTTP_URL;
  if (!hub) {
    return NextResponse.json({ error: "NEXT_PUBLIC_HUB_HTTP_URL 미설정 — 목데이터 모드에선 쓸 수 없습니다" }, { status: 503 });
  }
  const body = await request.text();
  try {
    const response = await fetch(`${hub}/voice/summary`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
    const data = await response.json().catch(() => ({}));
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    return NextResponse.json({ error: `hub 전달 실패: ${String(error)}` }, { status: 502 });
  }
}
