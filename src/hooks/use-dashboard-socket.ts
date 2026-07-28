"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  mockCallSummary,
  mockHospitalCapacity,
  mockHospitalMatch,
  mockVitals,
} from "@/lib/mock-data";
import type {
  ApprovalAction,
  DashboardState,
  InboundMessage,
} from "@/types/dashboard";

const INITIAL_STATE: DashboardState = {
  callSummary: null,
  vitals: null,
  hospitalMatch: null,
  hospitalCapacity: null,
};

// voice/vital 브랜치는 아직 WS 서버가 없다. NEXT_PUBLIC_DASHBOARD_WS_URL이
// 설정되지 않으면 목데이터를 순차적으로 흘려보내 화면 작업을 진행할 수 있게 한다.
function applyInboundMessage(
  state: DashboardState,
  message: InboundMessage,
): DashboardState {
  if ("transcript" in message) {
    return { ...state, callSummary: message };
  }
  if ("vitals" in message) {
    return { ...state, vitals: message };
  }
  if ("hospitals" in message) {
    return { ...state, hospitalMatch: message };
  }
  if ("specialist_on_call" in message) {
    return { ...state, hospitalCapacity: message };
  }
  return state;
}

export function useDashboardSocket() {
  const [state, setState] = useState<DashboardState>(INITIAL_STATE);
  const [connectionMode, setConnectionMode] = useState<"live" | "mock">(
    "mock",
  );
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const wsUrl = process.env.NEXT_PUBLIC_DASHBOARD_WS_URL;

    if (!wsUrl) {
      // 완료된 정보부터 순차적으로 갱신 (CLAUDE.md 실시간 갱신 원칙)
      const timers = [
        setTimeout(
          () =>
            setState((prev) => applyInboundMessage(prev, mockCallSummary)),
          600,
        ),
        setTimeout(
          () => setState((prev) => applyInboundMessage(prev, mockVitals)),
          1400,
        ),
        setTimeout(
          () =>
            setState((prev) => applyInboundMessage(prev, mockHospitalMatch)),
          2200,
        ),
        setTimeout(
          () =>
            setState((prev) =>
              applyInboundMessage(prev, mockHospitalCapacity),
            ),
          2800,
        ),
      ];
      return () => timers.forEach(clearTimeout);
    }

    const socket = new WebSocket(wsUrl);
    socketRef.current = socket;

    socket.onopen = () => setConnectionMode("live");
    socket.onclose = () => setConnectionMode("mock");
    socket.onerror = () => setConnectionMode("mock");
    socket.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data) as InboundMessage;
        setState((prev) => applyInboundMessage(prev, parsed));
      } catch {
        // 파싱 불가능한 메시지는 무시
      }
    };

    return () => socket.close();
  }, []);

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
