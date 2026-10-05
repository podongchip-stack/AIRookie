"use client";

import { useEffect, useState } from "react";
import { css } from "styled-system/css";
import type { CallStatus } from "@/types/dashboard";

function mmss(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

// 병원 대시보드: 구급대가 휴대폰 통화 화면에서 이 병원을 골라 건 통화(2026-10-03). 통화는 연출이라 음성은 오지
// 않는다 — "지금 이 병원에 전화가 와 있다"는 것과, 끝난 뒤 환자 정보(매칭 결과)가 올 때까지의 상태만 보여 준다.
export function CallStatusBanner({
  statuses,
  arrivedCaseIds,
}: {
  // 이 병원으로 건 통화들
  statuses: CallStatus[];
  // 환자 정보(매칭 결과)가 이미 도착한 사건 — 그 통화는 배너에서 내린다
  arrivedCaseIds: Set<string>;
}) {
  const visible = statuses.filter((s) => s.state === "calling" || !arrivedCaseIds.has(s.caseId));
  const anyCalling = visible.some((s) => s.state === "calling");
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!anyCalling) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [anyCalling]);

  if (visible.length === 0) return null;
  return (
    <div className={css({ display: "flex", flexDirection: "column", gap: "2", marginBottom: "4" })}>
      {visible.map((s) => {
        const calling = s.state === "calling";
        const who = s.ambulanceName ?? `구급 ${s.apid}`;
        return (
          <p
            key={s.caseId}
            className={css({
              paddingX: "4",
              paddingY: "2.5",
              borderRadius: "panel",
              fontSize: "sm",
              fontWeight: "semibold",
              color: "ink",
              backgroundColor: calling ? "mintSoft" : "surfaceSub",
              borderWidth: "1px",
              borderColor: calling ? "mint" : "line",
            })}
          >
            {calling
              ? `📞 ${who} 통화 중 · ${mmss(now - Date.parse(s.startedAt))}`
              : `📞 ${who} 통화 종료 — 환자 정보를 정리해 곧 보냅니다`}
            <span className={css({ fontWeight: "normal", color: "ink2", marginLeft: "2", fontSize: "xs" })}>
              시연용 연출 통화 · 통화 내용은 음성 인식(AI) 뒤 후보 병원 모두에 동시 전달
            </span>
          </p>
        );
      })}
    </div>
  );
}
