// 구급차/병원 대시보드 지도 패널 둘 다 상태별 색상 마커 + 이름 라벨이 필요해서
// 공용으로 뺐다. 카카오맵 기본 마커(빨간 핀)는 상태 구분이 안 되니, 기존 CSS
// 점 마커 스타일(색상 원 + 흰 테두리)을 SVG data URI로 대신 그린다.
function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function createColoredMarkerImage(hexColor: string): kakao.maps.MarkerImage {
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22">` +
    `<circle cx="11" cy="11" r="8" fill="${hexColor}" stroke="#FFFFFF" stroke-width="3"/></svg>`;
  const dataUrl = `data:image/svg+xml;base64,${window.btoa(svg)}`;
  // size/offset은 반드시 kakao.maps.Size/Point 인스턴스여야 한다 — 평범한
  // {width,height} 객체를 넘기면 SDK 내부가 그 위에서 자기 프로토타입 메서드를
  // 호출하려다 "is not a function"으로 죽는다(2026-08-11 실제로 재현·확인됨).
  return new window.kakao.maps.MarkerImage(
    dataUrl,
    new window.kakao.maps.Size(22, 22),
    { offset: new window.kakao.maps.Point(11, 11) },
  );
}

export function createLabelOverlay(
  position: kakao.maps.LatLng,
  text: string,
  opts?: { muted?: boolean },
): kakao.maps.CustomOverlay {
  const color = opts?.muted ? "#66778A" : "#16222E";
  const html =
    `<div style="transform:translateY(14px);font-size:11px;font-weight:600;white-space:nowrap;` +
    `background:#FFFFFF;border:1px solid #E2E8EF;padding:1px 6px;border-radius:6px;color:${color};">` +
    `${escapeHtml(text)}</div>`;
  return new window.kakao.maps.CustomOverlay({ position, content: html, yAnchor: 0 });
}
