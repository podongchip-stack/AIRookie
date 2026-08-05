"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { mockHubMatchResult } from "@/lib/mock-data";
import type { ApprovalAction, DashboardState, HubMatchResult } from "@/types/dashboard";

const INITIAL_STATE: DashboardState = {
  matchResult: null,
  receivedAt: null,
};

// feature/hub가 dashboard와 직접 통신하는 유일한 브랜치다 (CLAUDE.md). voice/info는
// hub를 거쳐서만 도착하므로, dashboard가 실제로 받는 건 hub의 통합 매칭 결과 메시지
// 하나뿐이다. NEXT_PUBLIC_DASHBOARD_WS_URL이 설정되지 않으면 목데이터를 흘려보내
// 화면 작업을 진행할 수 있게 한다.
export function useDashboardSocket() {
  const [state, setState] = useState<DashboardState>(INITIAL_STATE);
  const [connectionMode, setConnectionMode] = useState<"live" | "mock">(
    "mock",
  );
  const socketRef = useRef<WebSocket | null>(null);

  const applyMatchResult = useCallback((matchResult: HubMatchResult) => {
    setState((prev) => ({
      matchResult,
      receivedAt: prev.receivedAt ?? new Date().toISOString(),
    }));
  }, []);

  useEffect(() => {
    const wsUrl = process.env.NEXT_PUBLIC_DASHBOARD_WS_URL;

    if (!wsUrl) {
      const timer = setTimeout(() => applyMatchResult(mockHubMatchResult), 900);
      return () => clearTimeout(timer);
    }

    const socket = new WebSocket(wsUrl);
    socketRef.current = socket;

    socket.onopen = () => setConnectionMode("live");
    socket.onclose = () => setConnectionMode("mock");
    socket.onerror = () => setConnectionMode("mock");
    socket.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data) as HubMatchResult;
        applyMatchResult(parsed);
      } catch {
        // 파싱 불가능한 메시지는 무시
      }
    };

    return () => socket.close();
  }, [applyMatchResult]);

  const sendAction = useCallback((action: ApprovalAction) => {
    const socket = socketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(action));
    } else {
      console.info("[mock] 승인 액션 전송(WS 미연결):", action);
    }
  }, []);

  return { state, connectionMode, sendAction };
}
