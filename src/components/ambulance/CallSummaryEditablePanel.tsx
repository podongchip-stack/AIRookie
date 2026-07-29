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
import type { CallSummaryMessage, Severity } from "@/types/dashboard";

type SummaryDraft = CallSummaryMessage["summary"];

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

// AI가 생성한 통화 요약은 최종 전송 전 구급대원이 확인·수정할 수 있어야 한다 (Override, CLAUDE.md).
export function CallSummaryEditablePanel({ data }: { data: CallSummaryMessage | null }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<SummaryDraft | null>(data?.summary ?? null);
  // 증상/처치는 편집 중 배열이 아닌 순수 문자열로 유지한다 (쉼표 입력 도중 배열 변환을
  // 거치면 빈 항목이 즉시 filter(Boolean)로 제거되어 콤마가 사라진 것처럼 보이는 버그 방지).
  const [symptomsText, setSymptomsText] = useState(toListInput(data?.summary.symptoms ?? []));
  const [treatmentText, setTreatmentText] = useState(toListInput(data?.summary.treatment ?? []));
  // data가 새로 도착했을 때만 draft를 리셋한다 (렌더링 중 상태 조정 패턴).
  const [syncedData, setSyncedData] = useState(data);
  if (data !== syncedData) {
    setSyncedData(data);
    setDraft(data?.summary ?? null);
    setSymptomsText(toListInput(data?.summary.symptoms ?? []));
    setTreatmentText(toListInput(data?.summary.treatment ?? []));
    setEditing(false);
  }

  if (!data || !draft) {
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
        <dt className={kvDt}>환자</dt>
        <dd>
          {editing ? (
            <input
              className={inputStyle}
              value={draft.patient}
              onChange={(e) => setDraft({ ...draft, patient: e.target.value })}
            />
          ) : (
            <span className={kvValue}>{draft.patient}</span>
          )}
        </dd>
        <dt className={kvDt}>기전</dt>
        <dd>
          {editing ? (
            <input
              className={inputStyle}
              value={draft.mechanism}
              onChange={(e) => setDraft({ ...draft, mechanism: e.target.value })}
            />
          ) : (
            <span className={kvValue}>{draft.mechanism}</span>
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
            <span className={kvValue}>{draft.symptoms.join(", ")}</span>
          )}
        </dd>
        <dt className={kvDt}>처치</dt>
        <dd>
          {editing ? (
            <input
              className={inputStyle}
              value={treatmentText}
              onChange={(e) => setTreatmentText(e.target.value)}
            />
          ) : (
            <span className={kvValue}>{draft.treatment.join(", ")}</span>
          )}
        </dd>
      </dl>

      <div className={css({ display: "flex", gap: "1.5", flexWrap: "wrap", marginTop: "3" })}>
        <span className={severityBadge({ severity: draft.severity_tag })}>
          {SEVERITY_RISK_LABEL[draft.severity_tag]} · {draft.mechanism}
        </span>
      </div>

      <div className={css({ display: "flex", gap: "2", justifyContent: "flex-end", marginTop: "auto" })}>
        {editing ? (
          <>
            <button
              type="button"
              className={secondaryButtonStyle}
              onClick={() => {
                setDraft(data.summary);
                setSymptomsText(toListInput(data.summary.symptoms));
                setTreatmentText(toListInput(data.summary.treatment));
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
                  symptoms: fromListInput(symptomsText),
                  treatment: fromListInput(treatmentText),
                });
                setEditing(false);
              }}
            >
              확인 완료
            </button>
          </>
        ) : (
          <button type="button" className={secondaryButtonStyle} onClick={() => setEditing(true)}>
            수정 (Override)
          </button>
        )}
      </div>
    </Panel>
  );
}
