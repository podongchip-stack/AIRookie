"use client";

import { useEffect, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import Link from "next/link";
import {
  SCENARIOS,
  STEP_INTERVAL_MS,
  TIER_LABEL,
} from "@/components/ambulance/TransportMonitorPanel";
import { useDashboardSocket } from "@/hooks/use-dashboard-socket";
import { searchPlaces } from "@/lib/geocode";
import { PHASE_SHORT } from "@/lib/monitor";
import { REJECTION_REASON_GROUPS, rejectionReasonLabel, unavailableReasonLabel } from "@/lib/rejection";
import { usePauseToast } from "@/components/ui/PauseToast";
import type {
  AmbulanceSimState,
  GeocodeResult,
  HospitalStatus,
  MapHospital,
  MonitorCase,
  MonitorCaseHospital,
  RejectionReason,
  VitalObservationIn,
} from "@/types/dashboard";

// 시연 시나리오 콘솔 (2026-10-04, 3차 — 위저드형 / 2026-10-05 디자인 시안 적용). 한 화면에 다 깔지 않고
// **앱처럼 한 번에 한 단계만** 보여준다: 버튼을 누르면 다음 화면으로 넘어가고, 출동·매칭처럼 기다리는
// 구간은 중간 화면이 뜬다. 화면 전환은 라우팅이 아니라 hub 상태로 계산한다 — 상태가 곧 단계라서
// 운영자가 잘못된 순서로 누를 수 없고, 수용 완료 후엔 저절로 ①로 돌아온다(새 상황 준비 완료).
//
// - 통화 버튼 없음 — 통화는 대원 휴대폰 전화 앱(P-코드) 담당. ② [환자 상태 확정]을 누르면
//   내부적으로만 요약 전송(hub 흐름 불변).
// - ③에는 **일괄 처리**가 있다: 미응답 병원 전부 승인/전부 불가 (전부 불가는 거절 비율
//   존 확장을 눈앞에서 보여주는 연출로도 쓰인다).
// - 대량사고는 시안의 5단계(출동 → 현장 확인 → 분배 → 이송 → 도착 결과)를 **사상자별 실제 사건**으로
//   보여준다. 병원 분배는 시안처럼 콘솔이 계산하지 않고 hub가 사건마다 정한다(중증→센터 가산 + 이송 중
//   부하 페널티) — 콘솔은 그 결과를 사상자 × 병원 현황으로 모아 보이고 일괄 조작만 한다.
// - 모든 조작은 기존 hub 메시지 그대로. 가짜 환자 전송만 Next 프록시(/api/demo/voice).
// - 운영자 전용·인증 없음(시연 범위). 가상 데이터에는 전부 가상 표시가 남는다.

const PATIENT_TEMPLATES = [
  {
    key: "cardiac", label: "흉통 · 경색 의심", severity: "중증" as const,
    detail: "62세 남성 · 흉통, 호흡 곤란 · 필요 진료과 순환기내과",
    symText: "흉통, 호흡 곤란",
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
    symText: "흉부·복부 충격, 의식 혼미",
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
    symText: "지속되는 복통, 구토",
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
    symText: "발목 통증·부종",
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

type Template = (typeof PATIENT_TEMPLATES)[number];
type SevLabel = Template["severity"];
const templateOf = (key: string | null | undefined): Template | null =>
  PATIENT_TEMPLATES.find((t) => t.key === key) ?? null;

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

// ── 시안 색 (2026-10-05, 시연 시나리오 콘솔 시안) ──
const C = {
  bg: "#f3f7fa", line: "#dbe5ee", lineSoft: "#e6edf4", ink: "#16202b", ink2: "#4a5a6b", ink3: "#5d6b7a",
  muted: "#7a8896", faint: "#98a4b1", blue: "#1d5fa8", blueSoft: "#e8f1fb", blueDept: "#e1edf9", blueOff: "#b3c6de",
  green: "#0f9d6e", greenInk: "#0b7a56", greenSoft: "#e4f5ec", greenRow: "#f0faf4", greenLine: "#b9e3cc",
  red: "#d93025", redInk: "#c5221f", redSoft: "#fdeceb", redLine: "#f0c9c6",
  amberSoft: "#fdf0d5", amberInk: "#9a5b00", orangeSoft: "#fdecd3", orangeInk: "#a85a00", control: "#cfdbe8",
  pin: "#e0457b",
} as const;

const SEV_COLORS: Record<SevLabel, { bg: string; fg: string }> = {
  중증: { bg: C.redSoft, fg: C.redInk },
  중등증: { bg: C.amberSoft, fg: C.amberInk },
  경증: { bg: C.greenSoft, fg: C.greenInk },
};

const STATUS_CHIP: Record<HospitalStatus, { label: string; bg: string; fg: string }> = {
  pending: { label: "판단 대기", bg: C.amberSoft, fg: C.amberInk },
  approved: { label: "수용 승인", bg: C.greenSoft, fg: C.greenInk },
  rejected: { label: "수용 불가", bg: C.redSoft, fg: C.redInk },
  confirmed: { label: "이송 확정", bg: C.blueSoft, fg: C.blue },
};

const LEVEL_SHORT: Record<string, string> = {
  권역응급의료센터: "권역센터",
  지역응급의료센터: "지역센터",
  지역응급의료기관: "지역기관",
};

// 대량사고 사상자 한 명 = 실제 사건 하나(출동 때 만든 caseId)
type MciCasualty = { no: number; caseId: string; apid: string; templateKey: string };

export default function ControlPage() {
  const { state, connectionMode, sendAction, sendCallSignal, sendSimCommand, sendTransportVitals, sendZoneExpand } =
    useDashboardSocket({ role: "monitor", id: "control" });
  const simOn = state.identity.simDispatch === true;
  const ambulances = state.mapOverview?.ambulances ?? [];
  const hospitalInfo = new Map<string, MapHospital>((state.mapOverview?.hospitals ?? []).map((h) => [h.hospitalId, h]));
  const [selectedApid, setSelectedApid] = useState<string | null>(null);
  const apid = selectedApid ?? ambulances[0]?.apid ?? null;
  const sim = apid ? state.ambulanceSim[apid] ?? null : null;
  const phase = sim?.phase ?? "idle";
  const ambulanceName = (target: string | null | undefined) =>
    ambulances.find((a) => a.apid === target)?.name ?? target ?? "구급대";

  const [localCaseIds, setLocalCaseIds] = useState<Record<string, string>>({});
  const caseId = (simOn ? sim?.caseId : null) ?? (apid ? localCaseIds[apid] : null) ?? null;
  const myCase: MonitorCase | null = caseId ? state.monitorCases[caseId] ?? null : null;
  const confirmedHospital = myCase?.hospitals.find((h) => h.status === "confirmed") ?? null;
  const confirmedId = confirmedHospital?.hospitalId ?? null;

  // 발생 지점은 항상 명시한다(기본 첫 프리셋) — 출동 구급대는 운영자가 고르지 않고
  // 지점에서 가장 가까운 대기 구급대가 자동 결정되므로, 지점 없는 '무작위'는 뺐다(2026-10-04).
  const [spot, setSpot] = useState<Spot>(PRESET_LOCATIONS[0]);
  // 신고 접수 때 고른 1차 증상(2026-10-04) — 실무에선 상황실이 신고 전화에서 증상 개요를
  // 먼저 안다. 출동과 함께 예비 고지에 실리고, ②(현장 확인)에서 기본 선택으로 이어진다.
  const [reportedKey, setReportedKey] = useState<string | null>(null);
  // ② 현장 확인 카드 선택(2026-10-05 시안) — 예전엔 카드를 누르는 즉시 전송했지만, 시안대로 고른 뒤
  // [환자 상태 확정]으로 보낸다. 고르지 않았으면 신고 증상이 기본값.
  const [verifyKey, setVerifyKey] = useState<string | null>(null);
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
  // 상황 요약 띠의 '최근 기록'(2026-10-05 시안) — 예전 초록 안내 상자(5초 뒤 사라짐)를 대신한다.
  // 콘솔 조작과 hub 사건 기록(case_history) 중 더 최근 것을 한 줄로 보인다.
  const [lastNote, setLastNote] = useState<{ t: string; text: string } | null>(null);
  // 출동 정보(상황 요약 띠용) — 출동한 뒤에도 어느 지점·어느 구급대였는지 남긴다
  const [dispatchInfo, setDispatchInfo] = useState<{ apid: string; spot: string; km: number; reportedKey: string } | null>(null);
  const [playing, setPlaying] = useState<Record<string, string | null>>({});
  const timersRef = useRef<Record<string, ReturnType<typeof setInterval>>>({});

  const now = () => new Date().toISOString();
  const note = (text: string) => setLastNote({ t: new Date().toISOString(), text });
  // 시연 일시정지 중엔 [재개]·[시연 초기화] 말고는 모든 조작을 막고, 누르면 위쪽에 안내를 잠깐 띄운다(2026-10-05)
  const locked = simOn && sim?.paused === true;
  const pauseToast = usePauseToast(state.actionRefused);
  const g = (fn: () => void) => pauseToast.guard(locked, fn);
  // 불가 사유 선택 모달(2026-10-05) — 병원 대시보드와 같은 4축 사유. 이송 중 수용 철회·도착 후 수용 불가도 같은 모달
  type RejectAction = "hospital_reject" | "transport_withdraw" | "arrival_refused";
  const [rejectTarget, setRejectTarget] = useState<{ caseId: string; hospitalId: string; name: string; action: RejectAction } | null>(null);
  function sendReject(reason: RejectionReason) {
    if (!rejectTarget) return;
    const { caseId: targetCase, hospitalId, name, action } = rejectTarget;
    setRejectTarget(null);
    if (locked) {
      pauseToast.notify();
      return;
    }
    sendAction({ caseId: targetCase, action, hospital_id: hospitalId, actor: "hospital", timestamp: now(), reason });
    const label = rejectionReasonLabel(reason) ?? "사유 없음";
    if (action === "arrival_refused") {
      setManualArrival(false);
      note(`도착 후 수용 불가(${label}) — 재선택 대기(병원 응답 화면으로)`);
    } else if (action === "transport_withdraw") {
      note(`${name} 이송 중 수용 철회(${label}) — 구급차는 다른 승인 병원으로 재선택`);
    } else {
      note(`${name} 수용 불가 · ${label}`);
    }
  }
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
    // 출동대는 수동 선택과 무관하게 **항상 자동**(최근접 대기 구급대)
    const chosenApid = responder?.apid ?? null;
    const template = templateOf(reportedKey);
    if (!template) return;
    if (!chosenApid) {
      note("출동 가능한 구급대가 없습니다");
      return;
    }
    setSelectedApid(chosenApid);
    const newCaseId = crypto.randomUUID();
    setLocalCaseIds((prev) => ({ ...prev, [chosenApid]: newCaseId }));
    setManualArrival(false);
    setVerifyKey(null);
    setInputMode("template");
    const target = spot ? { lat: spot.lat, lng: spot.lng, label: spot.label, mode: "map" as const } : null;
    const report = { symptom: template.label, severity: template.summary.severity_tag };
    if (sendSimCommand("dispatch", chosenApid, newCaseId, target, report)) {
      setDispatchInfo({ apid: chosenApid, spot: spot?.label ?? "무작위 지점", km: responder?.km ?? 0, reportedKey: template.key });
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
    const template = templateOf(templateKey);
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
  // 사상자별 사건(2026-10-05, 대량사고 현황표) — 화면에 그리려고 ref와 별도로 상태로도 든다
  const [mciCasualties, setMciCasualties] = useState<MciCasualty[]>([]);
  const [mciTotal, setMciTotal] = useState(0);
  const [mciSpotLabel, setMciSpotLabel] = useState("");
  // 사건별로 마지막에 본 이송 확정 병원 — 사건이 닫혀(case_closed) 목록에서 사라진 뒤에도 표에 남긴다
  const [caseHospital, setCaseHospital] = useState<Record<string, string>>({});

  const idleAmbulances = () =>
    ambulances.filter((a) => ["idle", "returning"].includes(state.ambulanceSim[a.apid]?.phase ?? "idle"));

  function mciDispatchTo(targetApid: string) {
    const templateKey = mciQueueRef.current.shift();
    const scene = mciSpotRef.current;
    if (!templateKey || !scene) return false;
    const template = templateOf(templateKey)!;
    const newCaseId = crypto.randomUUID();
    setLocalCaseIds((prev) => ({ ...prev, [targetApid]: newCaseId }));
    mciPlanRef.current[newCaseId] = templateKey;
    pendingDispatchRef.current[targetApid] = newCaseId;
    const index = mciDispatchedRef.current++;
    setMciCasualties((prev) => [...prev, { no: index + 1, caseId: newCaseId, apid: targetApid, templateKey }]);
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
    setMciSpotLabel(spot.label);
    mciDispatchedRef.current = 0;
    setMciCasualties([]);
    setMciTotal(total);
    setMciOn(true);
    const firstWave = Math.min(idle.length, total);
    idle.slice(0, firstWave).forEach((ambulance) => mciDispatchTo(ambulance.apid));
    note(
      `대량사고 접수 — ${spot.label} · 사상자 ${total}명 · 1차 출동 ${firstWave}대(중증 우선), ` +
        `대기 ${mciQueueRef.current.length}명(복귀하는 대로 자동 재출동)`,
    );
  }

  // 대량사고 자동 신고 + 자원 재분배: 계획된 사건의 구급차가 현장에 도착하면 그 자리에서
  // 신고를 보내고, 어떤 구급대든 대기(복귀)로 돌아오면 대기열의 다음 사상자에게 재출동한다.
  useEffect(() => {
    for (const unit of Object.values(state.ambulanceSim)) {
      // 보낸 출동이 반영됐으면 중복 방지 표시 해제
      if (pendingDispatchRef.current[unit.apid] && unit.caseId === pendingDispatchRef.current[unit.apid]) {
        delete pendingDispatchRef.current[unit.apid];
      }
      const planCaseId = unit.caseId;
      if (planCaseId && unit.phase === "on_scene") {
        const templateKey = mciPlanRef.current[planCaseId];
        if (templateKey && !reported[planCaseId] && !autoSendingRef.current.has(planCaseId)) {
          autoSendingRef.current.add(planCaseId);
          void handleReportFor(unit.apid, planCaseId, templateKey).finally(() => {
            autoSendingRef.current.delete(planCaseId);
          });
        }
      }
      // 재분배: 대기 사상자가 남아 있으면 복귀한 구급대를 바로 다시 보낸다
      if (
        mciOn &&
        mciQueueRef.current.length > 0 &&
        ["idle", "returning"].includes(unit.phase) &&
        !unit.caseId &&
        !pendingDispatchRef.current[unit.apid]
      ) {
        mciDispatchTo(unit.apid);
      }
    }
    if (mciOn && mciQueueRef.current.length === 0) setMciRemaining(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.ambulanceSim, reported, mciOn]);

  // 이송 확정 병원 기억(대량사고 현황표용) — 렌더 중 이전 값과 비교해 바뀐 것만 반영(React의 '이전 렌더 정보 저장' 방식)
  const confirmedNow: Record<string, string> = {};
  for (const monitorCase of Object.values(state.monitorCases)) {
    const hospital = monitorCase.hospitals.find((h) => h.status === "confirmed");
    if (hospital) confirmedNow[monitorCase.caseId] = hospital.name;
  }
  if (Object.entries(confirmedNow).some(([id, name]) => caseHospital[id] !== name)) {
    setCaseHospital({ ...caseHospital, ...confirmedNow });
  }

  function bulkRespond(target: MonitorCase, action: "hospital_approve" | "hospital_reject") {
    const pending = target.hospitals.filter((h) => h.status === "pending");
    pending.forEach((hospital) =>
      sendAction({ caseId: target.caseId, action, hospital_id: hospital.hospitalId, actor: "hospital", timestamp: now() }),
    );
    return pending.length;
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
    setMciCasualties([]);
    setMciTotal(0);
    setLocalCaseIds({});
    setReported({});
    setManualArrival(false);
    setDispatchInfo(null);
    setVerifyKey(null);
    if (sendSimCommand("sim_reset", "*", "")) note("시연 초기화 — 모든 사건 종료, 전 구급대 기지 복귀");
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

  // 이동 진행 바 — hub는 남은 시간(etaSec, 실제 도로 기준)과 배속만 보내므로, 구간마다 처음 본
  // 남은 시간을 기준으로 진행률을 계산한다(화면 초 = etaSec / 배속).
  const [tripStart, setTripStart] = useState<Record<string, number>>({});
  const tripKey = (unit: AmbulanceSimState) => `${unit.apid}:${unit.caseId}:${unit.phase}`;
  const tripLeft = (unit: AmbulanceSimState) => unit.etaSec! / Math.max(1, unit.speedup ?? 1);
  const startUpdates: Record<string, number> = {};
  for (const unit of Object.values(state.ambulanceSim)) {
    if (unit.etaSec == null || !["dispatching", "transporting"].includes(unit.phase)) continue;
    const left = tripLeft(unit);
    if (left > (tripStart[tripKey(unit)] ?? 0)) startUpdates[tripKey(unit)] = left;
  }
  if (Object.keys(startUpdates).length > 0) setTripStart({ ...tripStart, ...startUpdates });
  function tripProgress(unit: AmbulanceSimState | null): { left: number | null; p: number } {
    if (!unit || unit.etaSec == null || !["dispatching", "transporting"].includes(unit.phase)) return { left: null, p: 0 };
    const left = tripLeft(unit);
    const start = Math.max(tripStart[tripKey(unit)] ?? 0, left);
    return { left: Math.ceil(left), p: start > 0 ? Math.min(1, Math.max(0, 1 - left / start)) : 0 };
  }

  const simTrip = tripProgress(sim);
  const assessments = caseId ? state.transportAssessments[caseId] ?? [] : [];
  const latest = assessments[assessments.length - 1] ?? null;
  const playingKey = caseId ? playing[caseId] ?? null : null;

  // ── 대량사고 현황 계산 ──
  const casualtyView = mciCasualties.map((casualty) => {
    const template = templateOf(casualty.templateKey)!;
    const unit = state.ambulanceSim[casualty.apid] ?? null;
    const live = unit?.caseId === casualty.caseId;
    const monitorCase = state.monitorCases[casualty.caseId] ?? null;
    const confirmed = monitorCase?.hospitals.find((h) => h.status === "confirmed") ?? null;
    const unitPhase = live ? unit!.phase : null;
    // 0 출동 · 1 현장 확인 · 2 병원 응답 · 3 이송 · 4 도착 · 5 완료
    const stage = !live
      ? 5
      : unitPhase === "dispatching" ? 0
      : unitPhase === "on_scene" ? (monitorCase ? 2 : 1)
      : unitPhase === "transporting" ? (confirmed ? 3 : 2)
      : unitPhase === "at_hospital" ? 4
      : unitPhase === "rerouting" ? 2
      : 5;
    return { ...casualty, template, unit: live ? unit : null, monitorCase, confirmed, stage, hospitalName: confirmed?.name ?? caseHospital[casualty.caseId] ?? null };
  });
  const mciStep = (() => {
    if (!mciOn || casualtyView.length === 0) return 1;
    const active = casualtyView.filter((c) => c.stage < 5);
    if (active.length === 0) return mciRemaining > 0 ? 1 : 5;
    const lag = Math.min(...active.map((c) => c.stage));
    return [1, 2, 3, 4, 5][Math.min(4, lag)];
  })();
  const step = mciOn ? mciStep : SCREEN_STEP[screen];

  // ── 상황 요약 띠 ──
  const reportedTemplate = templateOf(dispatchInfo?.reportedKey ?? reportedKey);
  const caseTemplate = caseId && templateCases[caseId] ? PATIENT_TEMPLATES.find((t) => t.label === templateCases[caseId]) ?? null : null;
  const rank = SCREEN_STEP[screen];
  const zoneMax = myCase ? Math.max(1, ...myCase.zoneActive) : 1;
  type SummaryRow = { label: string; value: string; muted?: boolean; chip?: SevLabel | "대량" | null; sub?: string | null };
  const summaryRows: SummaryRow[] = mciOn
    ? [
        { label: "발생 지점", value: mciSpotLabel || "—" },
        { label: "신고 유형", value: `대량사고 · 사상자 ${mciTotal}명`, chip: "대량" },
        { label: "출동대", value: `구급대 ${casualtyView.filter((c) => c.stage < 5).length}대`, sub: mciRemaining > 0 ? `대기 ${mciRemaining}명` : null },
        {
          label: "현장 확인",
          value: `중증 ${mciCounts.high} · 중등증 ${mciCounts.medium} · 경증 ${mciCounts.low}`,
        },
        { label: "요청 범위", value: "사상자별 존", muted: true },
        {
          label: "이송 병원",
          value: (() => {
            const names = new Set(casualtyView.map((c) => c.hospitalName).filter(Boolean));
            return names.size > 0 ? `${names.size}곳에 분배` : "—";
          })(),
          muted: casualtyView.every((c) => !c.hospitalName),
        },
      ]
    : [
        { label: "발생 지점", value: rank >= 2 && dispatchInfo ? dispatchInfo.spot : spot?.label ?? "—" },
        {
          label: "신고 증상 (1차)",
          value: reportedTemplate?.label ?? "미선택",
          muted: !reportedTemplate,
          chip: reportedTemplate?.severity ?? null,
        },
        {
          label: "출동대",
          value: rank >= 2 && dispatchInfo ? ambulanceName(dispatchInfo.apid) : responder?.name ?? "—",
          sub: rank >= 2 && dispatchInfo ? `${dispatchInfo.km.toFixed(1)}km` : responder ? `${responder.km.toFixed(1)}km` : null,
        },
        {
          label: "현장 확인",
          value: rank >= 3
            ? caseSource === "voice" ? "음성 (AI 구조화)" : caseTemplate?.label ?? "확정"
            : rank === 2 ? "확인 중…" : "대기",
          muted: rank < 3,
          chip: rank >= 3 ? caseTemplate?.severity ?? null : null,
        },
        { label: "요청 범위", value: myCase ? (zoneMax > 1 ? `존 1~${zoneMax}` : "존 1") : "—", muted: !myCase },
        { label: "이송 병원", value: confirmedHospital?.name ?? "—", muted: !confirmedHospital },
      ];
  const counts = myCase && !mciOn
    ? {
        ok: myCase.hospitals.filter((h) => h.status === "approved" || h.status === "confirmed").length,
        no: myCase.hospitals.filter((h) => h.status === "rejected").length,
        wait: myCase.hospitals.filter((h) => h.status === "pending").length,
      }
    : null;
  const lastLog = (() => {
    const events = myCase?.events ?? (caseId ? state.caseMeta[caseId]?.events : undefined) ?? [];
    const lastEvent = events.length > 0 ? events[events.length - 1] : null;
    const candidates = [lastNote, lastEvent ? { t: lastEvent.t, text: lastEvent.text } : null].filter(
      (x): x is { t: string; text: string } => x != null,
    );
    if (candidates.length === 0) return null;
    return candidates.sort((a, b) => Date.parse(b.t) - Date.parse(a.t))[0];
  })();

  const verifyTemplate = templateOf(verifyKey ?? reportedKey ?? "cardiac")!;
  const voiceSelected = myCall != null || inputMode === "voice";

  return (
    // 화면 전체는 끌리지 않게 고정(2026-10-05 요청) — 상단바·단계·상황 요약은 그대로 두고, 넘치는 내용은 단계 카드 안에서만
    // 스크롤된다(③ 병원 응답은 병원 목록만). 페이지 스크롤·당겨서 새로고침·글자 끌기 선택을 막는다.
    <div className="ctl-root" style={{ boxSizing: "border-box", background: C.bg, color: C.ink, padding: "10px 16px 8px", display: "flex", justifyContent: "center", fontVariantNumeric: "tabular-nums" }}>
      <div style={{ width: "100%", maxWidth: 1500, height: "100%", minHeight: 0, display: "flex", flexDirection: "column", gap: 8 }}>
        <style>{CONSOLE_CSS}</style>
        {pauseToast.node}
        {rejectTarget && (
          <RejectReasonModal
            title={
              rejectTarget.action === "transport_withdraw"
                ? `${rejectTarget.name} — 이송 중 수용 철회 사유`
                : rejectTarget.action === "arrival_refused"
                  ? `${rejectTarget.name} — 도착 후 수용 불가 사유`
                  : `${rejectTarget.name} — 수용 불가 사유`
            }
            note={
              rejectTarget.action === "transport_withdraw"
                ? "철회한 병원은 이 사건에서 제외되고, 구급차는 그 자리에서 다른 승인 병원으로 재선택합니다."
                : "고른 사유는 병원 대시보드와 거절 로그에 그대로 남습니다."
            }
            onPick={sendReject}
            onClose={() => setRejectTarget(null)}
          />
        )}
        {/* 헤더 */}
        <header style={{ ...panel, padding: "8px 16px", display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10 }}>
            <Link href="/" style={{ fontSize: 18, fontWeight: 700, letterSpacing: "-0.5px", color: C.ink, textDecoration: "none" }}>
              골든<span style={{ color: C.blue }}>링크</span>
            </Link>
            <span style={{ width: 1, height: 16, background: C.line }} />
            <span style={{ fontSize: 13, fontWeight: 500 }}>시연 시나리오 콘솔</span>
            <span style={{ background: C.orangeSoft, color: C.orangeInk, fontSize: 13, fontWeight: 700, padding: "3px 10px", borderRadius: 999 }}>가상 시나리오</span>
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 6 }}>
            {simOn && sim && phase !== "idle" && !mciOn && (
              <button
                type="button"
                style={headerButton}
                title="구급차를 그 자리에 멈춥니다 — 사건은 그대로 남습니다(지우려면 시연 초기화)"
                onClick={() => sendSimCommand(sim.paused ? "sim_resume" : "sim_pause", apid!, sim.caseId ?? "") && note(sim.paused ? "재개" : "일시정지 — 사건은 유지됩니다")}
              >
                {sim.paused ? "재개" : "일시정지"}
              </button>
            )}
            {simOn && phase === "on_scene" && sim?.caseId && !mciOn && (
              <button type="button" style={headerButton} onClick={g(() => sendSimCommand("scene_end", apid!, sim.caseId!) && note("현장 종료 — 상황 취소, 복귀"))}>
                상황 취소
              </button>
            )}
            {/* 시연 초기화(2026-10-04) — 일시정지와 달리 **모든 것을 지우는 리셋**: 사건 전부 종료
                (모든 대시보드에서 사라짐) + 전 구급대 기지 복귀 + 이송 중 병상 차감 해제 */}
            {simOn && (
              <button type="button" style={headerButton} onClick={handleSimReset}>
                시연 초기화
              </button>
            )}
            <Link href="/map" style={{ fontSize: 14, fontWeight: 700, color: C.blue, textDecoration: "none", padding: "0 4px" }}>관제 지도 →</Link>
            <ConnectionDot mode={connectionMode} />
          </div>
        </header>

        {/* 스테퍼 — 지금 어느 화면인지(hub 상태로 정해져 누를 수 없다) */}
        <nav style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", alignItems: "center", gap: "2px 4px" }}>
          {STEP_TITLES.map((title, index) => {
            const n = index + 1;
            const cur = n === step;
            const done = n < step;
            return (
              <div key={title} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                {index > 0 && <div style={{ width: 22, height: 1, background: "#cdd9e5" }} />}
                <span style={{ display: "flex", alignItems: "center", gap: 7, padding: "3px 8px", minHeight: 28 }}>
                  <span
                    style={{
                      width: 20, height: 20, borderRadius: "50%", display: "inline-flex", alignItems: "center", justifyContent: "center",
                      fontSize: 11, fontWeight: 700,
                      background: done ? C.green : cur ? C.blue : "#e6edf4",
                      color: done || cur ? "#ffffff" : C.ink3,
                    }}
                  >
                    {done ? <Icon name="check" size={11} color="#ffffff" stroke={3.5} /> : n}
                  </span>
                  <span style={{ fontSize: 13, fontWeight: cur ? 700 : 500, color: cur ? C.blue : done ? "#0f8a62" : C.ink3 }}>{title}</span>
                </span>
              </div>
            );
          })}
        </nav>

        {/* 상황 요약 (가로 띠) */}
        <section style={{ ...panel, padding: "10px 18px", display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "8px 26px" }}>
            <span style={{ fontSize: 13, fontWeight: 700 }}>상황 요약</span>
            {summaryRows.map((row) => (
              <div key={row.label} style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
                <span style={{ fontSize: 11, fontWeight: 500, color: C.muted }}>{row.label}</span>
                <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "2px 8px" }}>
                  <span style={{ fontSize: 14, fontWeight: 700, color: row.muted ? C.faint : C.ink }}>{row.value}</span>
                  {row.chip && (row.chip === "대량" ? <SevChip sev="중증" text="대량" /> : <SevChip sev={row.chip} />)}
                  {row.sub && <span style={{ fontSize: 12, color: C.ink3 }}>{row.sub}</span>}
                </div>
              </div>
            ))}
            {counts && (
              <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
                <CountTile label="승인" n={counts.ok} bg={C.greenSoft} fg={C.greenInk} />
                <CountTile label="불가" n={counts.no} bg={C.redSoft} fg={C.redInk} />
                <CountTile label="대기" n={counts.wait} bg={C.amberSoft} fg={C.amberInk} />
              </div>
            )}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "4px 8px", borderTop: "1px solid #eef3f8", paddingTop: 7, fontSize: 12, color: C.ink2 }}>
            <span style={{ fontWeight: 700, color: C.muted }}>최근 기록</span>
            {lastLog ? (
              <>
                <span style={{ width: 8, height: 8, borderRadius: "50%", background: C.blue, display: "inline-block" }} />
                <span style={{ color: C.muted }}>{new Date(lastLog.t).toLocaleTimeString("ko-KR")}</span>
                <span style={{ color: C.ink }}>{lastLog.text}</span>
              </>
            ) : (
              <span style={{ color: C.faint }}>아직 접수된 사건이 없습니다.</span>
            )}
          </div>
        </section>

        {locked && !mciOn && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, background: C.orangeSoft, color: C.orangeInk, borderRadius: 10, padding: "8px 14px", fontSize: 13, fontWeight: 700 }}>
            시연 일시정지 중 — 조작이 잠겼습니다. 상단 [재개]를 누르면 이어 갑니다.
          </div>
        )}

        {/* 단계 본문 */}
        <main style={{ flex: "1 1 auto", minHeight: 0, display: "flex", flexDirection: "column", gap: 8 }}>
          {mciOn ? (
            <MciBoard
              total={mciTotal}
              remaining={mciRemaining}
              spotLabel={mciSpotLabel}
              casualties={casualtyView}
              ambulanceName={ambulanceName}
              tripProgress={tripProgress}
              onApproveAll={() => {
                let cases = 0;
                let hospitals = 0;
                for (const c of casualtyView.filter((x) => !x.unit?.paused)) {
                  if (c.stage === 2 && c.monitorCase && !c.confirmed) {
                    const n = bulkRespond(c.monitorCase, "hospital_approve");
                    if (n > 0) { cases += 1; hospitals += n; }
                  }
                }
                note(`대량사고 — 응답 대기 사건 ${cases}건의 미응답 병원 ${hospitals}곳 일괄 승인`);
              }}
              onConfirmAll={() => {
                let n = 0;
                for (const c of casualtyView.filter((x) => !x.unit?.paused)) {
                  if (c.stage !== 2 || !c.monitorCase || c.confirmed) continue;
                  const first = c.monitorCase.hospitals.find((h) => h.status === "approved");
                  if (!first) continue;
                  sendAction({ caseId: c.caseId, action: "final_approval", hospital_id: first.hospitalId, actor: "paramedic", timestamp: now() });
                  n += 1;
                }
                note(`대량사고 — 승인 병원 1순위로 ${n}건 이송 확정(병원 순위는 hub 규칙)`);
              }}
              onFastAll={() => {
                let n = 0;
                for (const c of casualtyView.filter((x) => !x.unit?.paused)) {
                  if (c.unit && ["dispatching", "transporting"].includes(c.unit.phase)) {
                    sendSimCommand("sim_fast_forward", c.apid, c.caseId);
                    n += 1;
                  }
                }
                note(`대량사고 — 이동 중인 구급대 ${n}대 빨리감기`);
              }}
              onAcceptAll={() => {
                let n = 0;
                for (const c of casualtyView.filter((x) => !x.unit?.paused)) {
                  if (c.stage === 4 && c.confirmed) {
                    sendAction({ caseId: c.caseId, action: "arrival_accepted", hospital_id: c.confirmed.hospitalId, actor: "hospital", timestamp: now() });
                    n += 1;
                  }
                }
                note(`대량사고 — 도착한 ${n}명 환자 수용 완료`);
              }}
              onCaseApprove={(c) => (c.unit?.paused ? pauseToast.notify() : c.monitorCase && bulkRespond(c.monitorCase, "hospital_approve"))}
              onCaseConfirm={(c) => {
                if (c.unit?.paused) return pauseToast.notify();
                const first = c.monitorCase?.hospitals.find((h) => h.status === "approved");
                if (first) sendAction({ caseId: c.caseId, action: "final_approval", hospital_id: first.hospitalId, actor: "paramedic", timestamp: now() });
              }}
              onCaseFast={(c) => (c.unit?.paused ? pauseToast.notify() : sendSimCommand("sim_fast_forward", c.apid, c.caseId))}
              onCaseArrival={(c, accepted) => {
                if (c.unit?.paused) return pauseToast.notify();
                if (!c.confirmed) return;
                sendAction({ caseId: c.caseId, action: accepted ? "arrival_accepted" : "arrival_refused", hospital_id: c.confirmed.hospitalId, actor: "hospital", timestamp: now() });
                note(`사상자 ${c.no} — ${accepted ? "환자 수용 완료" : "도착 후 수용 불가(재선택 대기)"}`);
              }}
              onEnd={() => {
                mciQueueRef.current = [];
                setMciRemaining(0);
                setMciOn(false);
                note("대량사고 종료 — 대기열을 비웠습니다(진행 중 이송은 그대로 끝까지)");
              }}
            />
          ) : (
            <>
              {/* ── 화면: 구급차 없음 ── */}
              {screen === "none" && (
                <ScreenCard title="구급차가 없습니다">
                  <p style={{ margin: 0, fontSize: 13, color: C.ink3 }}>run-demo 스킬의 seed 스크립트로 레지스트리(구급차·병원)를 먼저 주입하세요.</p>
                </ScreenCard>
              )}

              {/* ── ① 신고 접수 ── */}
              {screen === "occur" && (
                <ScreenCard title="① 신고 접수 — 발생 지점을 고르고, 단일 신고 또는 대량사고로 접수하세요">
                  <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "10px 14px" }}>
                    <div style={{ flex: "1 1 520px", display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 10 }}>
                      {PRESET_LOCATIONS.map((preset) => {
                        const sel = spot?.label === preset.label;
                        return (
                          <button
                            key={preset.label}
                            type="button"
                            onClick={() => setSpot(preset)}
                            style={{
                              display: "flex", alignItems: "center", justifyContent: "center", gap: 8, minHeight: 40, borderRadius: 12,
                              fontSize: 14, fontWeight: 700, cursor: "pointer", color: sel ? C.blue : C.ink,
                              background: sel ? C.blueSoft : C.bg, border: sel ? `2px solid ${C.blue}` : `1px solid ${C.line}`,
                            }}
                          >
                            <Icon name="pin" size={15} color={C.pin} />
                            <span>{preset.label}</span>
                          </button>
                        );
                      })}
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <input
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                        placeholder="주소·장소 검색 (카카오 키 필요)"
                        style={{ width: 250, boxSizing: "border-box", minHeight: 40, padding: "0 12px", border: `1px solid ${C.control}`, borderRadius: 10, fontSize: 13, color: C.ink, background: "#ffffff" }}
                      />
                      <button type="button" style={{ ...headerButton, minHeight: 36, padding: "0 12px" }} onClick={handleSearch}>검색</button>
                    </div>
                  </div>
                  {(searchError || searchResults.length > 0 || (spot && !PRESET_LOCATIONS.some((p) => p.label === spot.label))) && (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
                      {searchResults.map((result) => {
                        const sel = spot?.label === result.name;
                        return (
                          <button
                            key={`${result.lat}-${result.lng}`}
                            type="button"
                            onClick={() => setSpot({ label: result.name, lat: result.lat, lng: result.lng })}
                            style={{ minHeight: 30, padding: "0 12px", borderRadius: 999, fontSize: 12, fontWeight: 700, cursor: "pointer", color: sel ? C.blue : C.ink, background: sel ? C.blueSoft : "#ffffff", border: sel ? `2px solid ${C.blue}` : `1px solid ${C.line}` }}
                          >
                            {result.name}{result.etaMin != null ? ` · ${result.etaMin}분` : ""}
                          </button>
                        );
                      })}
                      {searchError && <span style={{ fontSize: 12, color: C.muted }}>{searchError}</span>}
                    </div>
                  )}

                  <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "stretch" }}>
                    {/* 단일 신고 — 신고 증상(1차)은 실무에선 상황실이 신고 전화에서 이미 안다. 중증 의심이면 출동과
                        동시에 인근 병원 예비 고지에 실려 나가고, 경증 신고는 예비 고지를 생략한다. */}
                    <div style={{ flex: "1.5 1 520px", minWidth: 0, boxSizing: "border-box", border: "1px solid #c9dcf0", background: "#fafcff", borderRadius: 12, padding: "14px 16px", display: "flex", flexDirection: "column", gap: 10 }}>
                      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "4px 10px" }}>
                        <span style={{ background: C.blue, color: "#ffffff", fontSize: 13, fontWeight: 700, padding: "3px 12px", borderRadius: 999 }}>단일 신고</span>
                        <span style={{ fontSize: 12, fontWeight: 700, color: C.ink2 }}>신고 증상 (1차 — 신고 전화에서 파악한 내용)</span>
                      </div>
                      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                        {PATIENT_TEMPLATES.map((template) => (
                          <SymptomRow key={template.key} template={template} selected={reportedKey === template.key} onPick={() => setReportedKey(template.key)} />
                        ))}
                      </div>
                      {spot && responder && (
                        <div style={{ fontSize: 13, color: C.ink2 }}>
                          <span style={{ color: C.ink, fontWeight: 500 }}>출동대 자동 선정:</span> <b style={{ color: C.ink }}>{responder.name}</b>{" "}
                          (기지에서 {responder.km.toFixed(1)}km — 발생 지점에서 가장 가까운 대기 구급대)
                        </div>
                      )}
                      {!simOn ? (
                        <p style={{ margin: 0, fontSize: 12, color: C.ink3 }}>출동 시뮬레이션이 꺼져 있어 지점 지정 없이 바로 신고 단계로 넘어갑니다.</p>
                      ) : (
                        <button
                          type="button"
                          disabled={!reportedKey}
                          onClick={handleOccur}
                          style={{
                            whiteSpace: "nowrap", minHeight: 44, border: "none", borderRadius: 12, color: "#ffffff", fontSize: 15, fontWeight: 700,
                            display: "flex", alignItems: "center", justifyContent: "center", gap: 8, padding: "0 16px",
                            cursor: reportedKey ? "pointer" : "not-allowed", background: reportedKey ? C.blue : "#a7bedb",
                          }}
                        >
                          <Icon name="siren" size={17} color="#ffffff" />
                          <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>
                            {reportedKey ? `신고 접수 — ${spot?.label} · 구급대 자동 출동` : `신고 접수 — ${spot?.label} (신고 증상을 먼저 선택)`}
                          </span>
                        </button>
                      )}
                    </div>

                    {/* 대량사고(2026-10-04, 자원 분배판) — 사상자 구성을 입력하면 중증 우선으로 가용
                        구급대에 배정하고, 초과분은 대기열 → 복귀하는 대로 자동 재출동(왕복 수송). */}
                    {simOn && (() => {
                      const total = mciCounts.high + mciCounts.medium + mciCounts.low;
                      const available = idleAmbulances().length;
                      const firstWave = Math.min(available, total);
                      const disabled = total === 0 || available === 0;
                      const rows: [keyof typeof mciCounts, SevLabel][] = [["high", "중증"], ["medium", "중등증"], ["low", "경증"]];
                      return (
                        <div style={{ flex: "1 1 380px", minWidth: 0, boxSizing: "border-box", border: `1px solid ${C.redLine}`, background: "#fffafa", borderRadius: 12, padding: "14px 16px", display: "flex", flexDirection: "column", gap: 10 }}>
                          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "4px 10px" }}>
                            <span style={{ display: "inline-flex", alignItems: "center", gap: 6, background: C.red, color: "#ffffff", fontSize: 13, fontWeight: 700, padding: "3px 12px", borderRadius: 999 }}>
                              <Icon name="flame" size={13} color="#ffffff" />대량사고
                            </span>
                            <span style={{ fontSize: 12, fontWeight: 700, color: C.redInk }}>다수 사상자 — 사상자 구성 입력 → 이송 자원 자동 분배</span>
                          </div>
                          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                            {rows.map(([key, label]) => (
                              <div key={key} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", background: "#ffffff", border: "1px solid #f0d9d7", borderRadius: 10, padding: "8px 14px" }}>
                                <span style={{ fontSize: 15, fontWeight: 700, color: SEV_COLORS[label].fg }}>{label}</span>
                                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                                  <button type="button" aria-label="감소" style={stepperButton} onClick={() => setMciCounts((p) => ({ ...p, [key]: Math.max(0, p[key] - 1) }))}>−</button>
                                  <span style={{ minWidth: 24, textAlign: "center", fontSize: 18, fontWeight: 700 }}>{mciCounts[key]}</span>
                                  <button type="button" aria-label="증가" style={stepperButton} onClick={() => setMciCounts((p) => ({ ...p, [key]: Math.min(20, p[key] + 1) }))}>+</button>
                                </div>
                              </div>
                            ))}
                          </div>
                          <div style={{ flex: "1 1 auto", fontSize: 12, lineHeight: 1.6, color: C.ink3 }}>
                            분배 계획: 사상자 {total}명 · 가용 구급대 {available}대 → 1차 {firstWave}명 이송(중증 우선), 대기 {Math.max(0, total - firstWave)}명은
                            구급대가 복귀하는 대로 자동 재출동. 병원 분배는 hub가 한다(중증→센터 가산 + 이송 중 부하 페널티로 한 병원 쏠림 방지).
                          </div>
                          <button
                            type="button"
                            disabled={disabled}
                            onClick={handleMciOccur}
                            style={{
                              whiteSpace: "nowrap", minHeight: 44, background: C.redSoft, border: `1px solid ${C.red}`, borderRadius: 12, color: C.red,
                              fontSize: 15, fontWeight: 700, cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.45 : 1,
                              display: "flex", alignItems: "center", justifyContent: "center", gap: 8, padding: "0 12px",
                            }}
                          >
                            <Icon name="flame" size={16} color={C.red} />대량사고 발생 — 사상자 {total}명 분배 시작
                          </button>
                        </div>
                      );
                    })()}
                  </div>
                </ScreenCard>
              )}

              {/* ── 출동 중 (중간 화면) ── */}
              {screen === "enroute" && (() => {
                const { left, p } = tripProgress(sim);
                const alert = caseId ? state.preAlerts[caseId] : undefined;
                return (
                  <ScreenCard title="출동 중…">
                    <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", gap: 14 }}>
                      <div style={{ fontSize: 15, color: C.ink2 }}>현장 출동 중 — 현장에 도착하면 현장 확인 화면으로 넘어갑니다.</div>
                      <ProgressTrack p={p} start={ambulanceName(apid)} end={dispatchInfo?.spot ?? "현장"} endIcon="pin" />
                      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "8px 12px" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 16, fontWeight: 700, color: C.blue }}>
                          <span style={{ width: 10, height: 10, borderRadius: "50%", background: C.blue, display: "inline-block" }} />
                          {left != null ? `예상 도착 ${left}초` : PHASE_SHORT[phase]}
                          {dispatchInfo ? ` · 거리 ${dispatchInfo.km.toFixed(1)}km` : ""}
                        </div>
                        {left != null && left > 3 && apid && caseId && (
                          <FastButton onClick={g(() => sendSimCommand("sim_fast_forward", apid, caseId) && note("빨리감기 — 3초 안에 현장에 도착합니다"))} />
                        )}
                      </div>
                      {alert?.hospitalCount != null && (
                        <div style={{ display: "flex", alignItems: "center", gap: 10, background: C.bg, borderRadius: 10, padding: "10px 14px", fontSize: 13, color: C.ink2 }}>
                          <Icon name="siren" size={16} color="#7ba0cc" />
                          <span>예비 고지 — 현장 인근 병원 <b>{alert.hospitalCount}곳</b>에 &ldquo;수용 요청이 올 수 있음&rdquo; 선 경고를 보냈습니다(병원 화면에 모달로 뜹니다).</span>
                        </div>
                      )}
                    </div>
                  </ScreenCard>
                );
              })()}

              {/* ── ② 현장 확인 ── */}
              {screen === "report" && (
                <ScreenCard title="② 현장 확인 — 환자 상태를 확정하면 인근 병원에 동시 전달됩니다">
                  {/* 입력 방식(2026-10-04) — 실제 음성(전화 앱) 또는 정해진 상황. 통화가 시작되면 음성으로 고정된다 */}
                  <div role="tablist" style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 10 }}>
                    {([
                      ["voice", "mic", "음성으로 확인", "대원 휴대폰 전화 앱 · 실제 통화 음성 → AI 구조화"],
                      ["template", "card", "정해진 상황 선택", "가상 환자 카드 · 음성 없이 바로 전달"],
                    ] as const).map(([mode, icon, label, sub]) => {
                      const selected = (myCall ? "voice" : inputMode) === mode;
                      return (
                        <button
                          key={mode}
                          type="button"
                          role="tab"
                          aria-selected={selected}
                          disabled={myCall != null || sending}
                          onClick={() => setInputMode(mode)}
                          style={{
                            textAlign: "left", display: "flex", flexDirection: "column", gap: 3, padding: "9px 14px", borderRadius: 12,
                            cursor: myCall != null ? "default" : "pointer", boxSizing: "border-box", color: C.ink,
                            background: selected ? C.blueSoft : "#ffffff", border: selected ? `2px solid ${C.blue}` : `1px solid ${C.line}`,
                          }}
                        >
                          <span style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 15, fontWeight: 700 }}>
                            <Icon name={icon} size={15} color={C.ink} />{label}
                          </span>
                          <span style={{ fontSize: 11, color: C.ink3 }}>{sub}</span>
                        </button>
                      );
                    })}
                  </div>

                  {voiceSelected ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                      {myCall?.state === "calling" ? (
                        <div style={{ ...softBox, display: "flex", alignItems: "center", gap: 10 }}>
                          <Pulse color={C.green} />
                          <span>
                            <b>{myCall.hospitalName ?? "병원"}</b>과 통화 중 — 통화를 끝내면 음성을 인식·구조화해 인근 병원에 동시 전달합니다.
                          </span>
                        </div>
                      ) : (
                        <>
                          <div style={softBox}>대원 휴대폰에서 전화 앱을 열고, 병원 목록에서 한 곳을 눌러 통화하세요. 통화 음성이 실제 STT 입력이 됩니다.</div>
                          <div style={{ fontSize: 12, lineHeight: 1.6, color: C.ink3 }}>
                            전화 앱 열기: 첫 페이지 코드 <b>P-AUTO</b>(자동 전환) 또는 <b>P-{apid}</b> · 음성 인식은 중앙 voice가 떠 있어야 합니다(voice/start-voice.sh를 인자 없이 실행).
                          </div>
                          <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 14, color: C.ink3 }}>
                            <Pulse color="#7ba0cc" />휴대폰 통화를 기다리는 중…
                          </div>
                          {/* 시연용 지름길 — 통화 없이 진행할 때. 음성처럼 꾸미지 않고 정해진 상황(신고 증상)으로 보내 출처가 정직하게 남는다 */}
                          <div>
                            <button
                              type="button"
                              disabled={sending}
                              onClick={g(() => handleReport(verifyTemplate.key))}
                              style={{ minHeight: 38, padding: "0 16px", background: "#ffffff", border: `1px dashed ${C.blue}`, borderRadius: 10, color: C.blue, fontSize: 13, fontWeight: 700, cursor: "pointer" }}
                            >
                              시연용 · 통화 없이 진행 ({verifyTemplate.label} — 정해진 상황으로 전달)
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                      {reportedTemplate && (
                        <div style={{ ...softBox, padding: "9px 14px", fontSize: 13, display: "flex", alignItems: "center", gap: 8 }}>
                          <Icon name="phone" size={15} color={C.pin} />
                          <span>신고 내용: <b>{reportedTemplate.label}</b> — 현장 평가가 신고와 다르면 다른 카드를 선택하세요(신고 ≠ 현장일 수 있습니다).</span>
                        </div>
                      )}
                      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                        {PATIENT_TEMPLATES.map((template) => (
                          <SymptomRow key={template.key} template={template} selected={verifyTemplate.key === template.key} disabled={sending} onPick={() => setVerifyKey(template.key)} />
                        ))}
                      </div>
                      <button
                        type="button"
                        disabled={sending}
                        onClick={g(() => handleReport(verifyTemplate.key))}
                        style={{ minHeight: 46, background: C.blue, border: "none", borderRadius: 10, color: "#ffffff", fontSize: 15, fontWeight: 700, cursor: sending ? "wait" : "pointer", opacity: sending ? 0.6 : 1 }}
                      >
                        {sending ? "환자 정보 전송 중…" : `환자 상태 확정 — ${verifyTemplate.label} · 인근 병원에 동시 전달`}
                      </button>
                    </div>
                  )}
                </ScreenCard>
              )}

              {/* ── 매칭 중 (중간 화면) ── */}
              {screen === "matching" && (
                <ScreenCard title="병원 매칭 중…">
                  <SourceBadge source={caseSource} label={caseId ? templateCases[caseId] : undefined} />
                  <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 15, color: C.ink2 }}>
                    <Pulse color={C.blue} />
                    {caseSource === "voice"
                      ? "통화 음성을 인식(STT)·구조화(MF_BERT)한 뒤 존(Zone) 안 후보 병원에 동시에 요청을 보냅니다."
                      : "존(Zone) 안 후보 병원을 적합도로 정렬해 동시에 요청을 보내고 있습니다."}
                  </div>
                </ScreenCard>
              )}

              {/* ── ③ 병원 응답 ── */}
              {screen === "respond" && myCase && (
                <ScreenCard title="③ 병원 응답 — 대신 누르거나, 실제 병원 탭에서 눌러도 됩니다" fixed>
                  <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "8px 10px" }}>
                    <SourceBadge source={caseSource} label={caseId ? templateCases[caseId] : undefined} need={caseTemplate?.summary.required_department} />
                    {(() => {
                      const pendingCount = myCase.hospitals.filter((h) => h.status === "pending").length;
                      return (
                        <>
                          <button type="button" disabled={pendingCount === 0} style={bulkButton("green", pendingCount === 0)}
                            onClick={g(() => note(`미응답 ${bulkRespond(myCase, "hospital_approve")}곳 일괄 승인`))}>
                            <Icon name="check" size={13} color={C.greenInk} stroke={3} />미응답 {pendingCount}곳 전부 승인
                          </button>
                          <button type="button" disabled={pendingCount === 0} style={bulkButton("red", pendingCount === 0)}
                            onClick={g(() => note(`미응답 ${bulkRespond(myCase, "hospital_reject")}곳 일괄 불가 (사유 없음)`))}>
                            <Icon name="x" size={13} color={C.red} stroke={3} />미응답 {pendingCount}곳 전부 불가 (존 확장 연출)
                          </button>
                        </>
                      );
                    })()}
                  </div>
                  <ZoneCountdown
                    expandAt={myCase.zoneExpandAt ?? null}
                    pausedLeft={myCase.zonePausedLeftSec ?? null}
                    zone={zoneMax}
                    onSkip={g(() => sendZoneExpand(myCase.caseId) && note("건너뛰기 — 요청 범위를 지금 한 단계 넓힙니다"))}
                  />
                  {/* 존이 넓혀져 병원이 늘어나도 이 목록 안에서만 스크롤된다 */}
                  <div className="ctl-scroll" style={{ flex: "1 1 auto", minHeight: 0, overflowY: "auto", alignContent: "start", display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(min(100%, 520px), 1fr))", gridAutoRows: "minmax(48px, auto)", gap: "8px 12px", paddingRight: 2 }}>
                    {myCase.hospitals.map((hospital) => (
                      <HospitalRow
                        key={hospital.hospitalId}
                        hospital={hospital}
                        info={hospitalInfo.get(hospital.hospitalId)}
                        onApprove={g(() => sendAction({ caseId: myCase.caseId, action: "hospital_approve", hospital_id: hospital.hospitalId, actor: "hospital", timestamp: now() }))}
                        onReject={g(() => setRejectTarget({ caseId: myCase.caseId, hospitalId: hospital.hospitalId, name: hospital.name, action: "hospital_reject" }))}
                        onConfirm={g(() => sendAction({ caseId: myCase.caseId, action: "final_approval", hospital_id: hospital.hospitalId, actor: "paramedic", timestamp: now() }))}
                      />
                    ))}
                  </div>
                  <div style={{ fontSize: 12, color: C.ink3 }}>승인 병원 중 한 곳에 [이송 확정]을 누르면 이송이 시작됩니다. 목록 순서는 hub 순위(이동 시간·진료과·등급)입니다.</div>
                </ScreenCard>
              )}

              {/* ── ④ 이송 중 상황 부여 ── */}
              {screen === "transport" && (
                  <ScreenCard title="④ 이송 중 — 상황을 부여하세요 (판정은 hub 규칙 엔진)">
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 14, alignItems: "stretch" }}>
                      <div style={{ flex: "1 1 380px", minWidth: 0, boxSizing: "border-box", background: "#f8fafc", border: `1px solid ${C.lineSoft}`, borderRadius: 12, padding: "20px 22px", display: "flex", flexDirection: "column", justifyContent: "center", gap: 16 }}>
                        {simOn ? (
                          <>
                            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                              <span style={{ fontSize: 12, fontWeight: 500, color: C.muted }}>병원까지 예상 소요</span>
                              <span style={{ display: "flex", alignItems: "baseline", gap: 6, color: C.blue }}>
                                <span style={{ fontSize: 56, fontWeight: 700, lineHeight: 1 }}>{simTrip.left ?? "—"}</span>
                                <span style={{ fontSize: 20, fontWeight: 700 }}>초</span>
                              </span>
                            </div>
                            <ProgressTrack p={simTrip.p} start={`현장 · ${dispatchInfo?.spot ?? ""}`} end={confirmedHospital?.name ?? "병원"} endIcon="hospital" />
                            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "8px 12px", fontSize: 13, color: C.ink3 }}>
                              <span>{sim?.paused ? "일시정지 중 — " : ""}도착하면 도착 결과 화면으로 넘어갑니다.</span>
                              {/* 빨리감기(2026-10-04) — 이송 30초 동안 상황을 다 골랐으면 3초 안에 병원 도착 */}
                              {phase === "transporting" && apid && caseId && (simTrip.left == null || simTrip.left > 3) && (
                                <FastButton onClick={g(() => sendSimCommand("sim_fast_forward", apid, caseId) && note("빨리감기 — 3초 안에 병원에 도착합니다"))} />
                              )}
                            </div>
                            {/* 이송 중 수용 철회(2026-10-05) — 목적지 병원 역할을 대신 연출한다(실제 병원 탭의 [이송 중 수용 철회]와 같다) */}
                            {phase === "transporting" && caseId && confirmedHospital && (
                              <button
                                type="button"
                                onClick={g(() => setRejectTarget({ caseId, hospitalId: confirmedHospital.hospitalId, name: confirmedHospital.name, action: "transport_withdraw" }))}
                                style={{ ...bulkButton("red", false), alignSelf: "flex-start" }}
                              >
                                <Icon name="x" size={13} color={C.red} stroke={3} />목적지 병원 수용 철회 (병원 역할 · 사유 선택)
                              </button>
                            )}
                          </>
                        ) : (
                          <>
                            <div style={{ fontSize: 15, color: C.ink2 }}>이송 병원 <b>{confirmedHospital?.name}</b></div>
                            <button type="button" style={{ minHeight: 46, background: C.blue, border: "none", borderRadius: 10, color: "#ffffff", fontSize: 15, fontWeight: 700, cursor: "pointer" }} onClick={() => setManualArrival(true)}>
                              병원 도착 — 도착 결과 입력으로
                            </button>
                          </>
                        )}
                        {latest && (
                          <div style={{ fontSize: 13, color: C.ink, borderTop: `1px solid ${C.lineSoft}`, paddingTop: 10 }}>
                            최근 판정: <b>{TIER_LABEL[latest.tier]}</b> · NEWS2 {latest.news2}
                            {latest.si != null ? ` · 쇼크지수 ${latest.si}` : ""}
                            {latest.reasons[0] ? <span style={{ color: C.muted }}> — {latest.reasons[0]}</span> : null}
                          </div>
                        )}
                      </div>
                      <div style={{ flex: "1.3 1 440px", minWidth: 0, display: "flex", flexDirection: "column", gap: 8 }}>
                        {SCENARIOS.map((scenario) => {
                          const sel = playingKey === scenario.key;
                          const disabled = playingKey !== null && !sel;
                          return (
                            <button
                              key={scenario.key}
                              type="button"
                              disabled={disabled}
                              onClick={() => (locked ? pauseToast.notify() : sel ? stopScenario(caseId!) : playScenario(scenario.key))}
                              style={{
                                flex: "1 1 60px", maxHeight: 100, textAlign: "left", borderRadius: 10, padding: "10px 16px", display: "flex", flexDirection: "column",
                                justifyContent: "center", gap: 3, cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.5 : 1,
                                background: sel ? C.blueSoft : C.bg, border: sel ? `2px solid ${C.blue}` : `1px solid ${C.line}`,
                              }}
                            >
                              <span style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, fontWeight: 700, color: C.ink }}>
                                <Icon name={sel ? "stop" : "play"} size={10} color={C.ink} />{scenario.label}
                              </span>
                              <span style={{ fontSize: 13, color: C.ink3 }}>{scenario.expects}</span>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  </ScreenCard>
              )}

              {/* ── ⑤ 도착 결과 ── */}
              {screen === "arrival" && confirmedId && caseId && (
                <ScreenCard title="⑤ 도착 결과 — 병원이 실제 수용 여부를 기록합니다">
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 14, alignItems: "stretch" }}>
                    <div style={{ flex: "1.2 1 420px", minWidth: 0, background: C.bg, borderRadius: 12, padding: "24px 28px", display: "flex", flexDirection: "column", justifyContent: "center", gap: 18 }}>
                      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                        <span style={{ fontSize: 13, fontWeight: 500, color: C.muted }}>도착 병원</span>
                        <span style={{ fontSize: 32, fontWeight: 700, lineHeight: 1.2 }}>{confirmedHospital?.name}</span>
                      </div>
                      <div style={{ height: 1, background: C.line }} />
                      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                        <span style={{ fontSize: 13, fontWeight: 500, color: C.muted }}>
                          환자 상태 {caseSource === "voice" ? "(통화 음성 · AI 구조화)" : "(가상 환자)"}
                        </span>
                        <span style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "6px 10px", fontSize: 24, fontWeight: 700 }}>
                          <span>{caseTemplate?.label ?? (caseSource === "voice" ? "통화로 확인한 환자" : "환자")}</span>
                          {caseTemplate && <SevChip sev={caseTemplate.severity} />}
                        </span>
                        {caseTemplate && <span style={{ fontSize: 15, lineHeight: 1.5, color: C.ink2 }}>{caseTemplate.detail}</span>}
                      </div>
                    </div>
                    <div style={{ flex: "1 1 360px", minWidth: 0, display: "flex", flexDirection: "column", gap: 12 }}>
                      <button
                        type="button"
                        onClick={g(() => { sendAction({ caseId, action: "arrival_accepted", hospital_id: confirmedId, actor: "hospital", timestamp: now() }); note("환자 수용 완료 — 사건 종료, 구급차 복귀 → ①로 돌아갑니다"); })}
                        style={{ flex: "1 1 100px", minHeight: 80, padding: "0 26px", background: C.blue, border: "none", borderRadius: 12, color: "#ffffff", fontSize: 22, fontWeight: 700, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 10 }}
                      >
                        <Icon name="check" size={24} color="#ffffff" stroke={3} />환자 수용 완료
                      </button>
                      <button
                        type="button"
                        onClick={g(() => setRejectTarget({ caseId, hospitalId: confirmedId, name: confirmedHospital?.name ?? "병원", action: "arrival_refused" }))}
                        style={{ flex: "1 1 100px", minHeight: 80, padding: "0 26px", background: C.redSoft, border: `1px solid ${C.red}`, borderRadius: 12, color: C.red, fontSize: 22, fontWeight: 700, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 10 }}
                      >
                        <Icon name="x" size={24} color={C.red} stroke={3} />도착 후 수용 불가 (재선택 시연)
                      </button>
                      <div style={{ fontSize: 13, color: C.ink3 }}>수용 완료 시 사건이 닫히고 구급차가 복귀해 자동으로 ① 화면으로 돌아옵니다.</div>
                    </div>
                  </div>
                </ScreenCard>
              )}
            </>
          )}
        </main>

        <div style={{ textAlign: "center", fontSize: 10, lineHeight: 1.5, color: C.muted, padding: "0 12px" }}>
          운영자 전용 시연 연출 화면 — 모든 조작은 실제 hub 흐름을 그대로 쓰고, 가상 데이터에는 전부 가상 표시가 남습니다. 통화 음성은
          대원 휴대폰 전화 앱(P-코드) 담당. 화면은 hub 상태를 따라 자동 전환됩니다.
        </div>
      </div>
    </div>
  );
}

// ── 대량사고 현황판(2026-10-05 시안의 대량 ①~⑤를 실제 사건으로) ──
type CasualtyView = MciCasualty & {
  template: Template;
  unit: AmbulanceSimState | null;
  monitorCase: MonitorCase | null;
  confirmed: MonitorCaseHospital | null;
  stage: number;
  hospitalName: string | null;
};

const STAGE_LABEL = ["현장 출동 중", "현장 확인 중", "병원 응답 대기", "병원 이송 중", "병원 도착", "완료"];

function MciBoard({
  total, remaining, spotLabel, casualties, ambulanceName, tripProgress,
  onApproveAll, onConfirmAll, onFastAll, onAcceptAll, onCaseApprove, onCaseConfirm, onCaseFast, onCaseArrival, onEnd,
}: {
  total: number;
  remaining: number;
  spotLabel: string;
  casualties: CasualtyView[];
  ambulanceName: (apid: string) => string;
  tripProgress: (unit: AmbulanceSimState | null) => { left: number | null; p: number };
  onApproveAll: () => void;
  onConfirmAll: () => void;
  onFastAll: () => void;
  onAcceptAll: () => void;
  onCaseApprove: (c: CasualtyView) => void;
  onCaseConfirm: (c: CasualtyView) => void;
  onCaseFast: (c: CasualtyView) => void;
  onCaseArrival: (c: CasualtyView, accepted: boolean) => void;
  onEnd: () => void;
}) {
  const bySev = (sev: SevLabel) => casualties.filter((c) => c.template.severity === sev).length;
  const active = casualties.filter((c) => c.stage < 5);
  const waitingResponse = casualties.filter((c) => c.stage === 2 && c.monitorCase && !c.confirmed);
  const confirmable = waitingResponse.filter((c) => c.monitorCase!.hospitals.some((h) => h.status === "approved"));
  const moving = casualties.filter((c) => c.unit && ["dispatching", "transporting"].includes(c.unit.phase));
  const arrived = casualties.filter((c) => c.stage === 4);
  const done = casualties.filter((c) => c.stage === 5 && c.hospitalName).length;

  // 병원별 분배 현황 — 이송 확정(또는 완료)된 사상자를 병원 × 중증도로 모은다(시안의 분배표 자리)
  const distribution = new Map<string, Record<SevLabel, number>>();
  for (const c of casualties) {
    if (!c.hospitalName) continue;
    const row = distribution.get(c.hospitalName) ?? { 중증: 0, 중등증: 0, 경증: 0 };
    row[c.template.severity] += 1;
    distribution.set(c.hospitalName, row);
  }

  const tiles: [string, number, string, string, string][] = [
    ["사상자 합계", total, "명", C.bg, C.ink],
    ["중증", bySev("중증"), "명", C.redSoft, C.redInk],
    ["중등증", bySev("중등증"), "명", C.amberSoft, C.amberInk],
    ["경증", bySev("경증"), "명", C.greenSoft, C.greenInk],
    ["활동 구급대", active.length, "대", C.blueSoft, C.blue],
    ["재출동 대기", remaining, "명", C.bg, C.ink3],
  ];

  return (
    <ScreenCard title={`대량사고 — ${spotLabel} · 사상자 ${total}명 (사상자마다 구급대 1대 · 사건 1건)`}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 10 }}>
        {tiles.map(([label, n, unit, bg, fg]) => (
          <div key={label} style={{ display: "flex", flexDirection: "column", gap: 6, padding: "12px 16px", borderRadius: 12, background: bg, color: fg }}>
            <span style={{ fontSize: 13, fontWeight: 700 }}>{label}</span>
            <span style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
              <span style={{ fontSize: 30, fontWeight: 700, lineHeight: 1 }}>{n}</span>
              <span style={{ fontSize: 15, fontWeight: 700 }}>{unit}</span>
            </span>
          </div>
        ))}
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "8px 10px" }}>
        <button type="button" disabled={waitingResponse.length === 0} style={bulkButton("green", waitingResponse.length === 0)} onClick={onApproveAll}>
          <Icon name="check" size={13} color={C.greenInk} stroke={3} />응답 대기 {waitingResponse.length}건 미응답 병원 전부 승인
        </button>
        <button type="button" disabled={confirmable.length === 0} style={bulkButton("blue", confirmable.length === 0)} onClick={onConfirmAll}>
          승인 병원 1순위로 {confirmable.length}건 이송 확정
        </button>
        <button type="button" disabled={moving.length === 0} style={bulkButton("plain", moving.length === 0)} onClick={onFastAll}>
          <Icon name="ff" size={11} color={C.ink} />이동 중 {moving.length}대 빨리감기
        </button>
        <button type="button" disabled={arrived.length === 0} style={bulkButton("green", arrived.length === 0)} onClick={onAcceptAll}>
          도착 {arrived.length}명 전부 수용 완료
        </button>
        <button type="button" style={{ ...bulkButton("red", false), marginLeft: "auto" }} onClick={onEnd}>
          대량사고 종료 (대기열 비우기)
        </button>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 14, alignItems: "flex-start" }}>
        {/* 사상자별 진행 — 시안 대량 ④의 구급대별 행 */}
        <div style={{ flex: "1.7 1 560px", minWidth: 0, display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: C.ink3 }}>사상자별 진행 — 가상 환자 · 완료 {done}명</div>
          {casualties.length === 0 && <div style={{ fontSize: 13, color: C.muted }}>출동 준비 중…</div>}
          {casualties.map((c) => {
            const { left, p } = tripProgress(c.unit);
            const finished = c.stage === 5;
            const responses = c.monitorCase?.hospitals ?? [];
            const okN = responses.filter((h) => h.status === "approved").length;
            const noN = responses.filter((h) => h.status === "rejected").length;
            const hospitalText = c.hospitalName
              ?? (c.stage === 2 && c.monitorCase ? `응답 승인 ${okN} · 불가 ${noN} · 대기 ${responses.length - okN - noN}` : "—");
            const barColor = finished || c.stage === 4 ? C.green : C.blue;
            const barWidth = finished || c.stage >= 4 ? 1 : c.stage === 3 ? p : c.stage === 0 ? p * 0.5 : 0;
            return (
              <div
                key={c.caseId}
                style={{
                  display: "grid", gridTemplateColumns: "28px 52px minmax(0, 1.1fr) minmax(0, 1.4fr) minmax(60px, 0.8fr) 52px auto", alignItems: "center",
                  columnGap: 10, padding: "6px 12px", borderRadius: 10, boxSizing: "border-box",
                  background: finished ? C.greenRow : "#ffffff", border: `1px solid ${finished ? C.greenLine : C.lineSoft}`,
                }}
              >
                <span style={{ fontSize: 13, fontWeight: 700, color: C.muted }}>{c.no}</span>
                <SevChip sev={c.template.severity} width={52} />
                <span style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 1 }}>
                  <span style={{ fontSize: 13, fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.template.label}</span>
                  <span style={{ fontSize: 11, color: C.muted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{ambulanceName(c.apid)} · {STAGE_LABEL[c.stage]}</span>
                </span>
                <span style={{ minWidth: 0, fontSize: 13, lineHeight: 1.3, color: c.hospitalName ? C.ink : C.ink3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{hospitalText}</span>
                <div style={{ position: "relative", height: 8, borderRadius: 4, background: C.lineSoft }}>
                  <div style={{ height: 8, borderRadius: 4, background: barColor, width: `${(barWidth * 100).toFixed(1)}%` }} />
                </div>
                <span style={{ textAlign: "right", fontSize: 13, fontWeight: 700, color: finished || c.stage === 4 ? C.greenInk : C.blue }}>
                  {finished ? "완료" : c.stage === 4 ? "도착" : left != null ? `${left}초` : ""}
                </span>
                <span style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                  {c.stage === 2 && c.monitorCase && responses.some((h) => h.status === "pending") && (
                    <button type="button" style={rowButton("green")} onClick={() => onCaseApprove(c)}>일괄 승인</button>
                  )}
                  {c.stage === 2 && okN > 0 && (
                    <button type="button" style={rowButton("blue")} onClick={() => onCaseConfirm(c)}>이송 확정</button>
                  )}
                  {c.unit && ["dispatching", "transporting"].includes(c.unit.phase) && (left == null || left > 3) && (
                    <button type="button" style={rowButton("plain")} onClick={() => onCaseFast(c)}>빨리감기</button>
                  )}
                  {c.stage === 4 && (
                    <>
                      <button type="button" style={rowButton("green")} onClick={() => onCaseArrival(c, true)}>수용</button>
                      <button type="button" style={rowButton("red")} onClick={() => onCaseArrival(c, false)}>불가</button>
                    </>
                  )}
                </span>
              </div>
            );
          })}
        </div>

        {/* 병원별 분배 — 시안 대량 ③의 분배표 자리. 분배 자체는 hub 규칙(사건마다)이 정한다 */}
        <div style={{ flex: "1 1 300px", minWidth: 0, display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: C.ink3 }}>병원별 분배 (이송 확정 기준)</div>
          {distribution.size === 0 ? (
            <div style={{ fontSize: 13, color: C.muted, background: C.bg, borderRadius: 10, padding: "10px 14px" }}>아직 이송 확정된 사상자가 없습니다.</div>
          ) : (
            [...distribution.entries()]
              .sort((a, b) => Object.values(b[1]).reduce((s, n) => s + n, 0) - Object.values(a[1]).reduce((s, n) => s + n, 0))
              .map(([name, row]) => (
                <div key={name} style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", borderRadius: 10, border: `1px solid ${C.lineSoft}`, background: "#ffffff" }}>
                  <span style={{ flex: "1 1 auto", minWidth: 0, fontSize: 13, fontWeight: 700, wordBreak: "keep-all", overflowWrap: "anywhere" }}>{name}</span>
                  {(Object.entries(row) as [SevLabel, number][]).filter(([, n]) => n > 0).map(([sev, n]) => (
                    <SevChip key={sev} sev={sev} text={`${sev} ${n}`} />
                  ))}
                </div>
              ))
          )}
          <div style={{ fontSize: 12, lineHeight: 1.6, color: C.ink3 }}>
            분배 규칙(hub): ① 중증은 권역·지역센터에 이동 시간 가산 ② 경증은 센터에 역가산(센터 보존) ③ 같은 병원으로
            이송 중인 환자가 쌓일수록 순위가 밀림(부하 페널티) — 만실 전에 자연히 다음 병원으로 분산됩니다.
          </div>
        </div>
      </div>
    </ScreenCard>
  );
}

// 불가 사유 선택 모달(2026-10-05) — 병원 대시보드의 [불가]와 같은 4축 어휘. "사유 없음"을 맨 앞에 둬 급할 땐 바로 보낸다.
function RejectReasonModal({ title, note, onPick, onClose }: {
  title: string;
  note: string;
  onPick: (reason: RejectionReason) => void;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const reasonButton: CSSProperties = {
    minHeight: 40, padding: "0 14px", borderRadius: 10, border: "1.5px solid #eba9a3", background: "#ffffff",
    color: C.redInk, fontSize: 14, fontWeight: 700, cursor: "pointer",
  };
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={onClose}
      style={{ position: "fixed", inset: 0, zIndex: 900, background: "rgba(22, 32, 43, 0.45)", display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ ...panel, width: "min(560px, 100%)", padding: "18px 20px", display: "flex", flexDirection: "column", gap: 12, boxShadow: "0 12px 40px rgba(22, 32, 43, 0.25)" }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
          <div>
            <div style={{ fontSize: 17, fontWeight: 700 }}>{title}</div>
            <div style={{ fontSize: 12, color: C.ink3, marginTop: 2 }}>{note}</div>
          </div>
          <button type="button" onClick={onClose} style={headerButton} aria-label="닫기">닫기</button>
        </div>
        <button type="button" onClick={() => onPick("UNSPECIFIED")} style={{ ...reasonButton, alignSelf: "flex-start", color: C.ink, borderColor: C.control }}>
          사유 없음 (바로 보내기)
        </button>
        {REJECTION_REASON_GROUPS.map((group) => (
          <div key={group.label} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span style={{ fontSize: 12, fontWeight: 700, color: C.muted }}>{group.label}</span>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {group.options.map((option) => (
                <button key={option.value} type="button" onClick={() => onPick(option.value)} style={reasonButton}>
                  {option.label}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── 공용 조각 ──
const panel: CSSProperties = { background: "#ffffff", border: `1px solid ${C.line}`, borderRadius: 14, boxSizing: "border-box" };
const softBox: CSSProperties = { background: "#f8fafc", borderRadius: 12, padding: "12px 14px", fontSize: 14 };
const headerButton: CSSProperties = {
  minHeight: 30, padding: "0 10px", background: "#ffffff", border: `1px solid ${C.control}`, borderRadius: 8,
  fontSize: 12, fontWeight: 700, color: C.ink, cursor: "pointer",
};
const stepperButton: CSSProperties = {
  width: 34, height: 34, background: "#ffffff", border: `1px solid ${C.control}`, borderRadius: 8, fontSize: 16, fontWeight: 700, cursor: "pointer", color: C.ink,
};

function bulkButton(tone: "green" | "red" | "blue" | "plain", disabled: boolean): CSSProperties {
  const tones = {
    green: { bg: C.greenSoft, bd: C.green, fg: C.greenInk },
    red: { bg: C.redSoft, bd: C.red, fg: C.red },
    blue: { bg: C.blue, bd: C.blue, fg: "#ffffff" },
    plain: { bg: "#ffffff", bd: C.control, fg: C.ink },
  }[tone];
  return {
    minHeight: 38, padding: "0 14px", background: tones.bg, border: `1px solid ${tones.bd}`, borderRadius: 10, color: tones.fg,
    fontSize: 13, fontWeight: 700, cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.4 : 1,
    display: "flex", alignItems: "center", gap: 6,
  };
}

function rowButton(tone: "green" | "red" | "blue" | "plain"): CSSProperties {
  const tones = {
    green: { bd: C.green, fg: C.greenInk, bg: "#ffffff" },
    red: { bd: C.red, fg: C.redInk, bg: "#ffffff" },
    blue: { bd: C.blue, fg: "#ffffff", bg: C.blue },
    plain: { bd: C.control, fg: C.ink, bg: "#ffffff" },
  }[tone];
  return {
    minHeight: 30, padding: "0 10px", background: tones.bg, border: `1px solid ${tones.bd}`, borderRadius: 8,
    fontSize: 12, fontWeight: 700, color: tones.fg, cursor: "pointer", whiteSpace: "nowrap",
  };
}

// 단계 카드 — 남은 높이를 채우고, 내용이 넘치면 카드 안에서만 스크롤한다. fixed면 카드 자체는 스크롤하지 않고
// 안쪽의 한 영역(③의 병원 목록)이 스크롤을 맡는다.
function ScreenCard({ title, children, fixed = false }: { title: string; children: ReactNode; fixed?: boolean }) {
  return (
    <section
      className={fixed ? undefined : "ctl-scroll"}
      style={{ ...panel, padding: "14px 18px", display: "flex", flexDirection: "column", gap: 12, flex: "1 1 auto", minHeight: 0, overflowY: fixed ? "hidden" : "auto" }}
    >
      <h2 style={{ margin: 0, fontSize: 17, fontWeight: 700, flex: "none" }}>{title}</h2>
      {children}
    </section>
  );
}

function SevChip({ sev, text, width }: { sev: SevLabel; text?: string; width?: number }) {
  const c = SEV_COLORS[sev];
  return (
    <span style={{ fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 999, background: c.bg, color: c.fg, whiteSpace: "nowrap", flex: "none", ...(width ? { width, boxSizing: "border-box", textAlign: "center" } : {}) }}>
      {text ?? sev}
    </span>
  );
}

function CountTile({ label, n, bg, fg }: { label: string; n: number; bg: string; fg: string }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 6, padding: "5px 12px", borderRadius: 10, background: bg, color: fg }}>
      <span style={{ fontSize: 12, fontWeight: 700 }}>{label}</span>
      <span style={{ fontSize: 17, fontWeight: 700, lineHeight: 1 }}>{n}</span>
    </div>
  );
}

function ConnectionDot({ mode }: { mode: string }) {
  const live = mode === "live";
  const color = live ? C.green : mode === "mock" ? C.orangeInk : C.red;
  const text = live ? "실시간 연동" : mode === "mock" ? "목데이터 모드" : "hub 재연결 중…";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, fontWeight: 500, color: live ? "#0f8a62" : color }}>
      <span style={{ width: 8, height: 8, borderRadius: "50%", background: color, display: "inline-block" }} />{text}
    </div>
  );
}

function Pulse({ color }: { color: string }) {
  return <span style={{ width: 12, height: 12, borderRadius: "50%", background: color, display: "inline-block", flex: "none", animation: "gl-pulse 1.2s ease-in-out infinite" }} />;
}

function FastButton({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} style={{ ...headerButton, minHeight: 30, display: "flex", alignItems: "center", gap: 5 }}>
      <Icon name="ff" size={11} color={C.ink} />빨리감기 (3초 안에 도착)
    </button>
  );
}

// 신고 증상·현장 확인 카드 한 줄(라디오 · 중증도 · 제목/증상 · 환자 · 필요 진료과)
function SymptomRow({ template, selected, disabled, onPick }: { template: Template; selected: boolean; disabled?: boolean; onPick: () => void }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onPick}
      style={{
        minHeight: 60, textAlign: "left", display: "grid", gridTemplateColumns: "18px 56px minmax(0, 1fr) 76px 88px", alignItems: "center",
        columnGap: 14, padding: "8px 14px", borderRadius: 10, cursor: disabled ? "wait" : "pointer", boxSizing: "border-box",
        background: selected ? C.blueSoft : "#ffffff", border: selected ? `2px solid ${C.blue}` : `1px solid ${C.line}`,
      }}
    >
      <span
        style={{
          width: 18, height: 18, boxSizing: "border-box", borderRadius: "50%",
          border: `2px solid ${selected ? C.blue : "#b7c5d4"}`, background: selected ? C.blue : "#ffffff",
          boxShadow: selected ? "inset 0 0 0 3px #ffffff" : "none",
        }}
      />
      <SevChip sev={template.severity} width={56} />
      <span style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
        <span style={{ fontSize: 15, fontWeight: 700, color: C.ink }}>{template.label}</span>
        <span style={{ fontSize: 13, lineHeight: 1.4, color: C.ink2 }}>{template.symText}</span>
      </span>
      <span style={{ fontSize: 14, fontWeight: 700, color: C.ink }}>{template.summary.patient}</span>
      <span style={{ boxSizing: "border-box", width: 88, textAlign: "center", fontSize: 13, fontWeight: 700, color: C.blue, background: C.blueDept, padding: "4px 0", borderRadius: 8 }}>
        {template.summary.required_department}
      </span>
    </button>
  );
}

// 출동·이송 진행 바(시작점 원 → 끝점 핀/병원, 구급차 표식이 진행률만큼 이동)
function ProgressTrack({ p, start, end, endIcon }: { p: number; start: string; end: string; endIcon: "pin" | "hospital" }) {
  const at = `calc(14px + (100% - 28px) * ${p.toFixed(3)})`;
  return (
    <div style={{ position: "relative", height: 92, margin: "4px 6px 0" }}>
      <div style={{ position: "absolute", left: 14, right: 14, top: 32, height: 5, borderRadius: 3, background: C.lineSoft }} />
      <div style={{ position: "absolute", left: 14, top: 32, height: 5, borderRadius: 3, background: C.blue, width: `calc((100% - 28px) * ${p.toFixed(3)})`, transition: "width 0.9s linear" }} />
      <div style={{ position: "absolute", left: 0, top: 22, width: 26, height: 26, boxSizing: "border-box", borderRadius: "50%", background: "#ffffff", border: `3px solid ${C.blue}` }} />
      {endIcon === "pin" ? (
        <div style={{ position: "absolute", right: 0, top: 18 }}>
          <svg width="28" height="34" viewBox="0 0 24 24" fill={C.pin} stroke="#ffffff" strokeWidth="1.2" strokeLinejoin="round" aria-hidden>
            <path d="M12 22s-7-6.2-7-12a7 7 0 0114 0c0 5.8-7 12-7 12z" /><circle cx="12" cy="10" r="2.6" fill="#ffffff" stroke="none" />
          </svg>
        </div>
      ) : (
        <div style={{ position: "absolute", right: 0, top: 20, width: 28, height: 28, borderRadius: 8, background: C.green, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <Icon name="plus" size={16} color="#ffffff" stroke={2.6} />
        </div>
      )}
      <div style={{ position: "absolute", top: 19, left: at, width: 30, height: 30, marginLeft: -15, borderRadius: "50%", background: C.blue, display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "0 2px 6px rgba(29, 95, 168, 0.35)", transition: "left 0.9s linear" }}>
        <Icon name="siren" size={17} color="#ffffff" />
      </div>
      <div style={{ position: "absolute", left: 0, top: 62, fontSize: 13, fontWeight: 700 }}>{start}</div>
      <div style={{ position: "absolute", right: 0, top: 62, fontSize: 13, fontWeight: 700, textAlign: "right" }}>{end}</div>
    </div>
  );
}

// ③ 병원 한 줄 — 상태 칩 + 승인/불가/이송 확정. 적합 여부 칸은 시안의 가상 '적합' 대신 실제 E-Gen 병상(미상 ≠ 만실)과
// 병원이 고른 거절 사유를 보인다.
function HospitalRow({ hospital, info, onApprove, onReject, onConfirm }: {
  hospital: MonitorCaseHospital;
  info: MapHospital | undefined;
  onApprove: () => void;
  onReject: () => void;
  onConfirm: () => void;
}) {
  const status = hospital.status;
  const chip = STATUS_CHIP[status];
  const lock = status !== "pending";
  const reason = status === "rejected"
    ? unavailableReasonLabel(hospital.unavailableReason) ?? rejectionReasonLabel(hospital.rejectReason) ?? "병원 판단"
    : null;
  const beds = info?.bedCountUnknown || info?.availableBedCount == null
    ? { text: "병상 미상", color: C.muted }
    : info.availableBedCount <= 0
      ? { text: "병상 없음", color: C.redInk }
      : { text: `응급실 ${info.availableBedCount}석`, color: C.greenInk };
  const fit = reason ? { text: reason, color: C.redInk } : beds;
  const km = hospital.roadDistanceKm ?? hospital.distanceKm;
  const sub = [
    info?.emergencyLevel ? LEVEL_SHORT[info.emergencyLevel] ?? info.emergencyLevel : null,
    `${hospital.roadDistanceKm != null ? "" : "직선 "}${km.toFixed(1)}km`,
    `존 ${hospital.zone}`,
    reason ? beds.text : null,
  ].filter(Boolean).join(" · ");
  const ok = status === "approved" || status === "confirmed";
  const btnBase: CSSProperties = {
    minHeight: 32, padding: "0 10px", background: "#ffffff", borderRadius: 8, fontSize: 13, fontWeight: 700,
    cursor: lock ? "not-allowed" : "pointer", display: "flex", alignItems: "center", gap: 4, opacity: lock ? 0.35 : 1,
  };
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "4px 10px", boxSizing: "border-box", border: `1px solid ${ok ? C.greenLine : C.lineSoft}`, borderRadius: 10, background: ok ? C.greenRow : "#ffffff" }}>
      <div style={{ flex: "1 1 auto", minWidth: 0, display: "flex", flexDirection: "column", gap: 2 }}>
        <span style={{ wordBreak: "keep-all", overflowWrap: "anywhere", fontSize: 13, lineHeight: 1.35, color: status === "rejected" ? "#8795a4" : C.ink, fontWeight: ok ? 700 : 400 }}>
          {hospital.name}
        </span>
        <span style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: "0 6px" }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: fit.color }}>{fit.text}</span>
          <span style={{ fontSize: 11, color: C.muted }}>{sub}</span>
        </span>
      </div>
      <span style={{ flex: "none", width: 78, boxSizing: "border-box", textAlign: "center", fontSize: 12, fontWeight: 700, padding: "4px 0", borderRadius: 999, background: chip.bg, color: chip.fg }}>
        {chip.label}
      </span>
      <div style={{ display: "flex", gap: 6, flex: "none" }}>
        <button type="button" disabled={lock} onClick={onApprove} style={{ ...btnBase, border: `1px solid ${C.green}`, color: C.greenInk }}>
          <Icon name="check" size={12} color={C.greenInk} stroke={3.2} />승인
        </button>
        <button type="button" disabled={lock} onClick={onReject} style={{ ...btnBase, border: `1px solid ${C.red}`, color: C.redInk }}>
          <Icon name="x" size={12} color={C.red} stroke={3.2} />불가
        </button>
        <button
          type="button"
          disabled={status !== "approved"}
          onClick={onConfirm}
          style={{ minHeight: 32, padding: "0 12px", border: "none", borderRadius: 8, fontSize: 13, fontWeight: 700, color: "#ffffff", cursor: status === "approved" ? "pointer" : "not-allowed", background: status === "approved" ? C.blue : C.blueOff }}
        >
          이송 확정
        </button>
      </div>
    </div>
  );
}

// 현장 확인 입력 출처 표시(2026-10-04) — 음성(전화 앱, AI 구조화)인지 정해진 상황(가상 환자)인지
function SourceBadge({ source, label, need }: { source: "voice" | "template" | null; label?: string; need?: string }) {
  if (!source) return null;
  const voice = source === "voice";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, alignSelf: "flex-start", background: voice ? C.blueSoft : C.orangeSoft, color: voice ? C.blue : C.orangeInk, fontSize: 13, fontWeight: 700, padding: "8px 12px", borderRadius: 10 }}>
      <Icon name={voice ? "mic" : "card"} size={14} color={voice ? C.blue : C.orangeInk} />
      {voice ? "현장 확인: 음성 (휴대폰 통화 · AI 구조화)" : `현장 확인: 정해진 상황${label ? ` — ${label}` : ""} (가상 환자)`}
      {need && <span style={{ fontWeight: 500 }}> · 필요: {need}</span>}
    </div>
  );
}

// 시간 기반 존 확장 카운트다운(2026-10-04) — 승인·확정 병원이 없으면 hub가 30초마다 요청 범위를 한 단계 넓힌다.
// [건너뛰기]는 기다리지 않고 바로 넓힌다. expandAt이 없으면(승인 병원 있음·더 넓힐 수 없음) 멈춤 안내만.
function ZoneCountdown({ expandAt, pausedLeft, zone, onSkip }: {
  expandAt: string | null;
  // [정지] 중이면 멈춰 있는 남은 시간(초) — 일시정지하면 존 확장 시간도 흐르지 않는다(2026-10-04)
  pausedLeft: number | null;
  zone: number;
  onSkip: () => void;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(timer);
  }, []);
  const left = expandAt ? Math.max(0, Math.ceil((Date.parse(expandAt) - now) / 1000)) : pausedLeft;
  const paused = !expandAt && pausedLeft != null;
  return (
    <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "6px 12px", background: C.bg, borderRadius: 10, padding: "8px 14px", fontSize: 14 }}>
      <span>
        요청 범위 <b>{zone > 1 ? `존 1~${zone}` : "존 1"}</b> ·{" "}
        {left == null ? (
          <span style={{ color: C.muted }}>자동 확장 멈춤(수용 승인 병원이 있거나 더 넓힐 곳이 없음)</span>
        ) : paused ? (
          <>일시정지 — 다음 존까지 <b>{left}초</b> 남은 채로 멈춤</>
        ) : (
          <>응답 없으면 <b style={{ color: "#c26a00" }}>{left}초</b> 뒤 다음 존으로 자동 확장</>
        )}
      </span>
      {left != null && (
        <button type="button" onClick={onSkip} style={{ ...headerButton, display: "flex", alignItems: "center", gap: 5 }}>
          <Icon name="skip" size={11} color={C.ink} />건너뛰기 (지금 확장)
        </button>
      )}
    </div>
  );
}

// 시안의 선 아이콘들(인라인 SVG)
function Icon({ name, size, color, stroke = 2.2 }: {
  name: "check" | "x" | "pin" | "siren" | "flame" | "mic" | "card" | "phone" | "ff" | "skip" | "play" | "stop" | "plus";
  size: number;
  color: string;
  stroke?: number;
}) {
  const common = { width: size, height: size, viewBox: "0 0 24 24", "aria-hidden": true } as const;
  const line = { fill: "none", stroke: color, strokeWidth: stroke, strokeLinecap: "round", strokeLinejoin: "round" } as const;
  switch (name) {
    case "check": return <svg {...common} {...line}><path d="M5 12l5 5 9-10" /></svg>;
    case "x": return <svg {...common} {...line}><path d="M6 6l12 12M18 6L6 18" /></svg>;
    case "pin": return <svg {...common} {...line}><path d="M12 21s-7-6.2-7-11a7 7 0 0114 0c0 4.8-7 11-7 11z" /><circle cx="12" cy="10" r="2.5" /></svg>;
    case "siren": return <svg {...common} {...line}><path d="M7 18v-6a5 5 0 0110 0v6M5 18h14M12 3v2M4.5 7l1.5 1M19.5 7L18 8" /></svg>;
    case "flame": return <svg {...common} {...line}><path d="M12 3c1 4 5 5 5 10a5 5 0 01-10 0c0-2 1-3 2-4 0 2 1 3 2 3 0-3-1-5 1-9z" /></svg>;
    case "mic": return <svg {...common} {...line}><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0014 0M12 18v3" /></svg>;
    case "card": return <svg {...common} {...line}><rect x="6" y="4" width="12" height="17" rx="2" /><path d="M9 4h6v3H9zM9 12h6M9 16h4" /></svg>;
    case "phone": return <svg {...common} {...line}><path d="M5 4h4l2 5-2.5 1.5a11 11 0 005 5L15 13l5 2v4a2 2 0 01-2 2A16 16 0 013 6a2 2 0 012-2z" /></svg>;
    case "plus": return <svg {...common} {...line}><path d="M12 5v14M5 12h14" /></svg>;
    case "ff": return <svg {...common} fill={color}><path d="M3 5l9 7-9 7zM12 5l9 7-9 7z" /></svg>;
    case "skip": return <svg {...common} fill={color}><path d="M4 4l11 8-11 8zM18 4h3v16h-3z" /></svg>;
    case "play": return <svg {...common} fill={color}><path d="M5 3l15 9-15 9z" /></svg>;
    case "stop": return <svg {...common} fill={color}><rect x="5" y="5" width="14" height="14" rx="2" /></svg>;
  }
}

const CONSOLE_CSS = `
@keyframes gl-pulse{0%,100%{opacity:1}50%{opacity:.3}}
html,body{overflow:hidden;overscroll-behavior:none;height:100%}
.ctl-root{height:100vh;height:100dvh;overflow:hidden;overscroll-behavior:none;user-select:none;-webkit-user-select:none;-webkit-touch-callout:none}
.ctl-root input{user-select:text;-webkit-user-select:text}
.ctl-root a,.ctl-root img{-webkit-user-drag:none}
.ctl-scroll{overscroll-behavior:contain}
.ctl-scroll > *{flex-shrink:0}
.ctl-scroll::-webkit-scrollbar{width:6px}
.ctl-scroll::-webkit-scrollbar-thumb{background:#b7c5d4;border-radius:4px}
`;
