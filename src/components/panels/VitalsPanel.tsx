import { css } from "styled-system/css";
import { Panel } from "@/components/layout/Panel";
import { SourceBadge } from "@/components/badges/SourceBadge";
import type { VitalsMessage } from "@/types/dashboard";

type VitalKey = keyof VitalsMessage["vitals"];

const VITAL_LABELS: Record<VitalKey, string> = {
  bp_systolic: "수축기 혈압",
  bp_diastolic: "이완기 혈압",
  pulse: "맥박",
  spo2: "산소포화도",
  gcs: "GCS",
  temperature: "체온",
  resp_rate: "호흡수",
};

const VITAL_UNITS: Partial<Record<VitalKey, string>> = {
  bp_systolic: "mmHg",
  bp_diastolic: "mmHg",
  pulse: "bpm",
  spo2: "%",
  temperature: "℃",
  resp_rate: "회/분",
};

export function VitalsPanel({ data }: { data: VitalsMessage | null }) {
  if (!data) {
    return (
      <Panel title="바이탈" badge={<SourceBadge source="rule" />}>
        <p className={css({ color: "gray.400", fontSize: "sm" })}>
          수신 대기 중...
        </p>
      </Panel>
    );
  }

  const keys = Object.keys(data.vitals) as VitalKey[];

  return (
    <Panel title="바이탈" badge={<SourceBadge source="rule" />}>
      <div
        className={css({
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
          gap: "4",
        })}
      >
        {keys.map((key) => (
          <div key={key} className={css({ display: "flex", flexDirection: "column" })}>
            <span className={css({ fontSize: "xs", color: "gray.500" })}>
              {VITAL_LABELS[key]}
            </span>
            <span className={css({ fontSize: "lg", fontWeight: "semibold" })}>
              {data.vitals[key]}
              {VITAL_UNITS[key] ? ` ${VITAL_UNITS[key]}` : ""}
            </span>
          </div>
        ))}
      </div>
    </Panel>
  );
}
