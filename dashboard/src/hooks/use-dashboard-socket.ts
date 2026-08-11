"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  mockHubMatchResult,
  mockHubMatchResultAmbulance2,
  mockHubMatchResultAmbulance3,
  mockHubMatchResultOngoing,
} from "@/lib/mock-data";
import type {
  ApprovalAction,
  ApprovalActionType,
  CallSignal,
  CallSignalType,
  DashboardIdentify,
  DashboardIdentityInfo,
  DashboardRole,
  DashboardState,
  HospitalStatus,
  HubMatchResult,
  InboundMessage,
} from "@/types/dashboard";

// hub의 hub_engine.py _ACTION_TO_STATUS와 동일한 매핑 — mock 모드에서 승인
// 액션을 로컬로 흉내낼 때 hub가 실제로 반영할 상태와 같게 맞춘다.
const MOCK_ACTION_TO_STATUS: Record<ApprovalActionType, HospitalStatus> = {
  hospital_approve: "approved",
  hospital_reject: "rejected",
  final_approval: "confirmed",
};

const INITIAL_STATE: DashboardState = {
  matchResults: {},
  receivedAt: null,
  identity: { name: null, known: null },
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
// 보였음). hub는 이 자기소개에 두 종류로 응답한다 — (1) 사건 유무와 무관한
// 즉시 신원 확인(identity_info, hub README "출력 스키마 6"), (2) 관련된 진행
// 중인 사건 따라잡기(평소 브로드캐스트와 같은 HubMatchResult). onmessage가
// `type` 필드로 둘을 구분해 각자 다른 상태로 저장한다.
export function useDashboardSocket(identity: { role: DashboardRole; id: string } | null) {
  const [state, setState] = useState<DashboardState>(INITIAL_STATE);
  const [connectionMode, setConnectionMode] = useState<"live" | "mock">(
    "mock",
  );
  const socketRef = useRef<WebSocket | null>(null);

  const applyMatchResult = useCallback((matchResult: HubMatchResult) => {
    setState((prev) => ({
      ...prev,
      matchResults: { ...prev.matchResults, [matchResult.caseId]: matchResult },
      receivedAt: prev.receivedAt ?? new Date().toISOString(),
    }));
  }, []);

  const applyIdentityInfo = useCallback((info: DashboardIdentityInfo) => {
    setState((prev) => ({ ...prev, identity: { name: info.name, known: info.known } }));
  }, []);

  useEffect(() => {
    const wsUrl = process.env.NEXT_PUBLIC_DASHBOARD_WS_URL;

    if (!wsUrl) {
      // 이펙트 본문에서 setState를 동기 호출하면 안 되므로(react-hooks/set-state-in-effect),
      // mock 응답들도 전부 타이머로 미룬다. hub가 없는 mock 모드에서는
      // known=false(접근 불가) 화면이 떠서 UI 작업이 막히면 안 되므로, identity가
      // 있으면 항상 known=true로 간주하고 간단한 표시용 이름을 채운다 — 실제 이름
      // 규칙(Supabase 데이터)과는 무관하다.
      //
      // 사건 소개 이후 사건 4개를 순차로 흘려보낸다 — 하나(mockHubMatchResult)는
      // C병원이 이미 confirmed라 "다른 병원으로 확정된 사건 숨기기" 규칙을 확인할
      // 수 있고, 나머지 셋(Ongoing/Ambulance2/Ambulance3)은 실제 구급차
      // 레지스트리의 3대(구급 1~3호차)가 동시에 A병원을 후보로 걸고 있는 상황을
      // 재현한다 — 병원 하나가 여러 구급차 사건을 동시에 카드로 받는지 확인용
      // (2026-08-11 요청).
      const timers = [
        ...(identity
          ? [
              setTimeout(
                () =>
                  applyIdentityInfo({
                    type: "identity_info",
                    role: identity.role,
                    id: identity.id,
                    name: identity.role === "hospital" ? `${identity.id}(mock)` : `구급 ${identity.id}호차(mock)`,
                    known: true,
                  }),
                0,
              ),
            ]
          : []),
        setTimeout(() => applyMatchResult(mockHubMatchResult), 900),
        setTimeout(() => applyMatchResult(mockHubMatchResultOngoing), 1400),
        setTimeout(() => applyMatchResult(mockHubMatchResultAmbulance2), 1900),
        setTimeout(() => applyMatchResult(mockHubMatchResultAmbulance3), 2400),
      ];
      return () => timers.forEach(clearTimeout);
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
        const parsed = JSON.parse(event.data) as InboundMessage;
        // HubMatchResult엔 type 필드 자체가 없어서 "type" in parsed로 구분한다
        // (parsed.type만 비교하면 두 타입 모두에 type이 있어야 좁혀지지 않는다).
        if ("type" in parsed && parsed.type === "identity_info") {
          applyIdentityInfo(parsed);
        } else {
          applyMatchResult(parsed as HubMatchResult);
        }
      } catch {
        // 파싱 불가능한 메시지는 무시
      }
    };

    return () => socket.close();
    // identity는 객체라 매 렌더 새 참조일 수 있으니, 원시값(role/id)만 의존성으로
    // 둬서 값이 실제로 바뀔 때만(사실상 마운트 시 한 번) 재연결한다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [applyMatchResult, applyIdentityInfo, identity?.role, identity?.id]);

  const sendAction = useCallback((action: ApprovalAction) => {
    const socket = socketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(action));
      return;
    }
    console.info("[mock] 승인 액션 전송(WS 미연결) — 로컬에서 hub 반응을 흉내냄:", action);
    // 실제 hub는 승인 액션을 처리한 뒤 갱신된 사건 결과를 재broadcast한다
    // (hub/app.py의 _handle_dashboard_action 참고). mock 모드엔 그 hub가
    // 없어서, 버튼을 눌러도 배지가 하나도 안 바뀌는 문제가 있었다(2026-08-11
    // 실제로 확인됨) — 같은 상태 전이를 로컬에서 재현해 화면으로 모든
    // 경우의수(판단 대기→승인/불가→이송 확정)를 직접 눌러볼 수 있게 한다.
    setState((prev) => {
      const result = prev.matchResults[action.caseId];
      if (!result) return prev;
      const nextStatus = MOCK_ACTION_TO_STATUS[action.action];
      const hospitals = result.hospitals.map((h) =>
        h.hospitalId === action.hospital_id ? { ...h, status: nextStatus } : h,
      );
      return { ...prev, matchResults: { ...prev.matchResults, [action.caseId]: { ...result, hospitals } } };
    });
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
