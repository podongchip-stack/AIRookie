"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { DEMO_UNIT } from "@/lib/demo-unit";
import { ControlMapPanel } from "@/components/map/ControlMapPanel";
import { CONNECTION_LABEL, useDashboardSocket } from "@/hooks/use-dashboard-socket";
import {
  AMB_CHIP, AMB_RANK, SIDEBAR_W, C, EVENT_TONE, LEVEL_DEFAULT, LEVEL_DOT, SEV_STYLE, ST_DOT, ST_LABEL, ST_TEXT, reqLabel,
  ambState, buildIncidents, counts, fmtClock, fmtElapsed, fmtHm, fmtMd, haversineKm, pastResult, sevOf, shortAmb, shortHospital,
  stageOf, zoneText,
  type AmbKey, type Incident, type St,
} from "@/lib/control-map";
import type { CaseHistoryItem } from "@/types/dashboard";
import { useCaseArchive } from "@/hooks/use-case-archive";
import { useControlAlerts } from "@/hooks/use-control-alerts";
import { isTransportStalled } from "@/lib/control-alerts";
import { CaseTimeline } from "@/components/map/CaseTimeline";
import { CaseStatusSummary } from "@/components/map/CaseStatusSummary";
import { HandlingActions } from "@/components/map/HandlingActions";
import { AlertSoundButton, AlertStack, topAlertOf, useAlertTabTitle } from "@/components/map/ControlAlerts";
import { ARCHIVE_MOCK, daysAgo, type ArchiveResult } from "@/lib/case-archive";
import { DemoVideoOverlay } from "@/components/ui/DemoVideoOverlay";
import { useAutoDemo } from "@/lib/auto-demo";

// 관제 지도(2026-10-03 신설, 2026-10-04 디자인 시안 "골든링크 관제"로 전면 개편). hub에 role=monitor로 붙어
// 사건 요약·구급차 위치만 받는다 — 통화 전문 등 환자 상세는 받지 않는다(증상은 한 줄뿐).
// 시연 조작을 열면 공통 DemoConsole이 별도 monitor 연결로 기존 시연 명령을 보낸다.
// 병원 대시보드는 첫 페이지에서 접근 코드로 연다(병원 점에 마우스를 올리면 H-코드가 보인다).
//
// 왼쪽: 진행 중인 사건(중증도 → 시작 순) · 지난 사건 보기 · 선택한 사건의 요청 병원(탭: 판단 대기/수용 불가/수용 승인)
// 오른쪽: 지도(선택한 사건의 병원 응답 상태·요청 범위, 전체 구급차) + 하단 구급차 패널(선택한 사건 기준 가까운 순)
// 위치·존·상태는 전부 규칙 기반이고, 구급차 위치는 시연용 시뮬레이션이다.

// 3D 거미줄(spider/serve.py, 포트 2700) 실시간 화면. 배포 도메인에선 같은 호스트의 /spider/ 아래로 열려 있고,
// 로컬 개발(3000)에선 NEXT_PUBLIC_SPIDER_URL(예: http://localhost:2700/spider/)로 덮어쓴다.
const SPIDER_URL = `${process.env.NEXT_PUBLIC_SPIDER_URL ?? "/spider/"}?mode=live&embed=1`;

const DemoConsole = dynamic(() => import("@/components/control/DemoConsole").then((module) => module.DemoConsole), {
  ssr: false,
  loading: () => <div role="status" style={{ padding: 24 }}>시연 조작을 불러오는 중…</div>,
});

type MapView = "2d" | "3d";
type Tab = "all" | St;
type AmbTab = "all" | "sd" | "t" | "b";

const LEGEND_LEVELS: [string, string][] = [
  [LEVEL_DOT["권역응급의료센터"], "권역센터 (중증)"],
  [LEVEL_DOT["지역응급의료센터"], "지역센터 (중등증)"],
  [LEVEL_DEFAULT, "응급의료기관 (경증)"],
];

export default function MonitorMapPage() {
  const { state, connectionMode } = useDashboardSocket({ role: "monitor", id: "map" });
  const overview = state.mapOverview;
  const [now, setNow] = useState(() => Date.now());
  const [selId, setSelId] = useState<string>("");
  const [tab, setTab] = useState<Tab>("all");
  const [ambTab, setAmbTab] = useState<AmbTab>("all");
  const [hoverHospital, setHoverHospital] = useState("");
  const [hoverAmb, setHoverAmb] = useState("");
  const [view, setView] = useState<MapView>("2d");
  const [showPast, setShowPast] = useState(false);
  const [consoleOpen, setConsoleOpen] = useState(false);
  // 닫아도 컴포넌트는 유지해 작성 중 입력·대량사고 대기열·재생 타이머를 보존한다.
  const [consoleMounted, setConsoleMounted] = useState(false);
  const [, setConsoleApid] = useState<string | null>(null);
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
  // 자동 시연(2026-10-06) — 콘솔로 실제 시연을 하지 않는 동안(실제 사건이 없을 때)만 이 화면 안에서 가짜 사건을 돌린다.
  // hub·다른 대시보드·로그와 무관하고, 실제 사건이 생기면 가짜 사건은 바로 모두 사라진다(lib/auto-demo.ts).
  const demo = useAutoDemo(realIncidents.length === 0 && !consoleMounted, overview, state.ambulanceSim);
  const incidents = useMemo(() => [...realIncidents, ...demo.incidents], [realIncidents, demo.incidents]);
  const ambulanceSim = useMemo(() => ({ ...state.ambulanceSim, ...demo.sims }), [state.ambulanceSim, demo.sims]);
  const selected = incidents.find((i) => i.caseId === selId) ?? incidents[0] ?? null;

  const selectCase = useCallback((caseId: string) => {
    setSelId(caseId);
    const apid = realIncidents.find((incident) => incident.caseId === caseId)?.apid;
    if (apid) setConsoleApid(apid);
    setTab("all");
    setSeenAt((prev) => ({ ...prev, [caseId]: Date.now() }));
  }, [realIncidents]);

  const selectConsoleAmbulance = useCallback((apid: string | null) => {
    setConsoleApid(apid);
    const incident = realIncidents.find((item) => item.apid === apid);
    if (incident) selectCase(incident.caseId);
  }, [realIncidents, selectCase]);

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
  const ambCount: Record<AmbKey, number> = { s: 0, d: 0, t: 0, b: 0 };
  for (const r of ambRows) ambCount[r.key]++;
  const inAmbTab = useCallback(
    (key: AmbKey) => ambTab === "all" || (ambTab === "sd" ? key === "s" || key === "d" : ambTab === key),
    [ambTab],
  );
  const ambKeyOf = useMemo(() => new Map(ambRows.map((r) => [r.apid, r.key])), [ambRows]);
  const ambInTab = useCallback((apid: string) => inAmbTab(ambKeyOf.get(apid) ?? "b"), [inAmbTab, ambKeyOf]);
  const ambList = ambRows
    .filter((r) => inAmbTab(r.key))
    .sort((p, q) => AMB_RANK[p.key] - AMB_RANK[q.key] || (p.km ?? 1e9) - (q.km ?? 1e9) || p.name.localeCompare(q.name));

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
  const RANK: Record<St, number> = { t: 0, a: 1, w: 2, r: 3 };
  const rows = (selected?.hospitals ?? [])
    .filter((h) => activeTab === "all" || h.st === activeTab)
    .sort((x, y) =>
      RANK[x.st] - RANK[y.st] ||
      (x.st === "w" ? x.km - y.km : Date.parse(y.respondedAt ?? "0") - Date.parse(x.respondedAt ?? "0")),
    );
  const emptyText: Record<Tab, string> = {
    all: selected && !selected.matched ? "현장 확인이 끝나면 인근 병원에 수용 요청이 나갑니다." : "",
    w: "판단 대기 중인 병원이 없습니다.",
    r: "아직 수용 불가로 응답한 병원이 없습니다.",
    a: "아직 수용 승인한 병원이 없습니다.",
    t: "아직 이송이 확정되지 않았습니다.",
  };

  const sevCount = { 중증: 0, 중등증: 0, 경증: 0 };
  for (const inc of incidents) if (inc.sev) sevCount[inc.sev]++;

  const past = state.caseHistory;
  const live = connectionMode === "live";
  const alertView = useControlAlerts(incidents, live);
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
    <div style={{ position: "fixed", inset: 0, overflow: "hidden", background: C.bg, color: C.ink, whiteSpace: "nowrap" }}>
      {/* 시연 영상 모드(2026-10-06) — 관제 지도는 ijs.mp4를 반복 재생(2026-10-08, /verify/stage 순환 없음) */}
      <DemoVideoOverlay src="/demo-videos/ijs.mp4" />
      <div style={{ position: "absolute", inset: 0, boxSizing: "border-box", padding: 18, display: "flex", flexDirection: "column", gap: 14 }}>
        {/* 헤더 + 범례 */}
        <header style={{ flex: "none", background: "#fff", border: `1px solid ${C.line}`, borderRadius: 14, padding: "12px 20px", display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <Link href="/" style={{ fontSize: 19, fontWeight: 900, letterSpacing: "-0.02em", color: C.navy }}>골든링크</Link>
            <div style={{ width: 1, height: 16, background: "#CDD3DA" }} />
            <div style={{ fontSize: 13, color: C.ink3 }}>관제 지도 · 병원·구급차 실시간 위치</div>
            <div style={{ flex: "1 1 0" }} />
            <button type="button" aria-expanded={consoleOpen} aria-controls="map-demo-console"
              onClick={() => {
                setConsoleMounted(true);
                if (!consoleOpen) {
                  const incident = realIncidents.find((item) => item.apid === DEMO_UNIT.apid);
                  if (incident) selectCase(incident.caseId);
                }
                setConsoleOpen((open) => !open);
              }}
              style={{ ...tab2Style, minHeight: 40, background: consoleOpen ? C.navy : "#E8EEF8", color: consoleOpen ? "#fff" : C.navy }}>
              {consoleOpen ? "관제 목록으로" : "시연 조작"}
            </button>
            <AlertSoundButton soundOn={alertView.soundOn} count={alertView.alerts.length} onToggle={alertView.toggleSound} />
            <div role="tablist" aria-label="지도 보기" style={{ display: "flex", gap: 4 }}>
              {([["2d", "2D 지도"], ["3d", "3D 거미줄"]] as [MapView, string][]).map(([key, label]) => {
                const on = view === key;
                return (
                  <button
                    key={key}
                    type="button"
                    role="tab"
                    aria-selected={on}
                    onClick={() => setView(key)}
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
        </header>
        {/* 관제 알림 카드 — 헤더 바로 아래 기준점에서 아래로 쌓인다(높이 0) */}
        <div style={{ position: "relative", flex: "none", height: 0, marginTop: -14, zIndex: 250 }}>
          <AlertStack alerts={alertView.alerts} incidents={incidents} onAck={alertView.ack} onAckAll={alertView.ackAll} onOpen={selectCase} onHandle={(caseId, keys) => { alertView.startHandling(caseId, keys); selectCase(caseId); }} />
        </div>
        <style>{"@keyframes ctlbl{0%,100%{opacity:1}50%{opacity:.3}}.ctl-live{animation:ctlbl 1.6s infinite}@keyframes ctlnew{0%,100%{background:#fff}50%{background:#FFD9D5}}.ctl-new{animation:ctlnew 1s ease-in-out 10;border-color:#D93025!important}.ctl-scroll{overflow-y:auto;scrollbar-width:thin;scrollbar-color:#C5CCD6 transparent}.ctl-scroll::-webkit-scrollbar{width:6px}.ctl-scroll::-webkit-scrollbar-thumb{background:#C5CCD6;border-radius:3px}"}</style>

        <style>{`
          .monitor-console-pane{flex:0 0 min(760px,56%);min-width:0;min-height:0;overflow:hidden;border:1px solid ${C.line};border-radius:14px;background:${C.bg}}
          @media(max-width:1100px){
            .monitor-workspace--control{flex-direction:column}
            .monitor-workspace--control .monitor-console-pane{flex:0 0 55%;width:100%}
            .monitor-workspace--control .monitor-ambulance-panel{display:none!important}
          }
        `}</style>
        <div className={`monitor-workspace${consoleOpen ? " monitor-workspace--control" : ""}`} style={{ flex: "1 1 0", minHeight: 0, display: "flex", gap: 16 }}>
          {/* 왼쪽: 진행 중인 사건 · 지난 사건 · 선택한 사건의 병원 */}
          <aside style={{ flex: "none", width: SIDEBAR_W, display: consoleOpen ? "none" : "flex", flexDirection: "column", gap: 12, minHeight: 0 }}>
            <div style={{ ...cardStyle, flex: "1 1 0", gap: 6 }}>
              <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", padding: "0 2px" }}>
                <div style={{ fontSize: 16, fontWeight: 700, color: C.navy }}>진행 중인 사건 {incidents.length}건</div>
                <div style={{ fontSize: 11.5, color: C.sub }}>중증 {sevCount.중증} · 중등증 {sevCount.중등증} · 경증 {sevCount.경증}</div>
              </div>

              <div style={{ position: "relative", flex: "none", height: 160 }}>
                <div className="ctl-scroll" style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", gap: 5, paddingRight: 6, scrollSnapType: "y mandatory" }}>
                  {incidents.length === 0 && (
                    <div style={{ padding: "40px 12px", textAlign: "center", fontSize: 12.5, color: C.muted, whiteSpace: "normal" }}>
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
                          ...irowStyle,
                          // 선택 표시는 연한 테두리 1px + 옅은 배경(2026-10-04) — 진한 이중선(테두리+그림자)은 스크롤
                          // 영역 가장자리에서 잘려 두께가 들쭉날쭉해 보였다
                          ...(on ? { border: "1px solid #C9D4E6", background: "#F5F8FF" } : {}),
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                          <NumBadge n={inc.num} />
                          {alertView.freshIds.has(inc.caseId) && (
                            <span style={{ flex: "none", fontSize: 9.5, fontWeight: 900, color: "#fff", background: "#D93025", borderRadius: 5, padding: "0 5px", lineHeight: "15px" }}>NEW</span>
                          )}
                          {inc.sev && <SevChip sev={inc.sev} />}
                          <span title={inc.name} style={{ flex: "none", fontSize: 13, fontWeight: 700, color: C.navy, maxWidth: 150, overflow: "hidden", textOverflow: "ellipsis" }}>{shortAmb(inc.name)}</span>
                          <span style={{ flex: "1 1 auto", minWidth: 0, overflow: "hidden" }}>{inc.sym && <SymChip text={inc.sym} />}</span>
                          <span style={{ flex: "none", fontSize: 12, color: C.sub, fontVariantNumeric: "tabular-nums" }}>{fmtElapsed(now - inc.startedAt)}</span>
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11.5, fontVariantNumeric: "tabular-nums" }}>
                          <span style={{ flex: "1 1 auto", minWidth: 0, fontWeight: 700, color: alertView.handling.has(inc.caseId) ? "#1F4E9C" : alert ? (alertRed ? "#D93025" : "#C75B00") : stage.color, overflow: "hidden", textOverflow: "ellipsis" }}>{alertView.handling.has(inc.caseId) ? `처리 중${alert ? ` · ${alert.title}` : ""}` : alert ? `${alert.title}${alert.detail ? ` · ${alert.detail}` : ""}` : stage.text}</span>
                          {unseen > 0 && (
                            <span style={{ flex: "none", fontSize: 10, fontWeight: 700, color: "#fff", background: C.blue, borderRadius: 8, padding: "0 6px", lineHeight: "15px" }}>새 {unseen}</span>
                          )}
                          <CountDot color="#F6C21B" n={c.w} />
                          <CountDot color="#D93025" n={c.r} />
                          <CountDot color="#7CB342" n={c.a + c.t} />
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>

              {incidents.length > 6 && (
                <div style={{ flex: "none", textAlign: "center", fontSize: 11, fontWeight: 700, color: "#1F4E9C", lineHeight: "14px" }}>
                  ▼ 스크롤하면 외 {incidents.length - 6}건 더 있어요
                </div>
              )}

              <div style={{ flex: "none", paddingTop: 2, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                <button
                  type="button"
                  aria-label="지난 사건 보기"
                  onClick={() => setShowPast(true)}
                  style={pastBtnStyle}
                >
                  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
                    <path d="M2.2 7a4.8 4.8 0 1 0 1.5-3.5M2 2v3h3" stroke={C.navy} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                    <path d="M7 4.5V7l1.8 1.2" stroke={C.navy} strokeWidth="1.5" strokeLinecap="round" />
                  </svg>
                  지난 사건 보기
                </button>
                <span style={{ fontSize: 11.5, color: C.sub }}>오늘 종료 {past.length}건</span>
              </div>

              {/* 선택한 사건의 병원 */}
              <div style={{ flex: "1 1 0", minHeight: 0, borderTop: `1px solid ${C.line2}`, paddingTop: 8, display: "flex", flexDirection: "column", gap: 6 }}>
                {selected ? (
                  <>
                    {/* 선택한 사건 머리(2026-10-04) — 한 줄에 다 넣으면 증상·요청 수에 밀려 구급대 이름이 사라졌다.
                        1줄: 번호·구급대 이름·중증도 / 2줄: 어떤 사건인지(증상)·요청 병원 수·범위·다음 확장 */}
                    <div style={{ display: "flex", flexDirection: "column", gap: 3, padding: "0 2px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
                        <NumBadge n={selected.num} />
                        <span title={selected.name} style={{ flex: "0 1 auto", minWidth: 0, fontSize: 14, fontWeight: 700, color: C.navy, overflow: "hidden", textOverflow: "ellipsis" }}>{shortAmb(selected.name)}</span>
                        {selected.sev && <SevChip sev={selected.sev} />}
                        {alertView.handling.has(selected.caseId) && (
                          <button
                            type="button"
                            onClick={() => alertView.finishHandling(selected.caseId)}
                            title="이 화면 안에서만 표시됩니다(다른 관제 화면과 공유되지 않음)"
                            style={{ marginLeft: "auto", flex: "none", height: 22, padding: "0 10px", border: "1px solid #1F4E9C", borderRadius: 11, background: "#fff", fontFamily: "inherit", fontSize: 11.5, fontWeight: 700, color: "#1F4E9C", cursor: "pointer" }}
                          >
                            처리 중 · 완료로 표시
                          </button>
                        )}
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0, fontSize: 11.5, color: C.sub }}>
                        {selected.sym && <span style={{ flex: "0 1 auto", minWidth: 0, display: "flex" }}><SymChip text={selected.sym} /></span>}
                        <span style={{ flex: "none" }}>
                          {selected.matched ? `요청 ${selected.hospitals.length}곳 · ${zoneText(selected.zone)}` : "요청 전"}
                        </span>
                      </div>
                    </div>

                    <CaseStatusSummary inc={selected} now={now} />

                    {isTransportStalled(selected, now) && <HandlingActions />}

                    <div role="tablist" style={{ display: "flex", gap: 4, width: "100%" }}>
                      {tabDefs.map(([key, label, count]) => {
                        const on = activeTab === key;
                        const empty = count === 0 && key !== "all";
                        return (
                          <button
                            key={key}
                            type="button"
                            role="tab"
                            aria-selected={on}
                            onClick={() => setTab(key)}
                            style={{ ...tabStyle, ...(on ? { background: C.navy, color: "#fff" } : { background: C.bg, color: empty ? C.faint : C.ink2 }) }}
                          >
                            <span style={{ fontSize: 10.5, fontWeight: 500, maxWidth: "100%", overflow: "hidden", textOverflow: "ellipsis" }}>{label}</span>
                            <span style={{ fontSize: 15, fontWeight: 900 }}>{count}</span>
                          </button>
                        );
                      })}
                    </div>

                    <div style={{ flex: "0 1 auto", minHeight: 0, maxHeight: "55%", display: "flex", flexDirection: "column" }}>
                      <div className="ctl-scroll" style={{ minHeight: 0, overflowY: "auto", display: "flex", flexDirection: "column", paddingRight: 2 }}>
                        {rows.map((h) => {
                          const on = hoverHospital === h.hospitalId;
                          const at = h.respondedAt ? Date.parse(h.respondedAt) : null;
                          const fresh = h.st !== "w" && at != null && now - at < 10000;
                          const flash = h.st !== "w" && at != null && now - at < 2400;
                          const text = reqLabel(h);
                          return (
                            <div
                              key={h.hospitalId}
                              onMouseEnter={() => setHoverHospital(h.hospitalId)}
                              onMouseLeave={() => setHoverHospital("")}
                              style={{
                                ...srowStyle,
                                background: flash ? "#FFF1B8" : on ? "#E8EEF8" : h.st === "r" ? "#FEF3F1" : h.st === "a" || h.st === "t" ? "#F1F8E9" : undefined,
                              }}
                            >
                              <span style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }} title={`${h.name} · H-${h.hospitalId}`}>
                                <span style={{ overflow: "hidden", textOverflow: "ellipsis", fontWeight: 500 }}>{shortHospital(h.name)}</span>
                                {h.reason && <span style={{ overflow: "hidden", textOverflow: "ellipsis", fontSize: 11, color: "#D93025" }}>사유 · {h.reason}</span>}
                              </span>
                              <span style={{ flex: "none", width: selected.zone > 1 ? 72 : 48, textAlign: "right", fontSize: 11.5, color: C.sub }}>{h.km.toFixed(1)}km{selected.zone > 1 ? `·존${h.zone}` : ""}</span>
                              <span style={{ flex: "none", width: 62, display: "flex", alignItems: "center", gap: 4, fontWeight: 700, color: ST_TEXT[h.st] }}>
                                <StatusIcon st={h.st} color={ST_TEXT[h.st]} />
                                {text}
                              </span>
                              <span style={{ flex: "none", width: 50, textAlign: "right", fontSize: 11.5, color: fresh ? C.blue : C.muted, fontWeight: fresh ? 700 : 400 }}>
                                {h.st === "w" || at == null ? "" : fresh ? "방금" : fmtClock(at)}
                              </span>
                            </div>
                          );
                        })}
                        {rows.length === 0 && emptyText[activeTab] && (
                          <div style={{ padding: "24px 12px", textAlign: "center", fontSize: 12.5, color: C.muted, whiteSpace: "normal" }}>{emptyText[activeTab]}</div>
                        )}
                      </div>
                    </div>
                    <CaseTimeline inc={selected} now={now} />
                  </>
                ) : (
                  <div style={{ padding: "24px 12px", textAlign: "center", fontSize: 12.5, color: C.muted, whiteSpace: "normal" }}>
                    사건을 고르면 그 사건의 요청 병원과 응답이 여기에 뜹니다.
                  </div>
                )}
              </div>
            </div>
          </aside>

          {consoleMounted && (
            <section id="map-demo-console" aria-label="시연 조작" className="monitor-console-pane" style={{ display: consoleOpen ? "flex" : "none" }}>
              <DemoConsole embedded activeApid={DEMO_UNIT.apid} onAmbulanceChange={selectConsoleAmbulance} />
            </section>
          )}

          {/* 오른쪽: 지도 + 하단 구급차 패널. 3D 보기 중에도 2D 지도는 숨기기만 해서 다시 켜도 지도가 초기화되지 않는다 */}
          {view === "3d" && (
            <iframe
              title="3D 거미줄"
              src={SPIDER_URL}
              style={{ flex: "1 1 0", minWidth: 0, border: `1px solid ${C.line}`, borderRadius: 14, background: "#fff" }}
            />
          )}
          <div style={{ display: view === "2d" ? "contents" : "none" }}>
          <ControlMapPanel
            overview={overview}
            incidents={incidents}
            selected={selected}
            activeTab={activeTab}
            ambulanceSim={ambulanceSim}
            hoverHospital={hoverHospital}
            hoverAmb={hoverAmb}
            ambInTab={ambInTab}
            alertCaseIds={alertCaseIds}
            onHoverHospital={setHoverHospital}
            onHoverAmb={setHoverAmb}
            onSelectCase={selectCase}
          >
            <div className="monitor-ambulance-panel" style={{ position: "absolute", left: 12, right: 12, bottom: 12, height: 158, boxSizing: "border-box", zIndex: 90, background: "#fff", border: `1px solid ${C.line}`, borderRadius: 12, boxShadow: "0 4px 16px rgba(20,30,50,.14)", padding: "10px 12px", display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "6px 14px" }}>
                <div style={{ fontSize: 15, fontWeight: 700, color: C.navy }}>구급차 {ambRows.length}대</div>
                <div role="tablist" style={{ display: "flex", gap: 6 }}>
                  {([["all", "전체", ambRows.length], ["sd", "현장·출동", ambCount.s + ambCount.d], ["t", "이송 중", ambCount.t], ["b", "기지 대기", ambCount.b]] as [AmbTab, string, number][]).map(([key, label, count]) => {
                    const on = ambTab === key;
                    return (
                      <button
                        key={key}
                        type="button"
                        role="tab"
                        aria-selected={on}
                        onClick={() => setAmbTab(key)}
                        style={{ ...tab2Style, ...(on ? { background: C.navy, color: "#fff" } : { background: C.bg, color: count === 0 && key !== "all" ? C.faint : C.ink2 }) }}
                      >
                        {label}<b style={{ fontWeight: 900, marginLeft: 5 }}>{count}</b>
                      </button>
                    );
                  })}
                </div>
                <div style={{ flex: "1 1 0" }} />
                <div style={{ fontSize: 12, color: C.sub }}>{selected ? "선택한 사건 기준 · 가까운 순" : "상태순"}</div>
              </div>
              <div className="ctl-scroll" style={{ flex: "none", height: 104, display: "grid", gridTemplateColumns: "repeat(2,minmax(0,1fr))", gridAutoRows: 30, gap: 7, alignContent: "start", paddingRight: 8, scrollSnapType: "y mandatory", boxSizing: "border-box" }}>
                {ambList.map((a) => {
                  const on = hoverAmb === a.apid;
                  return (
                    <div
                      key={a.apid}
                      onMouseEnter={() => setHoverAmb(a.apid)}
                      onMouseLeave={() => setHoverAmb("")}
                      style={{ ...acellStyle, background: on ? "#E8EEF8" : a.key === "s" ? "#FFF4EC" : undefined }}
                    >
                      <span title={a.name} style={{ flex: "1 1 auto", minWidth: 0, fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis" }}>{shortAmb(a.name)}</span>
                      <span style={{ flex: "none", color: C.sub, fontSize: 12, minWidth: 38, textAlign: "right" }}>
                        {a.km == null ? "" : a.km < 0.05 ? "현장" : `${a.km.toFixed(1)}km`}
                      </span>
                      <span style={{ flex: "none", width: 62, textAlign: "center", fontSize: 11.5, lineHeight: "17px", borderRadius: 9, ...AMB_CHIP[a.key] }}>{a.text}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          </ControlMapPanel>
          </div>
        </div>
      </div>

      {showPast && (
        <PastModal today={past} onClose={() => setShowPast(false)} />
      )}
    </div>
  );
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
    <div role="dialog" aria-modal="true" aria-label="지난 사건" style={{ position: "absolute", inset: 0, zIndex: 300, background: "rgba(20,33,61,.5)", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <button type="button" aria-label="닫기" onClick={onClose} style={{ position: "absolute", inset: 0, border: 0, background: "transparent", cursor: "default" }} />
      <div style={{ position: "relative", width: 940, height: 660, maxWidth: "calc(100% - 48px)", maxHeight: "calc(100% - 48px)", background: "#fff", borderRadius: 16, boxShadow: "0 20px 60px rgba(20,33,61,.35)", display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <div style={{ flex: "none", display: "flex", alignItems: "center", gap: 12, padding: "16px 22px", borderBottom: `1px solid ${C.line2}` }}>
          <div style={{ fontSize: 18, fontWeight: 900, color: C.navy }}>지난 사건</div>
          <div style={{ fontSize: 12.5, color: C.sub }}>
            {multiDay ? `${from} ~ ${to}` : from === daysAgo(0) ? "오늘" : from} 종료된 사건 {n}건 · 최근 종료 순
          </div>
          {ARCHIVE_MOCK && <span style={{ fontSize: 11, fontWeight: 700, color: "#C75B00", background: "#FFF1E0", borderRadius: 9, padding: "0 8px", lineHeight: "18px" }}>가짜 데이터 (설계 확인용)</span>}
          <div style={{ flex: "1 1 0" }} />
          <button type="button" onClick={onClose} style={{ fontFamily: "inherit", fontSize: 13, color: C.ink3, background: "#fff", border: `1px solid ${C.line}`, borderRadius: 8, padding: "5px 12px", cursor: "pointer" }}>닫기 ✕</button>
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
                    style={{ ...prowStyle, ...(on ? { background: "#F5F8FF", border: "1px solid #C9D4E6" } : {}) }}
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
                      <span style={{ flex: "none", fontWeight: 700, padding: "0 8px", borderRadius: 9, lineHeight: "17px", maxWidth: 210, overflow: "hidden", textOverflow: "ellipsis", ...res.style }}>{res.text}</span>
                    </div>
                  </button>
                );
              })}
              {error && <div style={{ padding: "40px 12px", textAlign: "center", fontSize: 12.5, color: "#D93025", whiteSpace: "normal" }}>{error}</div>}
              {!error && !loading && past.length === 0 && <div style={{ padding: "40px 12px", textAlign: "center", fontSize: 12.5, color: C.muted }}>조건에 맞는 사건이 없습니다.</div>}
              {total > past.length && <div style={{ padding: "8px 12px", textAlign: "center", fontSize: 11.5, color: C.muted }}>최근 {past.length}건만 표시 (전체 {total}건) — 통계는 전체 기준</div>}
            </div>
          </div>

          <div style={{ flex: "1 1 0", minWidth: 0, border: `1px solid ${C.line2}`, borderRadius: 12, padding: "16px 18px", display: "flex", flexDirection: "column", gap: 12 }}>
            {sel ? (
              <>
                <div style={{ flex: "none", display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 17, fontWeight: 900, color: C.navy, overflow: "hidden", textOverflow: "ellipsis" }}>{shortAmb(sel.ambulanceName ?? sel.apid ?? "구급차")}</span>
                  {selSev && <SevChip sev={selSev} />}
                  {sel.symptom && <SymChip text={sel.symptom} />}
                  {selRes && <span style={{ flex: "none", fontSize: 11.5, fontWeight: 700, padding: "0 9px", borderRadius: 9, lineHeight: "18px", ...selRes.style }}>{selRes.text}</span>}
                </div>
                <div style={{ flex: "none", display: "grid", gridTemplateColumns: "repeat(4,minmax(0,1fr))", gap: 8 }}>
                  <MiniStat label="요청 병원" value={`${sel.requested}곳`} />
                  <MiniStat label="수용 불가" value={`${sel.rejected}곳`} color="#D93025" />
                  <MiniStat label="요청 범위" value={sel.zone ? zoneText(sel.zone) : "요청 전"} />
                  <MiniStat label="총 소요" value={fmtElapsed(durMs(sel))} />
                </div>
                <div style={{ flex: "none", fontSize: 12.5, color: C.ink3, padding: "8px 12px", background: "#F5F8FF", borderRadius: 8, whiteSpace: "normal" }}>
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
                            {!last && <span style={{ position: "absolute", left: 6, top: 15, bottom: -3, width: 2, background: "#E1E5EB" }} />}
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
  return <span style={{ width: 1, height: 14, background: "#D5DAE1" }} />;
}

function NumBadge({ n }: { n: number }) {
  return (
    <span style={{ flex: "none", minWidth: 17, height: 17, padding: "0 4px", boxSizing: "border-box", borderRadius: 9, background: C.navy, color: "#fff", fontSize: 10, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center" }}>
      {n}
    </span>
  );
}

function SevChip({ sev }: { sev: keyof typeof SEV_STYLE }) {
  return <span style={{ flex: "none", fontSize: 10.5, fontWeight: 700, padding: "0 7px", borderRadius: 9, lineHeight: "16px", ...SEV_STYLE[sev] }}>{sev}</span>;
}

function SymChip({ text }: { text: string }) {
  return (
    <span
      title={text}
      style={{
        display: "inline-block", maxWidth: "100%", overflow: "hidden", textOverflow: "ellipsis", verticalAlign: "middle",
        fontSize: 10.5, fontWeight: 500, color: C.ink3, background: C.bg, borderRadius: 5, padding: "1px 6px", whiteSpace: "nowrap",
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
    <div style={{ border: `1px solid ${C.line2}`, borderRadius: 10, padding: "8px 12px" }}>
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

const cardStyle: React.CSSProperties = {
  background: "#fff", border: `1px solid ${C.line}`, borderRadius: 14, padding: 14, boxSizing: "border-box",
  display: "flex", flexDirection: "column", gap: 8, minHeight: 0,
};
const irowStyle: React.CSSProperties = {
  flex: "none", display: "flex", flexDirection: "column", justifyContent: "center", gap: 3, width: "100%", height: 42,
  boxSizing: "border-box", padding: "0 10px", border: `1px solid ${C.line2}`, borderRadius: 10, background: "#fff",
  fontFamily: "inherit", textAlign: "left", cursor: "pointer", scrollSnapAlign: "start", transition: "background .6s",
};
const srowStyle: React.CSSProperties = {
  display: "flex", alignItems: "center", gap: 5, flex: "none", minHeight: 24, padding: "1px 6px", borderRadius: 4, fontSize: 12,
  fontVariantNumeric: "tabular-nums", cursor: "default", transition: "background .6s",
};
const tabStyle: React.CSSProperties = {
  flex: "1 1 0", minWidth: 0, boxSizing: "border-box", fontFamily: "inherit", border: 0, borderRadius: 8, height: 38,
  padding: "0 2px", cursor: "pointer", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
  lineHeight: 1.15, fontVariantNumeric: "tabular-nums",
};
const tab2Style: React.CSSProperties = {
  flex: "none", boxSizing: "border-box", fontFamily: "inherit", fontSize: 12, fontWeight: 500, border: 0, borderRadius: 13,
  height: 26, padding: "0 12px", cursor: "pointer", fontVariantNumeric: "tabular-nums",
};
const acellStyle: React.CSSProperties = {
  display: "flex", alignItems: "center", gap: 8, height: 30, padding: "0 10px", border: `1px solid ${C.line2}`, borderRadius: 8,
  fontSize: 12.5, fontVariantNumeric: "tabular-nums", cursor: "default", boxSizing: "border-box", scrollSnapAlign: "start",
};
const dateInputStyle: React.CSSProperties = {
  boxSizing: "border-box", height: 26, padding: "0 8px", border: `1px solid ${C.line}`, borderRadius: 8,
  fontFamily: "inherit", fontSize: 12, color: C.ink2, background: "#fff",
};
const pastBtnStyle: React.CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: 6, height: 30, padding: "0 12px", border: "1px solid #CDD3DA",
  borderRadius: 8, background: "#fff", fontFamily: "inherit", fontSize: 12.5, fontWeight: 700, color: C.navy, cursor: "pointer",
};
const prowStyle: React.CSSProperties = {
  flex: "none", display: "flex", flexDirection: "column", justifyContent: "center", gap: 4, width: "100%", height: 58,
  boxSizing: "border-box", padding: "0 12px", border: `1px solid ${C.line2}`, borderRadius: 10, background: "#fff",
  fontFamily: "inherit", textAlign: "left", cursor: "pointer",
};
