// 지도 위에 겹친 패널(범례·버튼·하단 목록 등)을 빼고, 실제로 보이는 영역을 기준으로 지도를 맞춘다(2026-10-06).
// 예전엔 지도 전체 기준 정중앙에 두어, 하단 패널이 덮은 만큼 사고 위치가 보이는 영역의 아래쪽으로 치우쳤다.

type LatLngLike = { lat: number; lng: number };
type Insets = { top: number; right: number; bottom: number; left: number };

/** 지도(mapEl)의 형제 요소 중 지도를 덮는 것들로 가려진 가장자리 폭(px). 패널은 가까운 가장자리에 붙은 것으로 본다 —
 *  가로로 긴 패널은 위/아래, 세로로 긴 패널은 왼쪽/오른쪽. 크기 0인 요소와 지도 전체를 덮는 요소(로딩 안내)는 뺀다. */
function coveredInsets(mapEl: HTMLElement): Insets {
  const out = { top: 0, right: 0, bottom: 0, left: 0 };
  const frame = mapEl.parentElement;
  if (!frame) return out;
  const f = mapEl.getBoundingClientRect();
  for (const el of Array.from(frame.children)) {
    if (el === mapEl || el.tagName === "STYLE") continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (r.width >= f.width * 0.9 && r.height >= f.height * 0.9) continue;
    if (r.width >= r.height) {
      if (r.top - f.top <= f.bottom - r.bottom) out.top = Math.max(out.top, r.bottom - f.top);
      else out.bottom = Math.max(out.bottom, f.bottom - r.top);
    } else if (r.left - f.left <= f.right - r.right) {
      out.left = Math.max(out.left, r.right - f.left);
    } else {
      out.right = Math.max(out.right, f.right - r.left);
    }
  }
  // 지도 위에 따로 떠 있는 패널(2026-11-01 — 지도가 화면 전체 배경이 되면서 패널이 지도 칸의 형제가 아니게 됐다)은
  // data-map-cover="top|right|bottom|left"로 어느 가장자리를 덮는지 직접 밝힌다.
  for (const el of Array.from(document.querySelectorAll<HTMLElement>("[data-map-cover]"))) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    switch (el.dataset.mapCover) {
      case "top": out.top = Math.max(out.top, r.bottom - f.top); break;
      case "bottom": out.bottom = Math.max(out.bottom, f.bottom - r.top); break;
      case "left": out.left = Math.max(out.left, r.right - f.left); break;
      case "right": out.right = Math.max(out.right, f.right - r.left); break;
    }
  }
  return out;
}

/** point를 보이는 영역의 한가운데에 둔다(확대 수준은 그대로). */
export function centerInView(map: kakao.maps.Map, mapEl: HTMLElement, point: LatLngLike): void {
  const { kakao } = window;
  map.relayout(); // 숨겨져 있다 보이게 된 지도는 안쪽 크기가 옛값이라 좌표 변환이 어긋난다
  const i = coveredInsets(mapEl);
  const w = mapEl.clientWidth;
  const h = mapEl.clientHeight;
  map.setCenter(new kakao.maps.LatLng(point.lat, point.lng));
  // 보이는 영역 가운데(tx, ty)에 point가 오려면, 지금 화면에서 (w - tx, h - ty)에 있는 지점이 새 중심이어야 한다
  const tx = (i.left + w - i.right) / 2;
  const ty = (i.top + h - i.bottom) / 2;
  map.setCenter(map.getProjection().coordsFromContainerPoint(new kakao.maps.Point(w - tx, h - ty)));
}

/** center를 보이는 영역 한가운데 두면서 others도 모두 보이게 확대 수준을 맞춘다. others를 center 대칭으로 뒤집은 점까지
 *  넣은 범위를 가려진 폭만큼 안쪽 여백을 주고 맞추면, 범위의 가운데 = center가 보이는 영역의 가운데에 온다. */
export function fitAroundInView(
  map: kakao.maps.Map, mapEl: HTMLElement, center: LatLngLike, others: LatLngLike[], margin = 40,
): void {
  if (others.length === 0) {
    centerInView(map, mapEl, center);
    return;
  }
  const { kakao } = window;
  map.relayout();
  const bounds = new kakao.maps.LatLngBounds();
  bounds.extend(new kakao.maps.LatLng(center.lat, center.lng));
  for (const p of others) {
    bounds.extend(new kakao.maps.LatLng(p.lat, p.lng));
    bounds.extend(new kakao.maps.LatLng(2 * center.lat - p.lat, 2 * center.lng - p.lng));
  }
  const i = coveredInsets(mapEl);
  map.setBounds(bounds, i.top + margin, i.right + margin, i.bottom + margin, i.left + margin);
}

/** 단계에 맞춰 지도를 맞춘다(관제 지도 자동 포커스, 2026-10-06). others가 없으면 soloLevel로 확대해 center를 가운데에,
 *  있으면 모두 보이게 맞추되 너무 가까이 붙은 점들 때문에 지나치게 확대되지 않게 minLevel에서 멈춘다. */
export function focusInView(
  map: kakao.maps.Map, mapEl: HTMLElement, center: LatLngLike, others: LatLngLike[], minLevel = 3, soloLevel = 5,
): void {
  if (others.length === 0) {
    map.setLevel(soloLevel);
    centerInView(map, mapEl, center);
    return;
  }
  fitAroundInView(map, mapEl, center, others);
  if (map.getLevel() < minLevel) {
    map.setLevel(minLevel);
    centerInView(map, mapEl, center);
  }
}

/** point가 패널에 가리지 않은 보이는 영역 안(가장자리에서 margin px 안쪽)에 있는가 */
export function inView(map: kakao.maps.Map, mapEl: HTMLElement, point: LatLngLike, margin = 40): boolean {
  const i = coveredInsets(mapEl);
  const p = map.getProjection().containerPointFromCoords(new window.kakao.maps.LatLng(point.lat, point.lng));
  return p.x >= i.left + margin && p.x <= mapEl.clientWidth - i.right - margin &&
    p.y >= i.top + margin && p.y <= mapEl.clientHeight - i.bottom - margin;
}
