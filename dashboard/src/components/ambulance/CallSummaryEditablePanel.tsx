"use client";

import { useState } from "react";
import { css } from "styled-system/css";
import { severityBadge } from "styled-system/recipes";
import { Panel } from "@/components/layout/Panel";
import { Tag } from "@/components/hospital/Tag";
import {
  inputStyle,
  primaryButtonStyle,
  secondaryButtonStyle,
} from "@/components/ui/button-styles";
import type { HubMatchResult, PatientInfo, Severity } from "@/types/dashboard";

const SEVERITY_RISK_LABEL: Record<Severity, string> = {
  high: "중증 의심",
  medium: "중등도 의심",
  low: "경증 의심",
};

const kvDt = css({ color: "ink2", fontSize: "sm" });
const kvValue = css({ fontWeight: "medium", fontSize: "md", color: "ink" });

function toListInput(values: string[]) {
  return values.join(", ");
}

function fromListInput(value: string) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

// AI가 생성한 통화 요약(hub가 재가공해 넘긴 patientInfo)은 최종 전송 전 구급대원이
// 확인·수정할 수 있어야 한다 (Override, CLAUDE.md).
export function CallSummaryEditablePanel({ data }: { data: HubMatchResult | null }) {
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

  if (!patientInfo || !draft) {
    return (
      <Panel title="통화 요약 · 구조화" badge={<Tag source="ai">sLLM · KM-BERT</Tag>}>
        <p className={css({ color: "ink3", fontSize: "sm" })}>수신 대기 중...</p>
      </Panel>
    );
  }

  return (
    <Panel
      title="통화 요약 · 구조화"
      subtitle="실시간 음성 필터링 → 항목 추출"
      badge={<Tag source="ai">sLLM · KM-BERT</Tag>}
    >
      <dl
        className={css({
          display: "grid",
          gridTemplateColumns: "74px 1fr",
          gap: "30 10",
          alignItems: "center",
        })}
      >
        <dt className={kvDt}>예상 병명</dt>
        <dd>
          {editing ? (
            <input
              className={inputStyle}
              value={draft.expectedDiagnosis}
              onChange={(e) => setDraft({ ...draft, expectedDiagnosis: e.target.value })}
            />
          ) : (
            <span className={kvValue}>{draft.expectedDiagnosis}</span>
          )}
        </dd>
        <dt className={kvDt}>증상</dt>
        <dd>
          {editing ? (
            <input
              className={inputStyle}
              value={symptomsText}
              onChange={(e) => setSymptomsText(e.target.value)}
            />
          ) : (
            <span className={kvValue}>{draft.injuryStatus.join(", ")}</span>
          )}
        </dd>
      </dl>

      <div className={css({ display: "flex", gap: "1.5", flexWrap: "wrap", marginTop: "3" })}>
        <span className={severityBadge({ severity: draft.severityTag })}>
          {SEVERITY_RISK_LABEL[draft.severityTag]} · {draft.expectedDiagnosis}
        </span>
      </div>

      <div className={css({ display: "flex", gap: "2", justifyContent: "flex-end", marginTop: "auto" })}>
        {editing ? (
          <>
            <button
              type="button"
              className={secondaryButtonStyle}
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
              className={primaryButtonStyle}
              onClick={() => {
                setDraft({
                  ...draft,
                  injuryStatus: fromListInput(symptomsText),
                });
                setEditing(false);
              }}
            >
              확인 완료
            </button>
          </>
        ) : (
          <button type="button" className={secondaryButtonStyle} onClick={() => setEditing(true)}>
            수정
          </button>
        )}
      </div>
    </Panel>
  );
}
