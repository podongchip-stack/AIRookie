import type { CaseEvent, CaseHistoryItem } from "@/types/dashboard";

// 지난 사건 이력 조회(제안 계약 — hub에 아직 없음). 관제 '지난 사건' 모달이 날짜·검색으로 오늘 이전 사건도 보려는 용도.
// 설계를 먼저 화면에서 확인하려고 hub 응답과 같은 모양의 가짜 데이터(mock)를 두었다. hub가 이 계약대로 구현하면
// NEXT_PUBLIC_CASE_ARCHIVE_MOCK만 끄면 된다. 항목(CaseHistoryItem)은 오늘 종료 사건과 같은 형식이라 통화 전문·활력징후는 없다.
//
// GET {hub}/case-archive?from=YYYY-MM-DD&to=YYYY-MM-DD&q=&result=all|done|cancel&limit=200
//   from/to는 종료일(KST) 기준 양끝 포함. q는 증상·구급차 이름·이송 병원에 부분 일치. 최근 종료 순.
//   → { cases: CaseHistoryItem[], total: number, stats: CaseArchiveStats }   (stats는 limit과 무관하게 조건 전체 기준)

export type ArchiveResult = "all" | "done" | "cancel";

export interface CaseArchiveQuery {
  from: string;
  to: string;
  q: string;
  result: ArchiveResult;
}

export interface CaseArchiveStats {
  total: number;
  done: number;
  cancel: number;
  avgDurationSec: number;
  avgRejected: number;
  /** 수용 불가 수 ÷ 요청 병원 수 (0~1) */
  rejectRate: number;
  /** 요청 범위가 존 2 이상으로 넓어진 사건 수 */
  zoneExpanded: number;
}

export interface CaseArchiveResponse {
  cases: CaseHistoryItem[];
  total: number;
  stats: CaseArchiveStats;
}

export const ARCHIVE_LIMIT = 200;
export const ARCHIVE_MOCK = process.env.NEXT_PUBLIC_CASE_ARCHIVE_MOCK === "1";

const two = (n: number) => String(n).padStart(2, "0");
export const ymd = (d: Date) => `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}`;
export const daysAgo = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return ymd(d);
};

export function computeStats(cases: CaseHistoryItem[]): CaseArchiveStats {
  const n = cases.length;
  const requested = cases.reduce((a, c) => a + c.requested, 0);
  const rejected = cases.reduce((a, c) => a + c.rejected, 0);
  const dur = cases.reduce((a, c) => a + (Date.parse(c.endedAt) - Date.parse(c.startedAt)) / 1000, 0);
  return {
    total: n,
    done: cases.filter((c) => c.result === "done").length,
    cancel: cases.filter((c) => c.result === "cancel").length,
    avgDurationSec: n ? dur / n : 0,
    avgRejected: n ? rejected / n : 0,
    rejectRate: requested ? rejected / requested : 0,
    zoneExpanded: cases.filter((c) => c.zone >= 2).length,
  };
}

/** 조건에 맞는 사건만, 최근 종료 순. hub 조회가 하는 일을 오늘 실데이터·mock에도 똑같이 적용한다. */
export function filterCases(cases: CaseHistoryItem[], query: CaseArchiveQuery): CaseHistoryItem[] {
  const q = query.q.trim().toLowerCase();
  return cases
    .filter((c) => {
      const day = ymd(new Date(c.endedAt));
      if (day < query.from || day > query.to) return false;
      if (query.result !== "all" && c.result !== query.result) return false;
      if (!q) return true;
      return [c.symptom, c.ambulanceName, c.hospital].some((v) => v?.toLowerCase().includes(q));
    })
    .sort((a, b) => Date.parse(b.endedAt) - Date.parse(a.endedAt));
}

export async function fetchCaseArchive(query: CaseArchiveQuery, signal?: AbortSignal): Promise<CaseArchiveResponse> {
  if (ARCHIVE_MOCK) {
    const all = filterCases(mockArchive(), query);
    return { cases: all.slice(0, ARCHIVE_LIMIT), total: all.length, stats: computeStats(all) };
  }
  const httpUrl = process.env.NEXT_PUBLIC_HUB_HTTP_URL;
  if (!httpUrl) throw new Error("hub 주소가 없어 이전 날짜 기록을 불러올 수 없습니다(목데이터 모드)");
  const params = new URLSearchParams({ from: query.from, to: query.to, q: query.q, result: query.result, limit: String(ARCHIVE_LIMIT) });
  const res = await fetch(`${httpUrl.replace(/\/$/, "")}/case-archive?${params}`, { signal });
  if (res.status === 404) throw new Error("hub에 사건 이력 조회(/case-archive)가 아직 없습니다");
  if (!res.ok) throw new Error(`사건 이력 조회 실패 (${res.status})`);
  return (await res.json()) as CaseArchiveResponse;
}

// ── 가짜 데이터(설계 확인용) ─────────────────────────────────────────────────

const MOCK_DAYS = 30;
const SYMPTOMS: [CaseHistoryItem["severity"], string][] = [
  ["high", "흉통 · 경색 의심"], ["high", "교통사고 다발성 외상"], ["high", "의식 저하 · 뇌졸중 의심"],
  ["medium", "복통 · 구토"], ["medium", "낙상 · 대퇴부 골절 의심"], ["medium", "호흡곤란"],
  ["low", "발목 염좌"], ["low", "열상 · 출혈 조절됨"],
];
const AMBULANCES = ["역삼 구급 1", "성산 구급 1", "회현 구급 2", "마포 구급 1", "송파 구급 3", "노원 구급 1"];
const HOSPITALS = ["서울대학교병원", "서울아산병원", "삼성서울병원", "세브란스병원", "강북삼성병원", "한양대학교병원", "고려대학교안암병원", "중앙대학교병원"];
const CANCEL_REASONS = ["scene_ended", "unresolved_timeout", "retention_expired"];

// 날짜마다 같은 값이 나오게 하는 작은 난수(새로고침해도 목록이 바뀌지 않게)
function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

let mockCache: { day: string; cases: CaseHistoryItem[] } | null = null;
function mockArchive(): CaseHistoryItem[] {
  const todayKey = ymd(new Date());
  if (mockCache?.day === todayKey) return mockCache.cases;
  const out: CaseHistoryItem[] = [];
  for (let back = 0; back < MOCK_DAYS; back++) {
    const day = new Date();
    day.setDate(day.getDate() - back);
    day.setHours(0, 0, 0, 0);
    const key = ymd(day);
    const rand = rng(Number(key.replace(/-/g, "")));
    const pick = <T,>(xs: T[]) => xs[Math.floor(rand() * xs.length)];
    const count = 5 + Math.floor(rand() * 8);
    const items: CaseHistoryItem[] = [];
    for (let i = 0; i < count; i++) {
      const [severity, symptom] = pick(SYMPTOMS);
      const ambulanceName = pick(AMBULANCES);
      const startMs = day.getTime() + Math.floor(rand() * 23 * 3600_000);
      const cancelled = rand() < 0.12;
      const requested = 3 + Math.floor(rand() * 7);
      const rejected = Math.min(requested - (cancelled ? 0 : 1), Math.floor(rand() * rand() * 7));
      const zone = rejected >= 3 || rand() < 0.1 ? 2 + (rand() < 0.2 ? 1 : 0) : 1;
      const hospital = cancelled ? null : pick(HOSPITALS);
      const durationMs = (9 + rand() * 16) * 60_000;
      const at = (frac: number) => new Date(startMs + durationMs * frac).toISOString();
      const events: CaseEvent[] = [
        { t: at(0), kind: "p", text: `${ambulanceName} 출동` },
        { t: at(0.3), kind: "p", text: "현장 도착 · 통화 시작" },
        { t: at(0.4), kind: "s", text: `병원 ${requested}곳에 수용 요청 (존 1)` },
      ];
      for (let r = 0; r < rejected; r++) events.push({ t: at(0.45 + (0.25 * r) / Math.max(1, rejected)), kind: "r", text: `${pick(HOSPITALS)} 수용 불가` });
      if (zone > 1) events.push({ t: at(0.55), kind: "x", text: `요청 범위 확장 → 존 ${zone}` });
      if (!cancelled) {
        events.push({ t: at(0.7), kind: "a", text: `${hospital} 수용 승인` });
        events.push({ t: at(0.75), kind: "t", text: `이송 확정: ${hospital}` });
        events.push({ t: at(1), kind: "d", text: "이송 완료" });
      } else {
        events.push({ t: at(1), kind: "c", text: "상황 취소" });
      }
      events.sort((a, b) => Date.parse(a.t) - Date.parse(b.t));
      items.push({
        caseId: `arc-${key}-${i}`, num: 0, startedAt: at(0), endedAt: at(1), symptom, severity, apid: null, ambulanceName,
        requested, rejected, zone, hospital, result: cancelled ? "cancel" : "done",
        reason: cancelled ? pick(CANCEL_REASONS) : "done", events,
      });
    }
    items.sort((a, b) => Date.parse(a.startedAt) - Date.parse(b.startedAt)).forEach((c, i) => (c.num = i + 1));
    out.push(...items);
  }
  out.sort((a, b) => Date.parse(b.endedAt) - Date.parse(a.endedAt));
  mockCache = { day: todayKey, cases: out };
  return out;
}
