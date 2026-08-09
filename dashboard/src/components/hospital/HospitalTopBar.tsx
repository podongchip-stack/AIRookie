"use client";

import { css } from "styled-system/css";
import type { HospitalStatus } from "@/types/dashboard";
import { formatElapsed, useElapsedSeconds } from "@/hooks/use-elapsed-time";

const STATUS_LABEL: Record<HospitalStatus, string> = {
  pending: "수용 판단 대기",
  approved: "후보 등록됨 · 이송 승인 대기",
  rejected: "수용 불가 처리됨",
  confirmed: "이송 확정",
};

export function HospitalTopBar({
  status,
  since,
}: {
  status: HospitalStatus | null;
  since: string | null;
}) {
  const elapsed = useElapsedSeconds(since);

  return (
    <header
      className={css({
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        flexWrap: "wrap",
        gap: "4",
        backgroundColor: "surface",
        borderWidth: "1px",
        borderColor: "line",
        borderRadius: "panel",
        paddingX: "4.5",
        paddingY: "3",
        marginBottom: "3.5",
      })}
    >
      <div className={css({ display: "flex", alignItems: "center", gap: "3" })}>
        <span
          className={css({
            fontSize: "md",
            fontWeight: "bold",
            letterSpacing: "-0.01em",
            color: "ink",
          })}
        >
          골든<span className={css({ color: "navy" })}>링크</span>
        </span>
        <span
          className={css({
            fontSize: "xs",
            fontWeight: "semibold",
            color: "navy",
            backgroundColor: "navySoft",
            paddingX: "1.5",
            paddingY: "0.5",
            borderRadius: "chip",
          })}
        >
          v2.0
        </span>
        <span
          className={css({
            fontSize: "xs",
            color: "ink",
            paddingLeft: "3",
            borderLeftWidth: "1px",
            borderColor: "line",
          })}
        >
          병원 대시보드 · 응급의학과 수용 판단
        </span>
      </div>

      <div className={css({ display: "flex", alignItems: "center", gap: "4.5" })}>
        <span
          className={css({
            display: "inline-flex",
            alignItems: "center",
            gap: "1.5",
            fontSize: "xs",
            fontWeight: "semibold",
            color: "brand",
          })}
        >
          <span
            className={css({
              width: "1.5",
              height: "1.5",
              borderRadius: "full",
              backgroundColor: "brand",
              animation: "beat 1.8s ease-in-out infinite",
            })}
          />
          {status ? STATUS_LABEL[status] : "수신 대기 중"}
        </span>
        <span className={css({ fontSize: "xs", color: "ink" })}>
          정보 수신 후{" "}
          <b className={css({ color: "ink", fontWeight: "semibold" })}>
            {formatElapsed(elapsed)}
          </b>{" "}
          경과
        </span>
      </div>
    </header>
  );
}
