"""시뮬레이션 결과 → 자가완결 HTML 리포트 (외부 의존 0 — 파일 하나로 어디서든 열림).

색·마크 규칙은 dataviz 스킬의 검증 절차를 따랐다:
- 팔(arm) 3개 = 카테고리 슬롯 1~3 (blue/orange/aqua) — all-pairs 검증 통과
  (light aqua 대비 2.74:1 경고 → 직접 라벨 + 표 뷰로 해소)
- 초과 수용(병상보다 많은 도착)만 status critical(#d03b3b)로 — 시리즈 색과 역할 분리
- 라이트/다크 모두 지원 (prefers-color-scheme + data-theme 토글)
"""
from __future__ import annotations

import json

ARM_LABEL = {"nearest": "최근접 집중", "sequential": "순차 전화", "goldenlink": "골든링크"}
ARM_DESC = {
    "nearest": "정보 없이 전원 최근접 응급실로 — 만실은 도착해서야 안다 (이태원 당시)",
    "sequential": "가까운 순 전화, 자리 있는 곳 예약 후 출발 (평시 뺑뺑이)",
    "goldenlink": "존 전체 동시 요청 + 배정 공유 — 같은 병상을 두 번 세지 않는다",
}

_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>대량사고 이송 시뮬레이션 — 순차 전화 vs 골든링크</title>
<style>
  :root { color-scheme: light dark; }
  .viz-root {
    color-scheme: light;
    --surface-1: #fcfcfb; --page: #f9f9f7;
    --ink-1: #0b0b0b; --ink-2: #52514e; --ink-3: #898781;
    --grid: #e1e0d9; --axis: #c3c2b7; --ring: rgba(11,11,11,0.10);
    --arm-nearest: #2a78d6; --arm-sequential: #eb6834; --arm-goldenlink: #1baf7a;
    --critical: #d03b3b;
    --seq-100: #cde2fb; --seq-250: #86b6ef; --seq-400: #3987e5; --seq-550: #1c5cab; --seq-700: #0d366b;
  }
  @media (prefers-color-scheme: dark) {
    :root:where(:not([data-theme="light"])) .viz-root {
      color-scheme: dark;
      --surface-1: #1a1a19; --page: #0d0d0d;
      --ink-1: #ffffff; --ink-2: #c3c2b7; --ink-3: #898781;
      --grid: #2c2c2a; --axis: #383835; --ring: rgba(255,255,255,0.10);
      --arm-nearest: #3987e5; --arm-sequential: #d95926; --arm-goldenlink: #199e70;
    }
  }
  :root[data-theme="dark"] .viz-root {
    color-scheme: dark;
    --surface-1: #1a1a19; --page: #0d0d0d;
    --ink-1: #ffffff; --ink-2: #c3c2b7; --ink-3: #898781;
    --grid: #2c2c2a; --axis: #383835; --ring: rgba(255,255,255,0.10);
    --arm-nearest: #3987e5; --arm-sequential: #d95926; --arm-goldenlink: #199e70;
  }
  * { box-sizing: border-box; margin: 0; }
  body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
  .viz-root { background: var(--page); color: var(--ink-1); padding: 24px; min-height: 100vh; }
  .wrap { max-width: 1060px; margin: 0 auto; display: flex; flex-direction: column; gap: 16px; }
  h1 { font-size: 20px; letter-spacing: -0.01em; }
  h2 { font-size: 14px; color: var(--ink-1); margin-bottom: 2px; }
  .sub { font-size: 12px; color: var(--ink-2); }
  .note { font-size: 11px; color: var(--ink-3); }
  .card { background: var(--surface-1); border: 1px solid var(--ring); border-radius: 10px; padding: 16px; }
  .tiles { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
  @media (max-width: 760px) { .tiles { grid-template-columns: 1fr; } }
  .tile h3 { font-size: 13px; display: flex; align-items: center; gap: 6px; }
  .dot { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
  .tile .desc { font-size: 11px; color: var(--ink-3); margin: 2px 0 10px; min-height: 28px; }
  .hero { font-size: 34px; font-weight: 700; letter-spacing: -0.02em; }
  .hero small { font-size: 14px; font-weight: 400; color: var(--ink-2); }
  .tile .row { display: flex; gap: 14px; margin-top: 8px; font-size: 12px; color: var(--ink-2); flex-wrap: wrap; }
  .tile .row b { color: var(--ink-1); font-weight: 600; }
  .overload-note { color: var(--critical); font-weight: 600; }
  svg text { font-family: inherit; }
  .legend { display: flex; gap: 14px; font-size: 12px; color: var(--ink-2); margin-top: 6px; flex-wrap: wrap; }
  .legend span { display: inline-flex; align-items: center; gap: 5px; }
  .controls { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
  .controls button { font: inherit; font-size: 12px; padding: 4px 10px; border-radius: 6px;
    border: 1px solid var(--ring); background: transparent; color: var(--ink-2); cursor: pointer; }
  .controls button.active { color: var(--ink-1); border-color: var(--axis); font-weight: 600; }
  .controls input[type=range] { flex: 1; min-width: 160px; accent-color: var(--seq-400); }
  .controls .clock { font-variant-numeric: tabular-nums; font-size: 12px; color: var(--ink-1); min-width: 56px; }
  #tooltip { position: fixed; pointer-events: none; background: var(--surface-1); border: 1px solid var(--ring);
    border-radius: 6px; padding: 6px 9px; font-size: 12px; color: var(--ink-1); display: none;
    box-shadow: 0 2px 10px rgba(0,0,0,0.18); z-index: 10; max-width: 260px; }
  details { font-size: 12px; }
  details summary { cursor: pointer; color: var(--ink-2); }
  table { border-collapse: collapse; width: 100%; margin-top: 8px; font-variant-numeric: tabular-nums; }
  th, td { text-align: right; padding: 3px 8px; border-bottom: 1px solid var(--grid); font-size: 11.5px; }
  th:first-child, td:first-child { text-align: left; }
  th { color: var(--ink-3); font-weight: 600; }
  ul.assume { font-size: 11.5px; color: var(--ink-2); padding-left: 18px; display: flex; flex-direction: column; gap: 2px; }
</style>
</head>
<body>
<div class="viz-root"><div class="wrap">
  <header>
    <h1>대량사고 이송 시뮬레이션 — 분산 이송은 골든타임을 얼마나 지키나</h1>
    <p class="sub" id="scenario-line"></p>
    <p class="note">시연용 시뮬레이션 — 병원 위치·가용 병상은 실제 E-Gen 스냅샷, 시간 상수(전화·적재 등)는 가정(하단 참고). 세 방식은 같은 환자·같은 병상에서 출발하며 차이는 정보 전달 방식뿐.</p>
  </header>

  <section class="tiles" id="tiles"></section>

  <section class="card">
    <h2>환자가 몇 분 안에 수용되는가 (누적 %)</h2>
    <p class="sub">현장 출발 대기 시작 → 최종 수용 병원 도착. 재이송·전화 시간 포함 (대표 시드)</p>
    <div id="cdf"></div>
    <div class="legend" id="cdf-legend"></div>
  </section>

  <section class="card">
    <h2>병원별 도착 환자 — 쏠림이 어디서 생기나 (시드 평균)</h2>
    <p class="sub">막대 = 도착 환자, 세로선 = 그 병원의 가용 병상. <span class="overload-note">빨간 구간 = 병상을 넘겨 도착(재이송·과밀의 원인)</span></p>
    <div id="bars"></div>
  </section>

  <section class="card">
    <h2>재생 — 시간에 따라 병원이 차는 모습 (대표 시드)</h2>
    <div class="controls">
      <span id="arm-tabs"></span>
      <button id="play">▶ 재생</button>
      <input type="range" id="scrub" min="0" max="100" value="0" step="0.5">
      <span class="clock" id="clock">0분</span>
    </div>
    <div id="map"></div>
    <div class="legend">
      <span><span class="dot" style="background:var(--seq-100)"></span>여유</span>
      <span><span class="dot" style="background:var(--seq-400)"></span>포화 근접</span>
      <span><span class="dot" style="background:var(--seq-700)"></span>만실</span>
      <span><span class="dot" style="background:transparent;border:2.5px solid var(--critical);border-radius:50%"></span>병상 초과 도착</span>
      <span><span class="dot" style="border-radius:50%;background:var(--ink-2)"></span>구급차 (빨간 테두리 = 재이송 중, 흐린 점 = 복귀)</span>
      <span>원 크기 = 가용 병상 · ★ = 사고 현장</span>
    </div>
  </section>

  <section class="card">
    <details><summary>데이터 표 (병원별 · 방식별)</summary><div id="table"></div></details>
  </section>

  <section class="card">
    <h2>가정과 한계</h2>
    <ul class="assume" id="assume"></ul>
  </section>
</div></div>
<div id="tooltip"></div>
<script>
const DATA = __DATA__;
const ARMS = ["nearest", "sequential", "goldenlink"];
const ARM_LABEL = __ARM_LABEL__;
const ARM_DESC = __ARM_DESC__;
const ARM_VAR = { nearest: "--arm-nearest", sequential: "--arm-sequential", goldenlink: "--arm-goldenlink" };
const css = name => getComputedStyle(document.querySelector(".viz-root")).getPropertyValue(name).trim();
const tooltip = document.getElementById("tooltip");
function showTip(e, html) {
  tooltip.innerHTML = html; tooltip.style.display = "block";
  const pad = 12, w = tooltip.offsetWidth, h = tooltip.offsetHeight;
  tooltip.style.left = Math.min(e.clientX + pad, innerWidth - w - 8) + "px";
  tooltip.style.top = Math.min(e.clientY + pad, innerHeight - h - 8) + "px";
}
function hideTip() { tooltip.style.display = "none"; }

// ── 시나리오 줄 ──────────────────────────────────────────────────────────────
const S = DATA.scenario;
document.getElementById("scenario-line").textContent =
  `${S.scene.label} 반경 ${S.radiusKm}km · E-Gen 스냅샷 ${S.snapshotTs.slice(0,16).replace("T"," ")} 실측 ` +
  `(병원 ${S.nHospitals}곳 · 가용 ${S.totalBeds}병상) · 사상자 ${S.patients}명 · 구급차 ${S.ambulances}대 · 시드 ${S.seeds}회 평균`;

// ── 요약 타일 ────────────────────────────────────────────────────────────────
const tiles = document.getElementById("tiles");
for (const arm of ARMS) {
  const a = DATA.arms[arm];
  const extra = arm === "nearest"
    ? `<span>재이송 <b>${a.transfersMean}</b>건</span><span class="overload-note">쏠림 최대 ${a.maxLoadRatio.mean}배</span>`
    : arm === "sequential"
      ? `<span>거절 전화 <b>${a.rejectedCallsMean}</b>통</span><span>쏠림 <b>${a.maxLoadRatio.mean}</b>배</span>`
      : `<span>거절 전화 <b>0</b>통</span><span>쏠림 <b>${a.maxLoadRatio.mean}</b>배</span>`;
  tiles.insertAdjacentHTML("beforeend", `
    <div class="card tile">
      <h3><span class="dot" style="background:var(${ARM_VAR[arm]})"></span>${ARM_LABEL[arm]}</h3>
      <p class="desc">${ARM_DESC[arm]}</p>
      <div class="hero">${a.medianTransportMin.mean}<small>분 · 수용까지 중앙값</small></div>
      <div class="row"><span>p90 <b>${a.p90TransportMin.mean}분</b></span>${extra}</div>
    </div>`);
}

// ── CDF ─────────────────────────────────────────────────────────────────────
(function drawCdf() {
  const W = 1000, H = 300, L = 46, R = 120, T = 14, B = 34;
  const series = ARMS.map(arm => DATA.arms[arm].transportTimesSeed0);
  const xMax = Math.ceil(Math.max(...series.flat()) / 10) * 10;
  const x = v => L + (W - L - R) * v / xMax;
  const y = q => T + (H - T - B) * (1 - q);
  let g = "";
  for (let q = 0; q <= 1.0001; q += 0.25)
    g += `<line x1="${L}" y1="${y(q)}" x2="${W-R}" y2="${y(q)}" stroke="var(--grid)" stroke-width="1"/>` +
         `<text x="${L-8}" y="${y(q)+4}" text-anchor="end" font-size="11" fill="var(--ink-3)">${Math.round(q*100)}%</text>`;
  for (let v = 0; v <= xMax; v += 10)
    g += `<text x="${x(v)}" y="${H-10}" text-anchor="middle" font-size="11" fill="var(--ink-3)">${v}분</text>`;
  let paths = "", labels = "";
  ARMS.forEach(arm => {
    const times = DATA.arms[arm].transportTimesSeed0;
    const pts = times.map((t, i) => `${x(t)},${y((i + 1) / times.length)}`);
    paths += `<polyline points="${x(0)},${y(0)} ${pts.join(" ")}" fill="none" stroke="var(${ARM_VAR[arm]})" stroke-width="2" stroke-linejoin="round"/>`;
    const last = times[times.length - 1];
    labels += `<text x="${x(Math.min(last, xMax))+6}" y="${y(1)+4}" font-size="11.5" font-weight="600" fill="var(--ink-1)">${ARM_LABEL[arm]}</text>`;
  });
  const hover = `<rect id="cdf-hover" x="${L}" y="${T}" width="${W-L-R}" height="${H-T-B}" fill="transparent"/>` +
                `<line id="cdf-cross" y1="${T}" y2="${H-B}" stroke="var(--axis)" stroke-width="1" visibility="hidden"/>`;
  document.getElementById("cdf").innerHTML =
    `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto">${g}` +
    `<line x1="${L}" y1="${y(0)}" x2="${W-R}" y2="${y(0)}" stroke="var(--axis)" stroke-width="1"/>${paths}${labels}${hover}</svg>`;
  document.getElementById("cdf-legend").innerHTML = ARMS.map(arm =>
    `<span><span class="dot" style="background:var(${ARM_VAR[arm]})"></span>${ARM_LABEL[arm]}</span>`).join("");
  const svg = document.querySelector("#cdf svg"), cross = svg.querySelector("#cdf-cross");
  svg.querySelector("#cdf-hover").addEventListener("mousemove", e => {
    const rect = svg.getBoundingClientRect();
    const vx = (e.clientX - rect.left) * W / rect.width;
    const minutes = Math.max(0, Math.min(xMax, (vx - L) / (W - L - R) * xMax));
    cross.setAttribute("x1", x(minutes)); cross.setAttribute("x2", x(minutes));
    cross.setAttribute("visibility", "visible");
    const rows = ARMS.map(arm => {
      const times = DATA.arms[arm].transportTimesSeed0;
      const done = times.filter(t => t <= minutes).length;
      return `<div><span class="dot" style="background:var(${ARM_VAR[arm]});margin-right:5px"></span>` +
             `${ARM_LABEL[arm]}: <b>${Math.round(done / times.length * 100)}%</b></div>`;
    }).join("");
    showTip(e, `<b>${minutes.toFixed(0)}분까지 수용된 환자</b>${rows}`);
  });
  svg.querySelector("#cdf-hover").addEventListener("mouseleave", () => { cross.setAttribute("visibility", "hidden"); hideTip(); });
})();

// ── 병원별 막대 (팔별 3단) ───────────────────────────────────────────────────
(function drawBars() {
  const byMax = {};
  for (const arm of ARMS) for (const h of DATA.arms[arm].hospitals)
    byMax[h.hpid] = Math.max(byMax[h.hpid] || 0, h.arrivals);
  const top = Object.entries(byMax).sort((a, b) => b[1] - a[1]).slice(0, 12).map(([hpid]) => hpid);
  // 법인 접두사("학교법인가톨릭학원", "의료법인동신의료재단" 등)를 떼고 표시 —
  // 재단/학원으로 끝나는 머리말까지 통째로 제거한다.
  const name = {}; DATA.hospitals.forEach(h =>
    name[h.hpid] = h.name.replace(/^(학교법인|의료법인|사회복지법인)?[가-힣]*?(학원|재단)/, "").slice(0, 13));
  const xMax = Math.max(...top.map(h => byMax[h]), ...DATA.hospitals.map(h => h.capacity)) * 1.08;
  const rowH = 22, W = 1000, LBL = 150, colW = (W - LBL) / 3 - 18, H = top.length * rowH + 46;
  let svg = "";
  ARMS.forEach((arm, c) => {
    const ox = LBL + c * (colW + 18);
    svg += `<text x="${ox + colW/2}" y="14" text-anchor="middle" font-size="12" font-weight="600" fill="var(--ink-1)">${ARM_LABEL[arm]}</text>`;
    const rows = Object.fromEntries(DATA.arms[arm].hospitals.map(h => [h.hpid, h]));
    top.forEach((hpid, r) => {
      const h = rows[hpid]; if (!h) return;
      const yy = 26 + r * rowH;
      const wArr = Math.max(colW * h.arrivals / xMax, h.arrivals > 0 ? 2 : 0);
      const wCap = colW * h.capacity / xMax;
      const over = h.arrivals > h.capacity;
      const wOk = over ? Math.max(colW * h.capacity / xMax - 1, 0) : wArr;
      svg += `<g data-tip="${ARM_LABEL[arm]} · ${name[hpid]}|도착 ${h.arrivals}명 / 병상 ${h.capacity}${over ? `|<span style=color:var(--critical)>병상 초과 도착 ${(h.arrivals - h.capacity).toFixed(1)}명</span>` : ""}">`;
      svg += `<rect x="${ox}" y="${yy}" width="${wOk}" height="14" rx="3" fill="var(${ARM_VAR[arm]})"/>`;
      if (over) svg += `<rect x="${ox + wOk + 2}" y="${yy}" width="${Math.max(wArr - wOk - 2, 1.5)}" height="14" rx="3" fill="var(--critical)"/>`;
      svg += `<line x1="${ox + wCap}" y1="${yy - 2}" x2="${ox + wCap}" y2="${yy + 16}" stroke="var(--ink-2)" stroke-width="1.6"/>`;
      svg += `<rect x="${ox}" y="${yy - 3}" width="${colW}" height="20" fill="transparent"/></g>`;
    });
  });
  top.forEach((hpid, r) => {
    svg += `<text x="${LBL - 8}" y="${26 + r * rowH + 11}" text-anchor="end" font-size="11" fill="var(--ink-2)">${name[hpid]}</text>`;
  });
  document.getElementById("bars").innerHTML = `<svg viewBox="0 0 ${W} ${26 + top.length * rowH + 8}" style="width:100%;height:auto">${svg}</svg>`;
  document.querySelectorAll("#bars g[data-tip]").forEach(el => {
    el.addEventListener("mousemove", e => showTip(e, el.dataset.tip.split("|").map((s, i) => i ? `<div>${s}</div>` : `<b>${s}</b>`).join("")));
    el.addEventListener("mouseleave", hideTip);
  });
})();

// ── 재생 지도 ────────────────────────────────────────────────────────────────
(function replay() {
  const HOS = DATA.hospitals;
  const lats = HOS.map(h => h.lat).concat([S.scene.lat]), lngs = HOS.map(h => h.lng).concat([S.scene.lng]);
  const latMin = Math.min(...lats), latMax = Math.max(...lats);
  const lngMin = Math.min(...lngs), lngMax = Math.max(...lngs);
  const W = 1000, H = 480, PAD = 46;
  const kx = (W - 2 * PAD) / (lngMax - lngMin), ky = (H - 2 * PAD) / (latMax - latMin);
  const k = Math.min(kx, ky * 1.27);  // 경도 축척 보정(위도 37.5도)
  const px = lng => PAD + (lng - lngMin) * k;
  const py = lat => H - PAD - (lat - latMin) * k * 1.27;
  const seqRamp = ["--seq-100", "--seq-250", "--seq-400", "--seq-550", "--seq-700"];
  let currentArm = "goldenlink", tMax = 0, playing = null;
  const timelines = {}, trips = {};
  for (const arm of ARMS) {
    timelines[arm] = {};
    for (const row of DATA.arms[arm].timelineSeed0) timelines[arm][row.hpid] = row.events;
    for (const row of DATA.arms[arm].timelineSeed0)
      for (const ev of row.events) tMax = Math.max(tMax, ev[0]);
    trips[arm] = DATA.arms[arm].tripsSeed0 || [];
  }
  const coordOf = {};
  HOS.forEach(h => coordOf[h.hpid] = [h.lng, h.lat]);
  const posOf = hpid => hpid == null ? [px(S.scene.lng), py(S.scene.lat)] :
    [px(coordOf[hpid][0]), py(coordOf[hpid][1])];
  const mapEl = document.getElementById("map");
  let base = "";
  for (const h of HOS) {
    const r = 4 + Math.sqrt(h.capacity) * 2.6;
    base += `<g data-hpid="${h.hpid}"><circle class="hosp" cx="${px(h.lng)}" cy="${py(h.lat)}" r="${r}"
       fill="var(--seq-100)" stroke="var(--ring)" stroke-width="1"/></g>`;
  }
  base += `<text x="${px(S.scene.lng)}" y="${py(S.scene.lat) + 6}" text-anchor="middle" font-size="17">★</text>`;
  base += `<text x="${px(S.scene.lng)}" y="${py(S.scene.lat) + 22}" text-anchor="middle" font-size="10.5" fill="var(--ink-2)">이태원</text>`;
  base += `<g id="ambs"></g>`;  // 구급차 점 — 병원 원 위에 그린다
  mapEl.innerHTML = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;background:var(--surface-1);border-radius:8px">${base}</svg>`;
  const circles = {};
  mapEl.querySelectorAll("g[data-hpid]").forEach(g => circles[g.dataset.hpid] = g.querySelector("circle"));
  const ambLayer = mapEl.querySelector("#ambs");

  const stateAt = (arm, hpid, t) => {
    const evs = timelines[arm][hpid] || [];
    let arrivals = 0, admitted = 0;
    for (const [et, a, d] of evs) { if (et > t) break; arrivals = a; admitted = d; }
    return { arrivals, admitted };
  };
  function renderAt(t) {
    document.getElementById("clock").textContent = `${t.toFixed(0)}분`;
    for (const h of HOS) {
      const { arrivals } = stateAt(currentArm, h.hpid, t);
      const ratio = h.capacity > 0 ? arrivals / h.capacity : (arrivals > 0 ? 2 : 0);
      const step = ratio <= 0 ? 0 : Math.min(Math.floor(ratio * 4) + (ratio >= 1 ? 0 : 1), 4);
      const c = circles[h.hpid];
      c.setAttribute("fill", `var(${seqRamp[Math.min(step, 4)]})`);
      if (arrivals > h.capacity) { c.setAttribute("stroke", "var(--critical)"); c.setAttribute("stroke-width", "2.5"); }
      else { c.setAttribute("stroke", "var(--ring)"); c.setAttribute("stroke-width", "1"); }
      c.dataset.tip = `<b>${h.name}</b><div>가용 병상 ${h.capacity} · 도착 ${arrivals}명` +
        (arrivals > h.capacity ? ` <span style="color:var(--critical)">(+${arrivals - h.capacity} 초과)</span>` : "") + `</div>`;
    }
    // 이동 중인 구급차 — 구간(t0~t1) 안이면 직선 보간 위치에 점을 그린다.
    // 재이송(transfer) 구간은 critical 테두리로 구분 — 쏠림의 비용이 움직임으로 보인다.
    let dots = "";
    for (const tr of trips[currentArm]) {
      if (t < tr.t0 || t > tr.t1) continue;
      const [x0, y0] = posOf(tr.from), [x1, y1] = posOf(tr.to);
      const f = tr.t1 > tr.t0 ? (t - tr.t0) / (tr.t1 - tr.t0) : 1;
      const stroke = tr.kind === "transfer" ? "var(--critical)" : "var(--surface-1)";
      const opacity = tr.kind === "return" ? 0.35 : 1;
      dots += `<circle cx="${x0 + (x1 - x0) * f}" cy="${y0 + (y1 - y0) * f}" r="4"
        fill="var(${ARM_VAR[currentArm]})" stroke="${stroke}" stroke-width="1.6" opacity="${opacity}"/>`;
    }
    ambLayer.innerHTML = dots;
  }
  mapEl.querySelectorAll("circle.hosp").forEach(c => {
    c.addEventListener("mousemove", e => showTip(e, c.dataset.tip || ""));
    c.addEventListener("mouseleave", hideTip);
  });
  const scrub = document.getElementById("scrub");
  scrub.max = Math.ceil(tMax);
  scrub.addEventListener("input", () => { stop(); renderAt(+scrub.value); });
  const playBtn = document.getElementById("play");
  function stop() { if (playing) { clearInterval(playing); playing = null; playBtn.textContent = "▶ 재생"; } }
  playBtn.addEventListener("click", () => {
    if (playing) { stop(); return; }
    if (+scrub.value >= +scrub.max) scrub.value = 0;
    playBtn.textContent = "⏸ 정지";
    playing = setInterval(() => {
      scrub.value = Math.min(+scrub.value + Math.max(tMax / 240, 0.5), +scrub.max);
      renderAt(+scrub.value);
      if (+scrub.value >= +scrub.max) stop();
    }, 50);
  });
  const tabs = document.getElementById("arm-tabs");
  tabs.innerHTML = ARMS.map(arm =>
    `<button data-arm="${arm}" class="${arm === currentArm ? "active" : ""}">${ARM_LABEL[arm]}</button>`).join(" ");
  tabs.querySelectorAll("button").forEach(b => b.addEventListener("click", () => {
    currentArm = b.dataset.arm;
    tabs.querySelectorAll("button").forEach(x => x.classList.toggle("active", x === b));
    renderAt(+scrub.value);
  }));
  // #t=30&arm=nearest 형태의 해시로 초기 장면 지정 가능 (스크린샷·슬라이드 캡처용)
  const hash = new URLSearchParams(location.hash.slice(1));
  if (hash.get("arm") && ARMS.includes(hash.get("arm"))) {
    currentArm = hash.get("arm");
    tabs.querySelectorAll("button").forEach(x => x.classList.toggle("active", x.dataset.arm === currentArm));
  }
  scrub.value = Math.min(+(hash.get("t") || 0), +scrub.max);
  renderAt(+scrub.value);
})();

// ── 데이터 표 ────────────────────────────────────────────────────────────────
(function table() {
  let html = `<table><tr><th>병원</th><th>거리</th><th>병상</th>`;
  for (const arm of ARMS) html += `<th>${ARM_LABEL[arm]} 도착</th>`;
  html += `</tr>`;
  const rowsByArm = {};
  for (const arm of ARMS) rowsByArm[arm] = Object.fromEntries(DATA.arms[arm].hospitals.map(h => [h.hpid, h]));
  for (const h of DATA.hospitals) {
    html += `<tr><td>${h.name}</td><td>${h.distanceKm}km</td><td>${h.capacity}</td>`;
    for (const arm of ARMS) {
      const r = rowsByArm[arm][h.hpid];
      const over = r && r.arrivals > h.capacity;
      html += `<td${over ? ' style="color:var(--critical);font-weight:600"' : ""}>${r ? r.arrivals : "-"}</td>`;
    }
    html += `</tr>`;
  }
  document.getElementById("table").innerHTML = html + `</table>`;
})();

// ── 가정 ────────────────────────────────────────────────────────────────────
(function assume() {
  const p = S.params;
  const items = [
    `이동: 직선거리 × ${p.roadFactor}(도로 보정), 시속 ${p.speedKmh}km (심야 서울 가정)`,
    `시간 상수(가정): 적재 ${p.tLoadMin}분 · 인계 ${p.tHandoverMin}분 · 전화 1통 ${p.tCallMin}분 · 동시 요청 ${p.tBroadcastMin}분 · 재이송 추가 ${p.tTransferMin}분 — 상수를 흔들어도(민감도 run.py --sweep) 세 방식의 순서는 유지됨`,
    `중증도 분포(가정): immediate/urgent/delayed = ${p.severityMix.join("/")} — 이송 순서에만 사용`,
    `최근접·순차 전화 방식에도 구급차별 "직접 겪은 만실 기억"을 반영 — 베이스라인을 불리하게 과장하지 않기 위한 보정`,
    `병원 수용 능력은 E-Gen 가용 병상(hvec) 하나로 단순화 — 인력·수술실은 미반영. 신고 값이 처음부터 틀렸을 가능성(정보 무효)은 0으로 둔 보수적 설정(v2에서 infosurv 확률로 대체 예정)`,
    `사상자 수·중증도는 가정이며 실제 사건의 재현이 아님 — 병원 위치·병상만 실측`,
  ];
  document.getElementById("assume").innerHTML = items.map(s => `<li>${s}</li>`).join("");
})();
</script>
</body>
</html>
"""


def render(results: dict) -> str:
    return (
        _TEMPLATE
        .replace("__DATA__", json.dumps(results, ensure_ascii=False))
        .replace("__ARM_LABEL__", json.dumps(ARM_LABEL, ensure_ascii=False))
        .replace("__ARM_DESC__", json.dumps(ARM_DESC, ensure_ascii=False))
    )
