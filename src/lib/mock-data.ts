import type {
  CallSummaryMessage,
  HospitalMatchMessage,
  VitalsMessage,
} from "@/types/dashboard";

// backend(voice/vital)가 아직 준비되지 않았을 때 대시보드 UI를 확인하기 위한 목데이터.
// CLAUDE.md의 예시 JSON을 그대로 따른다.

export const mockCallSummary: CallSummaryMessage = {
  transcript: {
    raw_text:
      "구급대원: 환자 50대 남성, 교통사고 흉부 충격입니다... A병원: 네 잠시만요...",
    filtered_text: "환자 50대 남성, 교통사고 흉부 충격. 의식 저하, 호흡 곤란.",
    language: "ko",
    timestamp: "2026-07-28T14:32:31Z",
    duration_sec: 42.3,
  },
  summary: {
    patient: "50대 남성",
    mechanism: "교통사고 · 흉부 충격",
    symptoms: ["의식 저하", "호흡 곤란"],
    treatment: ["산소 공급", "지혈 완료"],
    severity_tag: "high",
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
