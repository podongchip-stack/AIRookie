import { css } from "styled-system/css";
import { Panel } from "@/components/layout/Panel";
import { SourceBadge } from "@/components/badges/SourceBadge";
import { HospitalStatusBadge } from "@/components/badges/HospitalStatusBadge";
import type { HospitalMatchMessage } from "@/types/dashboard";

export function HospitalListPanel({
  data,
  selectedHospitalId,
  onSelect,
}: {
  data: HospitalMatchMessage | null;
  selectedHospitalId?: string | null;
  onSelect?: (hospitalId: string) => void;
}) {
  if (!data) {
    return (
      <Panel title="병원 매칭" badge={<SourceBadge source="rule" />}>
        <p className={css({ color: "gray.400", fontSize: "sm" })}>
          수신 대기 중...
        </p>
      </Panel>
    );
  }

  return (
    <Panel
      title={`병원 매칭 · Zone ${data.zone_active.join(", ")}`}
      badge={<SourceBadge source="rule" />}
    >
      <ul className={css({ display: "flex", flexDirection: "column", gap: "2" })}>
        {data.hospitals.map((hospital) => {
          const selected = hospital.hospital_id === selectedHospitalId;
          const selectable = Boolean(onSelect) && hospital.status !== "rejected";

          return (
            <li key={hospital.hospital_id}>
              <button
                type="button"
                disabled={!selectable}
                onClick={() => onSelect?.(hospital.hospital_id)}
                className={css({
                  width: "100%",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "3",
                  borderRadius: "md",
                  borderWidth: "1px",
                  borderColor: selected ? "brand" : "gray.200",
                  backgroundColor: selected ? "amber.50" : "white",
                  cursor: selectable ? "pointer" : "default",
                  textAlign: "left",
                  _disabled: { opacity: 0.5 },
                })}
              >
                <div className={css({ display: "flex", flexDirection: "column" })}>
                  <span className={css({ fontWeight: "medium" })}>{hospital.name}</span>
                  <span className={css({ fontSize: "xs", color: "gray.500" })}>
                    {hospital.distance_km}km
                    {hospital.eta_min != null ? ` · ETA ${hospital.eta_min}분` : ""}
                  </span>
                </div>
                <HospitalStatusBadge status={hospital.status} />
              </button>
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}
