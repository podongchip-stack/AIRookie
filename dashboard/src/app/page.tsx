"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { css } from "styled-system/css";
import { inputStyle, primaryButtonStyle, secondaryButtonStyle } from "@/components/ui/button-styles";

// 코드 형식: "H-<병원ID>", "A-<차량ID>", "P-<차량ID>" (대소문자 무관, 대시 생략 가능).
// 예: H-A1100009 → 병원 대시보드, A-A0000001 → 구급차 대시보드, P-A0000001 → 그 구급차 대원 휴대폰 전화 앱(2026-10-03).
// 병원 접근 코드는 관제 지도의 병원 이름 옆에 보인다.
// 실제 인증 서버가 붙기 전까지는 이 코드로 역할/ID만 판단해 해당 대시보드로 라우팅한다.
const CODE_PATTERN = /^([HAP])-?(.+)$/i;
const ROUTE_BY_PREFIX = { H: "hospital", A: "ambulance", P: "phone" } as const;

// hub의 GET /identity로 hpid/apid가 실제로 존재하는지 라우팅 전에 미리 확인한다
// (2026-08-11). 예전엔 /hospital, /ambulance 페이지로 넘어간 뒤에야 알 수 있어서
// 잘못된 코드로 들어가면 그 페이지 전체가 "존재하지 않는 접근 코드" 화면으로
// 막히는 방식이었는데, 그 대신 이 첫 페이지에서 입력칸과 입장 버튼 사이에 빨간
// 글씨로 바로 알려주도록 옮겼다. hub가 없는 개발 환경(NEXT_PUBLIC_HUB_HTTP_URL
// 미설정)이거나 요청이 실패하면 검증 없이 통과시킨다 — 그 경우엔 목적지 페이지의
// WebSocket identify가 한 번 더 신원을 확인해주므로 완전히 무방비는 아니다.
async function checkCodeExists(role: "hospital" | "ambulance", id: string): Promise<boolean> {
  const httpUrl = process.env.NEXT_PUBLIC_HUB_HTTP_URL;
  if (!httpUrl) return true;
  try {
    const response = await fetch(`${httpUrl}/identity?role=${role}&id=${encodeURIComponent(id)}`);
    if (!response.ok) return true;
    const data = (await response.json()) as { known?: boolean };
    return data.known !== false;
  } catch {
    return true;
  }
}

export default function Home() {
  const router = useRouter();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const match = code.trim().match(CODE_PATTERN);
    if (!match) {
      setError("코드 형식이 올바르지 않습니다. 예: H-A1100009(병원), A-A0000001(구급차), P-A0000001(전화 앱)");
      return;
    }
    const [, roleChar, id] = match;
    const page = ROUTE_BY_PREFIX[roleChar.toUpperCase() as keyof typeof ROUTE_BY_PREFIX];
    const role = page === "hospital" ? "hospital" : "ambulance"; // 전화 앱도 구급차 코드로 확인한다

    setChecking(true);
    const exists = await checkCodeExists(role, id);
    setChecking(false);
    if (!exists) {
      setError("존재하지 않는 코드입니다.");
      return;
    }
    const href = `/${page}?id=${encodeURIComponent(id)}`;
    // 전화 앱은 페이지를 새로 불러 연다 — 화면 안 이동(router.push)이면 이 페이지에서 생긴 확대(입력칸 자동 확대 등)가
    // 그대로 남는데, 전화 앱은 확대를 막아 두어 되돌릴 수 없다. 새로 불러오면 배율이 1로 돌아간다.
    if (page === "phone") window.location.assign(href);
    else router.push(href);
  }

  return (
    <main
      className={css({
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: "6",
        minHeight: "100vh",
        padding: "8",
        backgroundColor: "gray.50",
      })}
    >
      <div className={css({ display: "flex", flexDirection: "column", gap: "1", textAlign: "center" })}>
        <h1 className={css({ fontSize: "2xl", fontWeight: "bold", color: "ink" })}>골든링크</h1>
        <p className={css({ color: "gray.500" })}>
          응급이송 골든타임 단축을 위한 실시간 병원 매칭 시스템
        </p>
      </div>

      <form
        onSubmit={handleSubmit}
        className={css({ display: "flex", flexDirection: "column", gap: "3", width: "280px", color: "ink" })}
      >
        <input
          value={code}
          onChange={(event) => {
            setCode(event.target.value);
            setError(null);
          }}
          placeholder="코드 입력 (예: H-A1100009, A-A0000001, P-A0000001)"
          className={inputStyle}
        />
        {error && (
          <p className={css({ color: "coral", fontSize: "xs" })}>{error}</p>
        )}
        <button type="submit" className={primaryButtonStyle} disabled={checking}>
          {checking ? "확인 중..." : "입장"}
        </button>
      </form>

      <div className={css({ display: "flex", flexDirection: "column", gap: "2", width: "280px", textAlign: "center" })}>
        <button type="button" className={secondaryButtonStyle} onClick={() => router.push("/map")}>
          관제 지도 열기
        </button>
        <p className={css({ fontSize: "xs", color: "gray.500" })}>
          병원·구급차 위치와 환자 요청 현황을 실시간으로 봅니다. 병원 접근 코드도 여기서 확인할 수 있습니다.
        </p>
      </div>
    </main>
  );
}
