"use client";

import { useEffect, useState } from "react";
import { css } from "styled-system/css";

// lidar3d(feature/lidar3d)의 3D 현장 뷰어 주소. 뷰어는 별도 서버(lidar3d FastAPI,
// 포트 8000)가 띄우는 독립 웹페이지라 dashboard는 주소만 알고 iframe으로 띄운다 —
// dashboard가 hub와만 통신한다는 원칙은 "데이터"에 대한 것이고, 이건 사람이 보는
// 별도 화면을 그대로 여는 것이라 hub를 거치지 않는다(3D 파일은 세션당 100MB대라
// 애초에 hub 경유가 불가능하다 — lidar3d 설계 문서 "전송 구조" 절).
//
// 값 예: https://lidar.rookie-goldenlink.xyz/viewer/?token=<LIDAR_TOKEN>
// 뷰어의 데이터 요청은 토큰이 필요해서 주소에 ?token=을 붙여 둔다. NEXT_PUBLIC_*은
// 빌드 결과에 그대로 박히므로 대시보드를 열 수 있는 사람은 이 토큰도 볼 수 있다 —
// 공개 운영 전에는 도메인 앞에 로그인(Cloudflare Access 등)을 두는 것을 전제로 한다.
// 미설정이면 버튼 자체를 숨긴다(3D가 없어도 매칭·승인은 정상 동작해야 하므로).
const VIEWER_URL = process.env.NEXT_PUBLIC_LIDAR_VIEWER_URL;

export function Viewer3DButton() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open]);

  if (!VIEWER_URL) return null;

  return (
    <>
      <button type="button" onClick={() => setOpen(true)} className={openButtonStyle}>
        3D 현장 뷰어
      </button>

      {open && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="3D 현장 뷰어"
          onClick={() => setOpen(false)}
          className={css({
            position: "fixed",
            inset: "0",
            zIndex: 1000,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "rgba(22, 34, 46, 0.55)",
            padding: "6",
          })}
        >
          {/* 바깥(어두운 배경)을 누르면 닫고, 안쪽 패널 클릭은 닫힘으로 번지지 않게 막는다. */}
          <div
            onClick={(event) => event.stopPropagation()}
            className={css({
              display: "flex",
              flexDirection: "column",
              width: "100%",
              maxWidth: "1400px",
              height: "100%",
              maxHeight: "900px",
              backgroundColor: "surface",
              borderRadius: "panel",
              overflow: "hidden",
              borderWidth: "1px",
              borderColor: "line",
            })}
          >
            <div
              className={css({
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: "3",
                paddingX: "4",
                paddingY: "2.5",
                borderBottomWidth: "1px",
                borderColor: "line",
              })}
            >
              <div className={css({ display: "flex", alignItems: "center", gap: "2" })}>
                <span className={css({ fontSize: "sm", fontWeight: "bold", color: "ink" })}>3D 현장 뷰어</span>
                <span
                  className={css({
                    fontSize: "xs",
                    fontWeight: "semibold",
                    color: "navy",
                    backgroundColor: "navySoft",
                    paddingX: "1.5",
                    paddingY: "0.5",
                    borderRadius: "chip",
                  })}
                >
                  LiDAR 촬영 · 사람 인식은 AI
                </span>
              </div>
              <div className={css({ display: "flex", alignItems: "center", gap: "2" })}>
                <a href={VIEWER_URL} target="_blank" rel="noopener noreferrer" className={linkButtonStyle}>
                  새 탭에서 열기
                </a>
                <button type="button" onClick={() => setOpen(false)} className={linkButtonStyle}>
                  닫기 (Esc)
                </button>
              </div>
            </div>
            <iframe
              src={VIEWER_URL}
              title="3D 현장 뷰어"
              allow="fullscreen"
              className={css({ flex: "1", width: "100%", border: "none", backgroundColor: "ink" })}
            />
          </div>
        </div>
      )}
    </>
  );
}

const openButtonStyle = css({
  fontSize: "xs",
  fontWeight: "semibold",
  color: "white",
  backgroundColor: "navy",
  paddingX: "3",
  paddingY: "1.5",
  borderRadius: "full",
  cursor: "pointer",
  _hover: { opacity: 0.9 },
});

const linkButtonStyle = css({
  fontSize: "xs",
  fontWeight: "semibold",
  color: "ink2",
  backgroundColor: "surfaceSub",
  borderWidth: "1px",
  borderColor: "line",
  paddingX: "2.5",
  paddingY: "1",
  borderRadius: "chip",
  cursor: "pointer",
  _hover: { color: "ink" },
});
