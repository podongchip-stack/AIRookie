"use client";

import { AD, cardStyle, pill } from "@/components/ambulance/ambulance-design";
import { VerificationButton } from "@/components/ui/VerificationButton";
import type { ConnectionMode } from "@/hooks/use-dashboard-socket";
import { formatElapsed, useElapsedSeconds } from "@/hooks/use-elapsed-time";

const CONNECTION: Record<ConnectionMode, { text: string; color: string }> = {
  live: { text: "실시간 연동", color: AD.green },
  reconnecting: { text: "hub 재연결 중…", color: AD.red },
  mock: { text: "목데이터 모드", color: AD.orange },
};

// 구급차 대시보드 상단바(2026-10-05 디자인 시안) — 로고 · 버전 · 구급대 이름 | 전화 앱 · 신뢰도 검증 · 이송 상태 · 연결 · 경과
export function AmbulanceTopBar({
  confirmedName,
  connectionMode,
  since,
  ambulanceId,
  ambulanceName,
}: {
  // 이송 확정 병원 이름(hub 기준). 없으면 "병원 선택 대기"
  confirmedName: string | null;
  connectionMode: ConnectionMode;
  since: string | null;
  ambulanceId: string;
  // hub 구급차 레지스트리의 실명("회현119안전센터 구급 1"). 아직 안 오면 URL의 ?id=로 대신 표시한다.
  ambulanceName: string | null;
}) {
  const elapsed = useElapsedSeconds(since);
  const status = confirmedName
    ? { label: `이송 확정 · ${confirmedName}`, color: AD.green }
    : { label: "병원 선택 대기", color: AD.orange };
  const connection = CONNECTION[connectionMode];

  return (
    <header
      style={{
        ...cardStyle,
        flex: "none",
        display: "flex",
        flexWrap: "wrap",
        alignItems: "center",
        justifyContent: "space-between",
        gap: "6px 20px",
        padding: "4px 18px",
        minHeight: 52,
      }}
    >
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "6px 12px" }}>
        <div style={{ fontSize: 19, fontWeight: 900, letterSpacing: "-0.02em", color: AD.navy }}>
          골든<span style={{ color: AD.blue }}>링크</span>
        </div>
        <div style={{ ...pill(AD.blueSoft, AD.blue, 700), padding: "2px 8px" }}>v2.0</div>
        <div style={pill(AD.chip, AD.ink3, 700)}>{ambulanceName ?? `구급 ${ambulanceId}`}</div>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "6px 18px" }}>
        {/* 대원 휴대폰 전화 앱(2026-10-03) — 휴대폰에선 첫 페이지에 P-<구급차ID>를 입력해도 된다 */}
        <a
          href={`/phone?id=${encodeURIComponent(ambulanceId)}`}
          target="_blank"
          rel="noopener noreferrer"
          title={`휴대폰에서는 첫 페이지에 P-${ambulanceId} 입력`}
          style={{ color: AD.blue, fontWeight: 500, fontSize: 12, textDecoration: "none" }}
        >
          전화 앱 (P-{ambulanceId})
        </a>
        <div style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 700, fontSize: 12, color: status.color }}>
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: status.color }} />
          {status.label}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, color: connection.color, fontWeight: 500, fontSize: 12 }}>
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: connection.color }} />
          {connection.text}
        </div>
        <div style={{ color: AD.sub, fontSize: 11.5 }}>
          수신 후 <b style={{ fontWeight: 700, color: AD.navy }}>{formatElapsed(elapsed)}</b> 경과
        </div>
        {/* 신뢰도 검증은 맨 오른쪽(2026-10-05 요청) */}
        <VerificationButton
          buttonStyle={{
            minHeight: 34, padding: "0 14px", border: 0, borderRadius: 999, background: AD.blue,
            color: "#FFFFFF", fontWeight: 700, fontSize: 12, cursor: "pointer",
          }}
        />
      </div>
    </header>
  );
}

// 범례 + AI 안내 한 줄(시안) — AI 처리 / 규칙 기반 / 의료진 판단 영역을 색으로 구분한다(CLAUDE.md 출처 표시 원칙)
export function AmbulanceLegend() {
  const item = (color: string, text: string) => (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span style={{ width: 9, height: 9, borderRadius: "50%", background: color }} />
      {text}
    </div>
  );
  return (
    <div
      style={{
        flex: "none",
        display: "flex",
        flexWrap: "wrap",
        alignItems: "center",
        justifyContent: "space-between",
        gap: "2px 20px",
        padding: "0 6px",
        fontSize: 11.5,
        color: AD.ink3,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
        {item(AD.blue, "AI 처리")}
        {item(AD.gray, "규칙 기반 · 센서 · API")}
        {item(AD.orange, "의료진 판단 영역")}
      </div>
      <div style={{ color: AD.sub }}>AI는 환자 정보 구조화와 기록 자동화만 수행합니다. 이송 최종 승인은 구급대원의 판단입니다.</div>
    </div>
  );
}
