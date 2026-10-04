"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { css, cx } from "styled-system/css";
import {
  SCENARIOS,
  STEP_INTERVAL_MS,
  TIER_LABEL,
} from "@/components/ambulance/TransportMonitorPanel";
import { thinScrollbarStyle } from "@/components/ui/scrollbar-style";
import { CONNECTION_LABEL, useDashboardSocket } from "@/hooks/use-dashboard-socket";
import { searchPlaces } from "@/lib/geocode";
import { PHASE_SHORT, STATUS_ICON, STATUS_SHORT, statusColor } from "@/lib/monitor";
import type { GeocodeResult, MonitorCase, VitalObservationIn } from "@/types/dashboard";

// 시연 시나리오 콘솔 (2026-10-04, 3차 — 위저드형). 한 화면에 다 깔지 않고 **앱처럼 한 번에
// 한 단계만** 보여준다: 버튼을 누르면 다음 화면으로 넘어가고, 출동·매칭처럼 기다리는 구간은
// 중간 화면이 뜬다. 화면 전환은 라우팅이 아니라 hub 상태로 계산한다 — 상태가 곧 단계라서
// 운영자가 잘못된 순서로 누를 수 없고, 수용 완료 후엔 저절로 ①로 돌아온다(새 상황 준비 완료).
//
// - 통화 버튼 없음 — 통화는 대원 휴대폰 전화 앱(P-코드) 담당. ② [환자 상태 카드]를 누르면
//   내부적으로만 통화 신호 + 요약 전송(hub 흐름 불변).
// - ③에는 **일괄 처리**가 있다: 미응답 병원 전부 승인/전부 불가 (전부 불가는 거절 비율
//   존 확장을 눈앞에서 보여주는 연출로도 쓰인다).
// - 모든 조작은 기존 hub 메시지 그대로. 가짜 환자 전송만 Next 프록시(/api/demo/voice).
// - 운영자 전용·인증 없음(시연 범위). 가상 데이터에는 전부 가상 표시가 남는다.

const PATIENT_TEMPLATES = [
  {
    key: "cardiac", label: "흉통 · 경색 의심", severity: "중증" as const,
    detail: "62세 남성 · 흉통, 호흡 곤란 · 필요 진료과 순환기내과",
    // KTAS·활력징후·의식·발생 시점까지 — 음성 요약(MF_BERT v2)이 실제로 뽑는 표시용
    // 값들을 데모 요약에도 넣어, 통화 요약·병원 카드의 환자 패널(PatientVitals)이 그려지게 한다.
    summary: {
      patient: "62세 남성", mechanism: "흉통(심장성) — 경색 의심",
      symptoms: ["흉통", "호흡 곤란"], treatment: ["산소 공급", "ECG"],
      severity_tag: "high", required_department: "순환기내과",
      ktas_level: 2, consciousness: "A", onset: "30분 전부터", chief_complaint: "흉통(심장성)",
      vitals: [{ sequence: 1, sbp: 150, dbp: 90, hr: 110, spo2: 96 }],
    },
    transcript: "환자 62세 남성, 흉통 호소. 혈압 150에 90, 맥박 110, 산소포화도 96.",
  },
  {
    key: "trauma", label: "교통사고 다발성 외상", severity: "중증" as const,
    detail: "35세 남성 · 흉부·복부 충격, 의식 혼미 · 필요 진료과 외과",
    summary: {
      patient: "35세 남성", mechanism: "교통사고 — 흉부·복부 충격, 다발성 외상 의심",
      symptoms: ["흉부 통증", "복부 압통", "의식 혼미"], treatment: ["경추 고정", "산소 공급"],
      severity_tag: "high", required_department: "외과",
      ktas_level: 2, consciousness: "V", onset: "사고 직후", chief_complaint: "다발성 외상",
      vitals: [{ sequence: 1, sbp: 100, hr: 115, rr: 22, spo2: 94 }],
    },
    transcript: "30대 남성 교통사고입니다. 흉부 복부 충격, 의식이 혼미합니다.",
  },
  {
    key: "abdominal", label: "복통 · 복부 압통", severity: "중등증" as const,
    detail: "48세 여성 · 지속되는 복통, 구토 · 필요 진료과 외과",
    summary: {
      patient: "48세 여성", mechanism: "급성 복통 — 복부 압통, 장폐색·충수염 의심",
      symptoms: ["복통", "구토"], treatment: ["금식", "수액"],
      severity_tag: "medium", required_department: "외과",
      ktas_level: 3, consciousness: "A", onset: "6시간 전부터", chief_complaint: "급성 복통",
      vitals: [{ sequence: 1, sbp: 125, hr: 95, bt: 37.8 }],
    },
    transcript: "40대 여성, 복통이 심하고 구토가 있습니다. 복부 압통이 뚜렷합니다.",
  },
  {
    key: "mild", label: "발목 염좌", severity: "경증" as const,
    detail: "24세 여성 · 발목 통증·부종 · 필요 진료과 정형외과",
    summary: {
      patient: "24세 여성", mechanism: "보행 중 접질림 — 발목 염좌 의심",
      symptoms: ["발목 통증", "부종"], treatment: ["부목 고정"],
      severity_tag: "low", required_department: "정형외과",
      ktas_level: 4, consciousness: "A", onset: "1시간 전부터", chief_complaint: "발목 통증",
      vitals: [{ sequence: 1, sbp: 120, hr: 78 }],
    },
    transcript: "20대 여성, 발목을 접질렸습니다. 통증과 부종 외 특이사항 없습니다.",
  },
] as const;

const PRESET_LOCATIONS = [
  { label: "서울시청 앞", lat: 37.5665, lng: 126.978 },
  { label: "이태원역", lat: 37.5345, lng: 126.9942 },
  { label: "강남역", lat: 37.4979, lng: 127.0276 },
  { label: "여의도공원", lat: 37.5219, lng: 126.9245 },
] as const;

type Spot = { label: string; lat: number; lng: number } | null;

// 실무에선 발생 지점마다 출동하는 구급대가 다르다 — 지점을 고르면 기지가 가장 가까운
// "대기 중" 구급차를 자동 선정한다(선정 주체는 상황실 운영자 = 이 콘솔, hub는 apid 그대로 받음).
function haversineKm(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const rad = (v: number) => (v * Math.PI) / 180;
  const a =
    Math.sin(rad(lat2 - lat1) / 2) ** 2 +
    Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(rad(lng2 - lng1) / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(a));
}
type Screen = "none" | "occur" | "enroute" | "report" | "matching" | "respond" | "transport" | "arrival";

const SCREEN_STEP: Record<Screen, number> = {
  none: 0, occur: 1, enroute: 1, report: 2, matching: 2, respond: 3, transport: 4, arrival: 5,
};
const STEP_TITLES = ["환자 발생", "신고 접수", "병원 응답", "이송 중", "도착 결과"];

export default function ControlPage() {
  const { state, connectionMode, sendAction, sendCallSignal, sendSimCommand, sendTransportVitals, sendZoneExpand } =
    useDashboardSocket({ role: "monitor", id: "control" });
  const simOn = state.identity.simDispatch === true;
  const ambulances = state.mapOverview?.ambulances ?? [];
  const [selectedApid, setSelectedApid] = useState<string | null>(null);
  const apid = selectedApid ?? ambulances[0]?.apid ?? null;
  const sim = apid ? state.ambulanceSim[apid] ?? null : null;
  const phase = sim?.phase ?? "idle";

  const [localCaseIds, setLocalCaseIds] = useState<Record<string, string>>({});
  const caseId = (simOn ? sim?.caseId : null) ?? (apid ? localCaseIds[apid] : null) ?? null;
  const myCase: MonitorCase | null = caseId ? state.monitorCases[caseId] ?? null : null;
  const confirmedId = myCase?.hospitals.find((h) => h.status === "confirmed")?.hospitalId ?? null;

  // 발생 지점은 항상 명시한다(기본 첫 프리셋) — 출동 구급대는 운영자가 고르지 않고
  // 지점에서 가장 가까운 대기 구급대가 자동 결정되므로, 지점 없는 '무작위'는 뺐다(2026-10-04).
  const [spot, setSpot] = useState<Spot>(PRESET_LOCATIONS[0]);
  // 신고 접수 때 고른 1차 증상(2026-10-04) — 실무에선 상황실이 신고 전화에서 증상 개요를
  // 먼저 안다. 출동과 함께 예비 고지에 실리고, ②(현장 확인)에서 기본 선택으로 이어진다.
  const [reportedKey, setReportedKey] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<GeocodeResult[]>([]);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [reported, setReported] = useState<Record<string, boolean>>({});
  // ② 현장 확인 입력 방식(2026-10-04): 대원 휴대폰 전화 앱의 실제 음성(STT → MF_BERT 구조화) 또는
  // 정해진 상황 카드(가상 환자). 어느 쪽으로 들어온 사건인지 이후 화면에 표시한다 — 음성 사건은 hub의
  // 통화 상태(call_status)로 알아보고, 정해진 상황은 보낼 때 templateCases에 기록한다.
  const [inputMode, setInputMode] = useState<"voice" | "template">("template");
  const [templateCases, setTemplateCases] = useState<Record<string, string>>({});
  const [sending, setSending] = useState(false);
  // sim이 꺼진 환경 전용 — 도착 게이팅이 없어 [도착 결과 입력]으로 수동 전환한다
  const [manualArrival, setManualArrival] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [playing, setPlaying] = useState<Record<string, string | null>>({});
  const timersRef = useRef<Record<string, ReturnType<typeof setInterval>>>({});

  const now = () => new Date().toISOString();
  const note = (text: string) => setFeedback(`${new Date().toLocaleTimeString("ko-KR")} · ${text}`);
  // 방금 한 동작 안내(초록 박스)는 5초 뒤 사라진다(2026-10-04). 새 안내가 오면 그때부터 다시 5초.
  useEffect(() => {
    if (!feedback) return;
    const timer = setTimeout(() => setFeedback(null), 5000);
    return () => clearTimeout(timer);
  }, [feedback]);
  const myCall = caseId ? state.callStatus[caseId] ?? null : null;
  // 휴대폰 통화가 끝나면 음성 분석(STT·구조화)을 기다리는 "매칭 중" 화면으로 넘어간다
  const isReported = caseId != null && (reported[caseId] === true || myCase != null || myCall?.state === "ended");
  const caseSource: "voice" | "template" | null = caseId
    ? templateCases[caseId] ? "template" : myCall ? "voice" : null
    : null;

  // ── 화면 = hub 상태 (상태가 곧 단계라 잘못된 순서로 누를 수 없다) ──
  const screen: Screen = (() => {
    if (!apid) return "none";
    if (simOn) {
      if (phase === "dispatching") return "enroute";
      if (phase === "on_scene") return !isReported ? "report" : myCase ? "respond" : "matching";
      if (phase === "transporting") return confirmedId ? "transport" : myCase ? "respond" : "matching";
      if (phase === "at_hospital") return "arrival";
      if (phase === "rerouting") return "respond"; // 도착 후 수용 불가 — 재선택
      return "occur"; // idle · returning
    }
    if (!isReported) return "report";
    if (!myCase) return "matching";
    if (!confirmedId) return "respond";
    return manualArrival ? "arrival" : "transport";
  })();
  const step = SCREEN_STEP[screen];

  // ── 조작 ──
  // 지점이 정해지면 기지가 가장 가까운 대기(복귀 중 포함) 구급차를 고른다 — 실무에선 발생
  // 지점마다 출동 구급대가 다르다. 선정 주체는 상황실(이 콘솔)이고 hub는 apid를 그대로 받는다.
  // 전부 바쁘면 가장 가까운 순 폴백.
  function nearestAmbulance(target: NonNullable<Spot>): { apid: string; name: string; km: number } | null {
    if (ambulances.length === 0) return null;
    const ranked = ambulances
      .map((a) => ({ apid: a.apid, name: a.name, km: haversineKm(target.lat, target.lng, a.base.lat, a.base.lng) }))
      .sort((a, b) => a.km - b.km);
    return ranked.find((a) => ["idle", "returning"].includes(state.ambulanceSim[a.apid]?.phase ?? "idle")) ?? ranked[0];
  }
  const responder = spot ? nearestAmbulance(spot) : null;

  function handleOccur() {
    // 출동대는 수동 선택과 무관하게 **항상 자동**(최근접 대기 구급대) — 상단 칩은 보기 전환일 뿐이다
    const chosenApid = responder?.apid ?? null;
    const template = PATIENT_TEMPLATES.find((t) => t.key === reportedKey) ?? null;
    if (!template) return;
    if (!chosenApid) {
      note("출동 가능한 구급대가 없습니다");
      return;
    }
    setSelectedApid(chosenApid);
    const newCaseId = crypto.randomUUID();
    setLocalCaseIds((prev) => ({ ...prev, [chosenApid]: newCaseId }));
    setManualArrival(false);
    const target = spot ? { lat: spot.lat, lng: spot.lng, label: spot.label, mode: "map" as const } : null;
    const report = { symptom: template.label, severity: template.summary.severity_tag };
    if (sendSimCommand("dispatch", chosenApid, newCaseId, target, report)) {
      note(
        `신고 접수 — ${template.label}(${template.severity}) · ${spot?.label ?? "무작위 지점"} · ${responder?.name ?? chosenApid} 출동` +
          (template.severity === "경증" ? " (경증 신고 — 예비 고지 생략)" : ""),
      );
    }
  }

  async function handleSearch() {
    if (!query.trim() || !apid) return;
    const { results, error } = await searchPlaces(query.trim(), apid);
    setSearchResults(results.slice(0, 5));
    setSearchError(error ?? (results.length === 0 ? "검색 결과가 없습니다" : null));
  }

  // 구급차·사건을 지정해 현장 확인(통화 신호 + 요약 전송)을 보낸다 — 수동 ②와 대량사고
  // 자동 신고가 같은 경로를 쓴다.
  async function handleReportFor(targetApid: string, targetCaseId: string, templateKey: string) {
    const template = PATIENT_TEMPLATES.find((t) => t.key === templateKey);
    if (!template) return;
    // 통화 신호는 시뮬레이션이 꺼진 환경에서만 보낸다(사건을 구급차에 묶는 용도). 시뮬레이션 중엔 출동 때 이미
    // 묶여 있고, 중앙 voice가 떠 있으면 이 신호가 빈 통화로 voice에 가서 음성 없는 요약이 정해진 상황을 덮어쓸
    // 수 있었다(2026-10-04) — 정해진 상황은 음성 경로를 아예 타지 않게 한다.
    const signal = !simOn;
    if (signal) sendCallSignal("call_started", targetApid, targetCaseId);
    setTemplateCases((prev) => ({ ...prev, [targetCaseId]: template.label }));
    try {
      const response = await fetch("/api/demo/voice", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          caseId: targetCaseId,
          transcript: { raw_text: template.transcript, filtered_text: template.transcript },
          summary: template.summary,
          source: "ai",
          // hub는 읽지 않는 필드 — 원본 사본(hub data/live/output)에서 음성 입력과 구분하는 표시
          model_used: { stt: "scenario-template", llm: "scenario-template" },
        }),
      });
      if (response.ok) {
        setReported((prev) => ({ ...prev, [targetCaseId]: true }));
        note(`현장 확인(정해진 상황) — ${template.label} · 인근 병원 동시 전달`);
      } else {
        setTemplateCases((prev) => {
          const next = { ...prev };
          delete next[targetCaseId];
          return next;
        });
        note(`전송 실패 (${response.status})`);
      }
    } finally {
      if (signal) sendCallSignal("call_ended", targetApid, targetCaseId);
    }
  }

  async function handleReport(templateKey: string) {
    if (!apid || sending) return;
    let activeCaseId = caseId;
    if (!activeCaseId) {
      activeCaseId = crypto.randomUUID();
      setLocalCaseIds((prev) => ({ ...prev, [apid]: activeCaseId! }));
    }
    setSending(true);
    setManualArrival(false);
    try {
      await handleReportFor(apid, activeCaseId, templateKey);
    } finally {
      setSending(false);
    }
  }

  // ── 대량사고(MCI) 모드 (2026-10-04, 자원 분배판) ──
  // 사상자 구성(중증/중등증/경증 수)을 입력하면 **이송 자원을 분배**한다: 가용 구급대 수만큼
  // 중증 우선으로 1차 배정하고, 초과 사상자는 대기열에 남겨 구급대가 복귀하는 대로 자동
  // 재출동한다(왕복 수송). 현장 도착 시 그 사상자의 중증도로 자동 신고. 병원 쪽 분배는
  // hub 몫이다 — 중증도-센터 가산과 이송 중 부하 페널티가 같은 병원에 몰아 보내지 않는다.
  const mciPlanRef = useRef<Record<string, string>>({});
  const autoSendingRef = useRef<Set<string>>(new Set());
  const mciQueueRef = useRef<string[]>([]);          // 대기 사상자(템플릿 키, 중증 우선 정렬)
  const mciSpotRef = useRef<Spot>(null);             // 이 대량사고의 현장(재출동도 같은 곳으로)
  const mciDispatchedRef = useRef(0);                // 현장 마커 간격용 누적 카운터
  const pendingDispatchRef = useRef<Record<string, string>>({}); // apid -> 방금 보낸 caseId(중복 출동 방지)
  const [mciOn, setMciOn] = useState(false);
  const [mciRemaining, setMciRemaining] = useState(0);
  const [mciCounts, setMciCounts] = useState({ high: 2, medium: 3, low: 4 });

  const idleAmbulances = () =>
    ambulances.filter((a) => ["idle", "returning"].includes(state.ambulanceSim[a.apid]?.phase ?? "idle"));

  function mciDispatchTo(targetApid: string) {
    const templateKey = mciQueueRef.current.shift();
    const scene = mciSpotRef.current;
    if (!templateKey || !scene) return false;
    const template = PATIENT_TEMPLATES.find((t) => t.key === templateKey)!;
    const newCaseId = crypto.randomUUID();
    setLocalCaseIds((prev) => ({ ...prev, [targetApid]: newCaseId }));
    mciPlanRef.current[newCaseId] = templateKey;
    pendingDispatchRef.current[targetApid] = newCaseId;
    const index = mciDispatchedRef.current++;
    // 같은 현장이되 사상자마다 수십 m 간격 — 마커가 완전히 겹치지 않게
    const jitter = {
      lat: scene.lat + ((index % 5) - 2) * 0.0012,
      lng: scene.lng + (Math.floor(index / 5) - 1) * 0.0012,
      label: scene.label,
      mode: "map" as const,
    };
    sendSimCommand("dispatch", targetApid, newCaseId, jitter, {
      symptom: template.label,
      severity: template.summary.severity_tag,
    });
    setMciRemaining(mciQueueRef.current.length);
    return true;
  }

  function handleMciOccur() {
    if (!spot) return;
    const idle = idleAmbulances();
    if (idle.length === 0) {
      note("출동 가능한 구급대가 없습니다");
      return;
    }
    // 사상자 큐 — 중증 우선(현장 triage와 같은 원칙). 중증은 외상·심혈관을 섞는다.
    const queue: string[] = [];
    for (let i = 0; i < mciCounts.high; i++) queue.push(i % 2 === 0 ? "trauma" : "cardiac");
    for (let i = 0; i < mciCounts.medium; i++) queue.push("abdominal");
    for (let i = 0; i < mciCounts.low; i++) queue.push("mild");
    if (queue.length === 0) {
      note("사상자 수를 입력하세요");
      return;
    }
    const total = queue.length;
    mciQueueRef.current = queue;
    mciSpotRef.current = spot;
    mciDispatchedRef.current = 0;
    setMciOn(true);
    const firstWave = Math.min(idle.length, total);
    idle.slice(0, firstWave).forEach((ambulance) => mciDispatchTo(ambulance.apid));
    note(
      `🔥 대량사고 — ${spot.label} · 사상자 ${total}명 · 1차 출동 ${firstWave}대(중증 우선), ` +
        `대기 ${mciQueueRef.current.length}명(복귀하는 대로 자동 재출동)`,
    );
  }

  // 대량사고 자동 신고 + 자원 재분배: 계획된 사건의 구급차가 현장에 도착하면 그 자리에서
  // 신고를 보내고, 어떤 구급대든 대기(복귀)로 돌아오면 대기열의 다음 사상자에게 재출동한다.
  useEffect(() => {
    for (const sim of Object.values(state.ambulanceSim)) {
      // 보낸 출동이 반영됐으면 중복 방지 표시 해제
      if (pendingDispatchRef.current[sim.apid] && sim.caseId === pendingDispatchRef.current[sim.apid]) {
        delete pendingDispatchRef.current[sim.apid];
      }
      const planCaseId = sim.caseId;
      if (planCaseId && sim.phase === "on_scene") {
        const templateKey = mciPlanRef.current[planCaseId];
        if (templateKey && !reported[planCaseId] && !autoSendingRef.current.has(planCaseId)) {
          autoSendingRef.current.add(planCaseId);
          void handleReportFor(sim.apid, planCaseId, templateKey).finally(() => {
            autoSendingRef.current.delete(planCaseId);
          });
        }
      }
      // 재분배: 대기 사상자가 남아 있으면 복귀한 구급대를 바로 다시 보낸다
      if (
        mciOn &&
        mciQueueRef.current.length > 0 &&
        ["idle", "returning"].includes(sim.phase) &&
        !sim.caseId &&
        !pendingDispatchRef.current[sim.apid]
      ) {
        mciDispatchTo(sim.apid);
      }
    }
    if (mciOn && mciQueueRef.current.length === 0) setMciRemaining(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.ambulanceSim, reported, mciOn]);

  function bulkRespond(action: "hospital_approve" | "hospital_reject") {
    if (!myCase) return;
    const pending = myCase.hospitals.filter((h) => h.status === "pending");
    pending.forEach((hospital) =>
      sendAction({ caseId: myCase.caseId, action, hospital_id: hospital.hospitalId, actor: "hospital", timestamp: now() }),
    );
    note(`미응답 ${pending.length}곳 일괄 ${action === "hospital_approve" ? "승인" : "불가"}`);
  }

  // [시연 초기화] — hub에 sim_reset을 보내고 콘솔 로컬 상태(대기열·계획·사건 기억)도 비운다
  function handleSimReset() {
    if (!window.confirm("모든 사건을 종료하고 전 구급대를 기지로 되돌릴까요? (시연 초기화)")) return;
    Object.values(timersRef.current).forEach(clearInterval);
    timersRef.current = {};
    mciQueueRef.current = [];
    mciPlanRef.current = {};
    pendingDispatchRef.current = {};
    setPlaying({});
    setMciOn(false);
    setMciRemaining(0);
    setLocalCaseIds({});
    setReported({});
    setManualArrival(false);
    if (sendSimCommand("sim_reset", "*", "")) note("🔄 시연 초기화 — 모든 사건 종료, 전 구급대 기지 복귀");
  }

  function stopScenario(targetCaseId: string) {
    const timer = timersRef.current[targetCaseId];
    if (timer) clearInterval(timer);
    delete timersRef.current[targetCaseId];
    setPlaying((prev) => ({ ...prev, [targetCaseId]: null }));
  }

  function playScenario(key: string) {
    const scenario = SCENARIOS.find((s) => s.key === key);
    if (!scenario || !caseId || !apid) return;
    stopScenario(caseId);
    setPlaying((prev) => ({ ...prev, [caseId]: key }));
    let stepIndex = 0;
    const send = () => {
      const vitals = scenario.steps[stepIndex];
      if (!vitals) {
        stopScenario(caseId);
        return;
      }
      stepIndex += 1;
      const observation: VitalObservationIn = { ...vitals, measuredAt: new Date().toISOString(), source: "demo" };
      sendTransportVitals(caseId, apid, observation, { demo: true, scenario: key });
    };
    send();
    timersRef.current[caseId] = setInterval(send, STEP_INTERVAL_MS);
  }

  const assessments = caseId ? state.transportAssessments[caseId] ?? [] : [];
  const latest = assessments[assessments.length - 1] ?? null;
  const playingKey = caseId ? playing[caseId] ?? null : null;

  return (
    <div className={css({ display: "flex", flexDirection: "column", minHeight: "100vh", backgroundColor: "bg", padding: "5", gap: "3.5", alignItems: "center" })}>
      <header className={css({ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "3", backgroundColor: "surface", borderWidth: "1px", borderColor: "line", borderRadius: "panel", paddingX: "4.5", paddingY: "3", width: "100%", maxWidth: "860px" })}>
        <div className={css({ display: "flex", alignItems: "center", gap: "3" })}>
          <Link href="/" className={css({ fontSize: "md", fontWeight: "bold", color: "ink" })}>
            골든<span className={css({ color: "navy" })}>링크</span>
          </Link>
          <span className={css({ fontSize: "xs", color: "ink", paddingLeft: "3", borderLeftWidth: "1px", borderColor: "line" })}>
            시연 시나리오 콘솔
          </span>
          <span className={css({ fontSize: "xs", fontWeight: "bold", color: "severity.medium", backgroundColor: "severity.medium.subtle", paddingX: "2", paddingY: "0.5", borderRadius: "chip" })}>
            가상 시나리오
          </span>
        </div>
        <div className={css({ display: "flex", alignItems: "center", gap: "2.5", fontSize: "xs", flexWrap: "wrap" })}>
          {simOn && sim && phase !== "idle" && (
            <button
              type="button"
              className={miniStyle}
              title="구급차를 그 자리에 멈춥니다 — 사건은 그대로 남습니다(지우려면 시연 초기화)"
              onClick={() => sendSimCommand(sim.paused ? "sim_resume" : "sim_pause", apid!, sim.caseId ?? "") && note(sim.paused ? "재개" : "일시정지 — 사건은 유지됩니다")}
            >
              {sim.paused ? "▶ 재개" : "⏸ 일시정지"}
            </button>
          )}
          {simOn && phase === "on_scene" && sim?.caseId && (
            <button type="button" className={miniStyle} onClick={() => sendSimCommand("scene_end", apid!, sim.caseId!) && note("현장 종료 — 상황 취소, 복귀")}>
              ⏏ 상황 취소
            </button>
          )}
          {/* 시연 초기화(2026-10-04) — 일시정지와 달리 **모든 것을 지우는 리셋**: 사건 전부 종료
              (모든 대시보드에서 사라짐) + 전 구급대 기지 복귀 + 이송 중 병상 차감 해제 */}
          {simOn && (
            <button type="button" className={miniStyle} onClick={handleSimReset}>
              🔄 시연 초기화
            </button>
          )}
          <Link href="/map" className={css({ color: "navy", fontWeight: "semibold" })}>관제 지도 →</Link>
          <span className={css({ color: CONNECTION_LABEL[connectionMode].color })}>{CONNECTION_LABEL[connectionMode].text}</span>
        </div>
      </header>

      {/* 단계 표시줄 — 지금 어느 화면인지 */}
      <nav className={css({ display: "flex", gap: "2", alignItems: "center", flexWrap: "wrap", justifyContent: "center" })}>
        {STEP_TITLES.map((title, index) => {
          const n = index + 1;
          const current = n === step;
          const passed = n < step;
          return (
            <span key={title} className={css({ display: "inline-flex", alignItems: "center", gap: "1.5", fontSize: "xs", fontWeight: current ? "bold" : "medium", color: current ? "navy" : passed ? "mint" : "ink3" })}>
              <span
                className={css({
                  display: "inline-flex", alignItems: "center", justifyContent: "center",
                  width: "5", height: "5", borderRadius: "full", fontSize: "2xs", fontWeight: "bold",
                  color: current || passed ? "white" : "ink3",
                  backgroundColor: current ? "navy" : passed ? "mint" : "surfaceSub",
                })}
              >
                {passed ? "✓" : n}
              </span>
              {title}
              {n < STEP_TITLES.length && <span className={css({ color: "line" })}>—</span>}
            </span>
          );
        })}
      </nav>

      {mciOn && (
        <p className={css({ display: "flex", alignItems: "center", gap: "2", justifyContent: "center", fontSize: "xs", fontWeight: "semibold", color: "coral", textAlign: "center" })}>
          🔥 대량사고 진행 중 — 대기 사상자 {mciRemaining}명(복귀하는 구급대가 자동 재출동).
          <button
            type="button"
            className={miniStyle}
            onClick={() => {
              mciQueueRef.current = [];
              setMciRemaining(0);
              setMciOn(false);
              note("대량사고 종료 — 대기열을 비웠습니다(진행 중 이송은 그대로 끝까지)");
            }}
          >
            대량사고 종료
          </button>
        </p>
      )}
      {feedback && (
        <p className={css({ fontSize: "xs", color: "ink", backgroundColor: "mintSoft", paddingX: "3.5", paddingY: "2", borderRadius: "field", width: "100%", maxWidth: "860px" })}>{feedback}</p>
      )}

      <main className={cx(css({ display: "flex", flexDirection: "column", gap: "3", width: "100%", maxWidth: "860px", flex: "1", minHeight: "0", overflowY: "auto", paddingBottom: "4" }), thinScrollbarStyle)}>
        {/* ── 화면: 구급차 없음 ── */}
        {screen === "none" && (
          <ScreenCard title="구급차가 없습니다">
            <p className={hintStyle}>run-demo 스킬의 seed 스크립트로 레지스트리(구급차·병원)를 먼저 주입하세요.</p>
          </ScreenCard>
        )}

        {/* ── ① 환자 발생 ── */}
        {screen === "occur" && (
          <ScreenCard title="① 신고 접수 — 발생 지점과 신고 증상(1차)을 입력하세요">
            <div className={css({ display: "grid", gridTemplateColumns: { base: "1fr 1fr", md: "repeat(5, 1fr)" }, gap: "2" })}>
              {PRESET_LOCATIONS.map((preset) => (
                <button key={preset.label} type="button" className={spot?.label === preset.label ? placeSelectedStyle : placeStyle} onClick={() => setSpot(preset)}>
                  📍 {preset.label}
                </button>
              ))}
            </div>
            <div className={css({ display: "flex", gap: "1.5", flexWrap: "wrap", alignItems: "center" })}>
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                placeholder="주소·장소 검색 (카카오 키 필요)"
                className={css({ fontSize: "xs", borderWidth: "1px", borderColor: "line", borderRadius: "field", paddingX: "2.5", paddingY: "1.5", backgroundColor: "surface", color: "ink", width: "260px" })}
              />
              <button type="button" className={miniStyle} onClick={handleSearch}>검색</button>
              {searchError && <span className={css({ fontSize: "2xs", color: "ink3" })}>{searchError}</span>}
            </div>
            {searchResults.length > 0 && (
              <div className={css({ display: "flex", gap: "1.5", flexWrap: "wrap" })}>
                {searchResults.map((result) => (
                  <button key={`${result.lat}-${result.lng}`} type="button" className={spot?.label === result.name ? chipSelectedStyle : chipStyle} onClick={() => setSpot({ label: result.name, lat: result.lat, lng: result.lng })}>
                    {result.name}{result.etaMin != null ? ` · ${result.etaMin}분` : ""}
                  </button>
                ))}
              </div>
            )}
            {/* 신고 증상(1차) — 실무에선 상황실이 신고 전화에서 이미 안다. 중증 의심이면 출동과
                동시에 인근 병원 예비 고지에 실려 나가고, 경증 신고는 예비 고지를 생략한다. */}
            <div className={css({ display: "flex", flexDirection: "column", gap: "1.5" })}>
              <span className={css({ fontSize: "xs", fontWeight: "bold", color: "ink2" })}>
                신고 증상 (1차 — 신고 전화에서 파악한 내용)
              </span>
              <div className={css({ display: "grid", gridTemplateColumns: { base: "1fr", md: "repeat(3, 1fr)" }, gap: "2" })}>
                {PATIENT_TEMPLATES.map((template) => (
                  <button
                    key={template.key}
                    type="button"
                    className={cx(templateCardStyle, reportedKey === template.key ? css({ borderColor: "navy", borderWidth: "2px", backgroundColor: "navySoft" }) : undefined)}
                    onClick={() => setReportedKey(template.key)}
                  >
                    <span className={css({ display: "flex", alignItems: "center", gap: "1.5", fontSize: "sm", fontWeight: "bold", color: "ink" })}>
                      {template.label}
                      <span className={template.severity === "중증" ? severeChipStyle : mildChipStyle}>{template.severity}</span>
                    </span>
                    <span className={css({ fontSize: "xs", color: "ink2", textAlign: "left" })}>{template.detail}</span>
                  </button>
                ))}
              </div>
            </div>
            {spot && responder && (
              <p className={css({ fontSize: "sm", color: "ink" })}>
                출동대 자동 선정: <b>{responder.name}</b>{" "}
                <span className={css({ color: "ink3", fontSize: "xs" })}>
                  (기지에서 {responder.km.toFixed(1)}km — 발생 지점에서 가장 가까운 대기 구급대)
                </span>
              </p>
            )}
            {!simOn ? (
              <p className={hintStyle}>출동 시뮬레이션이 꺼져 있어 지점 지정 없이 바로 신고 단계로 넘어갑니다.</p>
            ) : (
              <button type="button" className={bigButtonStyle} disabled={!reportedKey} onClick={handleOccur}>
                🚨 신고 접수 — {spot?.label} · {responder?.name ?? "구급대"} 자동 출동
                {!reportedKey ? " (신고 증상을 먼저 선택)" : ""}
              </button>
            )}
            {/* 대량사고(2026-10-04, 자원 분배판) — 사상자 구성을 입력하면 중증 우선으로 가용
                구급대에 배정하고, 초과분은 대기열 → 복귀하는 대로 자동 재출동(왕복 수송). */}
            {simOn && (() => {
              const total = mciCounts.high + mciCounts.medium + mciCounts.low;
              const available = idleAmbulances().length;
              const firstWave = Math.min(available, total);
              return (
                <div className={css({ display: "flex", flexDirection: "column", gap: "2", borderTopWidth: "1px", borderColor: "line", paddingTop: "3" })}>
                  <span className={css({ fontSize: "xs", fontWeight: "bold", color: "coral" })}>
                    🔥 대량사고 (다수 사상자) — 사상자 구성 입력 → 이송 자원 자동 분배
                  </span>
                  <div className={css({ display: "flex", gap: "3", flexWrap: "wrap" })}>
                    <CasualtyStepper label="중증" value={mciCounts.high} color="coral"
                      onChange={(v) => setMciCounts((p) => ({ ...p, high: v }))} />
                    <CasualtyStepper label="중등증" value={mciCounts.medium} color="severity.medium"
                      onChange={(v) => setMciCounts((p) => ({ ...p, medium: v }))} />
                    <CasualtyStepper label="경증" value={mciCounts.low} color="mint"
                      onChange={(v) => setMciCounts((p) => ({ ...p, low: v }))} />
                  </div>
                  <p className={hintStyle}>
                    분배 계획: 사상자 {total}명 · 가용 구급대 {available}대 → 1차 {firstWave}명 이송(중증 우선),
                    대기 {Math.max(0, total - firstWave)}명은 구급대가 복귀하는 대로 자동 재출동.
                    병원 분배는 hub가 한다(중증→센터 가산 + 이송 중 부하 페널티로 한 병원 쏠림 방지).
                  </p>
                  <button
                    type="button"
                    className={css({
                      fontSize: "sm", fontWeight: "bold", color: "coral",
                      borderWidth: "1px", borderColor: "coral", borderRadius: "field",
                      paddingX: "4", paddingY: "2.5", backgroundColor: "coralSoft", cursor: "pointer",
                      _disabled: { opacity: 0.4, cursor: "not-allowed" },
                    })}
                    disabled={total === 0 || available === 0}
                    onClick={handleMciOccur}
                  >
                    🔥 대량사고 발생 — {spot?.label} · 사상자 {total}명 분배 시작
                  </button>
                </div>
              );
            })()}
          </ScreenCard>
        )}

        {/* ── 출동 중 (중간 화면) ── */}
        {screen === "enroute" && (
          <ScreenCard title="출동 중…">
            <Waiting text={`${PHASE_SHORT[phase]} — 현장에 도착하면 신고 접수 화면으로 넘어갑니다.`} />
            {caseId && state.preAlerts[caseId]?.hospitalCount != null && (
              <p className={hintStyle}>
                📨 예비 고지 — 현장 인근 병원 <b>{state.preAlerts[caseId].hospitalCount}곳</b>에
                {" "}&ldquo;수용 요청이 올 수 있음&rdquo; 선 경고를 보냈습니다(병원 화면에 모달로 뜹니다).
              </p>
            )}
          </ScreenCard>
        )}

        {/* ── ② 신고 접수 ── */}
        {screen === "report" && (
          <ScreenCard title="② 현장 확인 — 환자 상태를 확정하면 인근 병원에 동시 전달됩니다">
            {/* 입력 방식(2026-10-04) — 실제 음성(전화 앱) 또는 정해진 상황. 통화가 시작되면 음성으로 고정된다 */}
            <div role="tablist" className={css({ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "2" })}>
              {([
                ["voice", "🎙 음성으로 확인", "대원 휴대폰 전화 앱 · 실제 통화 음성 → AI 구조화"],
                ["template", "📋 정해진 상황 선택", "가상 환자 카드 · 음성 없이 바로 전달"],
              ] as const).map(([mode, label, sub]) => {
                const selected = (myCall ? "voice" : inputMode) === mode;
                return (
                  <button
                    key={mode}
                    type="button"
                    role="tab"
                    aria-selected={selected}
                    disabled={myCall != null || sending}
                    className={cx(modeTabStyle, selected ? modeTabSelectedStyle : undefined)}
                    onClick={() => setInputMode(mode)}
                  >
                    <span className={css({ fontSize: "sm", fontWeight: "bold" })}>{label}</span>
                    <span className={css({ fontSize: "2xs", color: "ink2" })}>{sub}</span>
                  </button>
                );
              })}
            </div>

            {myCall != null || inputMode === "voice" ? (
              <div className={css({ display: "flex", flexDirection: "column", gap: "2.5" })}>
                {myCall?.state === "calling" ? (
                  <p className={voiceStatusStyle}>
                    <span className={css({ display: "inline-block", width: "2.5", height: "2.5", borderRadius: "full", backgroundColor: "mint", animation: "pulse 1.2s ease-in-out infinite" })} />
                    <span>
                      📞 <b>{myCall.hospitalName ?? "병원"}</b>과 통화 중 — 통화를 끝내면 음성을 인식·구조화해 인근 병원에 동시 전달합니다.
                    </span>
                  </p>
                ) : (
                  <>
                    <p className={voiceStatusStyle}>
                      대원 휴대폰에서 전화 앱을 열고, 병원 목록에서 한 곳을 눌러 통화하세요. 통화 음성이 실제 STT 입력이 됩니다.
                    </p>
                    <p className={hintStyle}>
                      전화 앱 열기: 첫 페이지 코드 <b>P-AUTO</b>(자동 전환) 또는 <b>P-{apid}</b> · 음성 인식은 중앙 voice가
                      떠 있어야 합니다(voice/start-voice.sh를 인자 없이 실행).
                    </p>
                    <Waiting text="휴대폰 통화를 기다리는 중…" />
                  </>
                )}
              </div>
            ) : (
              <>
                {reportedKey && (
                  <p className={css({ fontSize: "xs", color: "ink", backgroundColor: "surfaceSub", paddingX: "3", paddingY: "2", borderRadius: "field" })}>
                    📞 신고 내용: <b>{PATIENT_TEMPLATES.find((t) => t.key === reportedKey)?.label}</b> — 현장
                    평가가 신고와 다르면 다른 카드를 선택하세요(신고 ≠ 현장일 수 있습니다).
                  </p>
                )}
                <div className={css({ display: "grid", gridTemplateColumns: { base: "1fr", md: "repeat(3, 1fr)" }, gap: "2.5" })}>
                  {PATIENT_TEMPLATES.map((template) => (
                    <button
                      key={template.key}
                      type="button"
                      disabled={sending}
                      className={cx(templateCardStyle, reportedKey === template.key ? css({ borderColor: "navy", borderWidth: "2px" }) : undefined)}
                      onClick={() => handleReport(template.key)}
                    >
                      <span className={css({ display: "flex", alignItems: "center", gap: "1.5", fontSize: "sm", fontWeight: "bold", color: "ink" })}>
                        {template.label}
                        <span className={template.severity === "중증" ? severeChipStyle : mildChipStyle}>{template.severity}</span>
                      </span>
                      <span className={css({ fontSize: "xs", color: "ink2", textAlign: "left" })}>{template.detail}</span>
                    </button>
                  ))}
                </div>
                {sending && <Waiting text="환자 정보 전송 중…" />}
              </>
            )}
          </ScreenCard>
        )}

        {/* ── 매칭 중 (중간 화면) ── */}
        {screen === "matching" && (
          <ScreenCard title="병원 매칭 중…">
            <SourceBadge source={caseSource} label={caseId ? templateCases[caseId] : undefined} />
            <Waiting
              text={
                caseSource === "voice"
                  ? "통화 음성을 인식(STT)·구조화(MF_BERT)한 뒤 존(Zone) 안 후보 병원에 동시에 요청을 보냅니다."
                  : "존(Zone) 안 후보 병원을 적합도로 정렬해 동시에 요청을 보내고 있습니다."
              }
            />
          </ScreenCard>
        )}

        {/* ── ③ 병원 응답 ── */}
        {screen === "respond" && myCase && (
          <ScreenCard title="③ 병원 응답 — 대신 누르거나, 실제 병원 탭에서 눌러도 됩니다">
            <SourceBadge source={caseSource} label={caseId ? templateCases[caseId] : undefined} />
            <ZoneCountdown
              expandAt={myCase.zoneExpandAt ?? null}
              zone={Math.max(1, ...myCase.zoneActive)}
              onSkip={() => sendZoneExpand(myCase.caseId) && note("건너뛰기 — 요청 범위를 지금 한 단계 넓힙니다")}
            />
            {(() => {
              const pendingCount = myCase.hospitals.filter((h) => h.status === "pending").length;
              return (
                <div className={css({ display: "flex", gap: "2", flexWrap: "wrap" })}>
                  <button type="button" className={bulkButtonStyle} disabled={pendingCount === 0} onClick={() => bulkRespond("hospital_approve")}>
                    ✓ 미응답 {pendingCount}곳 전부 승인
                  </button>
                  <button type="button" className={bulkRejectStyle} disabled={pendingCount === 0} onClick={() => bulkRespond("hospital_reject")}>
                    ✕ 미응답 {pendingCount}곳 전부 불가 (존 확장 연출)
                  </button>
                </div>
              );
            })()}
            <ul className={css({ display: "flex", flexDirection: "column", gap: "1" })}>
              {myCase.hospitals.map((hospital) => (
                <li key={hospital.hospitalId} className={css({ display: "flex", alignItems: "center", gap: "2", fontSize: "xs", color: "ink", paddingY: "0.5" })}>
                  <span className={css({ flex: "1", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" })}>
                    {hospital.name}{" "}
                    <b style={{ color: statusColor(hospital.status) }}>
                      {STATUS_ICON[hospital.status]} {STATUS_SHORT[hospital.status]}
                    </b>
                  </span>
                  <button type="button" className={miniStyle} disabled={hospital.status !== "pending"} onClick={() => sendAction({ caseId: myCase.caseId, action: "hospital_approve", hospital_id: hospital.hospitalId, actor: "hospital", timestamp: now() })}>승인</button>
                  <button type="button" className={miniStyle} disabled={hospital.status !== "pending"} onClick={() => sendAction({ caseId: myCase.caseId, action: "hospital_reject", hospital_id: hospital.hospitalId, actor: "hospital", timestamp: now() })}>불가</button>
                  <button type="button" className={confirmMiniStyle} disabled={hospital.status !== "approved"} onClick={() => sendAction({ caseId: myCase.caseId, action: "final_approval", hospital_id: hospital.hospitalId, actor: "paramedic", timestamp: now() })}>이송 확정</button>
                </li>
              ))}
            </ul>
            <p className={hintStyle}>승인 병원 중 한 곳에 [이송 확정]을 누르면 이송이 시작됩니다.</p>
          </ScreenCard>
        )}

        {/* ── ④ 이송 중 상황 부여 ── */}
        {screen === "transport" && (
          <ScreenCard title="④ 이송 중 — 상황을 부여하세요 (판정은 hub 규칙 엔진)">
            <div className={css({ display: "grid", gridTemplateColumns: { base: "1fr", md: "repeat(2, 1fr)" }, gap: "2" })}>
              {SCENARIOS.map((scenario) => (
                <button
                  key={scenario.key}
                  type="button"
                  className={scenarioButtonStyle}
                  disabled={playingKey !== null && playingKey !== scenario.key}
                  onClick={() => (playingKey === scenario.key ? stopScenario(caseId!) : playScenario(scenario.key))}
                >
                  {playingKey === scenario.key ? "⏹ " : "▶ "}
                  {scenario.label}
                  <span className={css({ display: "block", fontWeight: "normal", color: "ink2" })}>{scenario.expects}</span>
                </button>
              ))}
            </div>
            {latest && (
              <p className={css({ fontSize: "sm", color: "ink" })}>
                최근 판정: <b>{TIER_LABEL[latest.tier]}</b> · NEWS2 {latest.news2}
                {latest.si != null ? ` · 쇼크지수 ${latest.si}` : ""}
                {latest.reasons[0] ? <span className={css({ fontSize: "xs", color: "ink3" })}> — {latest.reasons[0]}</span> : null}
              </p>
            )}
            {simOn ? (
              <div className={css({ display: "flex", alignItems: "center", gap: "3", flexWrap: "wrap" })}>
                <Waiting text={`${PHASE_SHORT[phase]} — 병원까지 30초, 도착하면 도착 결과 화면으로 넘어갑니다.`} />
                {/* 빨리감기(2026-10-04) — 이송 30초 동안 상황을 다 골랐으면 3초 안에 병원 도착 */}
                {phase === "transporting" && apid && caseId && (
                  <button
                    type="button"
                    className={miniStyle}
                    onClick={() => sendSimCommand("sim_fast_forward", apid, caseId) && note("빨리감기 — 3초 안에 병원에 도착합니다")}
                  >
                    ⏩ 빨리감기 (3초 안에 도착)
                  </button>
                )}
              </div>
            ) : (
              <button type="button" className={bigButtonStyle} onClick={() => setManualArrival(true)}>
                🏥 병원 도착 — 도착 결과 입력으로
              </button>
            )}
          </ScreenCard>
        )}

        {/* ── ⑤ 도착 결과 ── */}
        {screen === "arrival" && confirmedId && caseId && (
          <ScreenCard title="⑤ 도착 결과 — 병원이 실제 수용 여부를 기록합니다">
            <div className={css({ display: "flex", gap: "2.5", flexWrap: "wrap" })}>
              <button type="button" className={bigButtonStyle} onClick={() => { sendAction({ caseId, action: "arrival_accepted", hospital_id: confirmedId, actor: "hospital", timestamp: now() }); note("환자 수용 완료 — 사건 종료, 구급차 복귀 → ①로 돌아갑니다"); }}>
                ✅ 환자 수용 완료
              </button>
              <button type="button" className={refuseButtonStyle} onClick={() => { sendAction({ caseId, action: "arrival_refused", hospital_id: confirmedId, actor: "hospital", timestamp: now() }); setManualArrival(false); note("도착 후 수용 불가 — 재선택 대기(병원 응답 화면으로)"); }}>
                ✕ 도착 후 수용 불가 (재선택 시연)
              </button>
            </div>
            <p className={hintStyle}>수용 완료 시 사건이 닫히고 구급차가 복귀해 자동으로 ① 화면으로 돌아옵니다.</p>
          </ScreenCard>
        )}

        <p className={css({ fontSize: "2xs", color: "ink3", textAlign: "center" })}>
          운영자 전용 시연 연출 화면 — 모든 조작은 실제 hub 흐름을 그대로 쓰고, 가상 데이터에는 전부 가상 표시가
          남습니다. 통화 음성은 대원 휴대폰 전화 앱(P-코드) 담당. 화면은 hub 상태를 따라 자동 전환됩니다.
        </p>
      </main>
    </div>
  );
}

// 사상자 수 입력 스테퍼 — 대량사고 구성용(0~20)
function CasualtyStepper({ label, value, color, onChange }: {
  label: string; value: number; color: string; onChange: (value: number) => void;
}) {
  return (
    <span className={css({ display: "inline-flex", alignItems: "center", gap: "1.5" })}>
      <span className={css({ fontSize: "xs", fontWeight: "bold" })} style={{ color: `var(--colors-${color.replace(/\./g, "-")})` }}>
        {label}
      </span>
      <button type="button" className={miniStyle} onClick={() => onChange(Math.max(0, value - 1))}>−</button>
      <span className={css({ fontSize: "sm", fontWeight: "bold", color: "ink", minWidth: "4", textAlign: "center", fontVariantNumeric: "tabular-nums" })}>
        {value}
      </span>
      <button type="button" className={miniStyle} onClick={() => onChange(Math.min(20, value + 1))}>＋</button>
    </span>
  );
}

// 현장 확인 입력 출처 표시(2026-10-04) — 음성(전화 앱, AI 구조화)인지 정해진 상황(가상 환자)인지
function SourceBadge({ source, label }: { source: "voice" | "template" | null; label?: string }) {
  if (!source) return null;
  const voice = source === "voice";
  return (
    <p
      className={css({
        alignSelf: "flex-start", display: "inline-flex", alignItems: "center", gap: "1.5",
        fontSize: "xs", fontWeight: "semibold", paddingX: "2.5", paddingY: "1", borderRadius: "chip",
        color: voice ? "navy" : "severity.medium", backgroundColor: voice ? "navySoft" : "severity.medium.subtle",
      })}
    >
      {voice ? "🎙 현장 확인: 음성 (휴대폰 통화 · AI 구조화)" : `📋 현장 확인: 정해진 상황${label ? ` — ${label}` : ""} (가상 환자)`}
    </p>
  );
}

// 시간 기반 존 확장 카운트다운(2026-10-04) — 승인·확정 병원이 없으면 hub가 30초마다 요청 범위를 한 단계 넓힌다.
// [건너뛰기]는 기다리지 않고 바로 넓힌다. expandAt이 없으면(승인 병원 있음·더 넓힐 수 없음) 멈춤 안내만.
function ZoneCountdown({ expandAt, zone, onSkip }: { expandAt: string | null; zone: number; onSkip: () => void }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(timer);
  }, []);
  const left = expandAt ? Math.max(0, Math.ceil((Date.parse(expandAt) - now) / 1000)) : null;
  return (
    <div className={css({ display: "flex", alignItems: "center", gap: "2.5", flexWrap: "wrap", fontSize: "sm", color: "ink", backgroundColor: "surfaceSub", paddingX: "3.5", paddingY: "2.5", borderRadius: "field" })}>
      <span>
        요청 범위 <b>{zone > 1 ? `존 1~${zone}` : "존 1"}</b> ·{" "}
        {left == null ? (
          <span className={css({ color: "ink3" })}>자동 확장 멈춤(수용 승인 병원이 있거나 더 넓힐 곳이 없음)</span>
        ) : (
          <>
            응답 없으면 <b className={css({ color: "severity.medium", fontVariantNumeric: "tabular-nums" })}>{left}초</b> 뒤 다음 존으로 자동 확장
          </>
        )}
      </span>
      {left != null && (
        <button type="button" className={miniStyle} onClick={onSkip}>
          ⏭ 건너뛰기 (지금 확장)
        </button>
      )}
    </div>
  );
}

function ScreenCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    // flexShrink 0(2026-10-04): 스크롤 영역(main) 안의 세로 flex 자식이라 기본값(줄어듦)이면 내용이 길어져도
    // 카드(흰 배경)는 화면 높이에 맞춰 줄고 내용만 아래로 삐져나왔다 — 존 확장으로 병원이 늘어나는 ③에서 보임
    <section className={css({ display: "flex", flexDirection: "column", gap: "3", backgroundColor: "surface", borderWidth: "1px", borderColor: "line", borderRadius: "panel", padding: "5", minHeight: "320px", flexShrink: 0 })}>
      <h2 className={css({ fontSize: "md", fontWeight: "bold", color: "ink" })}>{title}</h2>
      {children}
    </section>
  );
}

function Waiting({ text }: { text: string }) {
  return (
    <p className={css({ fontSize: "sm", color: "ink2", display: "flex", alignItems: "center", gap: "2" })}>
      <span className={css({ display: "inline-block", width: "3", height: "3", borderRadius: "full", backgroundColor: "navy", animation: "pulse 1.2s ease-in-out infinite" })} />
      {text}
    </p>
  );
}

const hintStyle = css({ fontSize: "xs", color: "ink3" });
const modeTabStyle = css({
  display: "flex", flexDirection: "column", alignItems: "flex-start", gap: "0.5", textAlign: "left",
  paddingX: "3.5", paddingY: "2.5", borderRadius: "field", borderWidth: "1px", borderColor: "line",
  backgroundColor: "surface", color: "ink", cursor: "pointer",
  _disabled: { cursor: "default" },
});
const modeTabSelectedStyle = css({ borderColor: "navy", borderWidth: "2px", backgroundColor: "navySoft" });
const voiceStatusStyle = css({
  display: "flex", alignItems: "center", gap: "2", fontSize: "sm", color: "ink",
  backgroundColor: "surfaceSub", paddingX: "3.5", paddingY: "3", borderRadius: "field",
});
const chipStyle = css({
  fontSize: "xs", fontWeight: "semibold", color: "ink",
  borderWidth: "1px", borderColor: "line", borderRadius: "chip",
  paddingX: "2.5", paddingY: "1", backgroundColor: "surface", cursor: "pointer",
  _hover: { borderColor: "navy" },
});
const chipSelectedStyle = css({
  fontSize: "xs", fontWeight: "bold", color: "navy",
  borderWidth: "1px", borderColor: "navy", borderRadius: "chip",
  paddingX: "2.5", paddingY: "1", backgroundColor: "navySoft", cursor: "pointer",
});
const placeStyle = css({
  fontSize: "sm", fontWeight: "semibold", color: "ink",
  borderWidth: "1px", borderColor: "line", borderRadius: "field",
  paddingX: "3", paddingY: "3", backgroundColor: "bg", cursor: "pointer", textAlign: "center",
  _hover: { borderColor: "navy" },
});
const placeSelectedStyle = css({
  fontSize: "sm", fontWeight: "bold", color: "navy",
  borderWidth: "2px", borderColor: "navy", borderRadius: "field",
  paddingX: "3", paddingY: "3", backgroundColor: "navySoft", cursor: "pointer", textAlign: "center",
});
const miniStyle = css({
  fontSize: "2xs", fontWeight: "semibold", color: "ink",
  borderWidth: "1px", borderColor: "line", borderRadius: "chip",
  paddingX: "2", paddingY: "0.5", backgroundColor: "surface", cursor: "pointer",
  _hover: { borderColor: "navy" }, _disabled: { opacity: 0.4, cursor: "not-allowed" },
});
const confirmMiniStyle = css({
  fontSize: "2xs", fontWeight: "bold", color: "white",
  borderRadius: "chip", paddingX: "2.5", paddingY: "0.5", backgroundColor: "navy", cursor: "pointer",
  _disabled: { opacity: 0.35, cursor: "not-allowed" },
});
const bigButtonStyle = css({
  fontSize: "sm", fontWeight: "bold", color: "white",
  borderRadius: "field", paddingX: "5", paddingY: "3", backgroundColor: "navy", cursor: "pointer",
  _disabled: { opacity: 0.4, cursor: "not-allowed" },
});
const refuseButtonStyle = css({
  fontSize: "sm", fontWeight: "bold", color: "coral",
  borderWidth: "1px", borderColor: "coral", borderRadius: "field",
  paddingX: "5", paddingY: "3", backgroundColor: "coralSoft", cursor: "pointer",
});
const bulkButtonStyle = css({
  fontSize: "xs", fontWeight: "bold", color: "mint",
  borderWidth: "1px", borderColor: "mint", borderRadius: "field",
  paddingX: "3", paddingY: "2", backgroundColor: "mintSoft", cursor: "pointer",
  _disabled: { opacity: 0.4, cursor: "not-allowed" },
});
const bulkRejectStyle = css({
  fontSize: "xs", fontWeight: "bold", color: "coral",
  borderWidth: "1px", borderColor: "coral", borderRadius: "field",
  paddingX: "3", paddingY: "2", backgroundColor: "coralSoft", cursor: "pointer",
  _disabled: { opacity: 0.4, cursor: "not-allowed" },
});
const templateCardStyle = css({
  display: "flex", flexDirection: "column", gap: "1.5", alignItems: "flex-start",
  borderWidth: "1px", borderColor: "line", borderRadius: "field", padding: "4",
  backgroundColor: "bg", cursor: "pointer", textAlign: "left",
  _hover: { borderColor: "navy", backgroundColor: "navySoft" },
  _disabled: { opacity: 0.5, cursor: "wait" },
});
const scenarioButtonStyle = css({
  textAlign: "left", fontSize: "xs", fontWeight: "semibold", color: "ink",
  paddingX: "3", paddingY: "2", borderRadius: "field",
  borderWidth: "1px", borderColor: "line", backgroundColor: "bg", cursor: "pointer",
  _hover: { borderColor: "navy" }, _disabled: { opacity: 0.5, cursor: "not-allowed" },
});
const severeChipStyle = css({
  fontSize: "2xs", fontWeight: "bold", color: "coral", backgroundColor: "coralSoft",
  paddingX: "1.5", paddingY: "0.5", borderRadius: "chip",
});
const mildChipStyle = css({
  fontSize: "2xs", fontWeight: "bold", color: "mint", backgroundColor: "mintSoft",
  paddingX: "1.5", paddingY: "0.5", borderRadius: "chip",
});
