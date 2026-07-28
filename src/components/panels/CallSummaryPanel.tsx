"use client";

import { useState, type ReactNode } from "react";
import { css } from "styled-system/css";
import { Panel } from "@/components/layout/Panel";
import { SourceBadge } from "@/components/badges/SourceBadge";
import { SeverityBadge } from "@/components/badges/SeverityBadge";
import {
  inputStyle,
  primaryButtonStyle,
  secondaryButtonStyle,
} from "@/components/ui/button-styles";
import type { CallSummaryMessage } from "@/types/dashboard";

type SummaryDraft = CallSummaryMessage["summary"];

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className={css({ display: "flex", flexDirection: "column", gap: "1" })}>
      <span className={css({ fontSize: "xs", color: "gray.500" })}>{label}</span>
      {children}
    </div>
  );
}

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
export function CallSummaryPanel({ data }: { data: CallSummaryMessage | null }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<SummaryDraft | null>(data?.summary ?? null);
  // data가 새로 도착했을 때만 draft를 리셋한다 (렌더링 중 상태 조정 패턴).
  const [syncedData, setSyncedData] = useState(data);
  if (data !== syncedData) {
    setSyncedData(data);
    setDraft(data?.summary ?? null);
    setEditing(false);
  }

  if (!data || !draft) {
    return (
      <Panel title="통화 요약" badge={<SourceBadge source="ai" />}>
        <p className={css({ color: "gray.400", fontSize: "sm" })}>
          수신 대기 중...
        </p>
      </Panel>
    );
  }

  return (
    <Panel
      title="통화 요약"
      badge={
        <div className={css({ display: "flex", gap: "2", alignItems: "center" })}>
          <SeverityBadge severity={draft.severity_tag} />
          <SourceBadge source="ai" />
        </div>
      }
    >
      <div className={css({ display: "flex", flexDirection: "column", gap: "3" })}>
        <Field label="환자">
          {editing ? (
            <input
              className={inputStyle}
              value={draft.patient}
              onChange={(e) => setDraft({ ...draft, patient: e.target.value })}
            />
          ) : (
            <span>{draft.patient}</span>
          )}
        </Field>
        <Field label="사고 기전">
          {editing ? (
            <input
              className={inputStyle}
              value={draft.mechanism}
              onChange={(e) => setDraft({ ...draft, mechanism: e.target.value })}
            />
          ) : (
            <span>{draft.mechanism}</span>
          )}
        </Field>
        <Field label="증상">
          {editing ? (
            <input
              className={inputStyle}
              value={toListInput(draft.symptoms)}
              onChange={(e) =>
                setDraft({ ...draft, symptoms: fromListInput(e.target.value) })
              }
            />
          ) : (
            <span>{draft.symptoms.join(", ")}</span>
          )}
        </Field>
        <Field label="처치">
          {editing ? (
            <input
              className={inputStyle}
              value={toListInput(draft.treatment)}
              onChange={(e) =>
                setDraft({ ...draft, treatment: fromListInput(e.target.value) })
              }
            />
          ) : (
            <span>{draft.treatment.join(", ")}</span>
          )}
        </Field>
      </div>

      <div className={css({ display: "flex", gap: "2", justifyContent: "flex-end" })}>
        {editing ? (
          <>
            <button
              type="button"
              className={secondaryButtonStyle}
              onClick={() => {
                setDraft(data.summary);
                setEditing(false);
              }}
            >
              취소
            </button>
            <button
              type="button"
              className={primaryButtonStyle}
              onClick={() => setEditing(false)}
            >
              확인 완료
            </button>
          </>
        ) : (
          <button
            type="button"
            className={secondaryButtonStyle}
            onClick={() => setEditing(true)}
          >
            수정 (Override)
          </button>
        )}
      </div>
    </Panel>
  );
}
