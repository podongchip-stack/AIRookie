"use client";

import { useState } from "react";
import { css } from "styled-system/css";
import {
  mintButtonStyle,
  primaryButtonStyle,
} from "@/components/ui/button-styles";
import { REJECTION_REASON_GROUPS } from "@/lib/rejection";
import type { ApprovalAction, DashboardRole, RejectionReason } from "@/types/dashboard";

// info-v2 거절 로그(CLAUDE.md "거절 로그" 절, 2026-08-12)가 쓰는 4축 어휘를 그대로
// 라벨만 한글로 붙인다. "사유 없음"(UNSPECIFIED)을 맨 위에 둬 사유를 모를 때도
// 바로 거절을 보낼 수 있게 한다 — 사유 선택을 강제하면 급한 상황에서 거절 자체가
// 늦어질 수 있다.
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
  // 이 병원이 이미 [불가] 처리했을 때 고른 사유(hub rejectReason, 2026-10-03). 선택칸이 이 값을 보여준다 —
  // 예전엔 보낸 직후 "불가 (사유 선택)"으로 되돌아가 무슨 사유로 거절했는지 화면에 안 남았다.
  currentReason?: string | null;
}

// 병원의 "승인"은 후보 등록일 뿐이고, 구급대원의 "이송 승인"이 최종 확정이다 (CLAUDE.md).
export function ApprovalActions({ role, hospitalId, caseId, onAction, currentReason = null }: ApprovalActionsProps) {
  const disabled = !hospitalId;
  // 방금 고른 사유 — hub 응답(currentReason)이 오기 전에도 선택칸에 남게 한다. [병원 승인]으로 번복하면 지운다.
  const [reasonValue, setReasonValue] = useState("");
  const shownReason = currentReason ?? reasonValue;

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
          value={shownReason}
          onChange={(event) => {
            const value = event.target.value as RejectionReason | "";
            if (!value) return;
            dispatch("hospital_reject", "hospital", value);
            setReasonValue(value);
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
          onClick={() => {
            dispatch("hospital_approve", "hospital");
            setReasonValue("");
          }}
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

// 확정 병원 도착 뒤의 실제 수용 결과(2026-10-01). 구급차가 도착하면 이 결과를 꼭 골라야 한다 — 구급차는
// 결과가 나올 때까지 병원 앞에서 기다린다. 도착 후 수용 불가는 신뢰도 모델의 가장 강한 "정보가 틀렸다"
// 관측이라 사유를 같이 받는다. ready가 false면(구급차 도착 전) 버튼을 막는다.
export function ArrivalActions({
  hospitalId,
  caseId,
  ready,
  onAction,
}: {
  hospitalId: string;
  caseId: string;
  ready: boolean;
  onAction: (action: ApprovalAction) => void;
}) {
  const [reasonValue, setReasonValue] = useState("");

  function dispatch(action: "arrival_accepted" | "arrival_refused", reason?: RejectionReason) {
    onAction({
      caseId,
      action,
      hospital_id: hospitalId,
      actor: "hospital",
      timestamp: new Date().toISOString(),
      ...(reason ? { reason } : {}),
    });
  }

  return (
    <div className={css({ display: "flex", gap: "2", justifyContent: "flex-end" })}>
      <select
        disabled={!ready}
        value={reasonValue}
        onChange={(event) => {
          const value = event.target.value as RejectionReason | "";
          if (!value) return;
          dispatch("arrival_refused", value);
          setReasonValue("");
        }}
        className={rejectSelectStyle}
      >
        <option value="" disabled>
          도착 후 수용 불가 (사유)
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
      <button type="button" disabled={!ready} className={mintButtonStyle} onClick={() => dispatch("arrival_accepted")}>
        환자 수용 완료
      </button>
    </div>
  );
}
