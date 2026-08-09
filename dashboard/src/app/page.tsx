"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { css } from "styled-system/css";
import { inputStyle, primaryButtonStyle } from "@/components/ui/button-styles";

// 코드 형식: "H-<병원ID>" 또는 "A-<차량ID>" (대소문자 무관, 대시 생략 가능)
// 예: H-C → 병원 대시보드(병원 ID "C"), A-1 → 구급차 대시보드(차량 ID "1")
// 실제 인증 서버가 붙기 전까지는 이 코드로 역할/ID만 판단해 해당 대시보드로 라우팅한다.
const CODE_PATTERN = /^([HA])-?(.+)$/i;

export default function Home() {
  const router = useRouter();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const match = code.trim().match(CODE_PATTERN);
    if (!match) {
      setError("코드 형식이 올바르지 않습니다. 예: H-C(병원), A-1(구급차)");
      return;
    }
    const [, roleChar, id] = match;
    const role = roleChar.toUpperCase() === "H" ? "hospital" : "ambulance";
    router.push(`/${role}?id=${encodeURIComponent(id)}`);
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
          placeholder="코드 입력 (예: H-C, A-1)"
          className={inputStyle}
        />
        {error && (
          <p className={css({ color: "coral", fontSize: "xs" })}>{error}</p>
        )}
        <button type="submit" className={primaryButtonStyle}>
          입장
        </button>
      </form>
    </main>
  );
}
