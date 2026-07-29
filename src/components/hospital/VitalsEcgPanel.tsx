import { css } from "styled-system/css";
import { Panel } from "@/components/layout/Panel";
import { Tag } from "@/components/hospital/Tag";
import type { VitalsMessage } from "@/types/dashboard";

function VitalRow({
  label,
  note,
  value,
  unit,
  warn,
  layout = "list",
}: {
  label: string;
  note?: string;
  value: string;
  unit: string;
  warn?: boolean;
  layout?: "list" | "grid";
}) {
  if (layout === "grid") {
    return (
      <div
        className={css({
          borderWidth: "1px",
          borderColor: "line",
          borderRadius: "field",
          paddingX: "3",
          paddingY: "2.5",
        })}
      >
        <div className={css({ fontSize: "xs", color: "ink" })}>
          {label}
          {note && (
            <span className={css({ display: "block", fontSize: "2xs", color: "ink" })}>
              {note}
            </span>
          )}
        </div>
        <div
          className={css({
            marginTop: "0.5",
            fontSize: "xl",
            fontWeight: "semibold",
            letterSpacing: "-0.02em",
            color: warn ? "coral" : "ink",
          })}
        >
          {value}
          <span
            className={css({
              fontSize: "xs",
              fontWeight: "medium",
              color: "ink",
              marginLeft: "1",
            })}
          >
            {unit}
          </span>
        </div>
      </div>
    );
  }

  return (
    <div
      className={css({
        display: "flex",
        alignItems: "baseline",
        justifyContent: "space-between",
        gap: "2.5",
        paddingY: "2.5",
        borderBottomWidth: "1px",
        borderColor: "line",
        _last: { borderBottomWidth: 0 },
      })}
    >
      <span className={css({ fontSize: "xs", color: "ink" })}>
        {label}
        {note && (
          <span className={css({ display: "block", fontSize: "2xs", color: "ink" })}>
            {note}
          </span>
        )}
      </span>
      <span
        className={css({
          fontSize: "xl",
          fontWeight: "semibold",
          letterSpacing: "-0.02em",
          color: warn ? "coral" : "ink",
        })}
      >
        {value}
        <span
          className={css({
            fontSize: "xs",
            fontWeight: "medium",
            color: "ink",
            marginLeft: "1",
          })}
        >
          {unit}
        </span>
      </span>
    </div>
  );
}

const ECG_POINTS =
  "0,22 40,22 52,22 58,10 64,36 70,22 110,22 118,17 126,22 170,22 182,22 188,10 194,36 200,22 " +
  "240,22 248,17 256,22 300,22 312,22 318,10 324,36 330,22 370,22 378,17 386,22 430,22 442,22 " +
  "448,10 454,36 460,22 500,22 508,17 516,22 560,22 572,22 578,10 584,36 590,22 620,22";

export function VitalsEcgPanel({
  data,
  subtitle = "이송 확정 병원에만 실시간 전송",
  showLockNote = true,
  layout = "list",
}: {
  data: VitalsMessage | null;
  subtitle?: string;
  showLockNote?: boolean;
  layout?: "list" | "grid";
}) {
  if (!data) {
    return (
      <Panel
        title="구급차 내부 부상자 바이탈"
        subtitle={subtitle}
        badge={<Tag source="rule">센서 직결</Tag>}
      >
        <p className={css({ color: "ink", fontSize: "sm" })}>수신 대기 중...</p>
      </Panel>
    );
  }

  const v = data.vitals;
  const bpWarn = v.bp_systolic < 100;
  const spo2Warn = v.spo2 < 95;
  const pulseWarn = v.pulse < 60 || v.pulse > 100;

  return (
    <Panel
      title="구급차 내부 부상자 바이탈"
      subtitle={subtitle}
      badge={<Tag source="rule">센서 직결</Tag>}
    >
      <div
        className={css({
          backgroundColor: "surfaceSub",
          borderWidth: "1px",
          borderColor: "line",
          borderRadius: "field",
          paddingX: "2",
          paddingY: "1.5",
          marginBottom: "3.5",
          overflow: "hidden",
        })}
      >
        <svg
          viewBox="0 0 620 44"
          preserveAspectRatio="none"
          role="img"
          aria-label="심전도 파형"
          className={css({ display: "block", width: "100%", height: "11" })}
        >
          <polyline
            points={ECG_POINTS}
            fill="none"
            stroke="#0E9F6E"
            strokeWidth="1.6"
            strokeLinejoin="round"
            strokeDasharray="620"
            className={css({ animation: "sweep 2.4s linear infinite" })}
          />
        </svg>
      </div>

      {layout === "grid" ? (
        <div className={css({ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "2.5" })}>
          <VitalRow
            layout="grid"
            label="혈압"
            note={bpWarn ? "정상 범위 이하" : undefined}
            value={`${v.bp_systolic}/${v.bp_diastolic}`}
            unit="mmHg"
            warn={bpWarn}
          />
          <VitalRow
            layout="grid"
            label="맥박"
            note={pulseWarn ? "경계" : undefined}
            value={`${v.pulse}`}
            unit="bpm"
            warn={pulseWarn}
          />
          <VitalRow
            layout="grid"
            label="산소포화도"
            note={spo2Warn ? "정상 범위 이하" : undefined}
            value={`${v.spo2}`}
            unit="%"
            warn={spo2Warn}
          />
          <VitalRow layout="grid" label="의식 수준" note="GCS" value={`${v.gcs}`} unit="/15" />
          <VitalRow layout="grid" label="체온" value={`${v.temperature}`} unit="℃" />
          <VitalRow layout="grid" label="호흡수" value={`${v.resp_rate}`} unit="회/분" />
        </div>
      ) : (
        <>
          <VitalRow
            label="혈압"
            note={bpWarn ? "정상 범위 이하" : undefined}
            value={`${v.bp_systolic}/${v.bp_diastolic}`}
            unit="mmHg"
            warn={bpWarn}
          />
          <VitalRow
            label="맥박"
            note={pulseWarn ? "경계" : undefined}
            value={`${v.pulse}`}
            unit="bpm"
            warn={pulseWarn}
          />
          <VitalRow
            label="산소포화도"
            note={spo2Warn ? "정상 범위 이하" : undefined}
            value={`${v.spo2}`}
            unit="%"
            warn={spo2Warn}
          />
          <VitalRow label="의식 수준" note="GCS" value={`${v.gcs}`} unit="/15" />
          <VitalRow label="체온" value={`${v.temperature}`} unit="℃" />
          <VitalRow label="호흡수" value={`${v.resp_rate}`} unit="회/분" />
        </>
      )}

      {data.trend_note && (
        <div
          className={css({
            marginTop: "3.5",
            paddingX: "3",
            paddingY: "2.5",
            backgroundColor: "coralSoft",
            borderRadius: "field",
            fontSize: "xs",
            color: "coral",
          })}
        >
          {data.trend_note}
        </div>
      )}

      {showLockNote && (
        <div
          className={css({
            marginTop: "2.5",
            paddingX: "2.5",
            paddingY: "2",
            backgroundColor: "surfaceSub",
            borderWidth: "1px",
            borderStyle: "dashed",
            borderColor: "lineStrong",
            borderRadius: "field",
            fontSize: "xs",
            color: "ink",
            textAlign: "center",
          })}
        >
          이송 확정 전에는 최초 수신값만 표시됩니다
        </div>
      )}
    </Panel>
  );
}
