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
  MciPlanItem,
  MonitorCase,
  MonitorCaseHospital,
  RejectionReason,
  VitalObservationIn,
} from "@/types/dashboard";
import { DemoVideoOverlay } from "@/components/ui/DemoVideoOverlay";

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

// 정해진 상황 카드(2026-10-06 시연 대사집 반영) — 환자·활력징후는 대사집 ② 현장 확인 대본과 같게 맞추고, transcript는 그 대본을
// 압축한 것이다(버튼으로 부여할 때 병원에 가는 통화 문장). 대본 전문은 SCRIPTS(② ④ 화면의 대본 칸). 위 4개(key = report)는
// 신고 접수 증상이자 "신고대로" 현장 상황이고, 나머지는 같은 신고로 출동했는데 현장 평가가 달랐던 경우다 — ② 현장 확인은
// 그 신고(report)에 딸린 상황만 보여 준다. mechanism은 hub 질환군 키워드(disease_group.py)에 맞췄다.
// KTAS·활력징후·의식·발생 시점까지 넣어 통화 요약·병원 카드의 환자 패널(PatientVitals)이 그려지게 한다.
const PATIENT_TEMPLATES = [
  {
    key: "cardiac", report: "cardiac", label: "흉통 · 경색 의심", severity: "중증" as const,
    detail: "62세 남성 · 쥐어짜는 흉통, 호흡 곤란, 식은땀 · 필요 진료과 순환기내과",
    symText: "쥐어짜는 흉통, 호흡 곤란, 왼팔 방사통, 식은땀",
    summary: {
      patient: "62세 남성", mechanism: "흉통(심장성) — 경색 의심",
      symptoms: ["흉통", "호흡 곤란", "식은땀"], treatment: ["산소 공급", "ECG"],
      severity_tag: "high", required_department: "순환기내과",
      ktas_level: 2, consciousness: "A", onset: "30분 전부터", chief_complaint: "흉통(심장성)",
      vitals: [{ sequence: 1, sbp: 100, dbp: 60, hr: 110, spo2: 93 }],
    },
    transcript: "62세 남성, 30분 전부터 쥐어짜는 흉통과 호흡곤란, 왼팔 방사통·식은땀. 혈압 100에 60, 맥박 110, 산소포화도 93. 심근경색 의심입니다.",
  },
  {
    key: "trauma", report: "trauma", label: "교통사고 다발성 외상", severity: "중증" as const,
    detail: "35세 남성 · 흉부·복부 충격, 의식 혼미, 복부 강직 · 필요 진료과 외과",
    symText: "흉부·복부 충격, 의식 혼미, 복부 강직·압통",
    summary: {
      patient: "35세 남성", mechanism: "교통사고 — 흉부·복부 충격, 다발성 외상 의심",
      symptoms: ["흉부 통증", "복부 압통", "의식 혼미"], treatment: ["경추 고정", "산소 공급"],
      severity_tag: "high", required_department: "외과",
      ktas_level: 2, consciousness: "V", onset: "사고 직후", chief_complaint: "다발성 외상",
      vitals: [{ sequence: 1, sbp: 90, dbp: 55, hr: 125, rr: 28, spo2: 91 }],
    },
    transcript: "35세 남성, 승용차 충돌로 흉부·복부 충격, 의식 혼미(부르면 눈 뜸). 혈압 90에 55, 맥박 125, 호흡 28, 산소포화도 91. 복부 강직·압통, 다발성 외상 의심입니다.",
  },
  {
    key: "abdominal", report: "abdominal", label: "복통 · 복부 압통", severity: "중등증" as const,
    detail: "48세 여성 · 복통, 구토, 우하복부 압통·반발통 · 필요 진료과 외과",
    symText: "복통, 구토 2회, 우하복부 압통·반발통",
    summary: {
      patient: "48세 여성", mechanism: "급성 복통 — 복부 압통, 장폐색·충수염 의심",
      symptoms: ["복통", "구토", "우하복부 압통"], treatment: ["금식", "수액"],
      severity_tag: "medium", required_department: "외과",
      ktas_level: 3, consciousness: "A", onset: "어제 저녁부터", chief_complaint: "급성 복통",
      vitals: [{ sequence: 1, sbp: 125, dbp: 80, hr: 98, spo2: 98, bt: 37.8 }],
    },
    transcript: "48세 여성, 어제 저녁부터 복통·구토 2회, 우하복부 압통·반발통. 혈압 125에 80, 맥박 98, 체온 37.8, 산소포화도 98, 의식 명료. 복부 압통 소견입니다.",
  },
  {
    key: "mild", report: "mild", label: "발목 염좌", severity: "경증" as const,
    detail: "24세 여성 · 발목 바깥쪽 부종·통증, 보행 가능 · 필요 진료과 정형외과",
    symText: "발목 바깥쪽 부종·통증, 체중 부하 가능",
    summary: {
      patient: "24세 여성", mechanism: "보행 중 접질림 — 발목 염좌 의심",
      symptoms: ["발목 통증", "부종"], treatment: ["부목 고정"],
      severity_tag: "low", required_department: "정형외과",
      ktas_level: 4, consciousness: "A", onset: "방금 전", chief_complaint: "발목 통증",
      vitals: [{ sequence: 1, sbp: 118, dbp: 72, hr: 80, spo2: 99 }],
    },
    transcript: "24세 여성, 보도 턱에서 발목 접질림. 바깥쪽 부종·통증, 체중 부하·보행 가능, 피부 손상 없음. 혈압 118에 72, 맥박 80, 산소포화도 99. 발목 염좌 소견입니다.",
  },
  {
    key: "cardiac_aortic", report: "cardiac", label: "흉통 · 대동맥 박리 의심", severity: "중증" as const,
    detail: "58세 남성 · 찢어지는 흉통, 등으로 뻗침, 양팔 혈압 차 · 필요 진료과 심장혈관흉부외과",
    symText: "찢어지는 흉통, 등으로 뻗침, 양팔 혈압 차",
    summary: {
      patient: "58세 남성", mechanism: "대동맥질환 · 찢어지는 흉통 · 대동맥 박리 의심",
      symptoms: ["흉통", "등 통증"], treatment: ["산소 공급", "ECG"],
      severity_tag: "high", required_department: "심장혈관흉부외과",
      ktas_level: 2, consciousness: "A", onset: "갑자기", chief_complaint: "흉통(찢어지는 양상)",
      vitals: [{ sequence: 1, sbp: 150, dbp: 90, hr: 105 }],
    },
    transcript: "58세 남성, 갑자기 찢어지는 흉통이 등으로 뻗침. 양팔 혈압 차(오른팔 150에 90, 왼팔 110에 70), 맥박 105, 의식 명료. 대동맥 박리 의심입니다.",
  },
  {
    key: "cardiac_wall", report: "cardiac", label: "흉통 · 비심장성(흉벽 통증)", severity: "경증" as const,
    detail: "45세 남성 · 누르면 아픈 흉벽 통증, 심전도 정상 · 필요 진료과 내과",
    symText: "누르면·몸 비틀면 아픈 흉통, 심전도 이상 없음",
    summary: {
      patient: "45세 남성", mechanism: "흉벽 통증 — 근골격성 흉통 의심, 심전도 이상 없음",
      symptoms: ["흉벽 통증"], treatment: ["ECG"],
      severity_tag: "low", required_department: "내과",
      ktas_level: 4, consciousness: "A", onset: "어제 짐 옮긴 뒤부터", chief_complaint: "흉벽 통증",
      vitals: [{ sequence: 1, sbp: 125, dbp: 80, hr: 78, spo2: 98 }],
    },
    transcript: "45세 남성, 왼쪽 가슴 통증이 누르거나 숨 쉬고 몸 비틀 때 심해짐, 어제 무거운 짐 옮김. 혈압 125에 80, 맥박 78, 산소포화도 98, 심전도 이상 없음. 흉벽 통증 소견입니다.",
  },
  {
    key: "trauma_head", report: "trauma", label: "교통사고 두부 손상", severity: "중증" as const,
    detail: "41세 남성 · 머리 충격, 의식 저하, 구토 2회 · 필요 진료과 신경외과",
    symText: "머리 충격, 의식 저하, 구토 2회, 뒤통수 열상",
    summary: {
      patient: "41세 남성", mechanism: "교통사고 — 두부 충격, 외상성 뇌출혈 의심",
      symptoms: ["두부 손상", "의식 저하", "구토", "두피 열상"], treatment: ["경추 고정", "지혈", "산소 공급"],
      severity_tag: "high", required_department: "신경외과",
      ktas_level: 2, consciousness: "V", onset: "사고 직후", chief_complaint: "두부 손상",
      vitals: [{ sequence: 1, sbp: 150, dbp: 95, hr: 58, spo2: 96 }],
    },
    transcript: "41세 남성, 차량 충돌로 머리 부딪힘, 의식 저하(부르면 겨우 눈 뜸), 구토 2회, 뒤통수 열상 압박 지혈 중. 혈압 150에 95, 맥박 58, 산소포화도 96. 두부 손상 의심입니다.",
  },
  {
    key: "trauma_minor", report: "trauma", label: "교통사고 경상", severity: "경증" as const,
    detail: "29세 남성 · 목·어깨 통증, 팔 찰과상, 보행 가능 · 필요 진료과 정형외과",
    symText: "목·어깨 통증, 팔 찰과상, 혼자 보행",
    summary: {
      patient: "29세 남성", mechanism: "교통사고 — 경추 염좌·찰과상, 경상",
      symptoms: ["목 통증", "어깨 통증", "찰과상"], treatment: ["경추 고정", "상처 소독"],
      severity_tag: "low", required_department: "정형외과",
      ktas_level: 4, consciousness: "A", onset: "사고 직후", chief_complaint: "목 통증",
      vitals: [{ sequence: 1, sbp: 120, dbp: 78, hr: 82, spo2: 99 }],
    },
    transcript: "29세 남성, 접촉 사고·안전벨트 착용. 목·어깨 통증, 팔 찰과상, 혼자 걸어서 탑승. 혈압 120에 78, 맥박 82, 산소포화도 99, 의식 명료. 경상입니다.",
  },
  {
    key: "abdominal_gi", report: "abdominal", label: "복통 · 위장관 출혈", severity: "중증" as const,
    detail: "67세 여성 · 토혈, 흑색변, 어지러움·창백 · 필요 진료과 내과",
    symText: "토혈, 흑색변, 어지러움, 창백",
    summary: {
      patient: "67세 여성", mechanism: "위장관 출혈 — 토혈·흑색변, 출혈성 쇼크 우려",
      symptoms: ["복통", "토혈", "흑색변", "어지러움"], treatment: ["산소 공급", "수액"],
      severity_tag: "high", required_department: "내과",
      ktas_level: 2, consciousness: "A", onset: "오늘 아침", chief_complaint: "토혈",
      vitals: [{ sequence: 1, sbp: 90, dbp: 55, hr: 118, spo2: 96 }],
    },
    transcript: "67세 여성, 오늘 아침 토혈, 어제부터 흑색변, 어지러움·창백. 혈압 90에 55, 맥박 118, 산소포화도 96. 위장관 출혈 의심입니다.",
  },
  {
    key: "abdominal_mild", report: "abdominal", label: "복통 · 급성 위장염", severity: "경증" as const,
    detail: "31세 여성 · 외식 후 복통·설사, 압통 경미 · 필요 진료과 내과",
    symText: "외식 후 복통·설사, 배 전체 가벼운 통증",
    summary: {
      patient: "31세 여성", mechanism: "급성 위장염 의심 — 복통·설사, 탈수 경미",
      symptoms: ["복통", "설사"], treatment: ["수액"],
      severity_tag: "low", required_department: "내과",
      ktas_level: 4, consciousness: "A", onset: "어제 저녁부터", chief_complaint: "복통",
      vitals: [{ sequence: 1, sbp: 118, dbp: 74, hr: 84, spo2: 99, bt: 37.2 }],
    },
    transcript: "31세 여성, 어제 저녁 외식 후 복통·설사, 배 전체 가벼운 통증·압통 경미. 혈압 118에 74, 맥박 84, 체온 37.2, 산소포화도 99, 의식 명료. 급성 위장염 소견입니다.",
  },
  {
    key: "mild_fracture", report: "mild", label: "발목 골절 의심", severity: "중등증" as const,
    detail: "52세 여성 · 발목 변형·심한 부종, 체중 부하 불가 · 필요 진료과 정형외과",
    symText: "발목 변형·심한 부종, 체중 부하 불가",
    summary: {
      patient: "52세 여성", mechanism: "낙상 — 발목 변형, 골절 의심",
      symptoms: ["발목 통증", "변형", "부종"], treatment: ["부목 고정"],
      severity_tag: "medium", required_department: "정형외과",
      ktas_level: 3, consciousness: "A", onset: "방금 전", chief_complaint: "발목 통증",
      vitals: [{ sequence: 1, sbp: 130, dbp: 82, hr: 96, spo2: 98 }],
    },
    transcript: "52세 여성, 계단에서 헛디뎌 발목 꺾임. 변형·심한 부종, 체중 부하 불가, 피부 닫힘·발가락 감각 있음. 혈압 130에 82, 맥박 96, 산소포화도 98. 발목 골절 의심입니다.",
  },
  {
    key: "mild_open", report: "mild", label: "개방성 발목 골절", severity: "중증" as const,
    detail: "38세 여성 · 뼈 노출, 출혈, 발등 맥박 약함 · 필요 진료과 정형외과",
    symText: "발목 뼈 노출, 출혈 압박 중, 발가락 차가움",
    summary: {
      patient: "38세 여성", mechanism: "추락 — 개방성 발목 골절, 출혈",
      symptoms: ["발목 통증", "개방성 상처", "출혈"], treatment: ["지혈", "부목 고정"],
      severity_tag: "high", required_department: "정형외과",
      ktas_level: 2, consciousness: "A", onset: "사고 직후", chief_complaint: "개방성 골절",
      vitals: [{ sequence: 1, sbp: 105, dbp: 65, hr: 112, spo2: 97 }],
    },
    transcript: "38세 여성, 높은 곳에서 추락, 발목 뼈 노출·출혈 거즈 압박 중, 발등 맥박 약하고 발가락 차가움. 혈압 105에 65, 맥박 112, 산소포화도 97. 개방성 발목 골절입니다.",
  },
] as const;

type Template = (typeof PATIENT_TEMPLATES)[number];

type SevLabel = Template["severity"];

// ── 이송 중 상황(2026-10-06) — 현장 상황마다 따로 둔다. 예전엔 어떤 환자든 같은 상황(쇼크·의식 저하·호전, "흉통 악화")이라
// 발목 염좌 환자에게 흉통 악화를 부여하는 식으로 앞 단계와 이어지지 않았다.
//
// monitor: 이송 중 활력징후 시나리오 5종(TransportMonitorPanel SCENARIOS)의 **이름만** 환자에 맞게 바꾼다. 수치·판정은
//   hub 규칙 엔진 시연(기록·보류·전달·대체 병원 제안·헬기 권고·오경보 거름)이라 hub/test_transport_triage.py와 같은 값으로
//   고정 — 숫자는 건드리지 않는다.
// 상황 버튼 하나(2026-10-06 통합) = 위 활력징후 시나리오를 재생하고, 끝나면 목적지 병원에 추가 통화(2차 통화 요약)를 보낸다.
//   예전엔 활력징후 버튼과 추가 통화 버튼이 따로 있어 같은 상황을 두 번 골라야 했다. 추가 통화의 활력징후는 재생한 시나리오의
//   마지막 측정값이라 hub 판정(추가 통화 활력징후도 측정 1회로 들어감)은 그대로다. calls = 신고대로 4종의 통화 문장(시연 대사집
//   ④를 숫자 빼고 압축), 없으면 상황 이름으로 만든다. hub가 환자 정보에 덧붙인다(앞선 요약은 previousCalls로 남음).
type MonitorKey = "stable" | "shock" | "mismatch" | "consciousness" | "spike";
// 추가 통화 문장. 숫자는 넣지 않는다 — 활력징후는 재생한 시나리오의 마지막 측정값으로 함께 보내 화면·판정과 어긋나지 않게
type FollowupText = { mechanism: string; symptoms: string[]; transcript: string };
type Transport = { monitor: Record<MonitorKey, string>; calls?: Record<MonitorKey, FollowupText> };
const MONITOR_NUM: Record<MonitorKey, string> = { stable: "①", shock: "②", mismatch: "③", consciousness: "④", spike: "⑤" };

const TRANSPORT: Record<string, Transport> = {
  cardiac: {
    monitor: { stable: "통증 조절 · 활력 안정", shock: "심인성 쇼크 진행", mismatch: "흉통 악화·부정맥 — 목적지 부적합", consciousness: "심정지 전조 — 의식 저하", spike: "측정값 일시적 튐(전극 흔들림)" },
    calls: {
      stable: { mechanism: "흉통(심장성) — 경색 의심, 이송 중 통증 조절", symptoms: [],
        transcript: "흉통은 처음보다 줄었고 니트로글리세린 투여 후 통증 점수 3점입니다. 의식 명료, 변화 없이 안정적입니다." },
      shock: { mechanism: "흉통(심장성) — 경색 의심, 이송 중 심인성 쇼크", symptoms: ["혈압 저하", "식은땀"],
        transcript: "재측정에서 저혈압·빈맥이 계속되고 식은땀이 심하며 피부가 차갑습니다. 심인성 쇼크 진행 중입니다." },
      mismatch: { mechanism: "흉통(심장성) — 경색 의심, 이송 중 흉통 악화·부정맥(심혈관 중재술 병원 재확인)", symptoms: ["흉통 악화", "부정맥"],
        transcript: "흉통이 다시 심해졌고 심전도상 심한 부정맥, 불규칙한 빈맥입니다. 심혈관 중재술 가능 여부 재확인 부탁드립니다. 어려우면 다른 병원을 찾겠습니다." },
      consciousness: { mechanism: "흉통(심장성) — 경색 의심, 이송 중 의식 저하(심정지 전조)", symptoms: ["의식 저하", "불규칙한 맥박"],
        transcript: "의식이 떨어져 부르면 눈만 뜨고 말이 어눌합니다. 맥박이 약하고 불규칙하며 산소 투여 중입니다. 심정지 전조 소견입니다." },
      spike: { mechanism: "흉통(심장성) — 경색 의심, 이송 중 일시적 측정 오류(재측정 정상)", symptoms: [],
        transcript: "전극이 흔들려 부정맥이 한 번 찍혔으나 전극을 다시 붙이고 재측정하니 정상입니다. 일시적 측정 오류였습니다." },
    },
  },
  cardiac_aortic: {
    monitor: { stable: "통증 조절 · 혈압 목표 유지", shock: "박리 진행 — 혈압 저하", mismatch: "흉통 악화·하지 맥박 약화 — 목적지 부적합", consciousness: "뇌 관류 저하 — 의식 저하", spike: "측정값 일시적 튐(커프 위치)" },
  },
  cardiac_wall: {
    monitor: { stable: "통증 지속 · 활력 안정", shock: "실제 심장 원인 — 혈압 저하", mismatch: "심전도 변화 동반 흉통 악화 — 목적지 부적합", consciousness: "실신 — 의식 저하", spike: "측정값 일시적 튐" },
  },
  trauma: {
    monitor: { stable: "고정 후 활력 안정", shock: "출혈성 쇼크 진행", mismatch: "복강 내 출혈 악화 — 목적지 부적합", consciousness: "두부 손상 동반 — 의식 저하", spike: "측정값 일시적 튐(차량 진동)" },
    calls: {
      stable: { mechanism: "교통사고 — 다발성 외상, 이송 중 고정 후 안정", symptoms: [],
        transcript: "척추 고정과 부목 고정을 마쳤습니다. 변화 없이 안정적입니다." },
      shock: { mechanism: "교통사고 — 다발성 외상, 이송 중 출혈성 쇼크", symptoms: ["혈압 저하", "창백"],
        transcript: "재측정에서 저혈압·빈맥이 계속되고 피부가 차갑고 창백합니다. 출혈성 쇼크 진행 중입니다." },
      mismatch: { mechanism: "교통사고 — 다발성 외상, 이송 중 복강 내 출혈 악화(응급 수술·수혈 병원 재확인)", symptoms: ["복부 팽만", "혈압 저하"],
        transcript: "배가 점점 부풀고 단단해지며 혈압이 계속 떨어집니다. 복강 내 출혈 악화로 판단되어 응급 수술·수혈 가능 여부 재확인 부탁드립니다. 어려우면 다른 병원을 찾겠습니다." },
      consciousness: { mechanism: "교통사고 — 다발성 외상, 이송 중 두부 손상 동반 의식 저하·동공 부등(뇌출혈 의심)", symptoms: ["의식 저하", "동공 부등"],
        transcript: "머리를 부딪친 환자 의식이 떨어져 부르면 눈만 뜨고 지남력이 없습니다. 한쪽 동공이 커졌고 산소 투여 중입니다." },
      spike: { mechanism: "교통사고 — 다발성 외상, 이송 중 일시적 측정 오류(재측정 정상)", symptoms: [],
        transcript: "차량이 흔들려 맥박이 한 번 높게 찍혔으나 재측정하니 정상입니다. 일시적 측정 오류였습니다." },
    },
  },
  trauma_head: {
    monitor: { stable: "의식 유지 · 활력 안정", shock: "다발 손상 동반 — 혈압 저하", mismatch: "두개내압 상승 징후 — 목적지 부적합", consciousness: "의식 악화 — GCS 하락", spike: "측정값 일시적 튐" },
  },
  trauma_minor: {
    monitor: { stable: "통증 외 특이사항 없음", shock: "숨은 내부 출혈 — 혈압 저하", mismatch: "복통 새로 발생 — 목적지 부적합", consciousness: "지연성 두부 손상 — 의식 저하", spike: "측정값 일시적 튐" },
  },
  abdominal: {
    monitor: { stable: "통증 지속 · 활력 안정", shock: "패혈성 쇼크 진행", mismatch: "복막염 악화 — 목적지 부적합", consciousness: "패혈증 — 의식 저하", spike: "측정값 일시적 튐" },
    calls: {
      stable: { mechanism: "급성 복통 — 복부 압통, 장폐색·충수염 의심, 이송 중 안정", symptoms: [],
        transcript: "복통은 계속되지만 악화는 없습니다. 의식 명료, 변화 없이 안정적입니다." },
      shock: { mechanism: "급성 복통 — 장폐색·충수염 의심, 이송 중 패혈성 쇼크", symptoms: ["혈압 저하", "고열"],
        transcript: "재측정에서 저혈압·빈맥이 계속되고 고열에 피부가 차갑고 축축합니다. 패혈성 쇼크 진행 중입니다." },
      mismatch: { mechanism: "급성 복통 — 장폐색·충수염 의심, 이송 중 복막염 악화(응급 수술 병원 재확인)", symptoms: ["복부 강직", "반발통"],
        transcript: "배가 판자처럼 단단해졌고 반발통이 뚜렷해 복막염으로 판단됩니다. 응급 수술 가능 여부 재확인 부탁드립니다. 어려우면 다른 병원을 찾겠습니다." },
      consciousness: { mechanism: "급성 복통 — 장폐색·충수염 의심, 이송 중 패혈증 의식 저하", symptoms: ["의식 저하", "고열"],
        transcript: "의식이 떨어져 부르면 눈만 뜨고 지남력이 없습니다. 고열이 있고 산소 투여 중입니다. 패혈증으로 의식 저하가 왔습니다." },
      spike: { mechanism: "급성 복통 — 복부 압통, 장폐색·충수염 의심, 이송 중 일시적 측정 오류(재측정 정상)", symptoms: [],
        transcript: "센서가 움직여 맥박이 한 번 높게 찍혔으나 재측정하니 정상입니다. 일시적 측정 오류였습니다." },
    },
  },
  abdominal_gi: {
    monitor: { stable: "출혈 멈춤 · 활력 안정", shock: "재출혈 — 출혈성 쇼크", mismatch: "대량 토혈 — 목적지 부적합", consciousness: "쇼크로 의식 저하", spike: "측정값 일시적 튐" },
  },
  abdominal_mild: {
    monitor: { stable: "증상 호전 · 활력 안정", shock: "탈수 진행 — 혈압 저하", mismatch: "통증 우하복부 국한 — 목적지 부적합", consciousness: "탈수 — 어지러움·의식 저하", spike: "측정값 일시적 튐" },
  },
  mild: {
    monitor: { stable: "부목 고정 후 안정", shock: "숨은 손상 — 혈압 저하·빈맥", mismatch: "통증 급증·발 저림 — 목적지 부적합", consciousness: "실신 — 의식 저하", spike: "측정값 일시적 튐" },
    calls: {
      stable: { mechanism: "보행 중 접질림 — 발목 염좌 의심, 이송 중 안정", symptoms: [],
        transcript: "부목 고정하고 냉찜질 해 통증이 많이 줄었습니다. 변화 없이 안정적입니다." },
      shock: { mechanism: "발목 염좌 — 이송 중 저혈압·빈맥, 숨은 손상 의심", symptoms: ["혈압 저하", "창백"],
        transcript: "재측정에서 저혈압·빈맥이 계속되고 얼굴이 창백합니다. 숨은 손상이 의심됩니다." },
      mismatch: { mechanism: "발목 손상 — 이송 중 통증 급증·발 저림, 신경·혈관 손상 의심(수술 병원 재확인)", symptoms: ["통증 급증", "저림", "말단 허혈"],
        transcript: "발목 통증이 급증하고 발가락이 저리며 발등이 창백하고 맥박이 약합니다. 신경·혈관 손상 의심되어 수술 가능 여부 재확인 부탁드립니다. 어려우면 다른 병원을 찾겠습니다." },
      consciousness: { mechanism: "발목 염좌 — 이송 중 실신·의식 저하", symptoms: ["실신", "의식 저하"],
        transcript: "환자가 갑자기 쓰러졌고 부르면 눈만 뜨고 말이 어눌합니다. 산소 투여 중입니다. 실신 후 의식 저하입니다." },
      spike: { mechanism: "보행 중 접질림 — 발목 염좌 의심, 이송 중 일시적 측정 오류(재측정 정상)", symptoms: [],
        transcript: "센서가 움직여 맥박이 한 번 높게 찍혔으나 재측정하니 정상입니다. 일시적 측정 오류였습니다." },
    },
  },
  mild_fracture: {
    monitor: { stable: "부목 고정 후 안정", shock: "출혈·통증 — 혈압 저하", mismatch: "발 저림·창백(혈관 손상 의심) — 목적지 부적합", consciousness: "실신 — 의식 저하", spike: "측정값 일시적 튐" },
  },
  mild_open: {
    monitor: { stable: "지혈 후 안정", shock: "출혈 지속 — 출혈성 쇼크", mismatch: "말단 허혈 — 목적지 부적합", consciousness: "출혈로 의식 저하", spike: "측정값 일시적 튐" },
  },
};

// ── 시연 대사집(2026-10-06, 팀 Claude Docs "골든링크 시연 대사집" 4종) — ①·②·④ 화면의 대본 칸에 그대로 보인다.
// 대사집 원본은 ④ 이송 중 대본이 문서끼리 뒤바뀌어 있어(흉통 문서에 복통의 ④가 있는 식) 내용에 맞게 제자리로 옮겼다.
// ④의 병원 이름은 이송 확정 병원으로 바꿔 보인다. ① 신고 접수 대본(host·caller)은 2026-10-07 화면에서 뺐다(데이터만 남김).
// 버튼으로 부여하는 정해진 상황은 이 대본을 압축한 문장이다(PATIENT_TEMPLATES.transcript, TRANSPORT 신고대로 4종 followups).
type TransportScript = { label: string; note?: string; lines: string[] };
type Script = {
  host: string[];
  caller: string;
  callerShort: string;
  scene: Record<string, string>;
  transport: Record<MonitorKey, TransportScript>;
};

const SCRIPTS: Record<string, Script> = {
  cardiac: {
    host: [
      "먼저 사고 장소를 골라 주세요. 서울시청 앞, 이태원역, 강남역, 여의도공원 중에서 고르시면 됩니다.",
      "이번에는 서울시청 앞에서 흉통 환자가 발생한 상황으로 시작하겠습니다. 신고 전화를 직접 해 보시겠어요?",
    ],
    caller: "서울시청 앞입니다. 50대, 60대쯤 되어 보이는 남자분이 갑자기 가슴을 움켜쥐고 주저앉았어요. 가슴이 너무 아프다고 하고 숨쉬기도 힘들어합니다. 식은땀도 흘리고 있어요. 빨리 와주세요.",
    callerShort: "서울시청 앞입니다. 50~60대 남자분이 가슴이 아프다며 쓰러지듯 주저앉았어요. 숨도 못 쉬겠다고 합니다. 빨리 와주세요.",
    scene: {
      cardiac: "62세 남성입니다. 30분 전부터 가슴을 쥐어짜는 흉통이 있고 숨이 찹니다. 왼팔로 뻗치고 식은땀을 흘립니다. 혈압 100에 60, 맥박 110, 산소포화도 93퍼센트. 심근경색 의심입니다.",
      cardiac_aortic: "58세 남성입니다. 갑자기 가슴이 찢어지는 듯한 통증이 시작됐고 등으로 뻗칩니다. 양팔 혈압을 재보니 오른팔 150에 90, 왼팔 110에 70으로 차이가 큽니다. 맥박 105, 의식은 명료합니다. 대동맥 박리 의심입니다.",
      cardiac_wall: "45세 남성입니다. 가슴 왼쪽이 아픈데 손으로 누르면 더 아프고, 숨 쉴 때와 몸을 비틀 때 아픕니다. 어제 무거운 짐을 옮겼다고 합니다. 혈압 125에 80, 맥박 78, 산소포화도 98퍼센트이고 심전도 이상은 없습니다. 흉벽 통증 소견입니다.",
    },
    transport: {
      stable: { label: "통증 조절, 활력 안정", lines: ["흉통은 처음보다 줄었습니다. 니트로글리세린 투여 후 통증 점수 3점입니다. 혈압 118에 74, 맥박 82, 산소포화도 98퍼센트, 의식 명료합니다. 변화 없이 안정적입니다."] },
      shock: { label: "심인성 쇼크 진행", note: "1~2분 간격으로 두 번 읽기", lines: [
        "1차 재측정했습니다. 혈압 86에 54로 떨어졌고 맥박 120입니다. 식은땀이 심하고 피부가 차갑습니다.",
        "2차 다시 재측정했습니다. 혈압 80에 50, 맥박 126으로 계속 저혈압과 빈맥입니다. 심인성 쇼크가 진행 중입니다.",
      ] },
      mismatch: { label: "흉통 악화, 부정맥", note: "병원 변경 필요", lines: ["흉통이 다시 심해졌고 심전도에서 심한 부정맥이 보입니다. 맥박이 불규칙하고 빠릅니다. 심혈관 중재술이 가능한지 다시 확인 부탁드립니다. 어려우시면 다른 병원을 알아보겠습니다."] },
      consciousness: { label: "심정지 전조, 의식 저하", lines: ["환자 의식이 떨어졌습니다. 부르면 눈만 뜨고 말이 어눌합니다. 맥박이 약하고 불규칙하며 혈압 78에 48, 호흡 28회, 산소포화도 88퍼센트로 산소 투여 중입니다. 심정지 전조 소견입니다."] },
      spike: { label: "측정값 일시적 튐 (전극 흔들림)", note: "이어서 두 번 읽기", lines: [
        "1차 방금 심전도 모니터에 심한 부정맥이 한 번 찍혔습니다. 전극이 흔들려서 그런 것 같습니다.",
        "2차 전극을 다시 붙이고 측정했더니 맥박 84, 산소포화도 98퍼센트, 혈압 120에 76으로 정상입니다. 환자는 편안하고 의식도 명료합니다. 일시적인 측정 오류였습니다.",
      ] },
    },
  },
  trauma: {
    host: [
      "먼저 사고 장소를 골라 주세요. 서울시청 앞, 이태원역, 강남역, 여의도공원 중에서 고르시면 됩니다.",
      "이번에는 서울시청 앞에서 교통사고가 난 상황으로 시작하겠습니다. 신고 전화를 직접 해 보시겠어요?",
    ],
    caller: "서울시청 앞 도로입니다. 차 두 대가 크게 부딪혔어요. 30대, 40대쯤 되어 보이는 남자분이 도로에 쓰러져 있는데 가슴이랑 배를 부여잡고 있고 정신이 오락가락해요. 빨리 와주세요.",
    callerShort: "서울시청 앞 도로에서 교통사고예요. 30~40대 남자분이 쓰러져 있고 가슴과 배가 아프다는데 정신이 흐릿해요. 빨리 와주세요.",
    scene: {
      trauma: "35세 남성입니다. 승용차와 충돌한 사고로 흉부와 복부를 세게 부딪혔고 의식이 혼미합니다. 부르면 눈은 뜨지만 대답이 느립니다. 혈압 90에 55, 맥박 125, 호흡 28회, 산소포화도 91퍼센트. 복부가 단단하고 누르면 심하게 아파합니다. 다발성 외상 의심입니다.",
      trauma_head: "41세 남성입니다. 차량 충돌 때 머리를 부딪혔고 의식이 떨어졌습니다. 부르면 겨우 눈을 뜨고 구토를 두 번 했습니다. 뒤통수에 열상이 있고 출혈은 압박으로 조절됩니다. 혈압 150에 95, 맥박 58, 산소포화도 96퍼센트. 두부 손상 의심입니다.",
      trauma_minor: "29세 남성입니다. 접촉 사고였고 안전벨트를 착용했습니다. 목과 어깨가 아프다고 하고 팔에 찰과상이 있습니다. 혼자 걸어서 구급차에 탔습니다. 혈압 120에 78, 맥박 82, 산소포화도 99퍼센트, 의식 명료합니다. 경상입니다.",
    },
    transport: {
      stable: { label: "고정 후 활력 안정", lines: ["척추 고정과 부목 고정을 마쳤습니다. 혈압 122에 78, 맥박 90, 산소포화도 98퍼센트, 의식 명료합니다. 변화 없이 안정적입니다."] },
      shock: { label: "출혈성 쇼크 진행", note: "1~2분 간격으로 두 번 읽기", lines: [
        "1차 재측정했습니다. 혈압 88에 52로 떨어졌고 맥박 130입니다. 피부가 차갑고 창백합니다.",
        "2차 다시 재측정했습니다. 혈압 82에 48, 맥박 138로 계속 저혈압과 빈맥입니다. 출혈성 쇼크가 진행 중입니다.",
      ] },
      mismatch: { label: "복강 내 출혈 악화", note: "병원 변경 필요", lines: ["배가 점점 부풀어 오르고 단단해졌고, 혈압도 계속 떨어지고 있습니다. 복강 내 출혈이 악화된 것으로 판단됩니다. 응급 수술과 수혈 준비가 가능한지 다시 확인 부탁드립니다. 어려우시면 다른 병원을 알아보겠습니다."] },
      consciousness: { label: "두부 손상 동반, 의식 저하", lines: ["머리를 부딪친 환자의 의식이 떨어졌습니다. 부르면 눈만 뜨고 말이 어눌하며 지남력이 없습니다. 한쪽 동공이 커져 있습니다. 호흡 26회, 산소포화도 90퍼센트로 산소 투여 중이고, 혈압 85에 50, 맥박 130입니다. 두부 손상 동반 의식 저하입니다."] },
      spike: { label: "측정값 일시적 튐 (차량 진동)", note: "이어서 두 번 읽기", lines: [
        "1차 방금 맥박이 170으로 한 번 찍혔습니다. 차량이 심하게 흔들려서 센서가 흔들린 것 같습니다.",
        "2차 다시 측정했더니 맥박 88, 산소포화도 98퍼센트, 혈압 122에 78로 정상입니다. 환자는 안정적이고 의식도 명료합니다. 일시적인 측정 오류였습니다.",
      ] },
    },
  },
  abdominal: {
    host: [
      "먼저 사고 장소를 골라 주세요. 서울시청 앞, 이태원역, 강남역, 여의도공원 중에서 고르시면 됩니다.",
      "이번에는 서울시청 앞에서 복통 환자가 발생한 상황으로 시작하겠습니다. 신고 전화를 직접 해 보시겠어요?",
    ],
    caller: "서울시청 앞입니다. 40대, 50대쯤 되어 보이는 여자분이 배를 움켜쥐고 쪼그려 앉아 계세요. 배가 계속 아프다고 하고 구토도 했어요. 빨리 와주세요.",
    callerShort: "서울시청 앞입니다. 40~50대 여자분이 배가 너무 아프다며 주저앉았어요. 구토도 했어요. 빨리 와주세요.",
    scene: {
      abdominal: "48세 여성입니다. 어제 저녁부터 배가 계속 아프고 구토를 두 번 했습니다. 배 오른쪽 아래를 누르면 심하게 아파하고, 손을 떼면 더 아파합니다. 혈압 125에 80, 맥박 98, 체온 37.8도, 산소포화도 98퍼센트, 의식 명료합니다. 복부 압통 소견입니다.",
      abdominal_gi: "67세 여성입니다. 오늘 아침 피를 토했고 어제부터 까만 변을 봤습니다. 어지러워하고 얼굴이 창백합니다. 혈압 90에 55, 맥박 118, 산소포화도 96퍼센트입니다. 위장관 출혈 의심입니다.",
      abdominal_mild: "31세 여성입니다. 어제 저녁 외식 후부터 복통과 설사를 했습니다. 배 전체가 가볍게 아프고, 누르면 약간 불편한 정도입니다. 혈압 118에 74, 맥박 84, 체온 37.2도, 산소포화도 99퍼센트, 의식 명료합니다. 급성 위장염 소견입니다.",
    },
    transport: {
      stable: { label: "통증 지속, 활력 안정", lines: ["복통은 계속되고 있지만 악화는 없습니다. 혈압 125에 80, 맥박 88, 산소포화도 98퍼센트, 의식 명료합니다. 변화 없이 안정적입니다."] },
      shock: { label: "패혈성 쇼크 진행", note: "1~2분 간격으로 두 번 읽기", lines: [
        "1차 재측정했습니다. 혈압 82에 50으로 떨어졌고 맥박 128, 체온 39.2도입니다. 피부가 차갑고 축축합니다.",
        "2차 다시 재측정했습니다. 혈압 80에 48, 맥박 132로 여전히 저혈압과 빈맥입니다. 패혈성 쇼크가 진행 중입니다.",
      ] },
      mismatch: { label: "복막염 악화", note: "병원 변경 필요", lines: ["복부 상태가 악화됐습니다. 배가 판자처럼 단단해졌고 살짝 눌렀다 떼도 심하게 아파합니다. 반발통이 뚜렷해서 복막염으로 판단됩니다. 응급 수술이 필요해 보여, 수술 가능 여부를 다시 확인 부탁드립니다. 어려우시면 다른 병원을 알아보겠습니다."] },
      consciousness: { label: "패혈증, 의식 저하", lines: ["환자 의식이 떨어졌습니다. 부르면 눈만 뜨고 말이 어눌하며 지남력이 없습니다. 호흡 28회, 산소포화도 88퍼센트로 산소 투여 중입니다. 혈압 85에 55, 맥박 135, 체온 39.5도입니다. 패혈증으로 의식 저하가 왔습니다."] },
      spike: { label: "측정값 일시적 튐", note: "이어서 두 번 읽기", lines: [
        "1차 방금 맥박이 160으로 한 번 찍혔습니다. 손가락 센서가 움직여서 그런 것 같습니다.",
        "2차 다시 측정했더니 맥박 86, 산소포화도 98퍼센트, 혈압 124에 78로 정상입니다. 환자는 편안하고 의식도 명료합니다. 일시적인 측정 오류였습니다.",
      ] },
    },
  },
  mild: {
    host: [
      "먼저 사고 장소를 골라 주세요. 서울시청 앞, 이태원역, 강남역, 여의도공원 중에서 고르시면 됩니다.",
      "이번에는 서울시청 앞에서 발목을 다친 환자가 발생한 상황으로 시작하겠습니다. 신고 전화를 직접 해 보시겠어요?",
    ],
    caller: "서울시청 앞입니다. 30대, 40대쯤 되어 보이는 여자분이 길에서 발목을 접질려서 못 걷고 있어요. 발목이 아프다고 하고 점점 붓고 있어요. 와주세요.",
    callerShort: "서울시청 앞입니다. 여자분이 발목을 삐끗해서 걷기 힘들어해요. 와주세요.",
    scene: {
      mild: "24세 여성입니다. 보도 턱에서 발목을 접질렸습니다. 발목 바깥쪽이 붓고 아프지만 체중을 실을 수 있고 조금 걸을 수 있습니다. 피부 손상은 없습니다. 혈압 118에 72, 맥박 80, 산소포화도 99퍼센트, 의식 명료합니다. 발목 염좌 소견입니다.",
      mild_fracture: "52세 여성입니다. 계단에서 발을 헛디뎌 발목이 꺾였습니다. 발목이 눈에 띄게 변형되고 심하게 부었으며 체중을 전혀 실을 수 없습니다. 피부는 닫혀 있고 발가락 감각은 있습니다. 혈압 130에 82, 맥박 96, 산소포화도 98퍼센트, 의식 명료합니다. 발목 골절 의심입니다.",
      mild_open: "38세 여성입니다. 높은 곳에서 떨어져 발목을 크게 다쳤습니다. 발목 뼈가 피부 밖으로 노출되어 있고 출혈이 있어서 거즈로 압박 중입니다. 발등 맥박은 약하게 만져지고 발가락이 차갑습니다. 혈압 105에 65, 맥박 112, 산소포화도 97퍼센트입니다. 개방성 발목 골절입니다.",
    },
    transport: {
      stable: { label: "부목 고정 후 안정", lines: ["발목에 부목 고정하고 냉찜질 했습니다. 통증은 많이 줄었습니다. 혈압 122에 76, 맥박 78, 산소포화도 99퍼센트, 의식 명료합니다. 변화 없이 안정적입니다."] },
      shock: { label: "숨은 손상, 혈압 저하와 빈맥", note: "1~2분 간격으로 두 번 읽기", lines: [
        "1차 재측정했습니다. 혈압 92에 58로 떨어졌고 맥박 118입니다. 환자는 괜찮다고 하는데 얼굴이 창백합니다.",
        "2차 다시 재측정했습니다. 혈압 88에 54, 맥박 124로 계속 저혈압과 빈맥입니다. 숨은 손상이 의심됩니다.",
      ] },
      mismatch: { label: "통증 급증, 발 저림", note: "병원 변경 필요", lines: ["발목 통증이 갑자기 심해졌습니다. 발가락이 저리고 감각이 둔해졌고, 발등이 창백하며 맥박이 약하게 만져집니다. 신경과 혈관 손상이 의심돼서 수술 가능 여부를 다시 확인 부탁드립니다. 어려우시면 다른 병원을 알아보겠습니다."] },
      consciousness: { label: "실신, 의식 저하", lines: ["환자가 갑자기 쓰러졌습니다. 부르면 눈만 뜨고 말이 어눌합니다. 혈압 85에 50, 맥박 130, 호흡 26회, 산소포화도 90퍼센트로 산소 투여 중입니다. 실신 후 의식 저하 상태입니다."] },
      spike: { label: "측정값 일시적 튐", note: "이어서 두 번 읽기", lines: [
        "1차 방금 맥박이 170으로 한 번 찍혔습니다. 손가락 센서가 움직여서 그런 것 같습니다.",
        "2차 다시 측정했더니 맥박 80, 산소포화도 99퍼센트, 혈압 120에 76으로 정상입니다. 환자는 편안하고 의식도 명료합니다. 일시적인 측정 오류였습니다.",
      ] },
    },
  },
};

const templateOf = (key: string | null | undefined): Template | null =>
  PATIENT_TEMPLATES.find((t) => t.key === key) ?? null;
// ① 신고 접수 증상(4종) — 신고대로 현장 상황과 같은 카드
const REPORT_TEMPLATES = PATIENT_TEMPLATES.filter((t) => t.key === t.report);
// ② 현장 확인 선택지 — 그 신고에 딸린 현장 상황(신고대로가 맨 앞). 신고를 모르면 신고 증상 4종
const sceneOptions = (reportKey: string | null | undefined): Template[] => {
  const report = templateOf(reportKey)?.report;
  return report ? PATIENT_TEMPLATES.filter((t) => t.report === report) : REPORT_TEMPLATES;
};

// 대량사고 사상자 수 입력의 처음 값(시연 초기화 때도 이 값으로 되돌린다)
const MCI_DEFAULT_COUNTS = { high: 2, medium: 3, low: 4 };

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
  const { state, connectionMode, sendAction, sendCallSignal, sendSimCommand, sendTransportVitals, sendZoneExpand, sendMciAllocate, sendMciPreview, sendDemoMode, sendSceneInputMode } =
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
  // 개발 모드(2026-10-07) — 켜면 ② 현장 확인·④ 이송 중에 "정해진 상황 선택"(가상 환자·가상 상태 변화)이 보인다.
  // 끄면(기본) 음성(대원 휴대폰 통화)만 남고 정해진 상황 버튼·부여 상황이 화면에서 사라진다. hub에도 음성으로 알린다.
  const [devMode, setDevMode] = useState(false);
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
  const locked = simOn && sim?.paused === true && sim.pauseReason !== "call";
  const pauseToast = usePauseToast(state.actionRefused);
  const g = (fn: () => void) => pauseToast.guard(locked, fn);
  // 불가 사유 선택 모달(2026-10-05) — 병원 대시보드와 같은 4축 사유. 이송 중 수용 철회·도착 후 수용 불가도 같은 모달
  type RejectAction = "hospital_reject" | "transport_withdraw" | "arrival_refused";
  // ④ 목적지 병원과의 추가 통화(2026-10-05) — 음성(대원 휴대폰 전화 앱) / 정해진 상황(가상 상태 변화)
  const [followupMode, setFollowupMode] = useState<"voice" | "template">("template");
  const [followupSent, setFollowupSent] = useState<Record<string, string[]>>({});
  // caseIds: 대량사고 병원 행은 그 병원이 후보인 사건 여러 건에 한 번에 응답한다
  const [rejectTarget, setRejectTarget] = useState<{ caseIds: string[]; hospitalId: string; name: string; action: RejectAction } | null>(null);
  function sendReject(reason: RejectionReason) {
    if (!rejectTarget) return;
    const { caseIds: targetCases, hospitalId, name, action } = rejectTarget;
    setRejectTarget(null);
    if (locked && !mciOn) {
      pauseToast.notify();
      return;
    }
    for (const targetCase of targetCases) {
      sendAction({ caseId: targetCase, action, hospital_id: hospitalId, actor: "hospital", timestamp: now(), reason });
    }
    const label = rejectionReasonLabel(reason) ?? "사유 없음";
    if (action === "arrival_refused") {
      setManualArrival(false);
      note(`도착 후 수용 불가(${label}) — 재선택 대기(병원 응답 화면으로)`);
    } else if (action === "transport_withdraw") {
      note(`${name} 이송 중 수용 철회(${label}) — 구급차는 다른 승인 병원으로 재선택`);
    } else {
      note(`${name} 수용 불가 · ${label}${targetCases.length > 1 ? ` (사상자 ${targetCases.length}명)` : ""}`);
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

  // ② 현장 확인 방식을 hub에 알린다(2026-10-06) — "정해진 상황 선택"이면 그 구급차 휴대폰 앱의 전화 버튼이 막히고 hub도
  // 현장 통화 시작을 거부한다. 출동 중부터 알려, 현장에 도착한 휴대폰이 처음부터 맞는 상태로 뜨게 한다.
  const sceneInput: "voice" | "template" = devMode ? inputMode : "voice";
  const sceneMode: "voice" | "template" = myCall ? "voice" : sceneInput;
  useEffect(() => {
    if (!caseId || !apid || (screen !== "enroute" && screen !== "report")) return;
    sendSceneInputMode(caseId, apid, sceneMode);
  }, [caseId, apid, screen, sceneMode, sendSceneInputMode, connectionMode]);

  // ④ 이송 중 통화 방식도 같은 방식으로 알린다(2026-10-06) — "정해진 상황 선택"이면 휴대폰 앱의 [목적지 병원과 통화]가
  // 막히고 hub도 이송 중 통화를 거부한다. 휴대폰이 이미 통화 중이면 음성으로 둔다(아래 ④ 화면과 같은 판정).
  const followupCalling = !!caseId && state.callStatus[caseId]?.state === "calling" && !!state.callStatus[caseId]?.followup;
  const transportInput: "voice" | "template" = devMode ? followupMode : "voice";
  const transportMode: "voice" | "template" = followupCalling ? "voice" : transportInput;
  useEffect(() => {
    if (!caseId || !apid || screen !== "transport") return;
    sendSceneInputMode(caseId, apid, transportMode, "transport");
  }, [caseId, apid, screen, transportMode, sendSceneInputMode, connectionMode]);

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

  // 이송 중 목적지 병원과 2차 통화(정해진 상황) — 2차 통화 요약을 보내면 hub가 환자 정보에 덧붙인다(병원 목록·확정은 그대로).
  // 상황 버튼이 활력징후 시나리오를 다 재생한 뒤 부른다(playScenario의 onDone). 활력징후는 그 시나리오의 마지막 측정값.
  async function handleFollowup(key: MonitorKey) {
    if (!caseId) return;
    const base = transportBase;
    const label = transport.monitor[key];
    const call: FollowupText = transport.calls?.[key] ?? {
      mechanism: `${base.summary.mechanism} — 이송 중 ${label}`, symptoms: [], transcript: `이송 중 상태 보고드립니다. ${label}.`,
    };
    const scenario = SCENARIOS.find((sc) => sc.key === key);
    const last = scenario?.steps[scenario.steps.length - 1];
    const worse = key === "shock" || key === "mismatch" || key === "consciousness";
    setSending(true);
    try {
      const response = await fetch("/api/demo/voice", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          caseId,
          transcript: { raw_text: call.transcript, filtered_text: call.transcript },
          summary: {
            ...base.summary,
            mechanism: call.mechanism,
            severity_tag: worse ? "high" : base.summary.severity_tag,
            ktas_level: worse ? (key === "consciousness" ? 1 : Math.min(2, base.summary.ktas_level)) : base.summary.ktas_level,
            consciousness: last?.avpu ?? base.summary.consciousness,
            symptoms: [...base.summary.symptoms, ...call.symptoms],
            vitals: last ? [{ sequence: 2, sbp: last.sbp, hr: last.hr, rr: last.rr, spo2: last.spo2, ...(last.bt != null ? { bt: last.bt } : {}) }] : base.summary.vitals,
          },
          source: "ai",
          model_used: { stt: "scenario-template", llm: "scenario-template" },
        }),
      });
      if (response.ok) {
        setFollowupSent((prev) => ({ ...prev, [caseId]: [...(prev[caseId] ?? []), label] }));
        note(`이송 중 추가 통화(정해진 상황) — ${label} · ${confirmedHospital?.name ?? "목적지 병원"}에 덧붙여 전달`);
      } else {
        note(`추가 통화 전송 실패 (${response.status})`);
      }
    } finally {
      setSending(false);
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
  const mciQueueRef = useRef<string[]>([]);          // 대기 사상자(템플릿 키, 중증 우선 정렬)
  const mciSpotRef = useRef<Spot>(null);             // 이 대량사고의 현장(재출동도 같은 곳으로)
  const mciDispatchedRef = useRef(0);                // 현장 마커 간격용 누적 카운터
  const pendingDispatchRef = useRef<Record<string, string>>({}); // apid -> 방금 보낸 caseId(중복 출동 방지)
  const [mciOn, setMciOn] = useState(false);
  const [mciRemaining, setMciRemaining] = useState(0);
  const [mciCounts, setMciCounts] = useState(MCI_DEFAULT_COUNTS);
  // 사상자별 사건(2026-10-05, 대량사고 현황표) — 화면에 그리려고 ref와 별도로 상태로도 든다
  const [mciCasualties, setMciCasualties] = useState<MciCasualty[]>([]);
  const [mciTotal, setMciTotal] = useState(0);
  // ② 사상자마다 고른 현장 유형(caseId -> 템플릿 키) · ⑤ 사상자마다 기록한 도착 결과(병원 역할, 재분배·종료 때 hub로) ·
  // 재분배 중인 사상자(⑤의 수용 불가만 ③으로 되돌린다 — 이미 수용된 환자는 다시 처리하지 않는다)
  const [mciChoice, setMciChoice] = useState<Record<string, string>>({});
  const [mciDecisions, setMciDecisions] = useState<Record<string, { result: "accepted" | "refused" | "sent"; reason?: RejectionReason }>>({});
  const [mciRedo, setMciRedo] = useState<string[] | null>(null);
  const [mciRefuseTarget, setMciRefuseTarget] = useState<{ caseId: string; name: string } | null>(null);
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
    setMciChoice({});
    setMciDecisions({});
    setMciRedo(null);
    setMciOn(true);
    const firstWave = Math.min(idle.length, total);
    idle.slice(0, firstWave).forEach((ambulance) => mciDispatchTo(ambulance.apid));
    note(
      `대량사고 접수 — ${spot.label} · 사상자 ${total}명 · 1차 출동 ${firstWave}대(중증 우선), ` +
        `대기 ${mciQueueRef.current.length}명(복귀하는 대로 자동 재출동)`,
    );
  }

  // 대량사고 자원 재분배: 어떤 구급대든 대기(복귀)로 돌아오면 대기열의 다음 사상자에게 재출동한다.
  // 현장 확인(신고)은 자동으로 보내지 않는다(2026-10-05) — ② 현장 확인에서 사상자마다 유형을 고른 뒤 한 번에 보낸다(시안).
  useEffect(() => {
    for (const unit of Object.values(state.ambulanceSim)) {
      // 보낸 출동이 반영됐으면 중복 방지 표시 해제
      if (pendingDispatchRef.current[unit.apid] && unit.caseId === pendingDispatchRef.current[unit.apid]) {
        delete pendingDispatchRef.current[unit.apid];
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

  // [시연 초기화] — hub에 sim_reset을 보내고 콘솔 로컬 상태도 처음 연 화면 그대로 되돌린다(2026-10-06: 예전엔 사건·대량사고
  // 진행만 비우고 장소 검색어·결과, 고른 지점·신고 증상, 입력 방식, 추가 통화 선택, 대량사고 입력값 등이 남았다)
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
    setMciChoice({});
    setMciDecisions({});
    setMciRedo(null);
    setLocalCaseIds({});
    setReported({});
    setManualArrival(false);
    setDispatchInfo(null);
    setVerifyKey(null);
    // ① 신고 접수 입력
    setSelectedApid(null);
    setSpot(PRESET_LOCATIONS[0]);
    setReportedKey(null);
    setQuery("");
    setSearchResults([]);
    setSearchError(null);
    // ② 현장 확인 · ④ 이송 중
    setInputMode("template");
    setTemplateCases({});
    setSending(false);
    setFollowupMode("template");
    setFollowupSent({});
    setRejectTarget(null);
    setTripStart({});
    // 대량사고 입력·현장
    mciSpotRef.current = null;
    mciDispatchedRef.current = 0;
    setMciCounts(MCI_DEFAULT_COUNTS);
    setMciRefuseTarget(null);
    setMciSpotLabel("");
    setCaseHospital({});
    if (sendSimCommand("sim_reset", "*", "")) note("시연 초기화 — 모든 사건 종료, 전 구급대 기지 복귀");
  }

  function stopScenario(targetCaseId: string) {
    const timer = timersRef.current[targetCaseId];
    if (timer) clearInterval(timer);
    delete timersRef.current[targetCaseId];
    setPlaying((prev) => ({ ...prev, [targetCaseId]: null }));
  }

  // onDone: 마지막 측정까지 다 보낸 뒤 한 번(중간에 [정지]로 멈추면 부르지 않는다)
  function playScenario(key: string, onDone?: () => void) {
    const scenario = SCENARIOS.find((s) => s.key === key);
    if (!scenario || !caseId || !apid) return;
    stopScenario(caseId);
    setPlaying((prev) => ({ ...prev, [caseId]: key }));
    let stepIndex = 0;
    const send = () => {
      const vitals = scenario.steps[stepIndex];
      if (!vitals) {
        stopScenario(caseId);
        onDone?.();
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
      : unitPhase === "on_scene" ? (monitorCase || reported[casualty.caseId] ? 2 : 1)
      : unitPhase === "transporting" ? (confirmed ? 3 : 2)
      : unitPhase === "at_hospital" ? 4
      : unitPhase === "rerouting" ? 2
      : 5;
    return { ...casualty, template, unit: live ? unit : null, monitorCase, confirmed, stage, hospitalName: confirmed?.name ?? caseHospital[casualty.caseId] ?? null };
  });
  // 대량사고 화면 단계(시안의 대량 ①~⑤) — 아직 도착 결과를 기록하지 않은 사상자 중 가장 늦은 단계를 보여 준다
  const mciStage: MciStage = (() => {
    const open = casualtyView.filter((c) => !mciDecisions[c.caseId] && c.stage < 5);
    if (casualtyView.length === 0 || open.some((c) => c.stage === 0)) return "dispatch";
    if (open.some((c) => c.stage === 1)) return "verify";
    if (open.some((c) => c.stage === 2)) return "hospital";
    if (open.some((c) => c.stage === 3)) return "transit";
    return "arrival";
  })();
  const mciRedoActive = mciRedo && casualtyView.some((c) => mciRedo.includes(c.caseId) && c.stage === 2) ? mciRedo : null;
  const mciStep = { dispatch: 1, verify: 2, hospital: 3, transit: 4, arrival: 5 }[mciStage];
  const step = mciOn ? mciStep : SCREEN_STEP[screen];

  // ── 상황 요약 띠 ──
  const reportedTemplate = templateOf(dispatchInfo?.reportedKey ?? reportedKey);
  const caseTemplate = caseId && templateCases[caseId] ? PATIENT_TEMPLATES.find((t) => t.label === templateCases[caseId]) ?? null : null;
  // 이송 중 상황은 현장 확인한 환자(카드) 기준 — 음성으로 들어온 사건은 신고 증상의 "신고대로" 상황으로
  const transportBase: Template = caseTemplate ?? reportedTemplate ?? PATIENT_TEMPLATES[0];
  const transport = TRANSPORT[transportBase.key];
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
          value: mciStep >= 3
            ? `중증 ${casualtyView.filter((c) => c.template.severity === "중증").length} · 중등증 ${casualtyView.filter((c) => c.template.severity === "중등증").length} · 경증 ${casualtyView.filter((c) => c.template.severity === "경증").length}`
            : mciStep === 2 ? "확인 중…" : "대기",
          muted: mciStep < 3,
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

  const verifyTemplate = templateOf(verifyKey ?? reportedTemplate?.key ?? "cardiac")!;
  const voiceSelected = myCall != null || sceneInput === "voice";

  return (
    // 화면 전체는 끌리지 않게 고정(2026-10-05 요청) — 상단바·단계·상황 요약은 그대로 두고, 넘치는 내용은 단계 카드 안에서만
    // 스크롤된다(③ 병원 응답은 병원 목록만). 페이지 스크롤·당겨서 새로고침·글자 끌기 선택을 막는다.
    <div className="ctl-root" style={{ boxSizing: "border-box", background: C.bg, color: C.ink, padding: "10px 16px 8px", display: "flex", justifyContent: "center", fontVariantNumeric: "tabular-nums" }}>
      <div style={{ width: "100%", maxWidth: 1500, height: "100%", minHeight: 0, display: "flex", flexDirection: "column", gap: 8 }}>
        <style>{CONSOLE_CSS}</style>
        {pauseToast.node}
        <DemoVideoOverlay src="/demo-videos/console.mp4" />
        {mciRefuseTarget && (
          <RejectReasonModal
            title={`${mciRefuseTarget.name} — 도착 후 수용 불가 사유`}
            note="기록만 해 둡니다 — [수용 불가 N명 재분배]를 누르면 그 병원을 빼고 ③에서 다시 분배합니다."
            onPick={(reason) => {
              setMciDecisions((prev) => ({ ...prev, [mciRefuseTarget.caseId]: { result: "refused", reason } }));
              setMciRefuseTarget(null);
            }}
            onClose={() => setMciRefuseTarget(null)}
          />
        )}
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
            {/* 시연 영상 모드(2026-10-06) — 연결된 모든 화면(관제 지도·병원·콘솔·구급차)이 각자 영상으로. 영상 위 [시연 모드]로 돌아온다 */}
            <button type="button" style={headerButton} onClick={() => sendDemoMode("video") || note("hub와 연결이 끊겨 영상 모드로 바꾸지 못했습니다")}>
              영상 모드
            </button>
            <button
              type="button"
              aria-pressed={devMode}
              title="켜면 ② 현장 확인·④ 이송 중에 '정해진 상황 선택'이 보입니다"
              onClick={() => setDevMode((v) => !v)}
              style={devMode ? { ...headerButton, background: C.orangeSoft, border: `1px solid ${C.orangeInk}`, color: C.orangeInk } : headerButton}
            >
              {devMode ? "개발 모드 켜짐" : "개발 모드"}
            </button>
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
            <MciWizard
              stage={mciStage}
              plan={state.mciPlan?.plan ?? null}
              onPreview={sendMciPreview}
              total={mciTotal}
              remaining={mciRemaining}
              spotLabel={mciSpotLabel}
              casualties={casualtyView}
              choice={mciChoice}
              decisions={mciDecisions}
              redoIds={mciRedoActive}
              hospitalInfo={hospitalInfo}
              ambulanceName={ambulanceName}
              tripProgress={tripProgress}
              sending={sending}
              lastAllocation={
                state.mciAllocated
                  ? {
                      confirmed: state.mciAllocated.results.filter((r) => r.reason === "confirmed").length,
                      skipped: state.mciAllocated.results.filter((r) => r.reason === "no_approved_hospital").length,
                    }
                  : null
              }
              onChoose={(id, key) => setMciChoice((prev) => ({ ...prev, [id]: key }))}
              onVerify={async (batch) => {
                setSending(true);
                try {
                  const keys = Object.fromEntries(batch.map((c) => [c.caseId, mciChoice[c.caseId] ?? c.templateKey]));
                  setMciCasualties((prev) => prev.map((c) => (keys[c.caseId] ? { ...c, templateKey: keys[c.caseId] } : c)));
                  await Promise.all(batch.map((c) => handleReportFor(c.apid, c.caseId, keys[c.caseId])));
                  note(`현장 확인 — 사상자 ${batch.length}명(${sevSummary(batch.map((c) => ({ ...c, template: templateOf(keys[c.caseId])! })))}) 인근 병원 동시 전달`);
                } finally {
                  setSending(false);
                }
              }}
              onHospitalApprove={(hospitalId, ids) => {
                ids.forEach((id) => sendAction({ caseId: id, action: "hospital_approve", hospital_id: hospitalId, actor: "hospital", timestamp: now() }));
                note(`병원 응답(병원 역할) — ${hospitalInfo.get(hospitalId)?.name ?? hospitalId} 사상자 ${ids.length}명 수용 승인`);
              }}
              onHospitalReject={(hospitalId, name, ids) => setRejectTarget({ caseIds: ids, hospitalId, name, action: "hospital_reject" })}
              onBulk={(action, pairs) => {
                pairs.forEach((p) => sendAction({ caseId: p.caseId, action, hospital_id: p.hospitalId, actor: "hospital", timestamp: now() }));
                const n = new Set(pairs.map((p) => p.hospitalId)).size;
                note(action === "hospital_approve" ? `병원 응답(병원 역할) — 미응답 병원 ${n}곳 모두 승인` : `병원 응답(병원 역할) — 미응답 병원 ${n}곳 전부 불가(사유 없음)`);
              }}
              onAllocate={(ids) => {
                if (sendMciAllocate(ids)) {
                  setMciRedo(null);
                  note(`분배 확정(상황실·구급대) — 사상자 ${ids.length}명을 중증부터 hub 순위로 배정`);
                }
              }}
              onFastAll={(phase) => {
                let n = 0;
                for (const c of casualtyView) {
                  if (c.unit?.phase === phase && !(c.unit.paused && c.unit.pauseReason !== "call")) {
                    sendSimCommand("sim_fast_forward", c.apid, c.caseId);
                    n += 1;
                  }
                }
                note(`대량사고 — ${phase === "dispatching" ? "출동" : "이송"} 중인 구급대 ${n}대 빨리감기`);
              }}
              onDecide={(c, result) => {
                if (result === "undo") {
                  setMciDecisions((prev) => {
                    const next = { ...prev };
                    delete next[c.caseId];
                    return next;
                  });
                } else if (result === "refused") {
                  setMciRefuseTarget({ caseId: c.caseId, name: c.hospitalName ?? "병원" });
                } else {
                  setMciDecisions((prev) => ({ ...prev, [c.caseId]: { result: "accepted" } }));
                }
              }}
              onAcceptAllLocal={(list) =>
                setMciDecisions((prev) => ({ ...prev, ...Object.fromEntries(list.map((c) => [c.caseId, { result: "accepted" as const }])) }))
              }
              onRedistribute={() => {
                // 수용 완료는 hub에 기록(사건 종료), 수용 불가는 도착 후 수용 불가로 보내 그 병원을 빼고 ③에서 다시 분배
                const refusedIds: string[] = [];
                for (const c of casualtyView) {
                  const d = mciDecisions[c.caseId];
                  if (!d || !c.confirmed || d.result === "sent") continue;
                  const action = d.result === "accepted" ? "arrival_accepted" : "arrival_refused";
                  sendAction({ caseId: c.caseId, action, hospital_id: c.confirmed.hospitalId, actor: "hospital", timestamp: now(), ...(d.reason ? { reason: d.reason } : {}) });
                  if (d.result === "refused") refusedIds.push(c.caseId);
                }
                setMciDecisions((prev) => {
                  const next: typeof prev = {};
                  for (const [id, d] of Object.entries(prev)) if (d.result !== "refused") next[id] = { result: "sent" };
                  return next;
                });
                setMciRedo(refusedIds);
                note(`수용 불가 ${refusedIds.length}명 재분배 — 그 병원을 빼고 ③ 병원 응답에서 다시 분배합니다`);
              }}
              onFinish={() => {
                for (const c of casualtyView) {
                  const d = mciDecisions[c.caseId];
                  if (d?.result === "accepted" && c.confirmed) {
                    sendAction({ caseId: c.caseId, action: "arrival_accepted", hospital_id: c.confirmed.hospitalId, actor: "hospital", timestamp: now() });
                  }
                }
                mciQueueRef.current = [];
                setMciRemaining(0);
                setMciOn(false);
                setMciCasualties([]);
                setMciDecisions({});
                setMciChoice({});
                setMciRedo(null);
                note("대량사고 종료 — 모든 사상자 수용 완료, ① 화면으로");
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
                        {REPORT_TEMPLATES.map((template) => (
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
                  <div role="tablist" style={{ display: "grid", gridTemplateColumns: devMode ? "repeat(2, minmax(0, 1fr))" : "minmax(0, 1fr)", gap: 10 }}>
                    {([
                      ["voice", "mic", "음성으로 확인", "대원 휴대폰 전화 앱 · 실제 통화 음성 → AI 구조화"],
                      ["template", "card", "정해진 상황 선택", "가상 환자 카드 · 음성 없이 바로 전달"],
                    ] as const).filter(([mode]) => devMode || mode === "voice").map(([mode, icon, label, sub]) => {
                      const selected = sceneMode === mode;
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
                          {devMode && <div style={{ fontSize: 12, color: C.ink3 }}>통화가 어려우면 위의 <b>정해진 상황 선택</b> 탭으로 바꿔 진행하세요.</div>}
                        </>
                      )}
                    </div>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                      {reportedTemplate && (
                        <div style={{ ...softBox, padding: "9px 14px", fontSize: 13, display: "flex", alignItems: "center", gap: 8 }}>
                          <Icon name="phone" size={15} color={C.pin} />
                          <span>신고 내용: <b>{reportedTemplate.label}</b> — 이 신고로 확인할 수 있는 현장 상황입니다. 현장 평가가 신고와 다르면(더 심각·더 가벼움) 해당 상황을 고르세요.</span>
                        </div>
                      )}
                      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                        {sceneOptions(reportedTemplate?.key).map((template) => (
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
                  {/* 대본(시연 대사집 ②) — 이 신고에 딸린 현장 상황 대본(음성이면 대원이 읽고, 버튼이면 압축본이 전달) */}
                  {reportedTemplate && (
                    <ScriptBox title="② 현장 확인 · 구급대원 — 상황 하나를 골라 읽습니다">
                      {sceneOptions(reportedTemplate.key).map((t, i) => (
                        <ScriptLine key={t.key} who={`${"ABC"[i] ?? ""}. ${t.label}`} text={SCRIPTS[t.report].scene[t.key]} />
                      ))}
                    </ScriptBox>
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
                        onReject={g(() => setRejectTarget({ caseIds: [myCase.caseId], hospitalId: hospital.hospitalId, name: hospital.name, action: "hospital_reject" }))}
                      />
                    ))}
                  </div>
                  <div style={{ fontSize: 12, color: C.ink3 }}>병원이 승인하면 구급차 대시보드에 승인 병원 정보가 뜹니다 — 구급대원이 [이송 승인]을 누르면 이송이 시작됩니다. 목록 순서는 hub 순위(이동 시간·진료과·등급)입니다.</div>
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
                              <span>
                                {sim?.paused ? (sim.pauseReason === "call" ? "추가 통화 중 — 통화 내용이 반영될 때까지 이송 잠시 멈춤 · " : "일시정지 중 — ") : ""}
                                도착하면 도착 결과 화면으로 넘어갑니다.
                              </span>
                              {/* 빨리감기(2026-10-04) — 이송 30초 동안 상황을 다 골랐으면 3초 안에 병원 도착 */}
                              {phase === "transporting" && apid && caseId && (simTrip.left == null || simTrip.left > 3) && (
                                <FastButton onClick={g(() => sendSimCommand("sim_fast_forward", apid, caseId) && note("빨리감기 — 3초 안에 병원에 도착합니다"))} />
                              )}
                            </div>
                            {/* 이송 중 수용 철회(2026-10-05) — 목적지 병원 역할을 대신 연출한다(실제 병원 탭의 [이송 중 수용 철회]와 같다) */}
                            {phase === "transporting" && caseId && confirmedHospital && (
                              <button
                                type="button"
                                onClick={g(() => setRejectTarget({ caseIds: [caseId], hospitalId: confirmedHospital.hospitalId, name: confirmedHospital.name, action: "transport_withdraw" }))}
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
                      {/* 상황 부여(2026-10-06 통합) — 방식을 먼저 고른다. 음성: 대원 휴대폰 추가 통화를 기다린다.
                          정해진 상황: 버튼 하나 = 활력징후 시나리오 재생(hub 판정) → 끝나면 목적지 병원에 추가 통화 내용 전달. */}
                      {(() => {
                        const call = caseId ? state.callStatus[caseId] : undefined;
                        const phoneCalling = call?.state === "calling" && call.followup;
                        const mode = phoneCalling ? "voice" : transportInput;
                        const hospitalName = confirmedHospital?.name ?? "목적지 병원";
                        const sentList = caseId ? followupSent[caseId] ?? [] : [];
                        return (
                          <div style={{ flex: "1.3 1 440px", minWidth: 0, display: "flex", flexDirection: "column", gap: 8 }}>
                            <div role="tablist" style={{ display: "grid", gridTemplateColumns: devMode ? "repeat(2, minmax(0, 1fr))" : "minmax(0, 1fr)", gap: 8 }}>
                              {([
                                ["voice", "mic", "음성으로 통화", "대원 휴대폰 전화 앱 [목적지 병원과 통화]"],
                                ["template", "card", "정해진 상황 선택", "버튼 · 활력징후 재생 뒤 통화 내용 자동 전달"],
                              ] as const).filter(([m]) => devMode || m === "voice").map(([m, icon, label, sub]) => {
                                const selected = mode === m;
                                return (
                                  <button
                                    key={m}
                                    type="button"
                                    role="tab"
                                    aria-selected={selected}
                                    disabled={!!phoneCalling || playingKey !== null}
                                    onClick={() => setFollowupMode(m)}
                                    style={{
                                      textAlign: "left", display: "flex", flexDirection: "column", gap: 2, padding: "8px 12px", borderRadius: 10, cursor: "pointer",
                                      color: C.ink, background: selected ? C.blueSoft : "#ffffff", border: selected ? `2px solid ${C.blue}` : `1px solid ${C.line}`,
                                    }}
                                  >
                                    <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 14, fontWeight: 700 }}><Icon name={icon} size={14} color={C.ink} />{label}</span>
                                    <span style={{ fontSize: 11, color: C.ink3 }}>{sub}</span>
                                  </button>
                                );
                              })}
                            </div>
                            {mode === "voice" ? (
                              phoneCalling ? (
                                <div style={{ ...softBox, display: "flex", alignItems: "center", gap: 10 }}>
                                  <Pulse color={C.green} />
                                  <span><b>{call?.hospitalName ?? hospitalName}</b>과 추가 통화 중 — 대원이 [전송]을 누르면 인식·구조화해 환자 정보에 덧붙입니다.</span>
                                </div>
                              ) : (
                                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                                  <div style={softBox}>대원 휴대폰 전화 앱(이송 중 화면)에서 <b>[목적지 병원과 통화]</b>를 누르세요. 통화 음성이 2차 통화 요약이 됩니다.</div>
                                  <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13, color: C.ink3 }}>
                                    <Pulse color="#7ba0cc" />
                                    {call?.followup && call.state === "ended"
                                      ? call.cancelled ? "대원이 통화를 취소했습니다 — 전달된 내용 없음" : "통화 종료 — 음성을 인식해 환자 정보에 덧붙이는 중…"
                                      : "음성 인식 대기 중 — 휴대폰 추가 통화를 기다리는 중…"}
                                  </div>
                                </div>
                              )
                            ) : (
                              SCENARIOS.map((scenario) => {
                                const key = scenario.key as MonitorKey;
                                const sel = playingKey === key;
                                const disabled = (playingKey !== null && !sel) || sending;
                                return (
                                  <button
                                    key={key}
                                    type="button"
                                    disabled={disabled}
                                    onClick={() => (locked ? pauseToast.notify() : sel ? stopScenario(caseId!) : playScenario(key, () => void handleFollowup(key)))}
                                    style={{
                                      flex: "1 1 56px", maxHeight: 92, textAlign: "left", borderRadius: 10, padding: "8px 16px", display: "flex", flexDirection: "column",
                                      justifyContent: "center", gap: 3, cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.5 : 1,
                                      background: sel ? C.blueSoft : C.bg, border: sel ? `2px solid ${C.blue}` : `1px solid ${C.line}`,
                                    }}
                                  >
                                    <span style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, fontWeight: 700, color: C.ink }}>
                                      <Icon name={sel ? "stop" : "play"} size={10} color={C.ink} />
                                      {MONITOR_NUM[key]} {transport.monitor[key]}
                                    </span>
                                    <span style={{ fontSize: 13, color: C.ink3 }}>
                                      {sel ? `활력징후 재생 중 — 끝나면 ${hospitalName}에 추가 통화 내용 전달` : scenario.expects}
                                    </span>
                                  </button>
                                );
                              })
                            )}
                            {sentList.length > 0 && (
                              <div style={{ fontSize: 12, color: C.greenInk }}>
                                {hospitalName}에 전달한 추가 통화: {sentList.map((label, i) => `${i + 2}차 ${label}`).join(" · ")}
                              </div>
                            )}
                          </div>
                        );
                      })()}
                    </div>

                    {/* 대본(시연 대사집 ④) — 목적지 병원에 재통화. 활력징후 시나리오 ①~⑤·추가 통화 버튼과 같은 순서(A~E) */}
                    {(() => {
                      const script = SCRIPTS[transportBase.report];
                      return (
                        <ScriptBox title="④ 이송 중 · 구급대원 — 상황 하나를 골라 병원에 재통화합니다">
                          <span style={{ fontSize: 15, color: C.ink2 }}>
                            맨 앞에 <b>“{confirmedHospital?.name ?? "목적지 병원"} 응급실, 이송 중 상태 보고드립니다”</b>를 붙여 시작하세요.
                            {transportBase.key !== transportBase.report && ` (대사집 ④는 '${templateOf(transportBase.report)?.label}' 기준입니다)`}
                          </span>
                          {(Object.keys(MONITOR_NUM) as MonitorKey[]).map((k, i) => (
                            <ScriptLine
                              key={k}
                              who={`${"ABCDE"[i]}. ${script.transport[k].label}${script.transport[k].note ? ` (${script.transport[k].note})` : ""}`}
                              text={script.transport[k].lines.join("\n")}
                            />
                          ))}
                        </ScriptBox>
                      );
                    })()}
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
                        onClick={g(() => setRejectTarget({ caseIds: [caseId], hospitalId: confirmedId, name: confirmedHospital?.name ?? "병원", action: "arrival_refused" }))}
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

// ── 대량사고 화면(2026-10-05, 시연 시나리오 콘솔 시안의 대량 ①~⑤) ──
// 시안처럼 단계별 화면이다: ① 출동 중 → ② 현장 확인(사상자마다 유형 선택) → ③ 병원 응답·분배(병원 × 중증도) → ④ 이송 중 →
// ⑤ 도착 결과(병원 × 중증도, 사상자마다 수용/불가 → 불가만 재분배). 사상자 한 명 = 사건 한 건(hub)이고, 분배는 콘솔이
// 계산하지 않는다 — [분배 확정]을 hub가 받아 중증부터 사건마다 승인 병원 중 순위 1위로 확정한다(부하 페널티로 분산).
type CasualtyView = MciCasualty & {
  template: Template;
  unit: AmbulanceSimState | null;
  monitorCase: MonitorCase | null;
  confirmed: MonitorCaseHospital | null;
  stage: number;
  hospitalName: string | null;
};

type MciStage = "dispatch" | "verify" | "hospital" | "transit" | "arrival";
const SEVS: SevLabel[] = ["중증", "중등증", "경증"];
const SEV_DESC: Record<SevLabel, string> = {
  중증: "즉시 이송 · 생명 위협 외상·심정지 위험 · 상급종합 우선",
  중등증: "신속 이송 · 골절·출혈 등 중등도 부상",
  경증: "대기 가능 · 보행 가능 · 경미한 부상",
};

function sevSummary(list: CasualtyView[]): string {
  const n = (sev: SevLabel) => list.filter((c) => c.template.severity === sev).length;
  return `중증 ${n("중증")} · 중등증 ${n("중등증")} · 경증 ${n("경증")} (총 ${list.length}명)`;
}

function MciWizard({
  stage, plan, onPreview, total, remaining, spotLabel, casualties, choice, decisions, redoIds, hospitalInfo, ambulanceName, tripProgress,
  onChoose, onVerify, onHospitalApprove, onHospitalReject, onBulk, onAllocate, onFastAll, onDecide, onAcceptAllLocal,
  onRedistribute, onFinish, lastAllocation, sending,
}: {
  stage: MciStage;
  plan: MciPlanItem[] | null;
  onPreview: (caseIds: string[]) => boolean;
  total: number;
  remaining: number;
  spotLabel: string;
  casualties: CasualtyView[];
  choice: Record<string, string>;
  decisions: Record<string, { result: "accepted" | "refused" | "sent"; reason?: RejectionReason }>;
  redoIds: string[] | null;
  hospitalInfo: Map<string, MapHospital>;
  ambulanceName: (apid: string) => string;
  tripProgress: (unit: AmbulanceSimState | null) => { left: number | null; p: number };
  onChoose: (caseId: string, key: string) => void;
  onVerify: (batch: CasualtyView[]) => void;
  onHospitalApprove: (hospitalId: string, caseIds: string[]) => void;
  onHospitalReject: (hospitalId: string, name: string, caseIds: string[]) => void;
  onBulk: (action: "hospital_approve" | "hospital_reject", pairs: { caseId: string; hospitalId: string }[]) => void;
  onAllocate: (caseIds: string[]) => void;
  onFastAll: (phase: "dispatching" | "transporting") => void;
  onDecide: (c: CasualtyView, result: "accepted" | "refused" | "undo") => void;
  onAcceptAllLocal: (list: CasualtyView[]) => void;
  onRedistribute: () => void;
  onFinish: () => void;
  lastAllocation: { confirmed: number; skipped: number } | null;
  sending: boolean;
}) {
  const box = (bg: string, bd: string): CSSProperties => ({
    display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 1, minHeight: 40, minWidth: 0,
    padding: "3px 4px", boxSizing: "border-box", textAlign: "center", borderRadius: 8, background: bg, border: `1px solid ${bd}`,
  });
  // ③ 자동 분배 미리 보기 — 병원 응답이 바뀔 때마다 hub에 계획을 물어본다(확정 아님). [분배 확정]도 같은 계획으로 확정된다.
  const previewBatch = stage === "hospital"
    ? casualties.filter((c) => c.stage === 2 && c.monitorCase && (redoIds == null || redoIds.includes(c.caseId)))
    : [];
  const previewKey = previewBatch
    .map((c) => `${c.caseId}:${c.monitorCase!.hospitals.map((h) => `${h.hospitalId}=${h.status}`).join(",")}`)
    .join("|");
  useEffect(() => {
    if (!previewKey) return;
    onPreview(previewKey.split("|").map((part) => part.split(":")[0]));
  }, [previewKey, onPreview]);

  const colHead = (sev: SevLabel, n: number) => (
    <div key={sev} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4, background: "#f8fafc", border: `1px solid ${C.lineSoft}`, borderRadius: 10, padding: "6px 8px" }}>
      <SevChip sev={sev} text={`${sev} ${n}명`} />
    </div>
  );

  // ── ① 출동 중 ──
  if (stage === "dispatch") {
    const moving = casualties.filter((c) => c.stage === 0);
    const progress = moving.map((c) => tripProgress(c.unit));
    const left = progress.reduce<number | null>((max, x) => (x.left == null ? max : Math.max(max ?? 0, x.left)), null);
    const p = progress.length ? Math.min(...progress.map((x) => x.p)) : 0;
    const tiles: [string, number, string, string, string][] = [
      ["사상자 합계", total, "명", C.bg, C.ink],
      ["중증", casualties.filter((c) => c.template.severity === "중증").length, "명", C.redSoft, C.redInk],
      ["중등증", casualties.filter((c) => c.template.severity === "중등증").length, "명", C.amberSoft, C.amberInk],
      ["경증", casualties.filter((c) => c.template.severity === "경증").length, "명", C.greenSoft, C.greenInk],
      ["출동 구급대", moving.length, "대", C.blueSoft, C.blue],
      ["재출동 대기", remaining, "명", C.bg, C.ink3],
    ];
    return (
      <ScreenCard title={`출동 중… 대량사고 — 구급대 ${moving.length}대 동시 출동`}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 10 }}>
          {tiles.map(([label, n, unit, bg, fg]) => (
            <div key={label} style={{ display: "flex", flexDirection: "column", gap: 6, padding: "14px 16px", borderRadius: 12, background: bg, color: fg }}>
              <span style={{ fontSize: 13, fontWeight: 700 }}>{label}</span>
              <span style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
                <span style={{ fontSize: 34, fontWeight: 700, lineHeight: 1 }}>{n}</span>
                <span style={{ fontSize: 15, fontWeight: 700 }}>{unit}</span>
              </span>
            </div>
          ))}
        </div>
        <ProgressTrack p={p} start="인근 119안전센터" end={spotLabel || "현장"} endIcon="pin" />
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "8px 12px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 16, fontWeight: 700, color: C.blue }}>
            <span style={{ width: 10, height: 10, borderRadius: "50%", background: C.blue, display: "inline-block" }} />
            {left != null ? `마지막 구급대 현장 도착까지 ${left}초` : "현장 도착 대기"}
          </div>
          {left != null && left > 3 && <FastButton onClick={() => onFastAll("dispatching")} />}
        </div>
        <div style={{ background: "#fff6f5", border: "1px solid #f0d9d7", borderRadius: 10, padding: "10px 14px", fontSize: 13, lineHeight: 1.6, color: C.ink3 }}>
          분배 계획: 사상자 {total}명 · 1차 {casualties.length}명 이송(중증 우선), 대기 {remaining}명은 구급대가 복귀하는 대로 자동 재출동.
          병원 분배는 hub가 한다(중증→센터 가산 + 이송 중 부하 페널티로 한 병원 쏠림 방지).
        </div>
      </ScreenCard>
    );
  }

  // ── ② 현장 확인 — 사상자마다 유형 선택 ──
  if (stage === "verify") {
    const batch = casualties.filter((c) => c.stage === 1);
    const chosen = (c: CasualtyView) => templateOf(choice[c.caseId] ?? c.templateKey)!;
    const counts = (sev: SevLabel) => batch.filter((c) => chosen(c).severity === sev).length;
    return (
      <ScreenCard title="② 현장 확인 — 사상자 구성을 확정하면 인근 병원에 동시 전달됩니다">
        <div style={{ ...softBox, padding: "9px 14px", fontSize: 13 }}>
          신고 내용: <b>대량사고 · 사상자 {total}명</b> — 사상자마다 접수된 신고 유형에 딸린 현장 상황 중에서 트리아지 결과를 고르세요.
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 14, alignItems: "flex-start" }}>
          <div style={{ flex: "2.4 1 640px", minWidth: 0, display: "flex", flexDirection: "column", gap: 6 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: C.ink3 }}>
              환자별 현장 상태를 선택하세요 — 선택한 내용이 병원에 전달됩니다 (가상 환자 {batch.length}명)
            </div>
            {batch.map((c) => {
              const t = chosen(c);
              return (
                <div key={c.caseId} style={{ display: "grid", gridTemplateColumns: "28px 56px minmax(0, 1fr) 80px 84px", alignItems: "center", columnGap: 10, padding: "5px 12px", borderRadius: 10, background: "#ffffff", border: `1px solid ${C.line}` }}>
                  <span style={{ fontSize: 13, fontWeight: 700, color: C.muted }}>{c.no}</span>
                  <SevChip sev={t.severity} width={56} />
                  <div style={{ display: "grid", gridTemplateColumns: `repeat(${sceneOptions(c.templateKey).length}, minmax(0, 1fr))`, gap: 6, minWidth: 0 }}>
                    {sceneOptions(c.templateKey).map((o) => {
                      const on = o.key === t.key;
                      return (
                        <button
                          key={o.key}
                          type="button"
                          onClick={() => onChoose(c.caseId, o.key)}
                          style={{
                            minHeight: 36, padding: "2px 6px", textAlign: "center", fontSize: 13, lineHeight: 1.25, cursor: "pointer", borderRadius: 8,
                            color: C.ink, background: on ? C.blueSoft : "#ffffff", border: on ? `2px solid ${C.blue}` : `1px solid ${C.line}`,
                          }}
                        >
                          {o.label}
                        </button>
                      );
                    })}
                  </div>
                  <span style={{ fontSize: 13, fontWeight: 700 }}>{t.summary.patient}</span>
                  <span style={{ textAlign: "center", fontSize: 12, fontWeight: 700, color: C.blue, background: C.blueDept, padding: "4px 0", borderRadius: 8 }}>{t.summary.required_department}</span>
                </div>
              );
            })}
          </div>
          <div style={{ flex: "1 1 220px", minWidth: 0, display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: C.ink3 }}>병원 전달 요약</div>
            {SEVS.map((sev) => (
              <div key={sev} style={{ display: "flex", flexDirection: "column", gap: 6, padding: "10px 16px", borderRadius: 12, background: SEV_COLORS[sev].bg }}>
                <span style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                  <SevChip sev={sev} />
                  <span style={{ display: "flex", alignItems: "baseline", gap: 3, color: SEV_COLORS[sev].fg }}>
                    <span style={{ fontSize: 32, fontWeight: 700, lineHeight: 1 }}>{counts(sev)}</span>
                    <span style={{ fontSize: 14, fontWeight: 700 }}>명</span>
                  </span>
                </span>
                <span style={{ fontSize: 12, lineHeight: 1.4, color: C.ink2 }}>{SEV_DESC[sev]}</span>
              </div>
            ))}
          </div>
        </div>
        <button
          type="button"
          disabled={sending || batch.length === 0}
          onClick={() => onVerify(batch)}
          style={{ minHeight: 46, background: C.blue, border: "none", borderRadius: 10, color: "#ffffff", fontSize: 15, fontWeight: 700, cursor: sending ? "wait" : "pointer", opacity: sending ? 0.6 : 1 }}
        >
          {sending ? "전달 중…" : `사상자 ${batch.length}명 확정 — 인근 병원에 동시 전달`}
        </button>
      </ScreenCard>
    );
  }

  // ── ③ 병원 응답 · 분배 — 병원 × 중증도 ──
  if (stage === "hospital") {
    const redo = redoIds != null;
    const batch = casualties.filter((c) => c.stage === 2 && c.monitorCase && (!redo || redoIds!.includes(c.caseId)));
    const sevsInBatch = SEVS.filter((sev) => batch.some((c) => c.template.severity === sev));
    const grid = `minmax(180px, 1.4fr) repeat(${Math.max(1, sevsInBatch.length)}, minmax(0, 1fr)) 52px 78px 120px`;
    type Row = { hospitalId: string; name: string; zone: number; bySev: Record<SevLabel, { req: number; status: string[]; reason: string | null }>; pending: string[]; approved: number; rejected: number; total: number };
    const rows = new Map<string, Row>();
    for (const c of batch) {
      for (const h of c.monitorCase!.hospitals) {
        const row = rows.get(h.hospitalId) ?? {
          hospitalId: h.hospitalId, name: h.name, zone: h.zone, pending: [], approved: 0, rejected: 0, total: 0,
          bySev: { 중증: { req: 0, status: [], reason: null }, 중등증: { req: 0, status: [], reason: null }, 경증: { req: 0, status: [], reason: null } },
        };
        const cell = row.bySev[c.template.severity];
        cell.req += 1;
        cell.status.push(h.status);
        if (h.status === "rejected") cell.reason = unavailableReasonLabel(h.unavailableReason) ?? rejectionReasonLabel(h.rejectReason) ?? "병원 판단";
        row.total += 1;
        if (h.status === "pending" && !h.unavailableReason) row.pending.push(c.caseId);
        else if (h.status === "approved") row.approved += 1;
        else if (h.status === "rejected") row.rejected += 1;
        row.zone = Math.min(row.zone, h.zone);
        rows.set(h.hospitalId, row);
      }
    }
    if (batch.length === 0) {
      return (
        <ScreenCard title="③ 병원 응답 — 병원 매칭 중…">
          <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 15, color: C.ink2 }}>
            <Pulse color={C.blue} />존(Zone) 안 후보 병원을 사상자마다 정렬해 동시에 요청을 보내고 있습니다.
          </div>
        </ScreenCard>
      );
    }
    // hub 자동 분배 계획(미리 보기) — 이번 배치 사건 것만
    const batchIds = new Set(batch.map((c) => c.caseId));
    const planBy = new Map((plan ?? []).filter((item) => batchIds.has(item.caseId)).map((item) => [item.caseId, item]));
    const planReady = batch.every((c) => planBy.has(c.caseId));
    const assigned = (hospitalId: string) => batch.filter((c) => planBy.get(c.caseId)?.hospitalId === hospitalId);
    const hospitalRows = [...rows.values()].sort((a, b) => (b.approved > 0 ? 1 : 0) - (a.approved > 0 ? 1 : 0) || a.zone - b.zone || b.total - a.total);
    const pendingPairs = batch.flatMap((c) =>
      c.monitorCase!.hospitals.filter((h) => h.status === "pending" && !h.unavailableReason).map((h) => ({ caseId: c.caseId, hospitalId: h.hospitalId })),
    );
    const pendingHospitals = new Set(pendingPairs.map((p) => p.hospitalId)).size;
    const allocatable = planReady
      ? batch.filter((c) => planBy.get(c.caseId)?.hospitalId)
      : batch.filter((c) => c.monitorCase!.hospitals.some((h) => h.status === "approved"));
    const approvedHospitals = planReady
      ? new Set(allocatable.map((c) => planBy.get(c.caseId)!.hospitalId)).size
      : hospitalRows.filter((r) => r.approved > 0).length;
    const unassigned = batch.length - allocatable.length;
    const unassignedList = batch.filter((c) => !allocatable.includes(c));
    return (
      <ScreenCard
        title={redo ? `③ 병원 응답 — 수용 불가 환자 ${batch.length}명을 다른 병원에 다시 분배합니다` : "③ 병원 응답 — 승인한 병원에 hub가 사상자를 자동 분배합니다"}
        fixed
      >
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "8px 10px" }}>
          <div style={{ background: C.redSoft, color: C.redInk, fontSize: 13, fontWeight: 700, padding: "8px 12px", borderRadius: 10 }}>
            {redo ? "재분배 대상: " : "현장 확인: 대량사고 — "}{sevSummary(batch)}
          </div>
          <button type="button" disabled={pendingPairs.length === 0} style={bulkButton("green", pendingPairs.length === 0)} onClick={() => onBulk("hospital_approve", pendingPairs)}>
            <Icon name="check" size={13} color={C.greenInk} stroke={3} />미응답 {pendingHospitals}곳 일괄 응답 — 모두 승인 (병원 역할)
          </button>
          <button type="button" disabled={pendingPairs.length === 0} style={bulkButton("red", pendingPairs.length === 0)} onClick={() => onBulk("hospital_reject", pendingPairs)}>
            <Icon name="x" size={13} color={C.red} stroke={3} />미응답 {pendingHospitals}곳 전부 불가 (존 확장 연출)
          </button>
        </div>
        {redo && (
          <div style={{ background: C.bg, borderRadius: 10, padding: "8px 14px", fontSize: 13, lineHeight: 1.5, color: C.ink2 }}>
            {batch.map((c) => `#${c.no} ${c.template.label}`).join(" · ")} — 도착 후 수용 불가한 병원은 이 환자 배정에서 빠집니다. 이미 수용된 환자는 다시 처리하지 않습니다.
          </div>
        )}
        {unassigned > 0 && approvedHospitals > 0 && (
          <div style={{ background: C.redSoft, color: C.redInk, borderRadius: 10, padding: "8px 14px", fontSize: 13, fontWeight: 700 }}>
            배정 불가 {unassigned}명 — 그 환자들의 후보 중 승인한 병원이 없습니다. 병원 승인을 더 받거나 존을 넓히세요.
            <span style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
              {unassignedList.map((c) => <PatientTag key={c.caseId} c={c} />)}
            </span>
          </div>
        )}
        <div style={{ display: "grid", gridTemplateColumns: grid, columnGap: 10, padding: "0 12px", alignItems: "stretch" }}>
          <span style={{ alignSelf: "center", fontSize: 12, fontWeight: 700, color: C.ink3 }}>병원</span>
          {sevsInBatch.map((sev) => colHead(sev, batch.filter((c) => c.template.severity === sev).length))}
          <span style={{ alignSelf: "center", fontSize: 12, fontWeight: 700, color: C.ink3, textAlign: "center" }}>합계</span>
          <span style={{ alignSelf: "center", fontSize: 12, fontWeight: 700, color: C.ink3, textAlign: "center" }}>응답</span>
          <span style={{ alignSelf: "center", fontSize: 12, fontWeight: 700, color: C.ink3, textAlign: "center" }}>병원 응답</span>
        </div>
        <div className="ctl-scroll" style={{ flex: "1 1 auto", minHeight: 0, overflowY: "auto", display: "flex", flexDirection: "column", gap: 6 }}>
          {hospitalRows.map((row) => {
            const info = hospitalInfo.get(row.hospitalId);
            const beds = info?.bedCountUnknown || info?.availableBedCount == null ? "병상 미상" : `응급 ${info.availableBedCount}병상`;
            const level = info?.emergencyLevel ? LEVEL_SHORT[info.emergencyLevel] ?? info.emergencyLevel : null;
            const status = row.pending.length > 0 ? "pending" : row.approved > 0 ? "approved" : "rejected";
            const chip = STATUS_CHIP[status];
            const lock = row.pending.length === 0;
            return (
              <div
                key={row.hospitalId}
                style={{
                  flex: "0 0 auto", display: "grid", gridTemplateColumns: grid, columnGap: 10, alignItems: "center", padding: "4px 12px", borderRadius: 10,
                  border: `1px solid ${status === "approved" ? C.greenLine : C.lineSoft}`, background: status === "approved" ? C.greenRow : "#ffffff",
                  opacity: status === "rejected" ? 0.6 : 1,
                }}
              >
                <span style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 2 }}>
                  <span style={{ fontSize: 13, lineHeight: 1.35, fontWeight: status === "approved" ? 700 : 400, color: status === "rejected" ? "#8795a4" : C.ink, wordBreak: "keep-all", overflowWrap: "anywhere" }}>{row.name}</span>
                  <span style={{ fontSize: 11, color: C.muted }}>{[level, `존 ${row.zone}`].filter(Boolean).join(" · ")}</span>
                </span>
                {sevsInBatch.map((sev) => {
                  const cell = row.bySev[sev];
                  if (cell.req === 0) return <div key={sev} style={box("#f8fafc", "#eef2f6")}><span style={{ fontSize: 14, color: C.faint }}>—</span></div>;
                  if (cell.status.every((st) => st === "rejected")) {
                    return (
                      <div key={sev} style={box("#f1f3f5", "#e1e6eb")}>
                        <span style={{ fontSize: 12, fontWeight: 700, color: "#8795a4" }}>수용 불가</span>
                        <span style={{ fontSize: 11, color: "#a0abb7" }}>{cell.reason}</span>
                      </div>
                    );
                  }
                  const approved = cell.status.filter((st) => st === "approved").length;
                  const toHere = assigned(row.hospitalId).filter((c) => c.template.severity === sev).length;
                  return approved > 0 ? (
                    <div key={sev} style={box(C.green, C.green)}>
                      <span style={{ fontSize: 13, fontWeight: 700, color: "#ffffff" }}>{approved}명 수용 가능</span>
                      <span style={{ fontSize: 11, color: "#d8f3e8" }}>{planReady ? `자동 배정 ${toHere}명 · ${beds}` : beds}</span>
                    </div>
                  ) : (
                    <div key={sev} style={box(C.greenSoft, C.greenLine)}>
                      <span style={{ fontSize: 12, fontWeight: 700, color: C.greenInk }}>요청 {cell.req}명</span>
                      <span style={{ fontSize: 11, color: "#4d8f74" }}>{beds}</span>
                    </div>
                  );
                })}
                <span style={{ textAlign: "center", fontSize: 14, fontWeight: 700 }}>{row.total}명</span>
                <span style={{ textAlign: "center", fontSize: 12, fontWeight: 700, padding: "4px 0", borderRadius: 999, background: chip.bg, color: chip.fg }}>{chip.label}</span>
                <span style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                  <button type="button" disabled={lock} style={{ ...rowButton("green"), opacity: lock ? 0.35 : 1 }} onClick={() => onHospitalApprove(row.hospitalId, row.pending)}>승인</button>
                  <button type="button" disabled={lock} style={{ ...rowButton("red"), opacity: lock ? 0.35 : 1 }} onClick={() => onHospitalReject(row.hospitalId, row.name, row.pending)}>불가</button>
                </span>
                {row.approved > 0 && planReady && (
                  <div style={{ gridColumn: "1 / -1", display: "flex", flexWrap: "wrap", alignItems: "center", gap: 6, padding: "6px 0 2px", borderTop: `1px dashed ${C.greenLine}`, marginTop: 4 }}>
                    <span style={{ fontSize: 12, fontWeight: 700, color: C.greenInk }}>자동 배정 →</span>
                    {assigned(row.hospitalId).length === 0 ? (
                      <span style={{ fontSize: 12, color: C.muted }}>배정 없음 — 이 환자들에겐 다른 승인 병원이 더 적합(순위·부하)</span>
                    ) : (
                      assigned(row.hospitalId).map((c) => <PatientTag key={c.caseId} c={c} />)
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
        <div style={{ fontSize: 12, lineHeight: 1.6, color: C.ink3, flex: "none" }}>
          [승인]/[불가]는 <b>병원의 응답</b>(콘솔이 병원 역할 연출) — 그 병원이 후보인 사상자 전부에 한 번에 응답합니다. 승인이 들어오면
          hub가 승인 병원들 사이의 <b>자동 배정</b>을 바로 계산해 병원 행 아래에 보여 주고, [분배 확정]은 보이는 그대로 확정합니다. 분배 규칙(hub 순위 그대로):
          ① 중증 → 중등증 → 경증 순서 ② 사상자마다 승인 병원 중 순위 1위(중증은 권역·지역센터 가산, 경증은 센터 역가산) ③ 같은 병원으로 이송 중인
          환자가 쌓이면 부하 페널티로 다음 병원에 배정 — 병상이 남아도 한꺼번에 몰아 받지 않습니다.
          {lastAllocation && ` · 직전 분배: ${lastAllocation.confirmed}명 확정${lastAllocation.skipped ? `, ${lastAllocation.skipped}명 보류` : ""}`}
        </div>
        <button
          type="button"
          disabled={allocatable.length === 0}
          onClick={() => onAllocate(batch.map((c) => c.caseId))}
          style={{
            flex: "none", minHeight: 46, border: "none", borderRadius: 10, color: "#ffffff", fontSize: 15, fontWeight: 700,
            cursor: allocatable.length === 0 ? "not-allowed" : "pointer", background: allocatable.length === 0 ? C.blueOff : C.blue,
          }}
        >
          {allocatable.length === 0
            ? "승인된 병원이 없습니다 — 한 곳 이상 승인하면 분배가 시작됩니다"
            : `${redo ? "재분배 확정" : "분배 확정"} — ${approvedHospitals}개 병원에 ${allocatable.length}명 이송 시작 (상황실·구급대 이송 승인)${unassigned ? ` · 배정 불가 ${unassigned}명 제외` : ""}`}
        </button>
      </ScreenCard>
    );
  }

  // ── ④ 이송 중 ──
  if (stage === "transit") {
    const units = casualties
      .filter((c) => c.stage === 3 || (c.stage === 4 && !decisions[c.caseId]))
      .sort((a, b) => SEVS.indexOf(a.template.severity) - SEVS.indexOf(b.template.severity));
    const progress = units.map((c) => ({ c, ...tripProgress(c.unit) }));
    const lastLeft = progress.reduce<number | null>((max, x) => (x.left == null ? max : Math.max(max ?? 0, x.left)), null);
    const hospitals = new Set(units.map((c) => c.hospitalName).filter(Boolean)).size;
    return (
      <ScreenCard title={`④ 이송 중 — 구급대 ${units.length}대가 분배된 병원으로 이송 중입니다`}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 14, alignItems: "stretch" }}>
          <div style={{ flex: "1 1 300px", minWidth: 0, background: "#f8fafc", border: `1px solid ${C.lineSoft}`, borderRadius: 12, padding: "20px 22px", display: "flex", flexDirection: "column", justifyContent: "center", gap: 16 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <span style={{ fontSize: 12, fontWeight: 500, color: C.muted }}>마지막 구급대 도착까지</span>
              <span style={{ display: "flex", alignItems: "baseline", gap: 6, color: C.blue }}>
                <span style={{ fontSize: 56, fontWeight: 700, lineHeight: 1 }}>{lastLeft ?? 0}</span>
                <span style={{ fontSize: 20, fontWeight: 700 }}>초</span>
              </span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 8 }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 4, padding: "10px 12px", borderRadius: 10, background: "#e8f1fb", color: C.blue }}>
                <span style={{ fontSize: 12, fontWeight: 700 }}>이송 중</span>
                <span style={{ fontSize: 22, fontWeight: 700, lineHeight: 1 }}>{units.filter((c) => c.stage === 3).length}명</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4, padding: "10px 12px", borderRadius: 10, background: "#ffffff", border: `1px solid ${C.line}`, color: C.ink3 }}>
                <span style={{ fontSize: 12, fontWeight: 700 }}>분배 병원</span>
                <span style={{ fontSize: 22, fontWeight: 700, lineHeight: 1, color: C.ink }}>{hospitals}곳</span>
              </div>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "8px 12px", fontSize: 13, color: C.ink3 }}>
              <span>모두 도착하면 도착 결과 화면으로 넘어갑니다.</span>
              {lastLeft != null && lastLeft > 3 && <FastButton onClick={() => onFastAll("transporting")} />}
            </div>
          </div>
          <div style={{ flex: "1.7 1 520px", minWidth: 0, display: "flex", flexDirection: "column", gap: 8 }}>
            {progress.map(({ c, left, p }) => {
              const arrived = c.stage === 4;
              return (
                <div key={c.caseId} style={{ flex: "1 1 44px", maxHeight: 64, display: "flex", alignItems: "center", gap: 12, padding: "6px 14px", borderRadius: 10, background: arrived ? C.greenRow : "#ffffff", border: `1px solid ${arrived ? C.greenLine : C.lineSoft}` }}>
                  <span style={{ flex: "none", width: 92, fontSize: 13, fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={ambulanceName(c.apid)}>#{c.no} {ambulanceName(c.apid).replace(/119안전센터\s*/, "")}</span>
                  <SevChip sev={c.template.severity} width={52} />
                  <span style={{ flex: "0 0 150px", minWidth: 0, fontSize: 13, fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={`${c.template.label} · ${c.template.summary.patient}`}>{c.template.label}</span>
                  <span style={{ flex: "0 0 190px", minWidth: 0, fontSize: 13, lineHeight: 1.3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>→ {c.hospitalName}</span>
                  <div style={{ flex: "1 1 auto", height: 8, borderRadius: 4, background: C.lineSoft }}>
                    <div style={{ height: 8, borderRadius: 4, background: arrived ? C.green : C.blue, width: `${((arrived ? 1 : p) * 100).toFixed(1)}%`, transition: "width 0.9s linear" }} />
                  </div>
                  <span style={{ flex: "none", width: 44, textAlign: "right", fontSize: 13, fontWeight: 700, color: arrived ? C.greenInk : C.blue }}>{arrived ? "도착" : left != null ? `${left}초` : ""}</span>
                </div>
              );
            })}
          </div>
        </div>
      </ScreenCard>
    );
  }

  // ── ⑤ 도착 결과 — 병원 × 중증도, 사상자마다 수용/불가 ──
  const reached = casualties.filter((c) => c.stage === 4 || decisions[c.caseId]);
  const accepted = reached.filter((c) => decisions[c.caseId]?.result === "accepted" || decisions[c.caseId]?.result === "sent").length;
  const refused = reached.filter((c) => decisions[c.caseId]?.result === "refused");
  const pendingArrivals = reached.filter((c) => !decisions[c.caseId]);
  const byHospital = new Map<string, CasualtyView[]>();
  for (const c of reached) {
    const key = c.hospitalName ?? "병원";
    byHospital.set(key, [...(byHospital.get(key) ?? []), c]);
  }
  const sevsInArrival = SEVS.filter((sev) => reached.some((c) => c.template.severity === sev));
  const grid = `minmax(170px, 1.3fr) repeat(${Math.max(1, sevsInArrival.length)}, minmax(0, 1fr)) 110px`;
  const allAccepted = reached.length > 0 && accepted === reached.length;
  const stillMoving = casualties.some((c) => c.stage < 4 && !decisions[c.caseId]);
  const itemButton = (tone: "green" | "red" | "plain"): CSSProperties => ({ ...rowButton(tone), minHeight: 28, padding: "0 10px" });
  return (
    <ScreenCard title="⑤ 도착 결과 — 병원별로 실제 수용 여부를 기록합니다" fixed>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10, flex: "none" }}>
        <span style={{ display: "flex", alignItems: "baseline", gap: 6, color: C.blue }}>
          <span style={{ fontSize: 13, fontWeight: 700 }}>수용 완료</span>
          <span style={{ fontSize: 26, fontWeight: 700, lineHeight: 1 }}>{accepted}</span>
          <span style={{ fontSize: 15, fontWeight: 700 }}>/ {reached.length}명</span>
        </span>
        <button
          type="button"
          disabled={refused.length === 0}
          onClick={onRedistribute}
          style={{ ...bulkButton("red", refused.length === 0) }}
        >
          수용 불가 {refused.length}명 재분배
        </button>
        <button type="button" disabled={pendingArrivals.length === 0} style={bulkButton("green", pendingArrivals.length === 0)} onClick={() => onAcceptAllLocal(pendingArrivals)}>
          전부 수용 완료 처리
        </button>
        <button
          type="button"
          disabled={!allAccepted || stillMoving}
          onClick={onFinish}
          style={{ minHeight: 42, padding: "0 20px", border: "none", borderRadius: 10, color: "#ffffff", fontSize: 14, fontWeight: 700, cursor: !allAccepted || stillMoving ? "not-allowed" : "pointer", background: !allAccepted || stillMoving ? C.blueOff : C.blue }}
        >
          사건 종료 — ① 화면으로
        </button>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: grid, columnGap: 10, padding: "0 12px", flex: "none" }}>
        <span style={{ alignSelf: "center", fontSize: 12, fontWeight: 700, color: C.ink3 }}>병원</span>
        {sevsInArrival.map((sev) => colHead(sev, reached.filter((c) => c.template.severity === sev).length))}
        <span style={{ alignSelf: "center", fontSize: 12, fontWeight: 700, color: C.ink3, textAlign: "center" }}>병원 전체</span>
      </div>
      <div className="ctl-scroll" style={{ flex: "1 1 auto", minHeight: 0, overflowY: "auto", display: "flex", flexDirection: "column", gap: 8 }}>
        {[...byHospital.entries()].map(([name, list]) => {
          const allOk = list.every((c) => decisions[c.caseId] && decisions[c.caseId].result !== "refused");
          const anyNo = list.some((c) => decisions[c.caseId]?.result === "refused");
          const open = list.filter((c) => !decisions[c.caseId]);
          return (
            <div key={name} style={{ flex: "0 0 auto", display: "grid", gridTemplateColumns: grid, columnGap: 10, alignItems: "center", padding: "6px 12px", borderRadius: 10, background: allOk ? C.greenRow : "#ffffff", border: `1px solid ${allOk ? C.greenLine : anyNo ? C.redLine : C.lineSoft}` }}>
              <span style={{ fontSize: 14, fontWeight: 700, lineHeight: 1.3, wordBreak: "keep-all", overflowWrap: "anywhere" }}>{name}</span>
              {sevsInArrival.map((sev) => {
                const people = list.filter((c) => c.template.severity === sev);
                if (people.length === 0) return <div key={sev} style={box("#f8fafc", "#eef2f6")}><span style={{ fontSize: 15, fontWeight: 700, color: "#b3bdc8" }}>—</span></div>;
                return (
                  <div key={sev} style={{ display: "flex", flexDirection: "column", gap: 6, padding: 5, borderRadius: 8, background: "#f8fafc", border: `1px solid ${C.lineSoft}` }}>
                    {people.map((c) => {
                      const d = decisions[c.caseId]?.result;
                      const ok = d === "accepted" || d === "sent";
                      const no = d === "refused";
                      return (
                        <div key={c.caseId} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 5, padding: 6, borderRadius: 6, background: ok ? C.greenSoft : no ? C.redSoft : "#ffffff", border: `1px solid ${ok ? C.greenLine : no ? C.redLine : C.line}` }}>
                          <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                            <span style={{ fontSize: 14, fontWeight: 700 }}>#{c.no}</span>
                            <span style={{ fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 999, background: ok || no ? "#ffffff" : C.amberSoft, color: ok ? C.greenInk : no ? C.redInk : C.amberInk }}>
                              {ok ? "수용 완료" : no ? "수용 불가" : "확인 대기"}
                            </span>
                          </span>
                          <span style={{ fontSize: 13, fontWeight: 700, lineHeight: 1.3, textAlign: "center", wordBreak: "keep-all" }}>{c.template.label}</span>
                          <span style={{ fontSize: 11, color: C.muted }}>{c.template.summary.patient} · {c.template.summary.required_department}</span>
                          {!d && (
                            <span style={{ display: "flex", gap: 6 }}>
                              <button type="button" style={itemButton("green")} onClick={() => onDecide(c, "accepted")}>수용</button>
                              <button type="button" style={itemButton("red")} onClick={() => onDecide(c, "refused")}>불가</button>
                            </span>
                          )}
                          {(d === "accepted" || d === "refused") && (
                            <button type="button" style={itemButton("plain")} onClick={() => onDecide(c, "undo")}>되돌리기</button>
                          )}
                        </div>
                      );
                    })}
                  </div>
                );
              })}
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <button type="button" disabled={open.length === 0} style={{ ...itemButton("green"), opacity: open.length === 0 ? 0.4 : 1 }} onClick={() => open.forEach((c) => onDecide(c, "accepted"))}>전체 수용</button>
                <button type="button" disabled={open.length === 0} style={{ ...itemButton("red"), opacity: open.length === 0 ? 0.4 : 1 }} onClick={() => open.forEach((c) => onDecide(c, "refused"))}>전체 불가</button>
              </div>
            </div>
          );
        })}
      </div>
      <div style={{ fontSize: 12, lineHeight: 1.6, color: C.ink3, flex: "none" }}>
        환자별로 수용 여부를 기록합니다(병원 역할 연출). 수용 불가는 표시만 되고, [수용 불가 N명 재분배]를 누르면 불가 환자만 모아 ③에서 다시
        분배합니다 — 이미 수용된 환자는 다시 처리하지 않습니다.{stillMoving ? " 아직 도착하지 않은 구급대가 있습니다." : ""}
      </div>
    </ScreenCard>
  );
}

// 대량사고 사상자 태그 — 번호만으론 누군지 몰라서 부상 유형까지 붙인다(2026-10-05)
function PatientTag({ c }: { c: CasualtyView }) {
  const color = SEV_COLORS[c.template.severity];
  return (
    <span
      title={`${c.template.label} · ${c.template.summary.patient} · ${c.template.summary.required_department}`}
      style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "3px 10px", borderRadius: 999, background: "#ffffff", border: `1px solid ${C.line}`, fontSize: 12, fontWeight: 700, color: C.ink }}
    >
      <span style={{ width: 8, height: 8, borderRadius: "50%", background: color.fg, display: "inline-block" }} />
      #{c.no} {c.template.label}
    </span>
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

// 시연 대본 칸(2026-10-06) — 진행자·신고자·구급대원이 읽을 대사. 접어 둘 수 있다(기본 펼침). 서서 읽도록 본문 18px
function ScriptBox({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details open style={{ background: "#fffdf4", border: "1px solid #eadfb8", borderRadius: 12, padding: "10px 14px" }}>
      <summary style={{ cursor: "pointer", fontSize: 15, fontWeight: 700, color: C.amberInk }}>대본 · {title}</summary>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>{children}</div>
    </details>
  );
}

function ScriptLine({ who, text }: { who: string; text: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <span style={{ fontSize: 14, fontWeight: 700, color: C.ink3 }}>{who}</span>
      <span style={{ fontSize: 18, lineHeight: 1.6, color: C.ink, whiteSpace: "pre-line" }}>{text}</span>
    </div>
  );
}

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

// ③ 병원 한 줄 — 상태 칩 + 승인/불가(이송 확정은 구급차 대시보드에서 — 2026-10-06 콘솔 버튼 삭제). 적합 여부 칸은 시안의 가상 '적합' 대신 실제 E-Gen 병상(미상 ≠ 만실)과
// 병원이 고른 거절 사유를 보인다.
function HospitalRow({ hospital, info, onApprove, onReject }: {
  hospital: MonitorCaseHospital;
  info: MapHospital | undefined;
  onApprove: () => void;
  onReject: () => void;
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

// 시간 기반 존 확장 카운트다운(2026-10-04) — 승인·확정 병원이 없으면 hub가 1분(HUB_ZONE_EXPAND_SEC)마다 요청 범위를 한 단계 넓힌다.
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
