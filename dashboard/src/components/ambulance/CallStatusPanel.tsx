"use client";

import { useEffect, useRef, useState } from "react";
import { css, cx } from "styled-system/css";
import { Tag } from "@/components/hospital/Tag";
import { thinScrollbarStyle } from "@/components/ui/scrollbar-style";
import type { CallStatus, CallTranscriptLine } from "@/types/dashboard";

function mmss(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

const clock = () => Date.now();

// 구급차 대시보드의 통화 현황(2026-10-03, 보기 전용). 통화는 대원 휴대폰 전화 앱(/phone, 첫 페이지 P-<apid>)으로만
// 하고 — hub를 --dashboard-call 없이 띄운 기본값 — 이 패널은 그 통화의 상태와 voice 실시간 자막(AI)만 보여 준다.
// 통화 중엔 대원이 휴대폰을 귀에 대고 있어 자막을 못 보므로, 함께 탄 대원·시연 화면용이다.
// --dashboard-call이면 이 패널 대신 [통화 시작] 버튼이 있는 CallDemoPanel이 뜬다.
export function CallStatusPanel({
  apid,
  callStatus,
  voiceLines,
  sentHospitalCount,
  waitingHint,
}: {
  apid: string;
  callStatus: CallStatus | null;
  voiceLines: CallTranscriptLine[];
  sentHospitalCount: number | null;
  // 통화 전 안내 대신 보일 문구(현장 도착 전 등)
  waitingHint?: string | null;
}) {
  const calling = callStatus?.state === "calling";
  const [now, setNow] = useState(clock);
  useEffect(() => {
    if (!calling) return;
    const timer = setInterval(() => setNow(clock()), 1000);
    return () => clearInterval(timer);
  }, [calling]);

  const boxRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const box = boxRef.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [voiceLines.length]);

  const hospital = callStatus?.hospitalName ?? "병원";
  const device = callStatus?.device === "tablet" ? "대시보드" : "휴대폰";
  let status: { text: string; tone: "idle" | "calling" | "ended" };
  if (calling) {
    status = { text: `📞 ${device}로 ${hospital}과 통화 중 · ${mmss(now - Date.parse(callStatus.startedAt))}`, tone: "calling" };
  } else if (callStatus?.state === "ended") {
    status = {
      text:
        sentHospitalCount != null
          ? `통화 종료 · 환자 정보가 후보 병원 ${sentHospitalCount}곳에 전달됐습니다`
          : `통화 종료(${hospital}) · 환자 정보를 정리하는 중…`,
      tone: "ended",
    };
  } else {
    status = { text: waitingHint ?? "통화 전 — 대원 휴대폰의 전화 앱으로 병원에 전화하세요", tone: "idle" };
  }

  return (
    <section
      className={css({
        display: "flex",
        flexDirection: "column",
        height: "100%",
        borderWidth: "1px",
        borderColor: "line",
        borderRadius: "panel",
        backgroundColor: "surface",
        padding: "4",
        minWidth: "0",
      })}
    >
      <header
        className={css({
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: "2.5",
          paddingBottom: "3",
          marginBottom: "3",
          borderBottomWidth: "1px",
          borderColor: "line",
        })}
      >
        <h2 className={css({ fontSize: "sm", fontWeight: "semibold", letterSpacing: "-0.01em", color: "ink" })}>
          통화 현황
          <span className={css({ display: "block", fontSize: "xs", fontWeight: "normal", color: "ink", marginTop: "0.5" })}>
            휴대폰 전화 앱 <b>P-{apid}</b> 의 통화 · 실시간 자막
          </span>
        </h2>
        <Tag source="ai">voice 음성 인식</Tag>
      </header>

      <div className={css({ display: "flex", flexDirection: "column", gap: "3", flex: "1", minHeight: "0" })}>
        <p
          className={css({
            flexShrink: "0",
            paddingX: "3",
            paddingY: "2.5",
            borderRadius: "field",
            fontSize: "sm",
            fontWeight: "semibold",
            fontVariantNumeric: "tabular-nums",
            borderWidth: "1px",
          })}
          style={
            status.tone === "calling"
              ? { color: "#16222E", backgroundColor: "#E6F6F0", borderColor: "#0E9F6E" }
              : status.tone === "ended"
                ? { color: "#16222E", backgroundColor: "#F8FAFC", borderColor: "#E2E8EF" }
                : { color: "#55697C", backgroundColor: "#F8FAFC", borderColor: "#E2E8EF", fontWeight: 400 }
          }
        >
          {status.text}
        </p>

        <div
          ref={boxRef}
          className={cx(
            css({
              flex: "1",
              minHeight: "0",
              overflowY: "auto",
              padding: "3",
              backgroundColor: "surfaceSub",
              borderWidth: "1px",
              borderColor: "line",
              borderRadius: "field",
              fontSize: "sm",
              color: "ink",
              lineHeight: "1.6",
            }),
            thinScrollbarStyle,
          )}
        >
          {voiceLines.length > 0 ? (
            <ol className={css({ display: "flex", flexDirection: "column", gap: "1" })}>
              {voiceLines.map((line) => (
                <li key={`${line.start}-${line.text}`} className={css({ display: "flex", gap: "2" })}>
                  <span className={css({ color: "ink3", fontVariantNumeric: "tabular-nums", flexShrink: "0" })}>
                    {mmss(line.start * 1000)}
                  </span>
                  <span>{line.text}</span>
                </li>
              ))}
            </ol>
          ) : (
            <p className={css({ color: "ink3" })}>
              {calling ? "말이 끊길 때마다 인식된 문장이 여기에 뜹니다." : "통화가 시작되면 실시간 자막이 여기 표시됩니다."}
            </p>
          )}
        </div>

        <p className={css({ fontSize: "2xs", color: "ink3", flexShrink: "0" })}>
          이 화면에선 통화를 걸지 않습니다(hub를 --dashboard-call로 띄우면 [통화 시작]이 생깁니다).
        </p>
      </div>
    </section>
  );
}
