import type { HubMatchResult } from "@/types/dashboard";

// feature/hub의 실시간 통신(Flask)이 아직 붙지 않았을 때 대시보드 UI를 확인하기 위한 목데이터.
// feature/hub README.md "출력 스키마 4" 예시 JSON을 그대로 옮긴 것이다.
//
// hub README상 etaMin은 "confirmed 병원만 필요"이지만, 이 목데이터는 모든 상태의
// 병원에 etaMin을 채워둔다 — 병원 대시보드 MapPanel이 선택된 사건이 pending/rejected
// 여도 도착 예상 시간을 비워두지 않고 보여주도록 화면 확인용으로 채운 값이다(실제
// 카카오내비 연동은 별도 작업, 2026-08-11). distanceKm 대비 대략 2.8배로 어림잡았다.
export const mockHubMatchResult: HubMatchResult = {
  caseId: "case-mock-demo",
  patientInfo: {
    injuryStatus: ["의식 저하", "호흡 곤란"],
    expectedDiagnosis: "흉부 손상",
    severityTag: "high",
    rawTranscript: "구급대원: 환자 50대 남성, 교통사고 흉부 충격입니다... A병원: 네 잠시만요...",
    filteredTranscript: "환자 50대 남성, 교통사고 흉부 충격. 의식 저하, 호흡 곤란.",
  },
  zoneActive: [1, 2],
  hospitals: [
    {
      hospitalId: "A",
      name: "A병원",
      gps: { lat: 35.1791, lng: 128.1058 },
      distanceKm: 1.4,
      specialtyMatch: { department: "외과", score: 0.61 },
      availableBedCount: 4,
      bedCountUnknown: false,
      status: "pending",
      etaMin: 4,
      // info-v2 신뢰도 진단 예시(설명용) — 병원 신고는 없지만 전문병원 지정이
      // 있어 낮게 잡히지 않은 케이스.
      reliability: {
        group: "복부응급수술",
        score: 0.8,
        confidence: "medium",
        basis: ["병원 신고 없음(정보미제공)", "전문병원 지정: 외과응급"],
      },
    },
    {
      hospitalId: "B",
      name: "B병원",
      gps: { lat: 35.1802, lng: 128.1101 },
      distanceKm: 1.9,
      specialtyMatch: { department: "흉부외과", score: 0.74 },
      availableBedCount: 6,
      bedCountUnknown: false,
      status: "approved",
      etaMin: 5,
      reliability: {
        group: "대동맥응급",
        score: 1.0,
        confidence: "high",
        basis: ["병원 신고: 가능", "마지막 입력 3분 전"],
      },
    },
    {
      hospitalId: "C",
      name: "C병원",
      gps: { lat: 35.1795, lng: 128.1076 },
      distanceKm: 2.1,
      specialtyMatch: { department: "흉부외과", score: 0.82 },
      availableBedCount: 12,
      bedCountUnknown: false,
      status: "confirmed",
      etaMin: 6,
    },
    {
      hospitalId: "D",
      name: "D병원",
      gps: { lat: 35.1768, lng: 128.1122 },
      distanceKm: 2.6,
      specialtyMatch: { department: "정형외과", score: 0.35 },
      availableBedCount: 0,
      bedCountUnknown: false,
      status: "rejected",
      etaMin: 7,
    },
    {
      // 병상 수가 "확인된 만실"(D병원)이 아니라 "미상"인 경우의 예시 —
      // availableBedCount는 D와 똑같이 0이지만 화면엔 "병상 없음"이 아니라
      // "병상 미상"으로 떠야 한다.
      hospitalId: "E",
      name: "E병원",
      gps: { lat: 35.1820, lng: 128.1030 },
      distanceKm: 3.0,
      specialtyMatch: { department: "외과", score: 0.48 },
      availableBedCount: 0,
      bedCountUnknown: true,
      status: "pending",
      etaMin: 8,
    },
  ],
  source: "rule",
};

// 위 사건은 C병원이 이미 confirmed라, 병원 대시보드에서 A/B/D/E로 들어가면
// "다른 병원으로 확정된 사건은 숨긴다" 규칙에 걸려 카드가 안 보인다(의도된
// 동작). 아직 아무도 확정 안 된 사건도 mock으로 흘려보내야 병원 쪽에서
// 승인/불가 배지·번복 가능한 버튼을 확인할 수 있어서 하나 더 둔다.
export const mockHubMatchResultOngoing: HubMatchResult = {
  caseId: "case-mock-demo-2",
  ambulanceName: "구급 1호차",
  patientInfo: {
    injuryStatus: ["복통", "오심"],
    expectedDiagnosis: "급성 복부 손상 의심",
    severityTag: "medium",
    rawTranscript: "구급대원: 환자 30대 여성, 복부 통증 호소 중입니다...",
    filteredTranscript: "30대 여성, 복부 통증. 오심 동반.",
  },
  zoneActive: [1],
  hospitals: [
    { hospitalId: "A", name: "A병원", gps: { lat: 35.1791, lng: 128.1058 }, distanceKm: 1.1,
      specialtyMatch: { department: "외과", score: 0.55 }, availableBedCount: 2, bedCountUnknown: false,
      status: "pending", etaMin: 3 },
    { hospitalId: "B", name: "B병원", gps: { lat: 35.1802, lng: 128.1101 }, distanceKm: 2.3,
      specialtyMatch: { department: "외과", score: 0.7 }, availableBedCount: 3, bedCountUnknown: false,
      status: "approved", etaMin: 6 },
    { hospitalId: "D", name: "D병원", gps: { lat: 35.1768, lng: 128.1122 }, distanceKm: 2.9,
      specialtyMatch: { department: "정형외과", score: 0.3 }, availableBedCount: 1, bedCountUnknown: false,
      status: "rejected", etaMin: 8 },
  ],
  source: "rule",
};

// 실제 구급차 레지스트리(Supabase ambulances 테이블)엔 3대(구급 1~3호차)가
// 있고, 이 3대가 동시에 사건을 진행할 수 있다 — 병원 하나가 여러 구급차의
// 후보 목록에 동시에 걸리는 상황을 mock으로 재현하려고 A병원이 공통으로
// 들어가는 사건을 2개 더 둔다(위 case-mock-demo-2까지 합쳐 총 3건 동시 진행,
// 2026-08-11 요청).
export const mockHubMatchResultAmbulance2: HubMatchResult = {
  caseId: "case-mock-demo-3",
  ambulanceName: "구급 2호차",
  patientInfo: {
    injuryStatus: ["고관절 통증", "보행 불가"],
    expectedDiagnosis: "낙상 · 고관절 골절 의심",
    severityTag: "medium",
    rawTranscript: "구급대원: 환자 70대 여성, 계단에서 낙상했습니다...",
    filteredTranscript: "70대 여성, 계단 낙상. 고관절 통증, 보행 불가.",
  },
  zoneActive: [1, 2],
  hospitals: [
    { hospitalId: "A", name: "A병원", gps: { lat: 35.1791, lng: 128.1058 }, distanceKm: 2.0,
      specialtyMatch: { department: "정형외과", score: 0.6 }, availableBedCount: 4, bedCountUnknown: false,
      status: "pending", etaMin: 6 },
    { hospitalId: "C", name: "C병원", gps: { lat: 35.1795, lng: 128.1076 }, distanceKm: 2.4,
      specialtyMatch: { department: "정형외과", score: 0.68 }, availableBedCount: 12, bedCountUnknown: false,
      status: "approved", etaMin: 7 },
    { hospitalId: "E", name: "E병원", gps: { lat: 35.1820, lng: 128.1030 }, distanceKm: 3.5,
      specialtyMatch: { department: "외과", score: 0.4 }, availableBedCount: 0, bedCountUnknown: true,
      status: "pending", etaMin: 10 },
  ],
  source: "rule",
};

export const mockHubMatchResultAmbulance3: HubMatchResult = {
  caseId: "case-mock-demo-4",
  ambulanceName: "구급 3호차",
  patientInfo: {
    injuryStatus: ["두드러기", "호흡 곤란"],
    expectedDiagnosis: "급성 알레르기 반응 의심",
    severityTag: "high",
    rawTranscript: "구급대원: 환자 20대 남성, 벌에 쏘인 뒤 전신 두드러기와 호흡 곤란입니다...",
    filteredTranscript: "20대 남성, 벌 쏘임 이후 전신 두드러기, 호흡 곤란.",
  },
  zoneActive: [1],
  hospitals: [
    { hospitalId: "A", name: "A병원", gps: { lat: 35.1791, lng: 128.1058 }, distanceKm: 1.6,
      specialtyMatch: { department: "응급의학과", score: 0.5 }, availableBedCount: 4, bedCountUnknown: false,
      status: "rejected", etaMin: 4 },
    { hospitalId: "B", name: "B병원", gps: { lat: 35.1802, lng: 128.1101 }, distanceKm: 2.1,
      specialtyMatch: { department: "외과", score: 0.45 }, availableBedCount: 6, bedCountUnknown: false,
      status: "pending", etaMin: 6 },
    { hospitalId: "D", name: "D병원", gps: { lat: 35.1768, lng: 128.1122 }, distanceKm: 2.8,
      specialtyMatch: { department: "정형외과", score: 0.3 }, availableBedCount: 0, bedCountUnknown: false,
      status: "approved", etaMin: 8 },
  ],
  source: "rule",
};
