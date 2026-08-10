"use client";

import { css } from "styled-system/css";
import { formatElapsed, useElapsedSeconds } from "@/hooks/use-elapsed-time";

export function HospitalTopBar({
  caseCount,
  connectionMode,
  since,
}: {
  // 여러 구급차가 동시에 본원을 후보로 걸 수 있어(다중 사건 지원), 사건 하나의
  // status 대신 "본원이 후보로 걸린 사건이 몇 건인지"를 보여준다 — 개별 사건의
  // 상태는 각 카드(CaseMatchPanel)에 이미 표시된다.
  caseCount: number;
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
          {caseCount > 0 ? `진행 중인 사건 ${caseCount}건` : "수신 대기 중"}
        </span>
        <span
          className={css({
            fontSize: "xs",
            color: connectionMode === "live" ? "hospitalStatus.confirmed" : "ink2",
          })}
        >
          {connectionMode === "live" ? "● 실시간 연동" : "○ 목데이터 모드"}
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
