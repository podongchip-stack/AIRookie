"use client";

import { css } from "styled-system/css";
import {
  dangerButtonStyle,
  mintButtonStyle,
  primaryButtonStyle,
} from "@/components/ui/button-styles";
import type { ApprovalAction, DashboardRole } from "@/types/dashboard";

interface ApprovalActionsProps {
  role: DashboardRole;
  hospitalId: string | null;
  onAction: (action: ApprovalAction) => void;
}

// 병원의 "승인"은 후보 등록일 뿐이고, 구급대원의 "이송 승인"이 최종 확정이다 (CLAUDE.md).
export function ApprovalActions({ role, hospitalId, onAction }: ApprovalActionsProps) {
  const disabled = !hospitalId;

  function dispatch(action: ApprovalAction["action"], actor: ApprovalAction["actor"]) {
    if (!hospitalId) return;
    onAction({
      action,
      hospital_id: hospitalId,
      actor,
      timestamp: new Date().toISOString(),
    });
  }

  if (role === "hospital") {
    return (
      <div className={css({ display: "flex", gap: "3", justifyContent: "flex-end" })}>
        <button
          type="button"
          disabled={disabled}
          className={dangerButtonStyle}
          onClick={() => dispatch("hospital_reject", "hospital")}
        >
          불가
        </button>
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
