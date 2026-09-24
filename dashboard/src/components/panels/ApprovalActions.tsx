"use client";

import { useState } from "react";
import { css } from "styled-system/css";
import {
  mintButtonStyle,
  primaryButtonStyle,
} from "@/components/ui/button-styles";
import type { ApprovalAction, DashboardRole, RejectionReason } from "@/types/dashboard";

// info-v2 거절 로그(CLAUDE.md "거절 로그" 절, 2026-08-12)가 쓰는 4축 어휘를 그대로
// 라벨만 한글로 붙인다. "사유 없음"(UNSPECIFIED)을 맨 위에 둬 사유를 모를 때도
// 바로 거절을 보낼 수 있게 한다 — 사유 선택을 강제하면 급한 상황에서 거절 자체가
// 늦어질 수 있다.
const REJECTION_REASON_GROUPS: { label: string; options: { value: RejectionReason; label: string }[] }[] = [
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

const rejectSelectStyle = css({
  paddingX: "3",
  paddingY: "1.5",
  borderRadius: "full",
  fontSize: "sm",
  fontWeight: "semibold",
  color: "coral",
  backgroundColor: "surface",
  borderWidth: "1px",
  borderColor: "coral",
  cursor: "pointer",
  _hover: { backgroundColor: "coralSoft" },
  _disabled: { opacity: 0.4, cursor: "not-allowed" },
});

interface ApprovalActionsProps {
  role: DashboardRole;
  hospitalId: string | null;
  // 여러 사건이 동시에 진행될 수 있어, 어느 사건에 대한 승인인지 hub에
  // 명시해야 한다 (해당 사건의 HubMatchResult.caseId를 그대로 넘긴다).
  caseId: string;
  onAction: (action: ApprovalAction) => void;
}

// 병원의 "승인"은 후보 등록일 뿐이고, 구급대원의 "이송 승인"이 최종 확정이다 (CLAUDE.md).
export function ApprovalActions({ role, hospitalId, caseId, onAction }: ApprovalActionsProps) {
  const disabled = !hospitalId;
  // select는 값이 남아있으면 같은 사유를 다시 골라도 onChange가 안 터진다 — 매번
  // "" 로 리셋해 다음 거절도 "불가 (사유 선택)" 상태에서 새로 고르게 한다.
  const [reasonValue, setReasonValue] = useState("");

  function dispatch(action: ApprovalAction["action"], actor: ApprovalAction["actor"], reason?: RejectionReason) {
    if (!hospitalId) return;
    onAction({
      caseId,
      action,
      hospital_id: hospitalId,
      actor,
      timestamp: new Date().toISOString(),
      ...(reason ? { reason } : {}),
    });
  }

  if (role === "hospital") {
    return (
      <div className={css({ display: "flex", gap: "2", justifyContent: "flex-end" })}>
        <select
          disabled={disabled}
          value={reasonValue}
          onChange={(event) => {
            const value = event.target.value as RejectionReason | "";
            if (!value) return;
            dispatch("hospital_reject", "hospital", value);
            setReasonValue("");
          }}
          className={rejectSelectStyle}
        >
          <option value="" disabled>
            불가 (사유 선택)
          </option>
          <option value="UNSPECIFIED">사유 없음</option>
          {REJECTION_REASON_GROUPS.map((group) => (
            <optgroup key={group.label} label={group.label}>
              {group.options.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
        <button
          type="button"
          disabled={disabled}
          className={mintButtonStyle}
          onClick={() => dispatch("hospital_approve", "hospital")}
        >
          병원 승인
        </button>
      </div>
    );
  }

  return (
    <div className={css({ display: "flex", justifyContent: "flex-end" })}>
      <button
        type="button"
        disabled={disabled}
        className={primaryButtonStyle}
        onClick={() => dispatch("final_approval", "paramedic")}
      >
        이송 승인
      </button>
    </div>
  );
}
