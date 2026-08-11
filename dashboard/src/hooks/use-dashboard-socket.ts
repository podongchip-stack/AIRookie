"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { mockHubMatchResult } from "@/lib/mock-data";
import type {
  ApprovalAction,
  CallSignal,
  CallSignalType,
  DashboardIdentify,
  DashboardRole,
  DashboardState,
  HubMatchResult,
} from "@/types/dashboard";

const INITIAL_STATE: DashboardState = {
  matchResults: {},
  receivedAt: null,
};

// feature/hub가 dashboard와 직접 통신하는 유일한 브랜치다 (CLAUDE.md). voice/info는
// hub를 거쳐서만 도착하므로, dashboard가 실제로 받는 건 hub의 통합 매칭 결과 메시지
// 뿐이다. 여러 구급차가 동시에 사건을 진행할 수 있어 caseId를 키로 맵에 담아둔다
// (예전엔 단일 값이라 나중에 온 사건이 이전 사건을 덮어썼다). NEXT_PUBLIC_DASHBOARD_WS_URL이
// 설정되지 않으면 목데이터를 흘려보내 화면 작업을 진행할 수 있게 한다.
//
// identity(role/id)를 넘기면 소켓이 열리자마자 hub에 자기소개(DashboardIdentify)를
// 보낸다 — hub는 그동안 연결을 완전히 익명으로 취급해서, 이미 진행 중인 사건이
// 있는 상태로 새 탭이 뒤늦게 열리면 그 사건의 이전 브로드캐스트를 놓쳐 화면에
// 아무것도 안 뜨는 문제가 있었다(2026-08-11 실제 재현됨 — 구급1호차·서울대병원
// 탭이 연결된 상태에서 매칭이 끝난 뒤 한양대병원 탭을 새로 열면 그 사건이 안
// 보였음). hub가 자기소개에 대한 응답으로 관련 사건들을 즉시 보내주므로, 응답
// 메시지도 평소 브로드캐스트와 같은 형식이라 onmessage에서 별도 분기 없이 그대로
// applyMatchResult()로 처리하면 된다.
export function useDashboardSocket(identity: { role: DashboardRole; id: string } | null) {
  const [state, setState] = useState<DashboardState>(INITIAL_STATE);
  const [connectionMode, setConnectionMode] = useState<"live" | "mock">(
    "mock",
  );
  const socketRef = useRef<WebSocket | null>(null);

  const applyMatchResult = useCallback((matchResult: HubMatchResult) => {
    setState((prev) => ({
      matchResults: { ...prev.matchResults, [matchResult.caseId]: matchResult },
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

    socket.onopen = () => {
      setConnectionMode("live");
      if (identity) {
        const message: DashboardIdentify = { type: "identify", role: identity.role, id: identity.id };
        socket.send(JSON.stringify(message));
      }
    };
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
    // identity는 객체라 매 렌더 새 참조일 수 있으니, 원시값(role/id)만 의존성으로
    // 둬서 값이 실제로 바뀔 때만(사실상 마운트 시 한 번) 재연결한다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [applyMatchResult, identity?.role, identity?.id]);

  const sendAction = useCallback((action: ApprovalAction) => {
    const socket = socketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(action));
    } else {
      console.info("[mock] 승인 액션 전송(WS 미연결):", action);
    }
  }, []);

  // 통화 시연(CallDemoPanel)이 통화 시작/종료를 hub에 알리는 신호. apid로 hub가
  // 중계할 voice 인스턴스를 찾고, caseId로 이번 통화의 사건을 식별한다 —
  // call_started 시점에 구급차 대시보드가 새로 생성해 넘긴다.
  const sendCallSignal = useCallback((signal: CallSignalType, apid: string, caseId: string) => {
    const payload: CallSignal = {
      type: "call_signal",
      signal,
      timestamp: new Date().toISOString(),
      apid,
      caseId,
    };
    const socket = socketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(payload));
    } else {
      console.info("[mock] 통화 신호 전송(WS 미연결):", payload);
    }
  }, []);

  // 마이크로 캡처한 오디오 조각을 실시간으로 hub에 전달한다(바이너리 프레임).
  // WS 미연결(mock 모드)에서는 hub로 보낼 대상이 없으니 조용히 버린다 — 화면
  // 시각화는 CallDemoPanel이 소켓과 무관하게 로컬에서 직접 처리한다.
  const sendAudioChunk = useCallback((chunk: Blob) => {
    const socket = socketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(chunk);
    }
  }, []);

  return { state, connectionMode, sendAction, sendCallSignal, sendAudioChunk };
}
