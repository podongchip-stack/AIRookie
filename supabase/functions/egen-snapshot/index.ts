// E-Gen 스냅샷 수집기 — Supabase Edge Function (pg_cron 20분 주기 호출, 2026-10-04)
//
// 노트북(수집 장비)을 들고 이동하게 되면서 수집 연속성이 깨지는 문제로, 수집기를
// 클라우드로 이관했다. 이 함수는 info/snapshot.py의 클라우드판이되 역할을 더 좁혔다:
//
//   - E-Gen 응답을 **가공 없이 원본 XML 그대로** Storage에 쌓는다(gzip).
//     해석(XML → items dict)은 로컬 sync 스크립트(info snapshot_cloud.py)가
//     기존 파서(HttpEgenClient._parse)로 한다 — 파서를 한 곳(python)에만 두어,
//     매핑 해석이 바뀌어도 과거 데이터를 다시 해석할 수 있다는 원칙을 지킨다.
//   - 실시간 2종(병상·중증질환)은 매 호출, 목록(좌표·등급)은 KST 하루 1회.
//   - 호출 실패도 .err.json으로 남긴다 — "데이터 없음"과 "호출 실패"는 다르다.
//
// Storage 레이아웃 (버킷 egen-snapshots, 공개 읽기):
//   raw/<KST날짜>/<HHMMSS>_<오퍼레이션>_p<페이지>.xml.gz   성공한 페이지 원문
//   raw/<KST날짜>/<HHMMSS>_<오퍼레이션>.err.json           실패 기록
//   days/<KST날짜>.jsonl.gz                                노트북 아카이브 시드(완결 날짜)
//
// 비밀값: EGEN_SERVICE_KEY (Edge Function secret — 대시보드에서 1회 등록).
// SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY는 런타임이 자동 주입한다.
//
// 검증 모드: ?probe=1 — 서비스키 없이 E-Gen에 호출해 "해외 IP에서 응답이 오는가"만
// 확인한다(인증 오류 XML이 와도 도달성은 증명됨).

import { createClient } from "npm:@supabase/supabase-js@2";

const BASE = "https://apis.data.go.kr/B552657/ErmctInfoInqireService";
const OP_REALTIME_BEDS = "getEmrrmRltmUsefulSckbdInfoInqire";
const OP_SEVERE_ILLNESS = "getSrsillDissAceptncPosblInfoInqire";
const OP_LIST_INFO = "getEgytListInfoInqire";
const REALTIME_OPS = [OP_REALTIME_BEDS, OP_SEVERE_ILLNESS];
const BUCKET = "egen-snapshots";
const NUM_OF_ROWS = 1000; // 전국 533곳이 한 페이지에 들어온다 (snapshot.py와 동일)
const MAX_PAGES = 20;     // 페이지 폭주 방지 — 일일 트래픽 한도 보호 (client.py와 동일)
const FETCH_TIMEOUT_MS = 20_000;

// KST 기준 날짜·시각 — 로컬 아카이브가 KST 날짜 파일이라 경계를 맞춘다.
function kstParts(): { date: string; hms: string } {
  const iso = new Date(Date.now() + 9 * 3600 * 1000).toISOString();
  return { date: iso.slice(0, 10), hms: iso.slice(11, 19).replaceAll(":", "") };
}

async function gzip(text: string): Promise<Uint8Array> {
  const stream = new Blob([text]).stream().pipeThrough(new CompressionStream("gzip"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

function egenUrl(operation: string, serviceKey: string, page: number): string {
  // 인코딩된 키(%포함)는 디코딩해서 넘긴다 — URLSearchParams가 다시 인코딩하므로
  // 그대로 쓰면 이중 인코딩으로 인증 실패한다 (egen/client.py와 같은 처리).
  const key = serviceKey.includes("%") ? decodeURIComponent(serviceKey) : serviceKey;
  const params = new URLSearchParams({
    serviceKey: key,
    pageNo: String(page),
    numOfRows: String(NUM_OF_ROWS),
    // 전국 수집: STAGE1/Q0은 보내지 않는다(빈 문자열은 생략과 다르다 — client.py 주석)
  });
  return `${BASE}/${operation}?${params}`;
}

// 응답이 정상 봉투인지 가볍게만 본다(본격 검증은 로컬 파서 몫). 둘 다 HTTP 200으로 온다.
function envelopeError(text: string): string | null {
  if (!text.includes("<response>")) {
    const m = text.match(/<returnAuthMsg>([^<]*)</);
    return `게이트웨이 오류: ${m ? m[1] : text.slice(0, 160)}`;
  }
  const code = text.match(/<resultCode>([^<]*)</)?.[1];
  if (code && code !== "00") {
    return `서비스 오류 [${code}] ${text.match(/<resultMsg>([^<]*)</)?.[1] ?? ""}`;
  }
  return null;
}

function totalCount(text: string): number | null {
  const m = text.match(/<totalCount>(\d+)</);
  return m ? Number(m[1]) : null;
}

async function fetchWithTimeout(url: string): Promise<Response> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS);
  try {
    return await fetch(url, { signal: ctrl.signal });
  } finally {
    clearTimeout(timer);
  }
}

Deno.serve(async (req: Request) => {
  const url = new URL(req.url);

  // ── 도달성 검증 모드: 키 없이 호출 — 오류 XML이라도 오면 네트워크는 통하는 것 ──
  if (url.searchParams.get("probe") === "1") {
    try {
      const res = await fetchWithTimeout(egenUrl(OP_REALTIME_BEDS, "PROBE", 1));
      const body = await res.text();
      return Response.json({
        reachable: true, httpStatus: res.status, bodyHead: body.slice(0, 200),
      });
    } catch (e) {
      return Response.json({ reachable: false, error: String(e) }, { status: 502 });
    }
  }

  const serviceKey = Deno.env.get("EGEN_SERVICE_KEY");
  if (!serviceKey) {
    return Response.json(
      { error: "EGEN_SERVICE_KEY secret이 없습니다 — 대시보드 Edge Functions → Secrets에 등록" },
      { status: 500 },
    );
  }
  const supabase = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
  );

  const { date, hms } = kstParts();
  const dir = `raw/${date}`;

  // 목록 오퍼레이션은 하루 1회 — 오늘 성공분(.xml.gz)이 이미 있으면 건너뛴다.
  // 실패(.err.json)만 있으면 다음 주기에 재시도한다 (snapshot.py already_taken_today와 동일).
  const ops = [...REALTIME_OPS];
  const { data: todays } = await supabase.storage.from(BUCKET).list(dir, { limit: 1000 });
  const listDone = (todays ?? []).some(
    (o) => o.name.includes(OP_LIST_INFO) && o.name.endsWith(".xml.gz"),
  );
  if (!listDone) ops.push(OP_LIST_INFO);

  const saved: string[] = [];
  const errors: string[] = [];
  for (const op of ops) {
    try {
      let page = 1;
      let got = 0;
      while (true) {
        const res = await fetchWithTimeout(egenUrl(op, serviceKey, page));
        const text = await res.text();
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const envErr = envelopeError(text);
        if (envErr) throw new Error(envErr);

        const path = `${dir}/${hms}_${op}_p${page}.xml.gz`;
        const { error: upErr } = await supabase.storage
          .from(BUCKET)
          .upload(path, await gzip(text), { contentType: "application/gzip", upsert: true });
        if (upErr) throw new Error(`업로드 실패: ${upErr.message}`);
        saved.push(path);

        const total = totalCount(text) ?? 0;
        const pageRows = (text.match(/<item>/g) ?? []).length;
        got += pageRows;
        if (pageRows === 0 || got >= total) break;
        if (page >= MAX_PAGES) throw new Error(`페이지 ${MAX_PAGES}쪽 초과 (${got}/${total}건)`);
        page += 1;
      }
    } catch (e) {
      // 실패도 한 줄 남긴다 — "그 시각 데이터 없음"과 "호출 실패"를 구분하기 위해
      const errPath = `${dir}/${hms}_${op}.err.json`;
      const payload = JSON.stringify({ ts: `${date}T${hms}`, operation: op, error: String(e) });
      await supabase.storage.from(BUCKET)
        .upload(errPath, new Blob([payload]), { contentType: "application/json", upsert: true })
        .catch(() => {});
      errors.push(`${op}: ${String(e)}`);
    }
  }

  return Response.json({ date, time: hms, saved, errors }, { status: errors.length && !saved.length ? 502 : 200 });
});
