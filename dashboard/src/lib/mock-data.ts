import type { HubMatchResult } from "@/types/dashboard";

// feature/hub의 실시간 통신(Flask)이 아직 붙지 않았을 때 대시보드 UI를 확인하기 위한 목데이터.
// feature/hub README.md "출력 스키마 4" 예시 JSON을 그대로 옮긴 것이다.
export const mockHubMatchResult: HubMatchResult = {
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
      status: "pending",
    },
    {
      hospitalId: "B",
      name: "B병원",
      gps: { lat: 35.1802, lng: 128.1101 },
      distanceKm: 1.9,
      specialtyMatch: { department: "흉부외과", score: 0.74 },
      availableBedCount: 6,
      status: "approved",
      etaMin: 5,
    },
    {
      hospitalId: "C",
      name: "C병원",
      gps: { lat: 35.1795, lng: 128.1076 },
      distanceKm: 2.1,
      specialtyMatch: { department: "흉부외과", score: 0.82 },
      availableBedCount: 12,
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
      status: "rejected",
    },
  ],
  source: "rule",
};
