"use client";

import { css } from "styled-system/css";
import { formatElapsed, useElapsedSeconds } from "@/hooks/use-elapsed-time";

export function AmbulanceTopBar({
  confirmed,
  connectionMode,
  since,
}: {
  confirmed: boolean;
  connectionMode: "live" | "mock";
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
          구급차 대시보드 · 이송 지원
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
            color: confirmed ? "hospitalStatus.confirmed" : "brand",
          })}
        >
          <span
            className={css({
              width: "1.5",
              height: "1.5",
              borderRadius: "full",
              backgroundColor: confirmed ? "hospitalStatus.confirmed" : "brand",
              animation: "beat 1.8s ease-in-out infinite",
            })}
          />
          {confirmed ? "이송 확정" : "병원 선택 대기"}
        </span>
        <span
          className={css({
            fontSize: "xs",
            color: connectionMode === "live" ? "hospitalStatus.confirmed" : "ink2",
          })}
        >
          {connectionMode === "live" ? "● 실시간 연동" : "○ 목데이터 모드"}
        </span>
        <span className={css({ fontSize: "xs", color: "ink2" })}>
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
