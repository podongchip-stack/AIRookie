"use client";

import { useEffect, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { AD, pill } from "@/components/ambulance/ambulance-design";
import type { BackupEquipmentRow, HospitalBackupView } from "@/types/dashboard";

// 후보 카드의 [배후역량] 버튼(2026-10-08) — 누를 때 hub GET /hospital-backup으로 그 병원의 배후진료를 가져와 모달로 띄운다.
// 카드에 다 넣으면 읽을 수 없어 버튼 하나로 접었다. 보유(심평원)는 갖춘 최대치일 뿐이라, 지금 쓸 수 있는지는 E-Gen 가용 값과
// 병원의 수용 승인으로 확인한다는 안내를 맨 위에 고정한다. 장비의 "지금 남은 수"는 공개 정보가 없어 그렇게 적는다.
// hub 주소가 없으면(목데이터 모드) 버튼 자체를 숨긴다(VerificationButton과 같은 규칙).
export function BackupCapacityButton({ hospitalId, name }: { hospitalId: string; name: string }) {
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<HospitalBackupView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const httpUrl = process.env.NEXT_PUBLIC_HUB_HTTP_URL;

  useEffect(() => {
    if (!open || !httpUrl) return;
    let cancelled = false;
    fetch(`${httpUrl}/hospital-backup?id=${encodeURIComponent(hospitalId)}`)
      .then(async (response) => {
        const body = await response.json();
        if (cancelled) return;
        if (!response.ok) setError(body.error ?? `불러오지 못했습니다(${response.status})`);
        else setView(body as HospitalBackupView);
      })
      .catch(() => !cancelled && setError("hub에 연결하지 못했습니다"));
    const onKeyDown = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      cancelled = true;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [open, httpUrl, hospitalId]);

  if (!httpUrl) return null;

  return (
    <>
      <button
        type="button"
        onClick={() => {
          setView(null);
          setError(null);
          setOpen(true);
        }}
        style={{ ...pill(AD.chip, AD.navy, 700), border: `1px solid ${AD.control}`, cursor: "pointer" }}
        title="이 병원의 수술실·중환자실·장비·전문의 — 보유와 지금 가용을 나란히"
      >
        배후역량
      </button>
      {open && (
        <div role="dialog" aria-modal="true" aria-label={`${name} 배후역량`} onClick={() => setOpen(false)} style={overlay}>
          <div onClick={(event) => event.stopPropagation()} style={panel}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                <span style={{ fontSize: 16, fontWeight: 800, color: AD.navy }}>{name} · 배후역량</span>
                {view?.emergencyLevel && <span style={pill(AD.chip, AD.ink3)}>{view.emergencyLevel}</span>}
              </div>
              <button type="button" onClick={() => setOpen(false)} style={{ ...pill(AD.chip, AD.ink3), border: "none", cursor: "pointer" }}>
                닫기 (Esc)
              </button>
            </div>
            <div style={{ fontSize: 12.5, color: AD.ink3, background: AD.blueSoft, borderRadius: 10, padding: "8px 12px" }}>
              <b>보유</b>(심평원)는 갖춘 최대치입니다. 지금 쓸 수 있는지는 <b>지금 가용</b>(E-Gen)과 병원의 수용 승인으로 확인하세요.
              장비가 지금 몇 대 남았는지는 공개된 정보가 없습니다.
            </div>
            {error ? (
              <div style={{ color: AD.red, fontSize: 13 }}>{error}</div>
            ) : !view ? (
              <div style={{ color: AD.muted, fontSize: 13 }}>불러오는 중…</div>
            ) : (
              <BackupBody view={view} />
            )}
          </div>
        </div>
      )}
    </>
  );
}

function BackupBody({ view }: { view: HospitalBackupView }) {
  const declarations = Object.entries(view.severeDeclarations?.groups ?? {});
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14, overflowY: "auto" }}>
      <Section title="병상">
        <table style={table}>
          <thead>
            <tr>
              {["", "보유(심평원)", "정원(E-Gen)", "지금 가용(E-Gen)", "가용 값 신뢰(AI)"].map((h) => (
                <th key={h} style={th}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {view.beds.map((row) => (
              <tr key={row.key}>
                <td style={td} title={row.note ?? undefined}>
                  {row.label}
                  {row.note && <div style={{ fontSize: 11, color: AD.muted }}>{row.note}</div>}
                </td>
                <td style={tdNum}>{num(row.hiraCapacity)}</td>
                <td style={tdNum}>{num(row.egenCapacity)}</td>
                <td style={{ ...tdNum, color: row.available === 0 ? AD.red : AD.ink, fontWeight: 700 }}>{num(row.available)}</td>
                <td style={tdNum}>{row.authority != null ? `${Math.round(row.authority * 100)}%` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {view.inFlightCount > 0 && <div style={{ fontSize: 12, color: AD.orange }}>이 병원으로 이송 중 {view.inFlightCount}건 — 응급실 가용에 반영됨</div>}
      </Section>

      <Section title="장비">
        <table style={table}>
          <thead>
            <tr>
              {["", "보유 대수(심평원)", "운영(E-Gen)", "지금 남은 수"].map((h) => (
                <th key={h} style={th}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {view.equipment.map((row) => (
              <tr key={row.key}>
                <td style={td}>
                  {row.label}
                  {row.note && <div style={{ fontSize: 11, color: AD.muted }}>{row.note}</div>}
                </td>
                <td style={tdNum}>{row.hiraCount != null ? `${row.hiraCount}대` : "—"}</td>
                <td style={tdNum}>{operating(row.egenOperating)}</td>
                <td style={{ ...tdNum, color: AD.gray, fontSize: 11.5 }}>공개 정보 없음</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title={`전문의(심평원)${view.nursingGrade ? ` · 간호등급 ${view.nursingGrade}` : ""}`}>
        {view.specialties.length ? (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {[...view.specialties].sort((a, b) => b.doctorCount - a.doctorCount).map((s) => (
              <span key={s.department} style={pill(AD.blueSoft, AD.blue)}>{s.department} {s.doctorCount}명</span>
            ))}
          </div>
        ) : (
          <Empty>심평원 전문의 정보 없음</Empty>
        )}
      </Section>

      <Section title="병원 신고(E-Gen) — 중증질환 수용 · 수용 제한 메시지">
        {declarations.length ? (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {declarations.map(([group, declaration]) => (
              <span key={group} style={declaration.value === "Y" ? pill(AD.greenSoft, AD.green) : pill(AD.redSoft, AD.red)}>
                {group} {declaration.value === "Y" ? "가능" : "불가"}
              </span>
            ))}
          </div>
        ) : (
          <Empty>중증질환 수용 신고 없음</Empty>
        )}
        {view.acceptanceMessages.map((m, i) => (
          <div key={i} style={{ fontSize: 12.5, color: m.kind === "severe" ? AD.red : AD.ink }}>
            · {m.kind === "severe" ? m.diseaseName ?? m.diseaseGroup : m.department ?? "응급실"} — {m.message}
          </div>
        ))}
      </Section>

      <div style={{ fontSize: 11, color: AD.muted }}>
        E-Gen 기준 {time(view.egenUpdatedAt)} · 심평원 수집 {time(view.hiraCollectedAt)} · 규칙 기반 조립, 순위와 무관
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ fontSize: 13, fontWeight: 800, color: AD.navy }}>{title}</div>
      {children}
    </section>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <div style={{ fontSize: 12, color: AD.muted }}>{children}</div>;
}

const num = (value?: number | null) => (value != null ? String(value) : "—");

function operating(value: BackupEquipmentRow["egenOperating"]) {
  if (value === "Y") return <span style={{ color: AD.green, fontWeight: 700 }}>운영 중</span>;
  if (value) return <span style={{ color: AD.muted }}>미운영({value})</span>;
  return "—";
}

function time(iso?: string | null) {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

const overlay: CSSProperties = {
  position: "fixed",
  inset: 0,
  zIndex: 1000,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  background: "rgba(22, 34, 46, 0.55)",
  padding: 16,
};

const panel: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 12,
  width: "100%",
  maxWidth: 720,
  maxHeight: "90vh",
  background: "#FFFFFF",
  borderRadius: 18,
  border: `1px solid ${AD.line}`,
  padding: "16px 18px",
};

const table: CSSProperties = { width: "100%", borderCollapse: "collapse", fontSize: 13 };
const th: CSSProperties = { textAlign: "right", fontSize: 11.5, fontWeight: 600, color: AD.sub, padding: "4px 8px", borderBottom: `1px solid ${AD.line}` };
const td: CSSProperties = { padding: "6px 8px", borderBottom: `1px solid ${AD.line}`, color: AD.ink, fontWeight: 600 };
const tdNum: CSSProperties = { ...td, textAlign: "right", fontWeight: 500, fontVariantNumeric: "tabular-nums" };
