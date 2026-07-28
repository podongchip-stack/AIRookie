import type {
  CallSummaryMessage,
  HospitalCapacitySnapshot,
  HospitalMatchMessage,
  VitalsMessage,
} from "@/types/dashboard";

// backend(voice/vital)가 아직 준비되지 않았을 때 대시보드 UI를 확인하기 위한 목데이터.
// CLAUDE.md의 예시 JSON을 기본으로 하되, turns/required_department/trend_note/
// capacity는 아직 정식 스키마가 없는 로컬 확장 필드다 (src/types/dashboard.ts 주석 참고).

export const mockCallSummary: CallSummaryMessage = {
  transcript: {
    raw_text:
      "구급대원: 환자 50대 남성, 교통사고 흉부 충격입니다... A병원: 네 잠시만요...",
    filtered_text: "환자 50대 남성, 교통사고 흉부 충격. 의식 저하, 호흡 곤란.",
    language: "ko",
    timestamp: "2026-07-28T14:32:31Z",
    duration_sec: 42.3,
    turns: [
      {
        speaker: "구급대원",
        timestamp: "14:32:08",
        text: "환자 50대 남성이고 교통사고 흉부 충격입니다. 의식 저하 있고 호흡 곤란 호소 중입니다.",
      },
      {
        speaker: "A병원",
        timestamp: "14:32:19",
        text: "네 잠시만요, 확인 좀 해보고요.",
        excludedFromSummary: true,
      },
      {
        speaker: "구급대원",
        timestamp: "14:32:31",
        text: "혈압 90에 60, 산소포화도 92%입니다. 산소 공급 중이고 지혈은 완료했습니다.",
      },
    ],
  },
  summary: {
    patient: "50대 남성",
    mechanism: "교통사고 · 흉부 충격",
    symptoms: ["의식 저하", "호흡 곤란"],
    treatment: ["산소 공급", "지혈 완료"],
    severity_tag: "high",
    required_department: "흉부외과",
  },
  source: "ai",
  model_used: {
    stt: "faster-whisper-large-v3",
    llm: "qwen3:14b",
  },
};

export const mockVitals: VitalsMessage = {
  vitals: {
    bp_systolic: 90,
    bp_diastolic: 60,
    pulse: 102,
    spo2: 92,
    gcs: 13,
    temperature: 36.4,
    resp_rate: 24,
  },
  timestamp: "2026-07-28T14:33:10Z",
  source: "rule",
  trend_note: "최근 3분 혈압 하강 · 산소포화도 하강 추세",
};

export const mockHospitalCapacity: HospitalCapacitySnapshot = {
  specialist_on_call: true,
  beds_available: 3,
  or_available: false,
  or_available_in_min: 60,
};

export const mockHospitalMatch: HospitalMatchMessage = {
  zone_active: [1, 2],
  hospitals: [
    {
      hospital_id: "A",
      name: "A병원",
      distance_km: 1.4,
      status: "pending",
    },
    {
      hospital_id: "B",
      name: "B병원",
      distance_km: 1.9,
      status: "approved",
      eta_min: 5,
    },
    {
      hospital_id: "C",
      name: "C병원",
      distance_km: 2.1,
      status: "confirmed",
      eta_min: 6,
    },
    {
      hospital_id: "D",
      name: "D병원",
      distance_km: 2.6,
      status: "rejected",
    },
  ],
  source: "rule",
};
