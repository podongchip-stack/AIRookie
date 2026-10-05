import type { RejectionReason } from "@/types/dashboard";

// 거절 사유 어휘(4축) — info hospital_score/rejection.py의 REASON_AXIS와 같다. 병원의 [불가] 선택칸과, 고른 사유를
// 다시 보여주는 화면들(병원 카드·구급차 후보·관제 지도, 2026-10-03)이 같은 한국어 이름을 쓰도록 한 곳에 둔다.
// "사유 없음"(UNSPECIFIED)을 맨 위에 둬 사유를 모를 때도 바로 거절을 보낼 수 있게 한다 — 사유 선택을 강제하면 급한
// 상황에서 거절 자체가 늦어질 수 있다.
export const REJECTION_REASON_GROUPS: { label: string; options: { value: RejectionReason; label: string }[] }[] = [
  {
    label: "구조적",
    options: [
      { value: "NO_WARD", label: "병동 없음" },
      { value: "NO_DEPARTMENT", label: "해당 진료과 없음" },
      { value: "NO_EQUIPMENT", label: "필요 장비 없음" },
    ],
  },
  {
    label: "주기적",
    options: [
      { value: "ON_CALL_MISMATCH", label: "당직과 불일치" },
      { value: "NIGHT_UNAVAILABLE", label: "야간 진료 불가" },
    ],
  },
  {
    label: "순간적",
    options: [
      { value: "BEDS_FULL", label: "병상 만실" },
      { value: "OR_OCCUPIED", label: "수술실 사용 중" },
      { value: "STAFF_BUSY", label: "인력 부족" },
    ],
  },
  {
    label: "환자 요인",
    options: [
      { value: "SEVERITY_EXCEEDED", label: "중증도 초과" },
      { value: "AGE_LIMIT", label: "연령 제한" },
    ],
  },
];

const LABELS: Record<string, string> = Object.fromEntries([
  ["UNSPECIFIED", "사유 없음"],
  ...REJECTION_REASON_GROUPS.flatMap((group) => group.options.map((o) => [o.value, o.label])),
]);

// 사유 코드 → 한국어 이름. 모르는 코드(어휘가 늘어난 hub)는 코드 그대로.
export function rejectionReasonLabel(code: string | null | undefined): string | null {
  if (!code) return null;
  return LABELS[code] ?? code;
}

// 병원이 누르지 않았는데도 지금 수용할 수 없는 이유(hub unavailableReason, 규칙 기반 — E-Gen 기준)
export function unavailableReasonLabel(code: string | null | undefined): string | null {
  if (!code) return null;
  return code === "beds_full" ? "병상 없음(E-Gen)" : code;
}
