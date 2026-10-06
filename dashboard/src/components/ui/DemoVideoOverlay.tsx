"use client";

import { useEffect, useRef, useState } from "react";
import type { DemoMode } from "@/types/dashboard";

// 시연 영상 모드(2026-10-06) — hub가 알린 모드가 video면 화면 전체를 이 화면의 영상으로 덮는다. 아래 시연 화면은 그대로
// 살아 있어서(연결·상태 유지) [시연 모드]를 누르면 새로고침 없이 직전 상태로 돌아온다. 영상은 dashboard/public/demo-videos/
// (Git LFS). 영상 모드에 들어올 때마다 처음부터 튼다.
// - 기본: 영상을 계속 반복
// - withStage(관제 지도): 영상이 끝나면 /verify/stage를 한 바퀴(10장) 돌리고 다시 영상 — stage가 마지막 장에서 첫 장으로
//   넘어갈 때 보내는 신호(goldenlink-stage-cycle)로 안다
// 페이지마다 화면 갈래(자동 전환·특정 구급차 등)가 여럿이라, 페이지 연결과 별개로 자기 연결 하나를 둔다. identify를 보내지
// 않아 사건 데이터는 받지 않고, hub가 연결 즉시·전환 때 보내는 demo_mode만 본다.
export function DemoVideoOverlay({ src, withStage = false }: { src: string; withStage?: boolean }) {
  const { mode, send } = useDemoMode();
  if (mode !== "video") return null;
  return <Overlay src={src} withStage={withStage} onLive={() => send("live")} />;
}

function useDemoMode() {
  const [mode, setMode] = useState<DemoMode>("live");
  const socketRef = useRef<WebSocket | null>(null);
  useEffect(() => {
    const url = process.env.NEXT_PUBLIC_DASHBOARD_WS_URL;
    if (!url) return;
    let disposed = false;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let delay = 1000;
    const connect = () => {
      const socket = new WebSocket(url);
      socketRef.current = socket;
      socket.onopen = () => { delay = 1000; };
      socket.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg?.type === "demo_mode" && (msg.mode === "live" || msg.mode === "video")) setMode(msg.mode);
        } catch {
          // 다른 메시지는 무시
        }
      };
      socket.onclose = () => {
        if (disposed) return;
        retry = setTimeout(connect, delay);
        delay = Math.min(delay * 2, 10000);
      };
    };
    connect();
    return () => {
      disposed = true;
      if (retry) clearTimeout(retry);
      socketRef.current?.close();
    };
  }, []);
  const send = (next: DemoMode) => {
    const socket = socketRef.current;
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "demo_mode", mode: next }));
  };
  return { mode, send };
}

function Overlay({ src, withStage = false, onLive }: { src: string; withStage?: boolean; onLive: () => void }) {
  const [part, setPart] = useState<"video" | "stage">("video");
  const videoRef = useRef<HTMLVideoElement | null>(null);

  // 소리가 있는 영상(관제 지도)은 소리를 켜고 틀되, 브라우저가 막으면(그 화면을 아직 클릭하지 않음) 음소거로라도 튼다
  useEffect(() => {
    const video = videoRef.current;
    if (!video || part !== "video") return;
    video.muted = false;
    video.play().catch(() => {
      video.muted = true;
      void video.play();
    });
  }, [part]);

  useEffect(() => {
    if (!withStage) return;
    const onMessage = (e: MessageEvent) => {
      if (e.origin === window.location.origin && e.data?.type === "goldenlink-stage-cycle") setPart("video");
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [withStage]);

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 10000, background: "#000" }}>
      {part === "video" ? (
        <video
          ref={videoRef}
          src={src}
          playsInline
          loop={!withStage}
          onEnded={withStage ? () => setPart("stage") : undefined}
          style={{ width: "100%", height: "100%", objectFit: "contain", display: "block" }}
        />
      ) : (
        <iframe title="검증 스테이지" src="/verify/stage" style={{ width: "100%", height: "100%", border: 0, display: "block" }} />
      )}
      <button
        type="button"
        onClick={onLive}
        style={{
          position: "absolute", right: 16, bottom: 16, padding: "8px 14px", borderRadius: 10, cursor: "pointer",
          background: "rgba(255,255,255,0.14)", border: "1px solid rgba(255,255,255,0.28)", color: "rgba(255,255,255,0.85)",
          fontSize: 13, fontWeight: 700,
        }}
      >
        시연 모드
      </button>
    </div>
  );
}
