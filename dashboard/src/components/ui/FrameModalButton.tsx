"use client";

import { useEffect, useState } from "react";
import { css } from "styled-system/css";

// 상단바 버튼 → 다른 화면을 iframe 모달로 띄운다(3D 현장 뷰어·신뢰도 검증이 같이 쓴다).
// 바깥(어두운 배경)·Esc로 닫고, "새 탭에서 열기"로 시연장 큰 화면에 따로 띄울 수 있다.
export function FrameModalButton({ label, badge, url }: { label: string; badge: string; url: string }) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open]);

  return (
    <>
      <button type="button" onClick={() => setOpen(true)} className={openButtonStyle}>
        {label}
      </button>

      {open && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={label}
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
                <span className={css({ fontSize: "sm", fontWeight: "bold", color: "ink" })}>{label}</span>
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
                  {badge}
                </span>
              </div>
              <div className={css({ display: "flex", alignItems: "center", gap: "2" })}>
                <a href={url} target="_blank" rel="noopener noreferrer" className={linkButtonStyle}>
                  새 탭에서 열기
                </a>
                <button type="button" onClick={() => setOpen(false)} className={linkButtonStyle}>
                  닫기 (Esc)
                </button>
              </div>
            </div>
            <iframe
              src={url}
              title={label}
              allow="fullscreen"
              className={css({ flex: "1", width: "100%", border: "none", backgroundColor: "surface" })}
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
