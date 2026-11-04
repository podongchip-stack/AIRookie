"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { ControlMapPanel } from "@/components/map/ControlMapPanel";
import { CONNECTION_LABEL, useDashboardSocket } from "@/hooks/use-dashboard-socket";
import {
  AMB_CHIP, AMB_RANK, SIDEBAR_W, C, GLASS, GLASS_BLOBS, EVENT_TONE, LEVEL_FILTERS, LEVEL_DEFAULT, LEVEL_DOT, SEV_STYLE, ST_DOT, ST_LABEL,
  ambState, buildIncidents, counts, fmtClock, fmtElapsed, fmtHm, fmtMd, haversineKm, pastResult, sevOf, shortAmb, shortHospital,
  stageOf, zoneText,
  type AmbKey, type Incident, type St,
} from "@/lib/control-map";
import type { CaseHistoryItem } from "@/types/dashboard";
import { useCaseArchive } from "@/hooks/use-case-archive";
import { useControlAlerts } from "@/hooks/use-control-alerts";
import { RejectionStatsModal } from "@/components/map/RejectionStatsModal";
import { AssignmentModal } from "@/components/map/AssignmentModal";
import { CaseDetailPanel } from "@/components/map/CaseDetailPanel";
import { MciRegisterModal } from "@/components/map/MciRegisterModal";
import { HospitalDetailModal } from "@/components/map/HospitalDetailModal";
import { HandlingActions, resultNotice } from "@/components/map/HandlingActions";
import { isConfirmDelayed, isTransportStalled } from "@/lib/control-alerts";
import { AlertStack, topAlertOf, useAlertTabTitle } from "@/components/map/ControlAlerts";
import { ARCHIVE_MOCK, daysAgo, type ArchiveResult } from "@/lib/case-archive";
import { DemoVideoOverlay } from "@/components/ui/DemoVideoOverlay";
import { useAutoDemo } from "@/lib/auto-demo";

// 관제 지도(2026-10-03 신설, 2026-10-04 디자인 시안 "골든링크 관제"로 전면 개편). hub에 role=monitor로 붙어
// 사건 요약·구급차 위치만 받는다 — 통화 전문 등 환자 상세는 받지 않는다(증상은 한 줄뿐).
// 병원 대시보드는 첫 페이지에서 접근 코드로 연다(병원 점에 마우스를 올리면 H-코드가 보인다).
//
// 왼쪽: 진행 사건 3건 스크롤 + 구급차 / 오른쪽: 전체 병원 기본 정보·규칙 기반 KTAS 범위.
// 가운데 지도는 두 패널의 가림 영역을 제외해 사건을 조준한다.
// 위치·존·상태는 전부 규칙 기반이고, 구급차 위치는 시연용 시뮬레이션이다.

// 3D 거미줄(spider/serve.py, 포트 2700) 실시간 화면. 배포 도메인에선 같은 호스트의 /spider/ 아래로 열려 있고,
// 로컬 개발(3000)에선 NEXT_PUBLIC_SPIDER_URL(예: http://localhost:2700/spider/)로 덮어쓴다.
// 거미줄 파일(spider/web)을 고치면 SPIDER_BUILD와 spider/web/index.html의 ?v=를 같이 올린다 — 공개 도메인이 .js를 4시간 캐시해서 주소가 바뀌어야 새 파일을 받는다.
const SPIDER_BUILD = "20261104-ktas1";
const SPIDER_URL = `${process.env.NEXT_PUBLIC_SPIDER_URL ?? (process.env.NODE_ENV === "development" ? "/spider/index.html" : "/spider/")}?mode=live&embed=1&v=${SPIDER_BUILD}`;

type MapView = "2d" | "3d";
type Tab = "all" | St;

const LEGEND_LEVELS: [string, string][] = [
  [LEVEL_DOT["권역응급의료센터"], "권역센터 (중증)"],
  [LEVEL_DOT["지역응급의료센터"], "지역센터 (중등증)"],
  [LEVEL_DEFAULT, "응급의료기관 (경증)"],
];

export default function MonitorMapPage() {
  const { state, connectionMode, sendAction, sendConfirmRequest, sendRaw, sendZoneExpand, sendAlternativesRequest, sendDirectTransport } = useDashboardSocket({ role: "monitor", id: "map" });
  const [leftTab, setLeftTab] = useState<"case" | "amb">("case");
  const [showMci, setShowMci] = useState(false);
  // 병원 상세(2026-11-04) — 오른쪽 병원 목록·사건 상세의 병원 줄·지도 병원 점을 누르면 연다
  const [detailHospital, setDetailHospital] = useState<string | null>(null);
  // 오른쪽 병원 목록·지도의 등급 필터(2026-11-04) — null이면 전체
  const [levelFilter, setLevelFilter] = useState<string | null>(null);
  const shownHospitals = (state.mapOverview?.hospitals ?? []).filter((h) => !levelFilter || h.emergencyLevel === levelFilter);
  // 상황실 배정 요청(2026-11-04) — hub가 1순위 수용 병원 겹침 + 여력 부족을 묶어 보낸다. 새 묶음이 생기면 모달을 자동으로 연다.
  const assignmentGroups = state.assignmentGroups;
  const assignmentCount = assignmentGroups.reduce((n, g) => n + g.caseIds.length, 0);
  const [showAssign, setShowAssign] = useState(false);
  const assignKey = assignmentGroups.map((g) => `${g.hospitalId}:${g.caseIds.join(",")}`).join("|");
  const [seenAssignKey, setSeenAssignKey] = useState("");
  if (assignKey !== seenAssignKey) {  // 렌더 중 이전 값과 비교 — 묶음이 새로 생기거나 바뀌면 열고, 없어지면 닫는다
    setSeenAssignKey(assignKey);
    setShowAssign(assignKey !== "");
  }
  const dispatchTo = useCallback((caseId: string, hospitalId: string) => {
    sendAction({ caseId, action: "final_approval", hospital_id: hospitalId, actor: "dispatcher", timestamp: new Date().toISOString() });
  }, [sendAction]);
  const overview = state.mapOverview;
  const [now, setNow] = useState(() => Date.now());
  const [selId, setSelId] = useState<string>("");
  const [tab, setTab] = useState<Tab>("all");
  const [ambQuery, setAmbQuery] = useState("");
  const [standbyOpen, setStandbyOpen] = useState(false);       // 기지 대기 전체 목록 펼침
  const [standbyOnMap, setStandbyOnMap] = useState(false);     // 지도에 기지 대기 구급차 전부 표시
  const [hoverHospital, setHoverHospital] = useState("");
  const [hoverAmb, setHoverAmb] = useState("");
  const [view, setView] = useState<MapView>("3d");   // 기본은 3D 거미줄(다크). 거미줄 서버가 안 뜨면 아래 점검이 2D로 돌려보낸다
  const dark = view === "3d";
  const [spiderReady, setSpiderReady] = useState(false);
  const spiderRef = useRef<HTMLIFrameElement | null>(null);
  const [showPast, setShowPast] = useState(false);
  // 브라우저 전체 화면(F11과 별개로 버튼 한 번) — Esc로 나가도 상태가 맞도록 fullscreenchange를 따른다
  const [fullscreen, setFullscreen] = useState(false);
  useEffect(() => {
    const sync = () => setFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", sync);
    return () => document.removeEventListener("fullscreenchange", sync);
  }, []);
  const toggleFullscreen = useCallback(() => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void document.documentElement.requestFullscreen?.();
  }, []);
  // 시연 콘솔의 원격 조작(2026-11-03) — 2D/3D는 바로 따른다. 전체 화면은 브라우저가 사용자 조작 없이는 막으므로 먼저 시도하고,
  // 막히면 이 화면에 눌러 달라는 안내를 띄운다(콘솔에서 보낸 요청이 조용히 사라지지 않게).
  const [fullscreenAsk, setFullscreenAsk] = useState(false);
  const mapCommand = state.mapCommand;
  useEffect(() => {
    if (!mapCommand) return;
    if (mapCommand.view) setView(mapCommand.view);
    if (mapCommand.fullscreen === "exit") {
      setFullscreenAsk(false);
      if (document.fullscreenElement) void document.exitFullscreen();
    } else if (mapCommand.fullscreen === "enter" && !document.fullscreenElement) {
      document.documentElement.requestFullscreen?.().then(() => setFullscreenAsk(false)).catch(() => setFullscreenAsk(true));
    }
  }, [mapCommand]);
  const [showReject, setShowReject] = useState(false);
  useEffect(() => {
    if (!mapCommand) return;
    if (mapCommand.panel === "past") { setShowReject(false); setShowPast(true); }
    else if (mapCommand.panel === "reject") { setShowPast(false); setShowReject(true); }
    else if (mapCommand.panel === "close") { setShowPast(false); setShowReject(false); }
    if (mapCommand.standby) setStandbyOnMap(mapCommand.standby === "on");
  }, [mapCommand]);
  // 사건별로 마지막으로 본 시각 — 그 뒤의 병원 응답이 "새 N"
  const [seenAt, setSeenAt] = useState<Record<string, number>>({});
  const [mountedAt] = useState(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const realIncidents = useMemo(
    () => buildIncidents({
      monitorCases: state.monitorCases, caseMeta: state.caseMeta, preAlerts: state.preAlerts,
      ambulanceSim: state.ambulanceSim, overview,
    }),
    [state.monitorCases, state.caseMeta, state.preAlerts, state.ambulanceSim, overview],
  );
  // 자동 시연(2026-10-06) — 실제 사건이 없는 동안만 이 화면 안에서 가짜 사건을 돌린다.
  // hub·다른 대시보드·로그와 무관하고, 실제 사건이 생기면 가짜 사건은 바로 모두 사라진다(lib/auto-demo.ts).
  const demo = useAutoDemo(realIncidents.length === 0, overview, state.ambulanceSim);
  const incidents = useMemo(() => [...realIncidents, ...demo.incidents], [realIncidents, demo.incidents]);
  const ambulanceSim = useMemo(() => ({ ...state.ambulanceSim, ...demo.sims }), [state.ambulanceSim, demo.sims]);
  const selected = incidents.find((i) => i.caseId === selId) ?? incidents[0] ?? null;

  // 사건을 누를 때마다 올리는 값 — 이미 고른 사건을 다시 눌러도 지도가 그 사건으로 줌인하게 한다(선택이 안 바뀌면 지도 효과가 안 돌았다)
  const [focusNonce, setFocusNonce] = useState(0);
  const selectCase = useCallback((caseId: string) => {
    setFocusNonce((n) => n + 1);
    setSelId(caseId);
    setLeftTab("case");
    setTab("all");
    setSeenAt((prev) => ({ ...prev, [caseId]: Date.now() }));
  }, []);

  // 콘솔로 새 실제 사건이 생기면 그 사건을 바로 고른다 — 지도도 그 사건 단계에 맞춰 자동으로 맞춰진다(ControlMapPanel)
  const knownRealRef = useRef<Set<string> | null>(null);
  useEffect(() => {
    const ids = realIncidents.map((i) => i.caseId);
    const known = knownRealRef.current;
    knownRealRef.current = new Set(ids);
    if (!known) return; // 처음 열 때 이미 있던 사건은 고르지 않는다
    const fresh = ids.filter((id) => !known.has(id));
    if (fresh.length) selectCase(fresh[fresh.length - 1]);
  }, [realIncidents, selectCase]);

  // 선택한 사건은 보는 중이므로 새 응답을 바로 본 것으로 친다
  const selectedId = selected?.caseId;
  const unseenOf = (inc: Incident) => {
    if (inc.caseId === selectedId) return 0;
    const since = seenAt[inc.caseId] ?? mountedAt;
    return inc.hospitals.filter((h) => h.st !== "w" && h.respondedAt && Date.parse(h.respondedAt) > since).length;
  };

  // ── 구급차 ──
  const ambulances = useMemo(() => overview?.ambulances ?? [], [overview]);
  const center = selected?.center ?? null;
  const ambRows = useMemo(() => {
    return ambulances.map((a) => {
      const sim = ambulanceSim[a.apid];
      const st = ambState(sim);
      const gps = sim?.gps ?? a.gps;
      const km = center ? haversineKm(center, gps) : null;
      return { apid: a.apid, name: a.name, key: st.key, text: st.text, km };
    });
  }, [ambulances, ambulanceSim, center]);
  // 움직이는 구급차(현장·출동·이송 중)를 먼저, 기지 대기는 접어 두고 선택한 사건에서 가까운 5대만(2026-11-01)
  const sortAmb = (list: typeof ambRows) =>
    [...list].sort((p, q) => AMB_RANK[p.key] - AMB_RANK[q.key] || (p.km ?? 1e9) - (q.km ?? 1e9) || p.name.localeCompare(q.name));
  const activeAmbs = sortAmb(ambRows.filter((r) => r.key !== "b"));
  const standbyAmbs = sortAmb(ambRows.filter((r) => r.key === "b"));
  const nearStandby = standbyAmbs.slice(0, 5);
  const ambQ = ambQuery.trim().toLowerCase();
  const ambHits = ambQ ? sortAmb(ambRows.filter((r) => r.name.toLowerCase().includes(ambQ))) : [];
  // 지도에 보이는 구급차: 움직이는 것 + 가까운 대기 5대 + 검색 결과(토글을 켜면 대기 전부)
  const ambShown = new Set([
    ...ambRows.filter((r) => r.key !== "b" || standbyOnMap), ...nearStandby, ...ambHits,
  ].map((r) => r.apid));
  const ambVisible = (apid: string) => ambShown.has(apid);
  const ambCount: Record<AmbKey, number> = { s: 0, d: 0, t: 0, b: 0 };
  for (const r of ambRows) ambCount[r.key]++;
  const renderAmb = (a: (typeof ambRows)[number]) => {
    const on = hoverAmb === a.apid;
    return (
      <div
        key={a.apid}
        onMouseEnter={() => setHoverAmb(a.apid)}
        onMouseLeave={() => setHoverAmb("")}
        style={{ ...acellStyle, flex: "none", background: on ? GLASS.tint : a.key === "s" ? "#FFF4EC" : undefined }}
      >
        <span title={a.name} style={{ flex: "1 1 auto", minWidth: 0, fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis" }}>{shortAmb(a.name)}</span>
        <span style={{ flex: "none", color: C.sub, fontSize: 12, minWidth: 38, textAlign: "right" }}>
          {a.km == null ? "" : a.km < 0.05 ? "현장" : `${a.km.toFixed(1)}km`}
        </span>
        <span style={{ flex: "none", width: 62, textAlign: "center", fontSize: 11.5, lineHeight: "17px", borderRadius: 3, ...AMB_CHIP[a.key] }}>{a.text}</span>
      </div>
    );
  };

  // ── 선택한 사건의 병원 ──
  const selCounts = selected ? counts(selected) : { w: 0, r: 0, a: 0, t: 0 };
  const tabDefs: [Tab, string, number][] = [
    ["all", "전체", selected?.hospitals.length ?? 0],
    ["w", "판단 대기", selCounts.w],
    ["r", "수용 불가", selCounts.r],
    ["a", "수용 승인", selCounts.a],
  ];
  if (selCounts.t > 0) tabDefs.push(["t", "이송 확정", selCounts.t]);
  const activeTab: Tab = tabDefs.some((d) => d[0] === tab) ? tab : "all";
  const sevCount = { 중증: 0, 중등증: 0, 경증: 0 };
  for (const inc of incidents) if (inc.sev) sevCount[inc.sev]++;

  const past = state.caseHistory;
  const live = connectionMode === "live";
  // 관제 판단 대기 사건 → 시작 시각(대기 시간 알림, 2026-11-04)
  const assignOpened = useMemo(() => {
    const out: Record<string, string> = {};
    for (const g of assignmentGroups) for (const c of g.caseIds) if (g.openedAt) out[c] = g.openedAt;
    return out;
  }, [assignmentGroups]);
  const alertView = useControlAlerts(incidents, live, assignOpened);

  // ── 3D 거미줄과의 연동(2026-11-01) — 같은 도메인의 iframe이라 거미줄 화면의 함수를 직접 부른다 ──
  type SpiderWin = Window & {
    setViewInsets?: (i: { left: number; right: number; top: number; bottom: number }) => void;
    focusPoint?: (lat: number, lng: number) => void;
    setSelectedCase?: (caseId: string | null) => void;
  };
  const spiderWin = useCallback(() => spiderRef.current?.contentWindow as SpiderWin | null | undefined, []);
  const selectedCaseRef = useRef(selectedId);
  useEffect(() => {
    selectedCaseRef.current = selectedId;
    if (view === "3d") spiderWin()?.setSelectedCase?.(selectedId ?? null);
  }, [selectedId, view, spiderWin]);
  // 패널이 덮은 폭을 알려 줘서, 카메라가 가려지지 않은 가운데에 목표를 놓게 한다
  const pushInsets = useCallback(() => {
    const w = spiderRef.current?.contentWindow as SpiderWin | null | undefined;
    if (!w?.setViewInsets) return false;
    const edge = (side: string) => document.querySelector<HTMLElement>(`[data-map-cover="${side}"]`)?.getBoundingClientRect();
    const l = edge("left"), r = edge("right"), t = edge("top");
    w.setViewInsets({ left: l ? l.right : 0, right: r ? window.innerWidth - r.left : 0, top: t ? t.bottom : 0, bottom: 0 });
    return true;
  }, []);
  const selCenter = selected?.center ?? null;
  // 2D(ControlMapPanel.focusTarget)와 같은 규칙으로 "지금 보여야 할 점들"을 고른다 — 출동 중이면 현장+구급차, 병원 요청 중이면 요청 병원들,
  // 이송 중이면 구급차+병원, 도착이면 병원. 이동 경로가 짧으면 거미줄이 더 가까이 확대한다.
  const focusPointsOf = (): { lat: number; lng: number }[] => {
    const sel = selected;
    if (!sel?.center) return [];
    const sim = sel.apid ? ambulanceSim[sel.apid] : undefined;
    const gpsOf = (id: string) => overview?.hospitals.find((h) => h.hospitalId === id)?.gps ?? null;
    const dest = sel.hospitals.find((h) => h.st === "t");
    const destGps = dest ? gpsOf(dest.hospitalId) : null;
    if (sim?.phase === "at_hospital" && destGps) return [destGps];
    if (sim?.phase === "transporting" && destGps && sim.gps) return [sim.gps, destGps];
    if (sim?.phase === "dispatching" && sim.gps) return [sel.center, sim.gps];
    if (sel.matched && !destGps) {
      const req = sel.hospitals.map((h) => gpsOf(h.hospitalId)).filter((g): g is { lat: number; lng: number } => g != null);
      return [sel.center, ...req];
    }
    return [sel.center];
  };
  const focusRef = useRef(focusPointsOf);
  useEffect(() => { focusRef.current = focusPointsOf; });
  // 다수 사상자 신고 모달의 [3D 거미줄로 보기](2026-11-04) — 3D가 뜨면 사고 지점으로 카메라를 옮긴다
  const pendingFocusRef = useRef<{ lat: number; lng: number } | null>(null);
  const focusSelected = useCallback(() => {
    if (!pushInsets()) return;
    const pending = pendingFocusRef.current;
    if (pending) {
      pendingFocusRef.current = null;
      spiderWin()?.focusPoint?.(pending.lat, pending.lng);
      return;
    }
    spiderWin()?.setSelectedCase?.(selectedCaseRef.current ?? null);
    const pts = focusRef.current();
    if (pts.length === 0) return;
    const w = spiderWin() as (SpiderWin & { focusPoints?: (p: { lat: number; lng: number }[]) => void }) | null | undefined;
    if (w?.focusPoints) w.focusPoints(pts);
    else if (pts[0]) w?.focusPoint?.(pts[0].lat, pts[0].lng);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pushInsets]);
  // 사건을 고르거나(다시 눌러도) 사건 단계가 바뀌면(출동→병원 요청→이송→도착) 거미줄 카메라를 맞춘다 — 카드에 가리지 않는 가운데에
  const selSimPhase = selected?.apid ? ambulanceSim[selected.apid]?.phase : undefined;
  const selConfirmed = selected?.hospitals.find((h) => h.st === "t")?.hospitalId ?? "";
  const focusKey3d = selected ? `${selected.caseId}|${selSimPhase ?? ""}|${selected.matched}|${selConfirmed}|${selected.zone}|${focusNonce}|${selCenter?.lat},${selCenter?.lng}` : "";
  useEffect(() => {
    if (view === "3d" && focusKey3d) focusSelected();
  }, [view, focusKey3d, focusSelected]);
  // 2D로 돌아오면 지도 칸이 숨겨져 있던 동안 크기가 0이라 포커스가 엉뚱한 곳에 맞았다 — 칸이 다시 보인 뒤 한 번 더 맞춘다
  useEffect(() => {
    if (view !== "2d") return;
    const t = setTimeout(() => setFocusNonce((n) => n + 1), 150);
    return () => clearTimeout(t);
  }, [view]);
  useEffect(() => {
    const onResize = () => { if (view === "3d") pushInsets(); };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [view, pushInsets]);
  // 서버 확인 전에 iframe을 열면 프록시 500 오류 문서가 남는다. 정상 응답 뒤에만 연다.
  // 일시적인 네트워크 흔들림은 3번 재시도하고, 실패하면 2D로 돌아간다.
  useEffect(() => {
    if (view !== "3d") return;
    const ctl = new AbortController();
    (async () => {
      for (let i = 0; i < 3; i++) {
        try {
          const r = await fetch(SPIDER_URL, { method: "HEAD", cache: "no-store", signal: ctl.signal });
          if (r.ok) {
            if (!ctl.signal.aborted) setSpiderReady(true);
            return;
          }
        } catch (e) {
          if ((e as Error)?.name === "AbortError") return;
        }
        await new Promise((res) => setTimeout(res, 1500));
        if (ctl.signal.aborted) return;
      }
      setView("2d");
    })();
    return () => ctl.abort();
  }, [view]);
  useAlertTabTitle(new Set(alertView.alerts.map((a) => a.caseId ?? a.key)).size);
  // 알림이 걸린 사건은 목록 맨 위에 고정하고 지도 마커를 강조한다. 알림은 오른쪽 위 카드로 쌓이고 색으로 등급을 나눈다(빨강 긴급·새 사건 / 주황 주의 / 회색 시스템).
  const alertCaseIds = useMemo(() => new Set(alertView.alerts.flatMap((a) => (a.caseId ? [a.caseId] : []))), [alertView.alerts]);
  const listIncidents = useMemo(
    () => [...incidents].sort((p, q) => Number(alertCaseIds.has(q.caseId)) - Number(alertCaseIds.has(p.caseId))),
    [incidents, alertCaseIds],
  );
  // 실제 사건에 새 긴급 알림이 생기면 그 사건으로 지도·목록을 바로 옮긴다(사람이 놓치지 않게)
  const prevUrgentRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    const now = new Set(alertView.alerts.filter((a) => a.level === "urgent" && !a.fake && a.caseId).map((a) => a.key));
    const fresh = alertView.alerts.find((a) => a.level === "urgent" && !a.fake && a.caseId && !prevUrgentRef.current.has(a.key));
    prevUrgentRef.current = now;
    if (fresh?.caseId) selectCase(fresh.caseId);
  }, [alertView.alerts, selectCase]);

  return (
    <div style={{ position: "fixed", inset: 0, overflow: "hidden", background: C.bg, color: C.ink, whiteSpace: "nowrap", fontFamily: GLASS.font }}>
      {/* 발표 자료와 같은 흐린 파스텔 원 — 지도가 덮지 않는 곳·지도가 뜨기 전에 보인다 */}
      <div aria-hidden style={{ position: "absolute", inset: 0, overflow: "hidden", pointerEvents: "none" }}>
        {GLASS_BLOBS.map((b, i) => (
          <span key={i} style={{ position: "absolute", left: b.left, top: b.top, width: b.size, height: b.size, borderRadius: "50%", background: `radial-gradient(circle, ${b.color} 0%, transparent 68%)`, filter: "blur(40px)" }} />
        ))}
      </div>
      {/* 시연 영상 모드(2026-10-06) — 관제 지도는 ijs.mp4를 반복 재생(2026-10-08, /verify/stage 순환 없음) */}
      <DemoVideoOverlay src="/demo-videos/ijs.mp4" />
      {fullscreenAsk && !fullscreen && (
        <button
          type="button"
          onClick={() => { setFullscreenAsk(false); toggleFullscreen(); }}
          style={{ position: "absolute", top: 70, left: "50%", transform: "translateX(-50%)", zIndex: 50, ...toolBtnStyle, background: C.navy, color: "#fff", boxShadow: "0 4px 16px rgba(0,0,0,.3)" }}
        >
          시연 콘솔이 전체 화면을 요청했습니다 — 눌러서 켜기
        </button>
      )}
      <div style={{ position: "absolute", inset: 0, boxSizing: "border-box", padding: 18, display: "flex", flexDirection: "column", gap: 14 }}>
        {/* 헤더 + 범례 */}
        <Glass as="header" dark={dark} data-map-cover="top" style={{ position: "relative", zIndex: 10, flex: "none", borderRadius: GLASS.radius, padding: "12px 22px", gap: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <Link href="/" style={{ fontSize: 19, fontWeight: 900, letterSpacing: "-0.02em", color: C.navy }}>골든링크</Link>
            <div style={{ width: 1, height: 16, background: C.line }} />
            <div style={{ fontSize: 13, color: C.ink3 }}>관제 지도 · 병원·구급차 실시간 위치</div>
            <div style={{ flex: "1 1 0" }} />
            <button type="button" aria-label="지난 사건 보기" onClick={() => setShowPast(true)} style={toolBtnStyle}>
              지난 사건 <b style={{ fontWeight: 900 }}>오늘 {past.length}</b>
            </button>
            <span title="골든링크 AI 에이전트 — 인식(휴대폰·서버 AI) → 판단·행동·학습(규칙). 최종 결정은 상황실" style={{ display: "inline-flex", alignItems: "center", gap: 6, height: 28, padding: "0 12px", borderRadius: 999, background: GLASS.tint, color: C.blue, fontSize: 12, fontWeight: 700 }}>
              <span className="ctl-live" style={{ width: 7, height: 7, borderRadius: "50%", background: C.blue }} />
              AI 에이전트 작동 중 · 사건 {realIncidents.length}
              {state.assignmentStats && state.assignmentStats.decided > 0 && ` · 제안 채택 ${state.assignmentStats.followed}/${state.assignmentStats.decided}`}
            </span>
            <button type="button" onClick={() => setShowMci(true)} style={{ ...toolBtnStyle, borderColor: C.blue, color: C.blue, fontWeight: 700 }}>다수 사상자 신고</button>
            {assignmentCount > 0 && (
              <button type="button" onClick={() => setShowAssign(true)} style={{ ...toolBtnStyle, background: "#D93025", borderColor: "#D93025", color: "#fff", fontWeight: 900 }}>
                배정 요청 {assignmentCount}건
              </button>
            )}
            <button type="button" onClick={() => setShowReject(true)} style={toolBtnStyle}>거절 사유 통계</button>
            <button type="button" aria-pressed={fullscreen} onClick={toggleFullscreen} style={toolBtnStyle}>{fullscreen ? "전체 화면 종료" : "전체 화면"}</button>
            <div role="tablist" aria-label="지도 보기" style={{ display: "flex", gap: 4 }}>
              {([["2d", "2D 지도"], ["3d", "3D 거미줄"]] as [MapView, string][]).map(([key, label]) => {
                const on = view === key;
                return (
                  <button
                    key={key}
                    type="button"
                    role="tab"
                    aria-selected={on}
                    onClick={() => { if (key === "3d" && view !== "3d") setSpiderReady(false); setView(key); }}
                    style={{ ...tab2Style, ...(on ? { background: C.navy, color: "#fff" } : { background: C.bg, color: C.ink2 }) }}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 14, fontSize: 12.5, color: C.ink2, flexWrap: "wrap", rowGap: 6 }}>
            {LEGEND_LEVELS.map(([color, label]) => (
              <span key={label} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ width: 14, height: 14, boxSizing: "border-box", borderRadius: "50%", background: color, border: `2px solid ${color}`, boxShadow: "inset 0 0 0 2px #fff" }} />
                {label}
              </span>
            ))}
            <Divider />
            {(["w", "a", "r", "t"] as St[]).map((st) => (
              <span key={st} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ width: 18, height: 18, borderRadius: "50%", background: st === "w" ? "#F6C21B" : ST_DOT[st], display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <StatusIcon st={st} color="#fff" />
                </span>
                {ST_LABEL[st]}
              </span>
            ))}
            <Divider />
            <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ width: 16, height: 16, borderRadius: 4, background: C.orange, display: "flex", alignItems: "center", justifyContent: "center" }}>
                <svg width="9" height="9" viewBox="0 0 9 9" aria-hidden="true"><path d="M4.5 0v9M0 4.5h9" stroke="#fff" strokeWidth="2.4" /></svg>
              </span>
              구급차 (시뮬레이션 위치)
            </span>
            <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ width: 16, height: 16, boxSizing: "border-box", borderRadius: "50%", border: `1.5px dashed ${C.zone}` }} />
              요청 존 범위
            </span>
            <span style={{ flex: "1 1 0" }} />
            <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, fontWeight: 500, color: live ? "#168A55" : "#C75B00" }}>
              <span className={live ? "ctl-live" : undefined} style={{ width: 7, height: 7, borderRadius: "50%", background: live ? "#168A55" : "#B0B7C2" }} />
              {CONNECTION_LABEL[connectionMode].text.replace(/^[●◌○]\s*/, "")}
            </span>
          </div>
        </Glass>
        {/* 관제 알림 카드 — 헤더 바로 아래 기준점에서 아래로 쌓인다(높이 0) */}
        <div style={{ position: "relative", flex: "none", height: 0, marginTop: -14, zIndex: 250 }}>
          <AlertStack dark={dark} alerts={alertView.alerts} incidents={incidents} onAck={alertView.ack} onAckAll={alertView.ackAll} onOpen={selectCase} onHandle={(caseId, keys) => { alertView.startHandling(caseId, keys); selectCase(caseId); }} />
        </div>
        <style>{"@keyframes ctlbl{0%,100%{opacity:1}50%{opacity:.3}}.ctl-live{animation:ctlbl 1.6s infinite}@keyframes ctlnew{0%,100%{background:#fff}50%{background:#FFD9D5}}.ctl-new{animation:ctlnew 1s ease-in-out 10;border-color:#D93025!important}.ctl-scroll{overflow-y:auto;scrollbar-width:thin;scrollbar-color:#CFC6F5 transparent}.ctl-scroll::-webkit-scrollbar{width:6px}.ctl-scroll::-webkit-scrollbar-thumb{background:#CFC6F5;border-radius:3px}"}</style>

        <div style={{ flex: "1 1 0", minHeight: 0, display: "flex", gap: 16 }}>
          {/* 왼쪽: 진행 중인 사건 · 지난 사건 · 선택한 사건의 병원 */}
          <aside data-map-cover="left" style={{ position: "relative", zIndex: 10, flex: "none", width: SIDEBAR_W, height: "100%", display: "flex", flexDirection: "column", gap: 12, minHeight: 0 }}>
            <Glass dark={dark} style={{ ...cardStyle, flex: "none", gap: 6 }}>
              <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", padding: "0 2px" }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: C.navy }}>진행 중인 사건 {incidents.length}건</div>
                <div style={{ fontSize: 11.5, color: C.sub }}>중증 {sevCount.중증} · 중등증 {sevCount.중등증} · 경증 {sevCount.경증}</div>
              </div>

              <div style={{ position: "relative", flex: "none" }}>
                <DragScroll label="진행 중인 사건 목록" style={{ maxHeight: 3 * 62 + 2 * 5, overflowY: incidents.length > 3 ? "auto" : "hidden", display: "flex", flexDirection: "column", gap: 5, paddingRight: 6, scrollSnapType: "y mandatory" }}>
                  {incidents.length === 0 && (
                    <div style={{ padding: "28px 12px", textAlign: "center", fontSize: 12.5, color: C.muted, whiteSpace: "normal" }}>
                      진행 중인 사건이 없습니다. 신고가 접수되면(구급대 출동) 여기에 뜹니다.
                    </div>
                  )}
                  {listIncidents.map((inc) => {
                    const on = inc.caseId === selected?.caseId;
                    const c = counts(inc);
                    const stage = stageOf(inc);
                    const alert = topAlertOf(alertView.alerts, inc.caseId);
                    const alertRed = alert?.level === "urgent" || alert?.level === "info";
                    const unseen = unseenOf(inc);
                    return (
                      <button
                        key={inc.caseId}
                        type="button"
                        aria-pressed={on}
                        className={alertView.freshIds.has(inc.caseId) ? "ctl-new" : undefined}
                        onClick={() => selectCase(inc.caseId)}
                        style={{
                          ...irowStyle, height: 62, minHeight: 62,
                          // 선택 표시는 연한 테두리 1px + 옅은 배경(2026-10-04) — 진한 이중선(테두리+그림자)은 스크롤
                          // 영역 가장자리에서 잘려 두께가 들쭉날쭉해 보였다
                          ...(on ? { border: `1px solid ${C.blue}`, background: GLASS.tint } : {}),
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                          <NumBadge n={inc.num} />
                          {alertView.freshIds.has(inc.caseId) && (
                            <span style={{ flex: "none", fontSize: 9.5, fontWeight: 900, color: "#fff", background: "#D93025", borderRadius: 3, padding: "0 5px", lineHeight: "15px" }}>NEW</span>
                          )}
                          {inc.sev && <SevChip sev={inc.sev} />}
                          {state.monitorCases[inc.caseId]?.ktasLevel != null && <span style={{ flex: "none", fontSize: 11, fontWeight: 700, color: C.navy }}>Pre-KTAS {state.monitorCases[inc.caseId].ktasLevel}</span>}
                          <span title={inc.name} style={{ flex: "none", fontSize: 13, fontWeight: 700, color: C.navy, maxWidth: 150, overflow: "hidden", textOverflow: "ellipsis" }}>{shortAmb(inc.name)}</span>
                          <span style={{ flex: "1 1 auto", minWidth: 0, overflow: "hidden" }}>{inc.sym && <SymChip text={inc.sym} />}</span>
                          <span style={{ flex: "none", fontSize: 12, color: C.sub, fontVariantNumeric: "tabular-nums" }}>{fmtElapsed(now - inc.startedAt)}</span>
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11.5, fontVariantNumeric: "tabular-nums" }}>
                          <span style={{ flex: "1 1 auto", minWidth: 0, fontWeight: 700, color: alertView.handling.has(inc.caseId) ? C.blue : alert ? (alertRed ? "#D93025" : "#C75B00") : stage.color, overflow: "hidden", textOverflow: "ellipsis" }}>{alertView.handling.has(inc.caseId) ? `처리 중${alert ? ` · ${alert.title}` : ""}` : alert ? `${alert.title}${alert.detail ? ` · ${alert.detail}` : ""}` : stage.text}</span>
                          {unseen > 0 && (
                            <span style={{ flex: "none", fontSize: 10, fontWeight: 700, color: "#fff", background: C.blue, borderRadius: 4, padding: "0 6px", lineHeight: "15px" }}>새 {unseen}</span>
                          )}
                          <CountDot color="#F6C21B" n={c.w} />
                          <CountDot color="#D93025" n={c.r} />
                          <CountDot color="#7CB342" n={c.a + c.t} />
                        </div>
                      </button>
                    );
                  })}
                </DragScroll>
              </div>

              {incidents.length > 3 && (
                <div style={{ flex: "none", textAlign: "center", fontSize: 11, fontWeight: 700, color: C.blue, lineHeight: "14px" }}>
                  드래그·스크롤로 나머지 {incidents.length - 3}건 확인
                </div>
              )}


            </Glass>
            {/* 사건 상세 / 구급차 — 진행 중인 사건을 누르면 사건 상세(환자 정보·진행 상황·AI 에이전트 활동·병원 응답·기록) */}
            <div role="tablist" aria-label="왼쪽 아래 패널" style={{ flex: "none", display: "flex", gap: 6 }}>
              {([["case", "사건 상세"], ["amb", `구급차 ${ambRows.length}대`]] as const).map(([key, label]) => (
                <button key={key} type="button" role="tab" aria-selected={leftTab === key} onClick={() => setLeftTab(key)}
                  style={{ ...tab2Style, ...(leftTab === key ? { background: C.blue, color: "#fff" } : { background: "rgba(255,255,255,.6)", color: C.ink2 }) }}>
                  {label}
                </button>
              ))}
            </div>
            {leftTab === "case" ? (
              <Glass dark={dark} style={{ ...cardStyle, flex: "1 1 0", gap: 8 }}>
                <div className="ctl-scroll" style={{ flex: "1 1 0", minHeight: 0, overflowY: "auto", paddingRight: 4 }}>
                  {selected && !selected.fake ? (
                    <CaseDetailPanel
                      inc={selected}
                      mc={state.monitorCases[selected.caseId]}
                      group={assignmentGroups.find((g) => g.caseIds.includes(selected.caseId))}
                      now={now}
                      onConfirmRequest={(caseId) => sendConfirmRequest(caseId)}
                      onZoneExpand={(caseId) => sendZoneExpand(caseId)}
                      onDesignate={dispatchTo}
                      onOpenHospital={setDetailHospital}
                      handling={(isTransportStalled(selected, now) || isConfirmDelayed(selected, now)) && (
                        <HandlingActions key={selected.caseId} dispatchOnly={!isTransportStalled(selected, now)} notice={resultNotice(state, selected.caseId, now)}
                          onZoneExpand={() => sendZoneExpand(selected.caseId)} onAlternatives={() => sendAlternativesRequest(selected.caseId)}
                          onDirect={(h) => sendDirectTransport(selected.caseId, h.hospitalId)} alternatives={state.alternatives[selected.caseId] ?? null}
                          phoneOf={(hospitalId) => overview?.hospitals.find((o) => o.hospitalId === hospitalId)?.erPhone ?? null}
                          waiting={selected.hospitals.filter((h) => h.st === "w").map((h) => ({
                            hospitalId: h.hospitalId, name: h.name,
                            phone: overview?.hospitals.find((o) => o.hospitalId === h.hospitalId)?.erPhone ?? null,
                          }))}
                          approved={selected.hospitals.filter((h) => h.st === "a" && !h.notSelected)}
                          onDispatch={(h) => dispatchTo(selected.caseId, h.hospitalId)} />
                      )}
                    />
                  ) : (
                    <div style={{ padding: "24px 12px", textAlign: "center", fontSize: 12.5, color: C.muted, whiteSpace: "normal" }}>
                      진행 중인 사건을 누르면 환자 정보·진행 상황·AI 에이전트 활동·기록이 여기에 뜹니다.
                    </div>
                  )}
                </div>
              </Glass>
            ) : (
              <Glass dark={dark} style={{ ...cardStyle, flex: "1 1 0", gap: 8 }}>
                <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", padding: "0 2px" }}>
                  <div style={{ fontSize: 14, fontWeight: 700, color: C.navy }}>구급차 {ambRows.length}대</div>
                  <div style={{ fontSize: 11.5, color: C.sub }}>{selected ? "선택한 사건 기준 · 가까운 순" : "상태순"}</div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <input
                    type="search"
                    value={ambQuery}
                    onChange={(e) => setAmbQuery(e.target.value)}
                    placeholder="구급차 이름 검색"
                    aria-label="구급차 이름 검색"
                    style={{ flex: "1 1 0", minWidth: 0, height: 28, boxSizing: "border-box", border: `1px solid ${C.line}`, borderRadius: 4, padding: "0 10px", fontFamily: "inherit", fontSize: 12.5, color: C.ink, background: "#fff" }}
                  />
                  <button
                    type="button"
                    aria-pressed={standbyOnMap}
                    onClick={() => setStandbyOnMap((v) => !v)}
                    title="켜면 기지 대기 구급차를 지도에 전부 표시합니다. 기본은 움직이는 구급차와 가까운 대기 5대만 보입니다."
                    style={{ flex: "none", height: 28, padding: "0 10px", border: `1px solid ${standbyOnMap ? C.navy : C.line}`, borderRadius: 6, fontFamily: "inherit", fontSize: 11.5, fontWeight: 700, cursor: "pointer", background: standbyOnMap ? C.navy : "#fff", color: standbyOnMap ? "#fff" : C.ink2 }}
                  >
                    지도에 대기 전체
                  </button>
                </div>
                <div className="ctl-scroll" tabIndex={0} aria-label="구급차 목록" style={{ minHeight: 0, overflowY: "auto", flex: "1 1 0" }}>
                {ambQ ? (
                  <div className="ctl-scroll" style={{ flex: "0 1 auto", minHeight: 0, display: "flex", flexDirection: "column", gap: 7, paddingRight: 6 }}>
                    <div style={{ flex: "none", fontSize: 11.5, fontWeight: 700, color: C.sub }}>검색 결과 {ambHits.length}대</div>
                    {ambHits.map(renderAmb)}
                    {ambHits.length === 0 && <div style={{ padding: "16px 8px", textAlign: "center", fontSize: 12.5, color: C.muted }}>이름이 맞는 구급차가 없습니다.</div>}
                  </div>
                ) : (
                  <>
                    {/* 움직이는 구급차는 고정, 스크롤은 기지 대기 목록만 */}
                    <div style={{ flex: "none", display: "flex", flexDirection: "column", gap: 7, paddingRight: 6 }}>
                      <div style={{ fontSize: 11.5, fontWeight: 700, color: C.sub }}>
                        움직이는 구급차 {activeAmbs.length}대 <span style={{ fontWeight: 500 }}>· 현장 {ambCount.s} · 출동 {ambCount.d} · 이송 중 {ambCount.t}</span>
                      </div>
                      {activeAmbs.map(renderAmb)}
                      {activeAmbs.length === 0 && <div style={{ padding: "10px 8px", textAlign: "center", fontSize: 12.5, color: C.muted }}>지금 움직이는 구급차가 없습니다.</div>}
                      <button
                        type="button"
                        aria-expanded={standbyOpen}
                        onClick={() => setStandbyOpen((v) => !v)}
                        style={{ flex: "none", marginTop: 4, display: "flex", alignItems: "center", justifyContent: "space-between", height: 30, padding: "0 10px", border: `1px solid ${C.line2}`, borderRadius: 4, background: C.bg, fontFamily: "inherit", fontSize: 12, fontWeight: 700, color: C.ink2, cursor: "pointer" }}
                      >
                        <span>기지 대기 {standbyAmbs.length}대{!standbyOpen && center ? " · 가까운 5대" : ""}</span>
                        <span aria-hidden="true">{standbyOpen ? "▴" : "▾"}</span>
                      </button>
                    </div>
                    <div className="ctl-scroll" style={{ flex: "0 1 auto", minHeight: 0, display: "flex", flexDirection: "column", gap: 7, paddingRight: 6 }}>
                      {(standbyOpen ? standbyAmbs : nearStandby).map(renderAmb)}
                      {!standbyOpen && !center && (
                        <div style={{ flex: "none", padding: "2px 8px", fontSize: 11.5, color: C.muted, whiteSpace: "normal" }}>기지 대기 구급차 5대 표시 · 위 버튼으로 전체를 펼칠 수 있어요.</div>
                      )}
                    </div>
                  </>
                )}
                </div>
              </Glass>
            )}
          </aside>
          <aside aria-label="병원 정보" data-map-cover="right" style={{ position: "relative", zIndex: 10, flex: "none", width: SIDEBAR_W, marginLeft: "auto", height: "100%", minHeight: 0, display: "flex" }}>
            <Glass dark={dark} style={{ ...cardStyle, width: "100%", flex: "1 1 0", gap: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                <strong style={{ fontSize: 14, color: C.navy }}>병원 {shownHospitals.length}곳</strong>
                <span style={{ fontSize: 12, color: C.sub }}>누르면 상세 · hub 실시간</span>
              </div>
              <div role="tablist" aria-label="병원 등급" style={{ flex: "none", display: "flex", flexWrap: "wrap", gap: 5 }}>
                {LEVEL_FILTERS.map((f) => {
                  const on = levelFilter === f.level;
                  const n = (overview?.hospitals ?? []).filter((h) => !f.level || h.emergencyLevel === f.level).length;
                  return (
                    <button key={f.key} type="button" role="tab" aria-selected={on} onClick={() => setLevelFilter(f.level)}
                      style={{ ...tab2Style, height: 26, padding: "0 10px", ...(on ? { background: C.blue, color: "#fff" } : { background: "rgba(255,255,255,.6)", color: C.ink2 }) }}>
                      {f.label} {n}
                    </button>
                  );
                })}
              </div>
              <div className="ctl-scroll" tabIndex={0} aria-label="병원 목록" style={{ flex: "1 1 0", minHeight: 0, overflowY: "auto", display: "flex", flexDirection: "column", gap: 8, paddingRight: 4 }}>
                {shownHospitals.map((h) => (
                  <article key={h.hospitalId} onClick={() => setDetailHospital(h.hospitalId)} title="눌러서 병원 상세 보기" onMouseEnter={() => setHoverHospital(h.hospitalId)} onMouseLeave={() => setHoverHospital("")} style={{ cursor: "pointer", flex: "none", border: `1px solid ${hoverHospital === h.hospitalId ? C.blue : C.line}`, borderRadius: GLASS.radiusSm, padding: 12, background: "rgba(255,255,255,.66)", whiteSpace: "normal" }}>
                    <div style={{ fontSize: 14, fontWeight: 700, color: C.navy }}>{h.name}</div>
                    <div style={{ display: "flex", gap: 12, marginTop: 8, fontSize: 12, color: C.ink2 }}>
                      <span>가용 병상 <b>{h.bedCountUnknown !== false || h.availableBedCount == null ? "미상" : `${h.availableBedCount}개`}</b></span>
                      <span>이송 중 {h.inFlightCount ?? 0}건</span>
                    </div>
                    {/* 가용 병상 숫자의 신뢰도(AI) — 누르지 않아도 늘 보인다 */}
                    <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginTop: 4, fontSize: 12 }}
                      title="정보 생존 모델(AI): 지금 보이는 가용 병상 숫자가 유효할 확률 — 수용 확률이 아닙니다">
                      <span style={{ color: C.sub }}>병상 신뢰도</span>
                      {h.bedAuthority != null ? (
                        <>
                          <b style={{ color: h.bedRiskLevel === "high" ? "#D9434B" : h.bedRiskLevel === "medium" ? "#B7791F" : "#1E9E6A" }}>{Math.round(h.bedAuthority * 100)}%</b>
                          <span style={{ color: C.sub }}>
                            {h.bedRiskLevel === "high" ? "변동 위험 높음" : h.bedRiskLevel === "medium" ? "변동 위험 보통" : "변동 위험 낮음"}
                            {h.bedCheckedAt ? ` · ${Math.max(0, Math.round((now - Date.parse(h.bedCheckedAt)) / 60_000))}분 전 확인` : ""}
                          </span>
                          <span style={{ fontSize: 10.5, fontWeight: 700, color: C.blue }}>AI</span>
                        </>
                      ) : <span style={{ color: C.muted }}>예측 없음</span>}
                    </div>
                    <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 5, marginTop: 10, fontSize: 12 }}>
                      <span style={{ color: C.sub }}>KTAS</span>
                      <span title="hub의 현재 유효 역량을 KTAS 필요 역량 기준에 대응한 규칙 기반 모형값(4·5는 같은 높이로 4 표시)" style={{ padding: "2px 9px", borderRadius: 4, background: C.bg, color: C.navy, fontWeight: 700 }}>
                        {h.mapKtasLevel ?? "정보 없음"}
                      </span>
                    </div>
                  </article>
                ))}
                {!overview?.hospitals.length && <div style={{ padding: "24px 8px", fontSize: 13, color: C.sub, whiteSpace: "normal", textAlign: "center" }}>hub에서 병원 정보를 기다리고 있습니다.</div>}
              </div>
            </Glass>
          </aside>

          {view === "3d" && spiderReady && (
            <iframe
              ref={spiderRef}
              title="3D 거미줄"
              src={SPIDER_URL}
              onLoad={() => { setTimeout(focusSelected, 400); pushInsets(); }}
              style={{ position: "absolute", inset: 0, zIndex: 0, width: "100%", height: "100%", border: 0, background: "#0a1024" }}
            />
          )}
          <div style={{ display: view === "2d" ? "contents" : "none" }}>
          <ControlMapPanel
            focusNonce={focusNonce}
            overview={overview}
            incidents={incidents}
            selected={selected}
            activeTab={activeTab}
            ambulanceSim={ambulanceSim}
            hoverHospital={hoverHospital}
            hoverAmb={hoverAmb}
            ambVisible={ambVisible}
            alertCaseIds={alertCaseIds}
            onHoverHospital={setHoverHospital}
            onHoverAmb={setHoverAmb}
            onSelectHospital={setDetailHospital}
            levelFilter={levelFilter}
                onSelectCase={selectCase}
          >
          </ControlMapPanel>
          </div>
        </div>
      </div>

      {showReject && <RejectionStatsModal onClose={() => setShowReject(false)} />}
      {detailHospital && (
        <HospitalDetailModal
          hospitalId={detailHospital}
          overview={overview?.hospitals.find((h) => h.hospitalId === detailHospital)}
          onClose={() => setDetailHospital(null)}
        />
      )}
      {showMci && (
        <MciRegisterModal
          assessment={state.mciAssessment}
          center={selected?.center ?? null}
          onClose={() => setShowMci(false)}
          onRegister={(body) => sendRaw({ type: "mci_register", ...body })}
          onDispatch={(incidentId) => sendRaw({ type: "mci_dispatch", incidentId })}
          onShow3d={(gps) => {
            setShowMci(false);
            pendingFocusRef.current = gps;
            if (view !== "3d") { setSpiderReady(false); setView("3d"); }
            else focusSelected();
          }}
        />
      )}
      {showAssign && assignmentCount > 0 && <AssignmentModal groups={assignmentGroups} now={now} onClose={() => setShowAssign(false)} onDispatch={dispatchTo} onConfirmRequest={(caseId) => sendConfirmRequest(caseId)} />}
      {showPast && (
        <PastModal today={past} onClose={() => setShowPast(false)} />
      )}
    </div>
  );
}

function DragScroll({ children, label, style }: { children: React.ReactNode; label: string; style: React.CSSProperties }) {
  const drag = useRef<{ y: number; top: number; moved: boolean } | null>(null);
  return <div className="ctl-scroll" tabIndex={0} aria-label={label} style={{ ...style, touchAction: "pan-y", overscrollBehavior: "contain", cursor: "grab", userSelect: "none" }}
    onPointerDown={(e) => {
      if (e.pointerType !== "mouse" || e.button !== 0) return;
      drag.current = { y: e.clientY, top: e.currentTarget.scrollTop, moved: false };
    }}
    onPointerMove={(e) => {
      const d = drag.current;
      if (!d || !(e.buttons & 1)) return;
      if (Math.abs(e.clientY - d.y) > 5) {
        d.moved = true;
        e.currentTarget.setPointerCapture(e.pointerId);
        e.currentTarget.scrollTop = d.top - (e.clientY - d.y);
      }
    }}
    onPointerUp={() => { if (drag.current && !drag.current.moved) drag.current = null; }}
    onPointerCancel={() => { drag.current = null; }}
    onClickCapture={(e) => { if (drag.current?.moved) { e.preventDefault(); e.stopPropagation(); } drag.current = null; }}
  >{children}</div>;
}

// ── 지난 사건 모달 ──────────────────────────────────────────────────────────

const RANGES: [string, string, number][] = [["today", "오늘", 0], ["7d", "최근 7일", 6], ["30d", "최근 30일", 29]];

function PastModal({ today, onClose }: {
  today: CaseHistoryItem[];
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const [from, setFrom] = useState(() => daysAgo(0));
  const [to, setTo] = useState(() => daysAgo(0));
  const [text, setText] = useState("");
  const [result, setResult] = useState<ArchiveResult>("all");
  const [pickId, setPickId] = useState("");
  const { cases: past, total, stats, loading, error } = useCaseArchive({ from, to, q: text, result }, today);
  const sel = past.find((p) => p.caseId === pickId) ?? past[0] ?? null;
  const n = stats.total;
  const onPick = setPickId;
  const multiDay = from !== to;
  const durMs = (p: CaseHistoryItem) => Date.parse(p.endedAt) - Date.parse(p.startedAt);
  const pct = (v: number) => `${Math.round(v * 100)}%`;
  const selSev = sel ? sevOf(sel.severity) : null;
  const selRes = sel ? pastResult(sel) : null;

  return (
    <div role="dialog" aria-modal="true" aria-label="지난 사건" style={{ position: "absolute", inset: 0, zIndex: 300, background: "rgba(28,31,42,.32)", backdropFilter: "blur(6px)", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <button type="button" aria-label="닫기" onClick={onClose} style={{ position: "absolute", inset: 0, border: 0, background: "transparent", cursor: "default" }} />
      <div style={{ position: "relative", width: 940, height: 660, maxWidth: "calc(100% - 48px)", maxHeight: "calc(100% - 48px)", background: GLASS.solid, border: GLASS.border, borderRadius: GLASS.radius, boxShadow: "0 24px 60px rgba(91,75,138,.28)", display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <div style={{ flex: "none", display: "flex", alignItems: "center", gap: 12, padding: "16px 22px", borderBottom: `1px solid ${C.line2}` }}>
          <div style={{ fontSize: 18, fontWeight: 900, color: C.navy }}>지난 사건</div>
          <div style={{ fontSize: 12.5, color: C.sub }}>
            {multiDay ? `${from} ~ ${to}` : from === daysAgo(0) ? "오늘" : from} 종료된 사건 {n}건 · 최근 종료 순
          </div>
          {ARCHIVE_MOCK && <span style={{ fontSize: 11, fontWeight: 700, color: "#C75B00", background: "#FFF1E0", borderRadius: 3, padding: "0 8px", lineHeight: "18px" }}>가짜 데이터 (설계 확인용)</span>}
          <div style={{ flex: "1 1 0" }} />
          <button type="button" onClick={onClose} style={{ fontFamily: "inherit", fontSize: 13, color: C.ink3, background: "#fff", border: `1px solid ${C.line}`, borderRadius: 4, padding: "5px 12px", cursor: "pointer" }}>닫기 ✕</button>
        </div>

        {/* 조회 조건 — 기간(빠른 선택·직접 지정)·검색(증상·구급차·병원)·결과 */}
        <div style={{ flex: "none", display: "flex", alignItems: "center", gap: 8, padding: "10px 22px 0", flexWrap: "wrap", rowGap: 6 }}>
          {RANGES.map(([key, label, back]) => {
            const on = from === daysAgo(back) && to === daysAgo(0);
            return (
              <button key={key} type="button" aria-pressed={on} onClick={() => { setFrom(daysAgo(back)); setTo(daysAgo(0)); }}
                style={{ ...tab2Style, ...(on ? { background: C.navy, color: "#fff" } : { background: C.bg, color: C.ink2 }) }}>
                {label}
              </button>
            );
          })}
          <input type="date" aria-label="시작일" value={from} max={to} onChange={(e) => e.target.value && setFrom(e.target.value)} style={dateInputStyle} />
          <span style={{ color: C.muted, fontSize: 12 }}>~</span>
          <input type="date" aria-label="종료일" value={to} min={from} max={daysAgo(0)} onChange={(e) => e.target.value && setTo(e.target.value)} style={dateInputStyle} />
          <input type="search" aria-label="사건 검색" placeholder="증상·구급차·병원 검색" value={text} onChange={(e) => setText(e.target.value)}
            style={{ ...dateInputStyle, width: 190 }} />
          <div role="group" aria-label="결과" style={{ display: "flex", gap: 4 }}>
            {([["all", "전체"], ["done", "이송 완료"], ["cancel", "취소"]] as [ArchiveResult, string][]).map(([key, label]) => {
              const on = result === key;
              return (
                <button key={key} type="button" aria-pressed={on} onClick={() => setResult(key)}
                  style={{ ...tab2Style, ...(on ? { background: C.navy, color: "#fff" } : { background: C.bg, color: C.ink2 }) }}>
                  {label}
                </button>
              );
            })}
          </div>
          {loading && <span style={{ fontSize: 12, color: C.muted }}>불러오는 중…</span>}
        </div>

        <div style={{ flex: "none", display: "grid", gridTemplateColumns: "repeat(4,minmax(0,1fr))", gap: 10, padding: "12px 22px 4px" }}>
          <Stat label="종료된 사건" value={`${n}건`} sub={`이송 완료 ${stats.done} · 취소 ${stats.cancel}`} />
          <Stat label="평균 소요 시간" value={fmtElapsed(stats.avgDurationSec * 1000)} />
          <Stat label="수용 불가율" value={pct(stats.rejectRate)} color="#D93025" sub={`사건당 평균 ${stats.avgRejected.toFixed(1)}곳`} />
          <Stat label="범위 확장(존 2 이상) 사건" value={`${stats.zoneExpanded}건`} color="#C75B00" sub={n ? `전체의 ${pct(stats.zoneExpanded / n)}` : undefined} />
        </div>

        <div style={{ flex: "1 1 0", minHeight: 0, display: "flex", gap: 14, padding: "10px 22px 20px" }}>
          <div style={{ flex: "none", width: 370, position: "relative" }}>
            <div className="ctl-scroll" style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", gap: 6, paddingRight: 6 }}>
              {past.map((p) => {
                const on = sel?.caseId === p.caseId;
                const sev = sevOf(p.severity);
                const res = pastResult(p);
                return (
                  <button
                    key={p.caseId}
                    type="button"
                    aria-pressed={on}
                    onClick={() => onPick(p.caseId)}
                    style={{ ...prowStyle, ...(on ? { background: GLASS.tint, border: `1px solid ${C.blue}` } : {}) }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                      {sev && <SevChip sev={sev} />}
                      <span style={{ flex: "1 1 auto", minWidth: 0, fontSize: 13.5, fontWeight: 700, color: C.navy, overflow: "hidden", textOverflow: "ellipsis" }}>
                        {shortAmb(p.ambulanceName ?? p.apid ?? "구급차")} {p.symptom && <SymChip text={p.symptom} />}
                      </span>
                      <span style={{ flex: "none", fontSize: 12, color: C.sub, fontVariantNumeric: "tabular-nums" }}>소요 {fmtElapsed(durMs(p))}</span>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, fontSize: 11.5 }}>
                      <span style={{ flex: "none", color: C.muted, fontVariantNumeric: "tabular-nums" }}>{multiDay ? `${fmtMd(p.endedAt)} ` : ""}{fmtHm(p.startedAt)} ~ {fmtHm(p.endedAt)}</span>
                      <span style={{ flex: "none", fontWeight: 700, padding: "0 8px", borderRadius: 3, lineHeight: "17px", maxWidth: 210, overflow: "hidden", textOverflow: "ellipsis", ...res.style }}>{res.text}</span>
                    </div>
                  </button>
                );
              })}
              {error && <div style={{ padding: "40px 12px", textAlign: "center", fontSize: 12.5, color: "#D93025", whiteSpace: "normal" }}>{error}</div>}
              {!error && !loading && past.length === 0 && <div style={{ padding: "40px 12px", textAlign: "center", fontSize: 12.5, color: C.muted }}>조건에 맞는 사건이 없습니다.</div>}
              {total > past.length && <div style={{ padding: "8px 12px", textAlign: "center", fontSize: 11.5, color: C.muted }}>최근 {past.length}건만 표시 (전체 {total}건) — 통계는 전체 기준</div>}
            </div>
          </div>

          <div style={{ flex: "1 1 0", minWidth: 0, border: `1px solid ${C.line2}`, borderRadius: 6, padding: "16px 18px", display: "flex", flexDirection: "column", gap: 12 }}>
            {sel ? (
              <>
                <div style={{ flex: "none", display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 17, fontWeight: 900, color: C.navy, overflow: "hidden", textOverflow: "ellipsis" }}>{shortAmb(sel.ambulanceName ?? sel.apid ?? "구급차")}</span>
                  {selSev && <SevChip sev={selSev} />}
                  {sel.symptom && <SymChip text={sel.symptom} />}
                  {selRes && <span style={{ flex: "none", fontSize: 11.5, fontWeight: 700, padding: "0 9px", borderRadius: 3, lineHeight: "18px", ...selRes.style }}>{selRes.text}</span>}
                </div>
                <div style={{ flex: "none", display: "grid", gridTemplateColumns: "repeat(4,minmax(0,1fr))", gap: 8 }}>
                  <MiniStat label="요청 병원" value={`${sel.requested}곳`} />
                  <MiniStat label="수용 불가" value={`${sel.rejected}곳`} color="#D93025" />
                  <MiniStat label="요청 범위" value={sel.zone ? zoneText(sel.zone) : "요청 전"} />
                  <MiniStat label="총 소요" value={fmtElapsed(durMs(sel))} />
                </div>
                <div style={{ flex: "none", fontSize: 12.5, color: C.ink3, padding: "8px 12px", background: GLASS.tint, borderRadius: GLASS.radiusSm, whiteSpace: "normal" }}>
                  {sel.result === "done"
                    ? `최종 이송 병원 ${sel.hospital ? shortHospital(sel.hospital) : "-"} · 요청 ${sel.requested}곳 중 ${sel.rejected}곳이 수용 불가`
                    : sel.hospital
                      ? `이송 확정 병원 ${shortHospital(sel.hospital)} · 이송을 마치지 못하고 종료됨`
                      : `병원 확정 없이 종료됨 · 요청 ${sel.requested}곳 중 ${sel.rejected}곳이 수용 불가`}
                </div>
                <div style={{ flex: "none", fontSize: 12, fontWeight: 700, color: C.navy }}>진행 과정</div>
                <div style={{ position: "relative", flex: "1 1 0", minHeight: 0 }}>
                  <div className="ctl-scroll" style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", paddingRight: 6 }}>
                    {sel.events.map((e, i) => {
                      const tone = EVENT_TONE[e.kind] ?? C.navy;
                      const last = i === sel.events.length - 1;
                      return (
                        <div key={`${e.t}-${i}`} style={{ flex: "none", display: "flex", gap: 10, minHeight: 44 }}>
                          <div style={{ flex: "none", width: 64, textAlign: "right", fontSize: 12, color: C.sub, fontVariantNumeric: "tabular-nums", lineHeight: 1.3 }}>
                            {fmtClock(e.t)}
                            <div style={{ fontSize: 11, color: C.faint }}>+{fmtElapsed(Date.parse(e.t) - Date.parse(sel.startedAt))}</div>
                          </div>
                          <div style={{ flex: "none", position: "relative", width: 14 }}>
                            <span style={{ position: "absolute", left: 2, top: 3, width: 10, height: 10, borderRadius: "50%", background: tone }} />
                            {!last && <span style={{ position: "absolute", left: 6, top: 15, bottom: -3, width: 2, background: C.line }} />}
                          </div>
                          <div style={{ flex: "1 1 auto", minWidth: 0, fontSize: 13, lineHeight: 1.35, color: tone, fontWeight: ["d", "t", "x"].includes(e.kind) ? 700 : 500, whiteSpace: "normal" }}>{e.text}</div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </>
            ) : (
              <div style={{ margin: "auto", fontSize: 12.5, color: C.muted }}>아직 종료된 사건이 없습니다.</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── 작은 조각 ────────────────────────────────────────────────────────────────

function Divider() {
  return <span style={{ width: 1, height: 14, background: C.line }} />;
}

function NumBadge({ n }: { n: number }) {
  return (
    <span style={{ flex: "none", minWidth: 17, height: 17, padding: "0 4px", boxSizing: "border-box", borderRadius: 3, background: C.navy, color: "#fff", fontSize: 10, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center" }}>
      {n}
    </span>
  );
}

function SevChip({ sev }: { sev: keyof typeof SEV_STYLE }) {
  return <span style={{ flex: "none", fontSize: 10.5, fontWeight: 700, padding: "0 7px", borderRadius: 3, lineHeight: "16px", ...SEV_STYLE[sev] }}>{sev}</span>;
}

function SymChip({ text }: { text: string }) {
  return (
    <span
      title={text}
      style={{
        display: "inline-block", maxWidth: "100%", overflow: "hidden", textOverflow: "ellipsis", verticalAlign: "middle",
        fontSize: 10.5, fontWeight: 500, color: C.ink3, background: C.bg, borderRadius: 3, padding: "1px 6px", whiteSpace: "nowrap",
      }}
    >
      {text}
    </span>
  );
}

function CountDot({ color, n }: { color: string; n: number }) {
  return (
    <span style={{ flex: "none", display: "flex", alignItems: "center", gap: 3, color: C.ink3 }}>
      <span style={{ width: 7, height: 7, borderRadius: "50%", background: color }} />
      {n}
    </span>
  );
}

function StatusIcon({ st, color }: { st: St; color: string }) {
  if (st === "w") return <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M5 1a3 3 0 0 0-3 3v2L1 8h8L8 6V4a3 3 0 0 0-3-3zM4 9h2" fill={color} stroke={color} strokeWidth=".8" /></svg>;
  if (st === "r") return <svg width="9" height="9" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 2l6 6M8 2L2 8" stroke={color} strokeWidth="2" /></svg>;
  if (st === "a") return <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M1.8 5.2L4 7.4 8.2 2.6" fill="none" stroke={color} strokeWidth="1.9" /></svg>;
  return (
    <svg width="12" height="10" viewBox="0 0 12 10" aria-hidden="true">
      <path d="M1 2h6v5H1zM7 4h2.5L11 5.5V7H7z" fill={color} />
      <circle cx="3" cy="8" r="1.1" fill="#fff" stroke={color === "#fff" ? "#168A55" : color} strokeWidth=".7" />
      <circle cx="9" cy="8" r="1.1" fill="#fff" stroke={color === "#fff" ? "#168A55" : color} strokeWidth=".7" />
    </svg>
  );
}

function Stat({ label, value, color = C.navy, sub }: { label: string; value: string; color?: string; sub?: string }) {
  return (
    <div style={{ border: `1px solid ${C.line2}`, borderRadius: 4, padding: "8px 12px" }}>
      <div style={{ fontSize: 11.5, color: C.sub }}>{label}</div>
      <div style={{ fontSize: 19, fontWeight: 900, color, fontVariantNumeric: "tabular-nums" }}>{value}</div>
      <div style={{ fontSize: 11, color: C.muted, minHeight: 14 }}>{sub}</div>
    </div>
  );
}

function MiniStat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: C.muted }}>{label}</div>
      <div style={{ fontSize: 14, fontWeight: 700, color, fontVariantNumeric: "tabular-nums" }}>{value}</div>
    </div>
  );
}

// ── 스타일(시안 값 그대로) ──────────────────────────────────────────────────

const DARK_FILTER = "invert(1) hue-rotate(180deg) brightness(1.25) saturate(1.15)";
const GLASS_COMMON: React.CSSProperties = { backdropFilter: GLASS.blur, WebkitBackdropFilter: GLASS.blur, boxShadow: GLASS.shadow };
/**
 * 지도 위에 떠 있는 유리 패널(2026-11-01). 3D 거미줄(어두운 지도) 위에서는 dark — 어두운 유리 + 안쪽 내용의 색을 반전한다.
 * 유리(배경·블러)와 내용(반전)을 두 겹으로 나눈 이유: 같은 요소에 filter를 걸면 뒤 지도의 블러까지 같이 반전돼 버린다.
 * 반전은 hue-rotate로 색상을 되돌려 빨강·초록·노랑 같은 상태색이 거의 그대로 남는다(흰 바탕·남색 글자만 뒤바뀐다).
 */
function Glass({ as = "div", dark, style, children, ...rest }: {
  as?: "div" | "header"; dark: boolean; style: React.CSSProperties; children: React.ReactNode; [k: string]: unknown;
}) {
  const Tag = as as React.ElementType;
  const { gap, ...outer } = style;
  return (
    <Tag
      {...rest}
      style={{
        ...outer, ...GLASS_COMMON, display: "flex", flexDirection: "column", boxSizing: "border-box",
        background: dark ? GLASS.darkPanel : GLASS.panel,
        border: dark ? GLASS.darkBorder : GLASS.border,
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap, minHeight: 0, flex: "1 1 auto", filter: dark ? DARK_FILTER : undefined }}>
        {children}
      </div>
    </Tag>
  );
}
const cardStyle: React.CSSProperties = {
  background: GLASS.panel, backdropFilter: GLASS.blur, WebkitBackdropFilter: GLASS.blur, border: GLASS.border, boxShadow: GLASS.shadow, borderRadius: GLASS.radius, padding: 16, boxSizing: "border-box",
  display: "flex", flexDirection: "column", gap: 8, minHeight: 0,
};
const irowStyle: React.CSSProperties = {
  flex: "none", display: "flex", flexDirection: "column", justifyContent: "center", gap: 3, width: "100%", minHeight: 42,
  boxSizing: "border-box", padding: "3px 12px", border: `1px solid ${C.line2}`, borderRadius: GLASS.radiusSm, background: "rgba(255,255,255,.66)",
  fontFamily: "inherit", textAlign: "left", cursor: "pointer", scrollSnapAlign: "start", transition: "background .6s",
};
const tab2Style: React.CSSProperties = {
  flex: "none", boxSizing: "border-box", fontFamily: "inherit", fontSize: 12, fontWeight: 600, border: 0, borderRadius: 999,
  height: 28, padding: "0 14px", cursor: "pointer", fontVariantNumeric: "tabular-nums",
};
const acellStyle: React.CSSProperties = {
  display: "flex", alignItems: "center", gap: 8, height: 28, padding: "0 6px", border: 0, borderBottom: `1px solid ${C.line2}`, borderRadius: 0,
  fontSize: 12.5, fontVariantNumeric: "tabular-nums", cursor: "default", boxSizing: "border-box", scrollSnapAlign: "start",
};
const dateInputStyle: React.CSSProperties = {
  boxSizing: "border-box", height: 26, padding: "0 8px", border: `1px solid ${C.line}`, borderRadius: GLASS.radiusSm,
  fontFamily: "inherit", fontSize: 12, color: C.ink2, background: "#fff",
};
const toolBtnStyle: React.CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: 6, height: 28, padding: "0 14px", border: `1px solid ${C.line}`, borderRadius: 999,
  background: "rgba(255,255,255,.6)", fontFamily: "inherit", fontSize: 12, fontWeight: 600, color: C.ink2, cursor: "pointer",
};
const prowStyle: React.CSSProperties = {
  flex: "none", display: "flex", flexDirection: "column", justifyContent: "center", gap: 4, width: "100%", height: 58,
  boxSizing: "border-box", padding: "0 12px", border: `1px solid ${C.line2}`, borderRadius: GLASS.radiusSm, background: "rgba(255,255,255,.66)",
  fontFamily: "inherit", textAlign: "left", cursor: "pointer",
};
