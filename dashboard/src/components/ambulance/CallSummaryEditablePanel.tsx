"use client";

import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { AD, cardStyle, pill } from "@/components/ambulance/ambulance-design";
import { formatVital } from "@/components/panels/PatientVitals";
import type { CallStatus, CallTranscriptLine, HubMatchResult, PatientInfo, Severity } from "@/types/dashboard";

const SEVERITY_RISK_LABEL: Record<Severity, string> = {
  high: "중증 의심",
  medium: "중등도 의심",
  low: "경증 의심",
};

const SEVERITY_COLOR: Record<Severity, { bg: string; fg: string }> = {
  high: { bg: AD.redSoft, fg: AD.red },
  medium: { bg: AD.orangeSoft, fg: AD.orange },
  low: { bg: AD.greenSoft, fg: AD.green },
};

const labelStyle: CSSProperties = { color: AD.sub, fontSize: 11.5 };
const inputStyle: CSSProperties = {
  width: "100%", boxSizing: "border-box", minHeight: 34, padding: "0 10px", border: `1px solid ${AD.control}`,
  borderRadius: 10, fontSize: 13, color: AD.ink, background: "#FFFFFF", fontFamily: "inherit",
};
const buttonStyle: CSSProperties = {
  minHeight: 44, padding: "0 18px", border: `1px solid ${AD.control}`, borderRadius: 12, background: AD.bg,
  color: AD.ink, fontWeight: 500, fontSize: 13, cursor: "pointer",
};

function toListInput(values: string[]) {
  return values.join(", ");
}

function fromListInput(value: string) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function mmss(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

// 통화 요약 · 구조화 카드(2026-10-05 디자인 시안). AI가 생성한 통화 요약(hub가 재가공해 넘긴 patientInfo)은
// 최종 전송 전 구급대원이 확인·수정할 수 있어야 한다(Override, CLAUDE.md). 카드 아래쪽 '통화 현황'은 예전
// 따로 있던 통화 현황 패널(보기 전용 — 통화는 대원 휴대폰 전화 앱 담당)을 합친 것이다: 통화 중엔 요약이 아직
// 없으니 본문에 실시간 자막(voice, AI)을 띄우고, 요약이 오면 자막은 접어 둔다.
export function CallSummaryEditablePanel({
  data,
  apid,
  callStatus = null,
  voiceLines = [],
  sentHospitalCount = null,
  waitingHint = null,
}: {
  data: HubMatchResult | null;
  apid: string;
  callStatus?: CallStatus | null;
  voiceLines?: CallTranscriptLine[];
  sentHospitalCount?: number | null;
  waitingHint?: string | null;
}) {
  const patientInfo = data?.patientInfo ?? null;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<PatientInfo | null>(patientInfo);
  // 증상은 편집 중 배열이 아닌 순수 문자열로 유지한다 (쉼표 입력 도중 배열 변환을
  // 거치면 빈 항목이 즉시 filter(Boolean)로 제거되어 콤마가 사라진 것처럼 보이는 버그 방지).
  const [symptomsText, setSymptomsText] = useState(toListInput(patientInfo?.injuryStatus ?? []));
  // patientInfo가 새로 도착했을 때만 draft를 리셋한다 (렌더링 중 상태 조정 패턴).
  const [syncedPatientInfo, setSyncedPatientInfo] = useState(patientInfo);
  if (patientInfo !== syncedPatientInfo) {
    setSyncedPatientInfo(patientInfo);
    setDraft(patientInfo);
    setSymptomsText(toListInput(patientInfo?.injuryStatus ?? []));
    setEditing(false);
  }
  const [showTranscript, setShowTranscript] = useState(false);

  // 통화 중이면 통화 시간을 1초마다
  const calling = callStatus?.state === "calling";
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!calling) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [calling]);

  const transcriptRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const box = transcriptRef.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [voiceLines.length, showTranscript]);

  const hospital = callStatus?.hospitalName ?? "병원";
  const device = callStatus?.device === "tablet" ? "대시보드" : "휴대폰";
  const callText = calling
    ? `${device}로 ${hospital}과 통화 중 · ${mmss(now - Date.parse(callStatus!.startedAt))}`
    : callStatus?.state === "ended"
      ? sentHospitalCount != null
        ? `통화 종료 · 후보 병원 ${sentHospitalCount}곳에 전달`
        : `통화 종료(${hospital}) · 환자 정보 정리 중…`
      : null;

  const transcriptBox = (
    <div
      ref={transcriptRef}
      style={{
        flex: "1 1 auto", minHeight: 90, maxHeight: 220, overflowY: "auto", padding: "8px 10px", background: AD.bg,
        border: `1px solid ${AD.line}`, borderRadius: 12, fontSize: 12.5, lineHeight: 1.6, color: AD.ink, whiteSpace: "normal",
      }}
    >
      {voiceLines.length > 0 ? (
        voiceLines.map((line) => (
          <div key={`${line.start}-${line.text}`} style={{ display: "flex", gap: 8 }}>
            <span style={{ color: AD.muted, flex: "none" }}>{mmss(line.start * 1000)}</span>
            <span>{line.text}</span>
          </div>
        ))
      ) : (
        <span style={{ color: AD.muted }}>{calling ? "말이 끊길 때마다 인식된 문장이 여기에 뜹니다." : "통화가 시작되면 실시간 자막이 여기 표시됩니다."}</span>
      )}
    </div>
  );

  const latestVital = draft?.vitals?.[draft.vitals.length - 1];
  const vitalText = latestVital ? formatVital(latestVital) : "";
  const patientLine = draft
    ? [draft.patient, draft.chiefComplaint, draft.consciousness && `의식 ${draft.consciousness}`].filter(Boolean).join(" · ")
    : "";
  const onsetLine = draft
    ? [draft.onset && `발생 ${draft.onset}`, draft.requiredDepartment && `필요 진료과 ${draft.requiredDepartment}`].filter(Boolean).join(" · ")
    : "";

  return (
    <section style={{ ...cardStyle, flex: "1 1 auto", minWidth: 0, padding: "14px 16px", display: "flex", flexDirection: "column", gap: 8, whiteSpace: "normal" }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8 }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, color: AD.navy }}>통화 요약 · 구조화</div>
          <div style={labelStyle}>통화 음성 → 항목 추출</div>
        </div>
        <div style={pill(AD.blueSoft, AD.blue)}>Qwen3-ASR · MF_BERT</div>
      </div>

      {!patientInfo || !draft ? (
        // 요약 전 — 통화 중이면 실시간 자막, 아니면 대기 안내
        calling || voiceLines.length > 0 ? (
          <>
            <div style={labelStyle}>실시간 자막 (voice 음성 인식)</div>
            {transcriptBox}
          </>
        ) : (
          <div style={{ color: AD.muted, fontSize: 13 }}>
            {waitingHint ?? "수신 대기 중 — 대원 휴대폰의 전화 앱으로 병원에 전화하면 통화 내용이 여기 정리됩니다."}
          </div>
        )
      ) : (
        <>
          <div style={{ minWidth: 0 }}>
            <div style={labelStyle}>예상 병명</div>
            {editing ? (
              <input style={inputStyle} value={draft.expectedDiagnosis} onChange={(e) => setDraft({ ...draft, expectedDiagnosis: e.target.value })} />
            ) : (
              <div style={{ fontSize: 13, fontWeight: 500, color: AD.navy }}>{draft.expectedDiagnosis}</div>
            )}
          </div>
          <div style={{ minWidth: 0 }}>
            <div style={labelStyle}>증상</div>
            {editing ? (
              <input style={inputStyle} value={symptomsText} onChange={(e) => setSymptomsText(e.target.value)} />
            ) : (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 2 }}>
                {draft.injuryStatus.length > 0
                  ? draft.injuryStatus.map((symptom) => <div key={symptom} style={pill(AD.chip, AD.ink3)}>{symptom}</div>)
                  : <span style={{ color: AD.muted, fontSize: 12 }}>—</span>}
              </div>
            )}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 6 }}>
            <div style={pill(SEVERITY_COLOR[draft.severityTag].bg, SEVERITY_COLOR[draft.severityTag].fg, 700)}>
              {SEVERITY_RISK_LABEL[draft.severityTag]}
            </div>
            {draft.ktasLevel != null && <div style={pill(AD.redSoft, AD.red, 700)}>KTAS {draft.ktasLevel}</div>}
            {patientLine && <div style={{ color: AD.ink3, fontSize: 12, marginLeft: 4 }}>{patientLine}</div>}
          </div>
          {onsetLine && <div style={{ color: AD.sub, fontSize: 12 }}>{onsetLine}</div>}
          {vitalText && (
            <div style={{ fontSize: 12, color: AD.ink3 }}>
              <b style={{ fontWeight: 700, color: AD.navy }}>활력징후</b>&nbsp; {vitalText}
              {(draft.vitals?.length ?? 0) > 1 && <span style={{ color: AD.muted }}> (측정 {draft.vitals?.length}회 중 최근)</span>}
            </div>
          )}
          {showTranscript && transcriptBox}
        </>
      )}

      {/* 통화 현황 — 휴대폰 전화 앱의 통화 상태(보기 전용) + [수정] */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginTop: "auto", paddingTop: 6, borderTop: `1px solid ${AD.line}` }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: AD.navy, display: "flex", alignItems: "center", gap: 6 }}>
            통화 현황
            {calling && <span style={{ width: 8, height: 8, borderRadius: "50%", background: AD.green, animation: "beat 1.4s ease-in-out infinite" }} />}
          </div>
          <div style={{ ...labelStyle, color: calling ? AD.green : AD.sub, fontWeight: calling ? 700 : 400 }}>
            {callText ?? (
              <>휴대폰 전화 앱 <b style={{ fontWeight: 700, color: AD.ink }}>P-{apid}</b></>
            )}
          </div>
        </div>
        <div style={{ flex: "none", display: "flex", alignItems: "center", gap: 8 }}>
          {patientInfo && voiceLines.length > 0 ? (
            <button type="button" onClick={() => setShowTranscript((v) => !v)} style={{ ...pill(AD.blueSoft, AD.blue), border: 0, cursor: "pointer" }}>
              {showTranscript ? "자막 접기" : `자막 ${voiceLines.length}줄`}
            </button>
          ) : (
            <div style={pill(AD.blueSoft, AD.blue)}>voice 음성 인식</div>
          )}
          {patientInfo && draft && (editing ? (
            <>
              <button
                type="button"
                style={buttonStyle}
                onClick={() => {
                  setDraft(patientInfo);
                  setSymptomsText(toListInput(patientInfo.injuryStatus));
                  setEditing(false);
                }}
              >
                취소
              </button>
              <button
                type="button"
                style={{ ...buttonStyle, background: AD.blue, borderColor: AD.blue, color: "#FFFFFF", fontWeight: 700 }}
                onClick={() => {
                  setDraft({ ...draft, injuryStatus: fromListInput(symptomsText) });
                  setEditing(false);
                }}
              >
                확인 완료
              </button>
            </>
          ) : (
            <button type="button" style={buttonStyle} onClick={() => setEditing(true)}>
              수정
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
