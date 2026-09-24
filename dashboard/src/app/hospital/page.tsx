"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { css, cx } from "styled-system/css";
import { HospitalTopBar } from "@/components/hospital/HospitalTopBar";
import { Legend } from "@/components/hospital/Legend";
import { CaseMatchPanel } from "@/components/hospital/CaseMatchPanel";
import { MapPanel } from "@/components/hospital/MapPanel";
import { thinScrollbarStyle } from "@/components/ui/scrollbar-style";
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
  //
  // 본원 자신의 승인/불가는 번복 가능한 후보 등록일 뿐이라 카드를 지우지 않지만
  // (CaseMatchPanel 참고), 그 사건이 "다른" 병원으로 이미 최종 확정됐다면 본원
  // 입장에서는 더 이상 의미가 없는 사건이라 목록에서 뺀다(2026-08-11 논의).
  const myCases = MY_HOSPITAL_ID
    ? Object.values(state.matchResults)
        .map((result) => ({
          result,
          hospital: result.hospitals.find((h) => h.hospitalId === MY_HOSPITAL_ID) ?? null,
        }))
        .filter((entry): entry is { result: typeof entry.result; hospital: NonNullable<typeof entry.hospital> } =>
          entry.hospital !== null,
        )
        .filter(
          ({ result, hospital }) =>
            hospital.status === "confirmed" ||
            !result.hospitals.some((h) => h.hospitalId !== MY_HOSPITAL_ID && h.status === "confirmed"),
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

  // 존재하지 않는 hpid는 이제 랜딩 페이지(src/app/page.tsx)에서 GET /identity로
  // 미리 걸러서 애초에 이 페이지까지 못 들어오게 한다 — 여기서 known===false로
  // 전체 화면을 막는 처리는 2026-08-11에 랜딩 페이지 쪽으로 옮겼다(직접 URL로
  // 들어온 경우엔 상단바 이름이 ID 폴백으로 남는 정도로만 티가 난다).

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
        hospitalName={state.identity.name ?? selected?.hospital.name ?? null}
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
            선택되어 오른쪽 지도에 그 사건 기준 거리/ETA가 표시된다.
            바깥 div가 그리드 셀 높이를 정확히 지키고(height:100% + minHeight:0
            + overflow:hidden), 안쪽 div만 스크롤한다 — 구급차 쪽 병원 후보
            리스트에서 겪은 것과 같은 문제(overflowY:auto 하나만으론 페이지
            전체가 늘어남)를 겪지 않으려고 처음부터 이 구조로 짰다(2026-08-11). */}
        <div
          className={css({
            display: "flex",
            flexDirection: "column",
            height: "100%",
            minHeight: "0",
            overflow: "hidden",
          })}
        >
        <div
          className={cx(
            css({
              display: "flex",
              flexDirection: "column",
              gap: "3.5",
              flex: "1",
              minHeight: "0",
              overflowY: "auto",
              paddingRight: "1",
            }),
            thinScrollbarStyle,
          )}
        >
          {myCases.length === 0 ? (
            <CaseMatchPanel patientInfo={null} hospital={null} hospitalId={MY_HOSPITAL_ID} caseId="" onAction={sendAction} />
          ) : (
            myCases.map(({ result, hospital }) => {
              const isSelected = selected?.result.caseId === result.caseId;
              return (
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
                    borderColor: isSelected ? "navy" : "transparent",
                  })}
                >
                  <CaseMatchPanel
                    patientInfo={result.patientInfo}
                    hospital={hospital}
                    hospitalId={MY_HOSPITAL_ID}
                    caseId={result.caseId}
                    ambulanceName={result.ambulanceName}
                    onAction={sendAction}
                  />
                </div>
              );
            })
          )}
        </div>
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
