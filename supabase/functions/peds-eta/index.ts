// 보호자 사이트의 "차로 N분"을 실제 도로 시간으로 바꾸는 프록시.
//
// 왜 프록시인가 — 카카오모빌리티 길찾기는 REST 키를 헤더에 넣어야 하는데, 이 사이트는
// 정적 페이지라 브라우저에 키를 두면 그대로 공개된다(쿼터 도용·차단). 키는 이 함수의
// secret에만 두고, 브라우저는 좌표만 보낸다.
//
// 개인정보 — 출발지 좌표가 이 함수를 거쳐 카카오로 간다. 사이트에서 "지도 배경은 외부로
// 간다"고 이미 밝힌 것과 같은 성격이라 화면 문구도 같이 고쳤다. **로그에 좌표를 남기지
// 않는다**(실패 사유만 남긴다). 캐시 키로만 쓰고 저장하지 않는다.
//
// 카카오 다중 목적지 API 제약(hub/routing.py와 같다)
//   · 한 번에 목적지 30곳
//   · 반경 10km — 그 밖은 값이 안 온다. 못 받은 병원은 결과에서 빠지고 화면은 추정값을 쓴다.
//
// 배포:
//   cp -r poc/edge/peds-eta supabase/functions/
//   npx supabase secrets set KAKAO_REST_API_KEY=... --project-ref <ref>
//   npx supabase functions deploy peds-eta --project-ref <ref> --no-verify-jwt
//
// 호출:
//   POST { origin: {lat, lng}, destinations: [{key, lat, lng}, ...] }
//   → { etas: { "<key>": {sec, m} }, source: "kakao" }

const KAKAO_URL = "https://apis-navi.kakaomobility.com/v1/destinations/directions";
const MAX_DESTINATIONS = 30;
const MAX_RADIUS_M = 10000;
const TIMEOUT_MS = 4000;
//: 같은 출발지·목적지는 잠깐 재사용한다. 교통 상황이 바뀌므로 짧게(hub와 같은 5분).
const CACHE_TTL_MS = 300_000;
//: 출발지를 약 10m로 반올림해 GPS 흔들림으로 캐시가 매번 빗나가지 않게 한다.
const round4 = (n: number) => Math.round(n * 1e4) / 1e4;

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

type Eta = { sec: number; m: number };
const cache = new Map<string, { at: number; eta: Eta }>();

function cacheKey(o: { lat: number; lng: number }, d: { lat: number; lng: number }) {
  return `${round4(o.lat)},${round4(o.lng)}>${round4(d.lat)},${round4(d.lng)}`;
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...CORS, "content-type": "application/json; charset=utf-8" },
  });
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return json({ error: "POST only" }, 405);

  const key = Deno.env.get("KAKAO_REST_API_KEY");
  if (!key) return json({ error: "no key" }, 500);

  let origin: { lat: number; lng: number };
  let destinations: { key: string; lat: number; lng: number }[];
  try {
    const body = await req.json();
    origin = body.origin;
    destinations = (body.destinations || []).slice(0, 120);   // 상한 — 한 번에 4묶음까지
    if (!origin || typeof origin.lat !== "number" || typeof origin.lng !== "number") {
      return json({ error: "origin required" }, 400);
    }
  } catch {
    return json({ error: "bad json" }, 400);
  }

  const etas: Record<string, Eta> = {};
  const pending: typeof destinations = [];
  const now = Date.now();
  for (const d of destinations) {
    if (typeof d?.lat !== "number" || typeof d?.lng !== "number" || !d.key) continue;
    const hit = cache.get(cacheKey(origin, d));
    if (hit && now - hit.at < CACHE_TTL_MS) etas[d.key] = hit.eta;
    else pending.push(d);
  }

  for (let i = 0; i < pending.length; i += MAX_DESTINATIONS) {
    const chunk = pending.slice(i, i + MAX_DESTINATIONS);
    const payload = {
      origin: { x: origin.lng, y: origin.lat },        // 카카오는 x=경도, y=위도
      destinations: chunk.map((d) => ({ key: d.key, x: d.lng, y: d.lat })),
      radius: MAX_RADIUS_M,
      priority: "TIME",
    };
    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
      const res = await fetch(KAKAO_URL, {
        method: "POST",
        headers: { Authorization: `KakaoAK ${key}`, "content-type": "application/json" },
        body: JSON.stringify(payload),
        signal: ctrl.signal,
      });
      clearTimeout(timer);
      if (!res.ok) { console.error(`kakao ${res.status}`); continue; }
      const data = await res.json();
      const byKey = new Map(chunk.map((d) => [d.key, d]));
      for (const route of data.routes || []) {
        const k = route.key;
        if (route.result_code !== 0 || !route.summary || !byKey.has(k)) continue;  // 10km 밖 등
        const eta: Eta = { sec: Number(route.summary.duration), m: Number(route.summary.distance) };
        etas[k] = eta;
        cache.set(cacheKey(origin, byKey.get(k)!), { at: Date.now(), eta });
      }
    } catch (e) {
      // 좌표는 남기지 않는다 — 사유만
      console.error(`kakao call failed: ${e instanceof Error ? e.name : "unknown"}`);
    }
  }

  return json({ etas, source: "kakao", radiusM: MAX_RADIUS_M });
});
