"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { css } from "styled-system/css";
import { HospitalTopBar } from "@/components/hospital/HospitalTopBar";
import { Legend } from "@/components/hospital/Legend";
import { CaseMatchPanel } from "@/components/hospital/CaseMatchPanel";
import { MapPanel } from "@/components/hospital/MapPanel";
import { useDashboardSocket } from "@/hooks/use-dashboard-socket";

// 병원 대시보드는 병원 1곳 전용 화면이라 자신의 병원 ID(hpid)가 고정된다.
// 랜딩 페이지(src/app/page.tsx)의 코드 입력에서 "?id="로 넘어온 값을 쓴다.
// 여러 구급차가 동시에 본원을 후보로 걸 수 있으므로("여러 사건"), id가 없으면
// 예전처럼 임의의 mock ID로 대체하지 않고 안내 문구를 보여준다 — 실제 hpid와
// 안 맞는 화면을 mock인 줄 모르고 보는 게 더 위험하다.
function HospitalDashboardContent() {
  const searchParams = useSearchParams();
  const MY_HOSPITAL_ID = searchParams.get("id");
  const { state, connectionMode, sendAction } = useDashboardSocket(
    MY_HOSPITAL_ID ? { role: "hospital", id: MY_HOSPITAL_ID } : null,
  );
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);

  // 본원이 후보로 들어있는 사건만 걸러 카드로 나열한다 — 하나의 병원이 여러
  // 구급차의 후보 목록에 동시에 들어갈 수 있어서, 사건 하나만 보던 예전
  // 구조로는 다른 구급차의 요청이 화면에서 사라져 보였다.
  const myCases = MY_HOSPITAL_ID
    ? Object.values(state.matchResults)
        .map((result) => ({
          result,
          hospital: result.hospitals.find((h) => h.hospitalId === MY_HOSPITAL_ID) ?? null,
        }))
        .filter((entry): entry is { result: typeof entry.result; hospital: NonNullable<typeof entry.hospital> } =>
          entry.hospital !== null,
        )
    : [];

  const selected = myCases.find((c) => c.result.caseId === selectedCaseId) ?? myCases[0] ?? null;

  if (!MY_HOSPITAL_ID) {
    return (
      <div
        className={css({
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          minHeight: "full",
          padding: "8",
        })}
      >
        <p className={css({ color: "coral", fontSize: "sm" })}>
          병원 ID가 없습니다. 랜딩 페이지에서 H-&lt;병원ID&gt; 형식의 코드로 다시 입장해주세요.
        </p>
      </div>
    );
  }

  return (
    <div
      className={css({
        display: "flex",
        flexDirection: "column",
        minHeight: "full",
        backgroundColor: "bg",
        padding: "7",
      })}
    >
      <HospitalTopBar
        caseCount={myCases.length}
        connectionMode={connectionMode}
        since={state.receivedAt}
        hospitalId={MY_HOSPITAL_ID}
        hospitalName={selected?.hospital.name ?? null}
      />
      <Legend />

      <main
        className={css({
          display: "grid",
          gridTemplateColumns: { base: "1fr", lg: "1.8fr 1fr" },
          gap: "6",
          alignItems: "stretch",
          flex: "1",
          minHeight: "0",
        })}
      >
        {/* 왼쪽: 본원이 후보로 걸린 사건을 전부 카드로 나열한다. 카드를 누르면
            선택되어 오른쪽 지도에 그 사건 기준 거리/ETA가 표시된다. */}
        <div
          className={css({
            display: "flex",
            flexDirection: "column",
            gap: "3.5",
            minHeight: "0",
            overflowY: "auto",
          })}
        >
          {myCases.length === 0 ? (
            <CaseMatchPanel patientInfo={null} hospital={null} hospitalId={MY_HOSPITAL_ID} caseId="" onAction={sendAction} />
          ) : (
            myCases.map(({ result, hospital }) => (
              // CaseMatchPanel 안에 승인/거절 버튼이 이미 있어서 이 카드 자체를
              // <button>으로 감싸면 button-in-button이 되어 유효하지 않은 HTML이
              // 된다 — 대신 role="button"을 준 <div>로 카드 선택만 처리한다.
              <div
                key={result.caseId}
                role="button"
                tabIndex={0}
                onClick={() => setSelectedCaseId(result.caseId)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") setSelectedCaseId(result.caseId);
                }}
                className={css({
                  display: "block",
                  width: "100%",
                  textAlign: "left",
                  borderRadius: "panel",
                  cursor: "pointer",
                  outline: "none",
                  borderWidth: "2px",
                  borderColor: selected?.result.caseId === result.caseId ? "navy" : "transparent",
                })}
              >
                <CaseMatchPanel
                  patientInfo={result.patientInfo}
                  hospital={hospital}
                  hospitalId={MY_HOSPITAL_ID}
                  caseId={result.caseId}
                  onAction={sendAction}
                />
              </div>
            ))
          )}
        </div>

        <MapPanel hospital={selected?.hospital ?? null} />
      </main>

      <p
        className={css({
          marginTop: "3.5",
          paddingX: "1",
          fontSize: "xs",
          color: "ink",
          textAlign: "center",
        })}
      >
        AI는 환자 정보 구조화와 기록 자동화만 수행합니다. 수용 결정은 본원 의료진의 판단입니다.
      </p>
    </div>
  );
}

export default function HospitalDashboardPage() {
  return (
    <Suspense fallback={null}>
      <HospitalDashboardContent />
    </Suspense>
  );
}
