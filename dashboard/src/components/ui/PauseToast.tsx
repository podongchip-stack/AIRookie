"use client";

import { useEffect, useState } from "react";

// 시연 일시정지 안내(2026-10-05) — 일시정지 중에 조작 버튼을 누르면 화면 위쪽에 "현재 시연 일시정지 중입니다."가 잠깐
// 떴다가 사라진다. 화면이 먼저 막고(notify), hub가 거부한 경우(action_refused)도 같은 안내를 띄운다.
export const PAUSED_MESSAGE = "현재 시연 일시정지 중입니다.";
const SHOW_MS = 2500;

/**
 * @param refused hub가 조작을 거부했을 때(일시정지 등) — 같은 안내를 띄운다
 * @param notice 거부가 아닌 일반 안내를 같은 토스트로 띄울 때(2026-10-22, 병원 미선택 통보 등).
 *               문구를 호출부가 정하므로 토스트 UI만 빌려 쓰는 셈이다.
 */
export function usePauseToast(
  refused: { at: number; reason: string } | null,
  notice?: { at: number; text: string } | null,
) {
  const [shownAt, setShownAt] = useState<number | null>(null);
  const [message, setMessage] = useState(PAUSED_MESSAGE);
  // hub가 거부를 알려 오면(다른 탭에서 우회한 경우 등) 같은 안내 — 렌더 중 이전 값과 비교(effect 대신)
  const [seenRefusal, setSeenRefusal] = useState<number | null>(refused?.at ?? null);
  if (refused && refused.at !== seenRefusal) {
    setSeenRefusal(refused.at);
    setMessage(refused.reason === "paused" ? PAUSED_MESSAGE
      : refused.reason === "already_arrived"
        ? "이미 병원에 도착해 이송 병원을 바꿀 수 없습니다. 현재 병원의 수용 불가 처리 후 다시 선택해 주세요."
        : "지금은 이 조작을 할 수 없습니다.");
    setShownAt(refused.at);
  }
  const [seenNotice, setSeenNotice] = useState<number | null>(notice?.at ?? null);
  if (notice && notice.at !== seenNotice) {
    setSeenNotice(notice.at);
    setMessage(notice.text);
    setShownAt(notice.at);
  }
  useEffect(() => {
    if (shownAt == null) return;
    const timer = setTimeout(() => setShownAt(null), SHOW_MS);
    return () => clearTimeout(timer);
  }, [shownAt]);

  const notify = () => {
    setMessage(PAUSED_MESSAGE);
    setShownAt(Date.now());
  };
  /** paused면 안내만 띄우고 fn을 실행하지 않는다 */
  const guard = (paused: boolean | null | undefined, fn: () => void) => () => {
    if (paused) notify();
    else fn();
  };
  const node = shownAt != null ? <PauseToast key={shownAt} text={message} /> : null;
  return { notify, guard, node };
}

function PauseToast({ text }: { text: string }) {
  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        position: "fixed", top: 16, left: "50%", transform: "translateX(-50%)", zIndex: 1000,
        display: "flex", alignItems: "center", gap: 10, padding: "12px 20px", borderRadius: 14,
        background: "#14213D", color: "#FFFFFF", fontSize: 14, fontWeight: 700,
        boxShadow: "0 8px 24px rgba(20, 33, 61, 0.28)", whiteSpace: "nowrap",
        animation: "gl-toast-in 0.18s ease-out",
      }}
    >
      <style>{"@keyframes gl-toast-in{from{opacity:0;transform:translate(-50%,-8px)}to{opacity:1;transform:translate(-50%,0)}}"}</style>
      <span style={{ display: "inline-flex", gap: 3 }} aria-hidden>
        <span style={{ width: 4, height: 14, borderRadius: 2, background: "#FFB86B" }} />
        <span style={{ width: 4, height: 14, borderRadius: 2, background: "#FFB86B" }} />
      </span>
      {text}
    </div>
  );
}
