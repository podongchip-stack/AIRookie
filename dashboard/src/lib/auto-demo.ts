import { useEffect, useRef, useState } from "react";
import { haversineKm, type IncHospital, type Incident, type Sev } from "@/lib/control-map";
import type { AmbulanceSimState, MapOverview } from "@/types/dashboard";

// 관제 지도 자동 시연(2026-10-06) — 콘솔로 실제 시연을 하지 않는 동안(진행 중인 실제 사건이 없을 때) 관제 지도 화면
// 안에서만 가짜 사건을 만들어 출동 → 현장 → 병원 응답 → 이송 → 도착 → 복귀를 돌린다. hub로 아무것도 보내지 않아
// 다른 대시보드·의사결정 로그·지난 사건 기록과 무관하다. 실제 사건이 생기면 가짜 사건은 바로 모두 지운다.
// 병원·구급차 위치만 hub의 실제 목록을 쓰고, 증상·응답·시간은 전부 꾸민 값이다.

const SPAWN_EVERY_MS = 14_000;
const MAX_CASES = 3;
const DUR = { dispatching: 8_000, on_scene: 6_000, transporting: 10_000, at_hospital: 5_000, returning: 6_000 };
const ZONE_KM = 5;
const MAX_HOSPITALS = 8;

const SCENES: [Sev, string][] = [
  ["중증", "흉통 · 경색 의심"], ["중증", "교통사고 다발성 외상"], ["중증", "의식 저하 · 뇌졸중 의심"],
  ["중등증", "복통 · 구토"], ["중등증", "낙상 · 대퇴부 골절 의심"], ["중등증", "호흡곤란"],
  ["경증", "발목 염좌"], ["경증", "열상 · 출혈 조절됨"],
];

type Phase = "dispatching" | "on_scene" | "matching" | "transporting" | "at_hospital" | "returning";
type LatLng = { lat: number; lng: number };

interface FakeCase {
  caseId: string;
  num: number;
  sev: Sev;
  sym: string;
  apid: string;
  name: string;
  base: LatLng;
  scene: LatLng;
  startedAt: number;
  phase: Phase;
  phaseAt: number;
  hospitals: IncHospital[];
  zone: number;
  nextResponseAt: number;
  dest: LatLng | null;
  road?: { phase: Phase; path: [number, number][]; at: number };
}

const rand = (a: number, b: number) => a + Math.random() * (b - a);
const pick = <T,>(xs: T[]): T => xs[Math.floor(Math.random() * xs.length)];
const lerp = (a: LatLng, b: LatLng, t: number): LatLng => {
  const k = Math.min(1, Math.max(0, t));
  return { lat: a.lat + (b.lat - a.lat) * k, lng: a.lng + (b.lng - a.lng) * k };
};

/** 존 zone 안쪽 병원(가까운 순, 최대 MAX_HOSPITALS)을 판단 대기로 */
function hospitalsWithin(overview: MapOverview, scene: LatLng, zone: number, already: IncHospital[]): IncHospital[] {
  const have = new Set(already.map((h) => h.hospitalId));
  return overview.hospitals
    .map((h) => ({ h, km: haversineKm(scene, h.gps) }))
    .filter(({ h, km }) => km <= zone * ZONE_KM && !have.has(h.hospitalId))
    .sort((a, b) => a.km - b.km)
    .slice(0, Math.max(0, MAX_HOSPITALS - already.length))
    .map(({ h, km }) => ({
      hospitalId: h.hospitalId, name: h.name, st: "w", bedsFull: false, km, zone: Math.max(1, Math.ceil(km / ZONE_KM)),
      respondedAt: null,
    }));
}

/** 한 단계 진행 — 끝난 사건이면 null */
function advance(c: FakeCase, now: number, overview: MapOverview): FakeCase | null {
  const moving = ["dispatching", "transporting", "returning"].includes(c.phase);
  if (moving && c.road?.phase !== c.phase) return c;
  const elapsed = now - (moving ? c.road!.at : c.phaseAt);
  const next = (phase: Phase, patch: Partial<FakeCase> = {}): FakeCase => ({ ...c, ...patch, phase, phaseAt: now });
  switch (c.phase) {
    case "dispatching":
      return elapsed >= DUR.dispatching ? next("on_scene") : c;
    case "on_scene": {
      if (elapsed < DUR.on_scene) return c;
      let zone = 1;
      let hospitals = hospitalsWithin(overview, c.scene, zone, []);
      while (hospitals.length < 3 && zone < 3) hospitals = hospitalsWithin(overview, c.scene, ++zone, []);
      return next("matching", { hospitals, zone, nextResponseAt: now + rand(2_000, 4_000) });
    }
    case "matching": {
      if (now < c.nextResponseAt) return c;
      const approved = c.hospitals.filter((h) => h.st === "a").sort((a, b) => a.km - b.km);
      const pending = c.hospitals.filter((h) => h.st === "w");
      // 승인 병원이 생기고 조금 지났거나 더 기다릴 병원이 없으면 가장 가까운 승인 병원으로 이송 확정
      if (approved.length && (pending.length === 0 || Math.random() < 0.6)) {
        const dest = approved[0];
        const gps = overview.hospitals.find((h) => h.hospitalId === dest.hospitalId)?.gps ?? null;
        return next("transporting", {
          hospitals: c.hospitals.map((h) => (h.hospitalId === dest.hospitalId ? { ...h, st: "t" } : h)),
          dest: gps,
        });
      }
      if (pending.length === 0) {
        // 전부 거절 — 다음 존으로 넓혀 다시 요청, 더 넓힐 곳이 없으면 가장 가까운 병원이 승인
        const more = c.zone < 3 ? hospitalsWithin(overview, c.scene, c.zone + 1, c.hospitals) : [];
        if (more.length) return { ...c, zone: c.zone + 1, hospitals: [...c.hospitals, ...more], nextResponseAt: now + rand(2_000, 4_000) };
        const nearest = [...c.hospitals].sort((a, b) => a.km - b.km)[0];
        return { ...c, hospitals: c.hospitals.map((h) => (h === nearest ? { ...h, st: "a", respondedAt: new Date(now).toISOString() } : h)), nextResponseAt: now + 2_000 };
      }
      const target = pick(pending);
      const reject = Math.random() < 0.55;
      return {
        ...c,
        hospitals: c.hospitals.map((h) =>
          h === target ? { ...h, st: reject ? "r" : "a", bedsFull: reject && Math.random() < 0.3, respondedAt: new Date(now).toISOString() } : h),
        nextResponseAt: now + rand(2_500, 5_000),
      };
    }
    case "transporting":
      return elapsed >= DUR.transporting ? next("at_hospital") : c;
    case "at_hospital":
      return elapsed >= DUR.at_hospital ? next("returning") : c;
    case "returning":
      return elapsed >= DUR.returning ? null : c;
  }
}

function positionOf(c: FakeCase, now: number): { gps: LatLng; path: [number, number][] | null } {
  const dest = c.dest ?? c.scene;
  const origin = c.phase === "dispatching" ? c.base : c.phase === "returning" ? dest : c.scene;
  if (["dispatching", "transporting", "returning"].includes(c.phase)) {
    if (c.road?.phase !== c.phase) return { gps: origin, path: null };
    const path = c.road.path;
    const lengths = path.slice(1).map((p, i) => haversineKm(
      { lat: path[i][0], lng: path[i][1] }, { lat: p[0], lng: p[1] }));
    const t = Math.min(1, Math.max(0, (now - c.road.at) / DUR[c.phase as keyof typeof DUR]));
    let remaining = lengths.reduce((a, b) => a + b, 0) * t;
    for (let i = 0; i < lengths.length; i++) {
      if (remaining <= lengths[i] || i === lengths.length - 1) {
        return { gps: lerp({ lat: path[i][0], lng: path[i][1] },
          { lat: path[i + 1][0], lng: path[i + 1][1] }, lengths[i] ? remaining / lengths[i] : 1), path };
      }
      remaining -= lengths[i];
    }
  }
  return { gps: c.phase === "at_hospital" ? dest : c.scene, path: null };
}

const SIM_PHASE: Record<Phase, AmbulanceSimState["phase"]> = {
  dispatching: "dispatching", on_scene: "on_scene", matching: "on_scene", transporting: "transporting",
  at_hospital: "at_hospital", returning: "returning",
};

/**
 * active이면 1초마다 가짜 사건을 진행하고 새로 만든다. active가 꺼지면(실제 사건이 생기면) 전부 지운다.
 * 돌려주는 incidents는 관제 지도 사건 목록에, sims는 구급차 위치에 실제 값 대신 얹는다(그 구급차가 기지 대기일 때만 빌린다).
 */
export function useAutoDemo(
  active: boolean,
  overview: MapOverview | null,
  realSim: Record<string, AmbulanceSimState>,
): { incidents: Incident[]; sims: Record<string, AmbulanceSimState> } {
  const [cases, setCases] = useState<FakeCase[]>([]);
  const [now, setNow] = useState(() => Date.now());
  // 진행은 ref에서 계산하고 결과만 state로 넘긴다 — setState 갱신 함수 안에 부작용(생성 시각 기록)을 두면 개발 모드가
  // 갱신 함수를 두 번 불러 새 사건이 사라졌다
  const casesRef = useRef<FakeCase[]>([]);
  const lastSpawnRef = useRef(0);
  const numRef = useRef(0);
  const inputRef = useRef({ overview, realSim });
  useEffect(() => {
    inputRef.current = { overview, realSim };
  }, [overview, realSim]);

  useEffect(() => {
    if (!active) return;
    casesRef.current = []; // 다시 켜질 때는 지난 가짜 사건을 버리고 새로 시작한다
    let cancelled = false;
    const pending = new Set<string>();
    const retryAt = new Map<string, number>();
    const tick = () => {
      const t = Date.now();
      const { overview: ov, realSim: sims } = inputRef.current;
      setNow(t);
      if (!ov) return;
      {
        // 실제로 출동한 구급차를 빌리고 있던 가짜 사건은 바로 끝낸다
        let next = casesRef.current
          .filter((c) => !sims[c.apid]?.caseId)
          .map((c) => advance(c, t, ov))
          .filter((c): c is FakeCase => c !== null);
        if (next.length < MAX_CASES && t - lastSpawnRef.current >= SPAWN_EVERY_MS) {
          const busy = new Set(next.map((c) => c.apid));
          const idle = ov.ambulances.filter((a) => !busy.has(a.apid) && !sims[a.apid]?.caseId && (sims[a.apid]?.phase ?? "idle") === "idle");
          if (idle.length) {
            lastSpawnRef.current = t;
            const a = pick(idle);
            const angle = rand(0, Math.PI * 2);
            const km = rand(1.5, 3.5);
            const scene = { lat: a.base.lat + (km / 111) * Math.sin(angle), lng: a.base.lng + (km / 88) * Math.cos(angle) };
            const [sev, sym] = pick(SCENES);
            numRef.current += 1;
            next = [...next, {
              caseId: `auto-${t}`, num: numRef.current, sev, sym, apid: a.apid, name: a.name, base: a.base, scene,
              startedAt: t, phase: "dispatching", phaseAt: t, hospitals: [], zone: 0, nextResponseAt: 0, dest: null,
            }];
          }
        }
        for (const c of next) {
          if (!["dispatching", "transporting", "returning"].includes(c.phase) || c.road?.phase === c.phase) continue;
          const key = `${c.caseId}:${c.phase}`;
          if (pending.has(key) || t < (retryAt.get(key) ?? 0)) continue;
          pending.add(key);
          const origin = c.phase === "dispatching" ? c.base : c.phase === "returning" ? c.dest ?? c.scene : c.scene;
          const dest = c.phase === "dispatching" ? c.scene : c.phase === "returning" ? c.base : c.dest ?? c.scene;
          void (async () => {
            try {
              const r = await fetch("/api/demo/route", { method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ origin, dest }), signal: AbortSignal.timeout(18000) });
              const data = await r.json();
              if (!r.ok || !Array.isArray(data.path) || data.path.length < 2
                || !data.path.every((p: number[]) => Array.isArray(p) && p.length === 2 && p.every(Number.isFinite))) return;
              if (cancelled) return;
              casesRef.current = casesRef.current.map(v => v.caseId === c.caseId && v.phase === c.phase
                ? { ...v, road: { phase: c.phase, path: data.path, at: Date.now() } } : v);
            } catch { /* 도로 조회 실패 시 정차한 채 재시도한다. */ }
            finally { pending.delete(key); retryAt.set(key, Date.now() + 10000); }
          })();
        }
        casesRef.current = next;
        setCases(next);
      }
    };
    tick();
    const timer = setInterval(tick, 1000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [active]);

  const incidents: Incident[] = [];
  const sims: Record<string, AmbulanceSimState> = {};
  for (const c of active ? cases : []) {
    const { gps, path } = positionOf(c, now);
    const dest = c.hospitals.find((h) => h.st === "t");
    sims[c.apid] = {
      type: "ambulance_position", apid: c.apid, caseId: c.phase === "returning" ? null : c.caseId,
      phase: SIM_PHASE[c.phase], gps, heading: 0, etaSec: null, path, base: c.base, incident: c.scene,
      hospitalId: dest?.hospitalId ?? null, simulated: true,
    };
    if (c.phase === "returning") continue; // 복귀 중이면 사건은 끝난 것 — 목록에서 빠진다(실제와 같다)
    const matched = c.phase !== "dispatching" && c.phase !== "on_scene";
    incidents.push({
      caseId: c.caseId, num: c.num, sev: c.sev, sym: c.sym, name: c.name, apid: c.apid, startedAt: c.startedAt,
      center: c.scene, matched, phase: SIM_PHASE[c.phase], hospitals: c.hospitals, zone: matched ? c.zone : 0,
      zoneStart: matched ? 1 : 0, zoneBandKm: ZONE_KM, events: [], zoneExpandAt: null, zonePausedLeft: null, fake: true,
    });
  }
  return { incidents, sims };
}
