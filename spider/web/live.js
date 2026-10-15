// 실시간 모드(2026-10-14) — hub WebSocket에 관제 지도와 같은 역할(role=monitor)로 붙어, 실제 사건(구급차 대시보드에서
// 출동 → 휴대폰 통화로 뽑힌 환자 정보 → 병원 승인·불가 → 이송 확정 → 이송 → 도착)을 거미줄 3D로 그린다.
// 받는 메시지는 관제 지도(/map)와 똑같다: map_overview(병원·구급차 전체), case_meta(매칭 전 사건), case_overview(사건 요약 —
// 환자 KTAS·예상 병명·진료과·병원별 승인 상태), ambulance_phase/position(출동 시뮬레이션 위치·경로), case_closed·case_sync.
// 통화 전문·활력징후는 hub가 관제에 보내지 않으므로 여기도 없다. 이 파일은 상태 관리와 그리기만 하고 hub에 아무것도 보내지
// 않는다(identify뿐). "누가 어디로 가는가"는 hub가 정한 것을 그대로 보여 주고, 거미줄 모델의 선택은 "제안"으로만 겹쳐 그린다.
// ?apid=<구급차> 로 열면(아이패드 구급차 앱) 그 구급차의 사건·이동만 그린다
const ONLY_APID = new URLSearchParams(location.search).get('apid') || null;
const myCases = () => Object.values(HUB.cases).filter(c => !ONLY_APID || c.apid === ONLY_APID);
const mySims = () => Object.values(HUB.sims).filter(s => !ONLY_APID || s.apid === ONLY_APID);
const HUB = { connected: false, url: null, cases: {}, sims: {}, overview: null, log: [], suggest: {}, cond: {}, lastErr: null };
let hubWs = null, hubRetry = null, hubWanted = false, hubCaseTick = 0, suggestTimer = null, suggestSeq = 0;
const SEV_K = { high: 2, medium: 3, low: 4 };              // KTAS가 없을 때(예전 voice·매칭 전) 중증도 → 대표 KTAS
const SEV_LABEL = { high: '중증', medium: '중등증', low: '경증' };
const LEVEL_G = { '권역응급의료센터': 4, '지역응급의료센터': 3, '지역응급의료기관': 2, '응급실운영신고기관': 1 };
const PHASE_LABEL = { idle: '대기', dispatching: '출동 중', on_scene: '현장', transporting: '이송 중', at_hospital: '병원 도착', rerouting: '재선택', returning: '복귀 중' };
const STATUS_LABEL = { pending: '판단 대기', approved: '수용 승인', rejected: '수용 불가', confirmed: '이송 확정' };
const OK_COL = [94, 227, 127], SUG_COL = [127, 255, 212], GRAY = [124, 123, 116];


// ── 아이패드 구급차 앱(embed + apid): 카메라가 내 사건을 따라간다 ──
// 출동하면 현장으로, 이송이 확정되면 현장~병원이 다 보이게. 앱 쪽 화면 배치가 바뀌어(병원 리스트가 아래에서 올라옴) 지도 크기가
// 바뀌면 이동이 중간에 끊겼다 — 크기가 바뀐 뒤 마지막 목표로 다시 맞춘다. 사람이 지도를 만지면 그때부터는 따라가지 않는다.
let EMBED_FOCUS = null, embedResizeT = null;
function embedFocus(points) {
  if (!document.body.classList.contains('embed') || !points.length) return;
  const lngs = points.map(p => p.lng), lats = points.map(p => p.lat);
  const span = Math.max((Math.max(...lngs) - Math.min(...lngs)) * 0.79, Math.max(...lats) - Math.min(...lats));
  const zoom = points.length > 1 ? Math.min(13.2, Math.max(10.5, Math.log2(0.6 / Math.max(span, 0.01)) + 9.0)) : 12.6;
  EMBED_FOCUS = { longitude: (Math.min(...lngs) + Math.max(...lngs)) / 2, latitude: (Math.min(...lats) + Math.max(...lats)) / 2, zoom, pitch: 55, bearing: -18 };
  goCam(EMBED_FOCUS);
}
window.addEventListener('resize', () => {
  clearTimeout(embedResizeT);
  embedResizeT = setTimeout(() => { if (FOLLOW && ONLY_APID) { const s = HUB.sims[ONLY_APID]; if (s && s.gps) { followTo(s.gps, 0); return; } } if (EMBED_FOCUS) { VIEW = { ...VIEW, ...EMBED_FOCUS, transitionDuration: 0 }; setCam(VIEW); } }, 350);
});
let EMBED_USER = false;   // 사람이 지도를 한 번이라도 만졌으면 자동 맞춤(전체 보기)을 하지 않는다
['pointerdown', 'touchstart', 'wheel'].forEach(t => document.getElementById('map').addEventListener(t, () => { EMBED_FOCUS = null; EMBED_USER = true; }, { passive: true }));
// 앱이 부르는 함수 — 상황판 사건 목록을 누르면 그 현장으로(아이패드 SpiderWebView의 spiderFocus)
window.focusPoint = (lat, lng) => embedFocus([{ lat, lng }]);

// ── 보기 유지(2026-10-15): 앱에서 구급차 화면 ↔ 상황판을 오가면 지도가 새로 열려 처음 보기로 돌아갔다. 줌·기울기·방향(상황판은 중심까지)을
// 이 기기에 저장해 다시 열 때 그대로 띄운다. 구급차 화면은 중심을 내 구급차로 두고 줌·기울기만 이어 간다.
// 키는 앱이 알려 주는 화면(?screen=ambulance|board)이 우선 — auto 모드에서 출동 전 구급차 화면은 apid 없이 열려 상황판과 같은 키를 써서,
// 구급차 화면에서 옮긴 보기가 상황판으로 돌아왔을 때 덮어써졌다(줄이 화면 밖에 있어 사라진 것처럼 보임, 2026-10-15)
const VIEW_KEY = 'spider.view.' + (new URLSearchParams(location.search).get('screen') || (ONLY_APID ? 'ambulance' : 'board'));
let FOLLOW = !!ONLY_APID, lastSavedView = '';
function loadSavedView() { try { return JSON.parse(localStorage.getItem(VIEW_KEY) || 'null'); } catch (e) { return null; } }
function saveView() {
  if (!document.body.classList.contains('embed')) return;
  const v = { longitude: VIEW.longitude, latitude: VIEW.latitude, zoom: VIEW.zoom, pitch: VIEW.pitch, bearing: VIEW.bearing };
  const key = JSON.stringify(v); if (key === lastSavedView) return;
  lastSavedView = key; try { localStorage.setItem(VIEW_KEY, key); } catch (e) { /* 저장 안 돼도 화면은 그대로 */ }
}
setInterval(saveView, 1500);
(function restoreView() {
  if (!document.body.classList.contains('embed')) return;
  const v = loadSavedView();
  if (ONLY_APID) {   // 구급차 화면: 중심은 내 구급차가 정한다 — 줌·기울기·방향만 되살린다(없으면 동네 단위)
    VIEW = { ...VIEW, zoom: v ? v.zoom : 13.4, pitch: v ? v.pitch : 55, bearing: v ? v.bearing : -18 };
  } else if (v) {    // 상황판: 마지막 보기 그대로 — 자동 전체 맞춤도 하지 않는다(사람이 맞춘 보기를 존중)
    VIEW = { ...VIEW, ...v }; EMBED_USER = true;
  }
  setCam({ ...VIEW, transitionDuration: 0 });
})();
// 손가락이 지도에 닿아 있는 동안은 따라가기를 잠시 쉰다 — 핀치 도중 카메라를 옮기면 제스처가 끊긴다
let TOUCHING = 0;
['touchstart', 'pointerdown'].forEach(t => document.getElementById('map').addEventListener(t, () => { TOUCHING = Date.now(); }, { passive: true }));
['touchend', 'touchcancel', 'pointerup'].forEach(t => document.addEventListener(t, () => { TOUCHING = 0; }, { passive: true }));
function followTo(gps, dur, force) {
  if (!FOLLOW || !gps || (!force && TOUCHING && Date.now() - TOUCHING < 8000)) return;
  VIEW = { ...VIEW, longitude: gps.lng, latitude: gps.lat, transitionDuration: dur };
  setCam(VIEW);
}
// 내 구급차 위치 — 시뮬레이션 위치가 없으면(아직 상태를 못 받음) hub 구급차 목록의 위치(기지)
function myGps() {
  const s = HUB.sims[ONLY_APID]; if (s && s.gps) return s.gps;
  const a = HUB.overview && (HUB.overview.ambulances || []).find(x => x.apid === ONLY_APID);
  return a ? a.gps : null;
}
// 사람이 지도를 끌어 옮기면 따라가기를 멈춘다(확대·축소·회전은 따라가기 유지). 앱의 [내 구급차] 버튼이 followMine()으로 다시 켠다.
window.onUserPan = () => { if (ONLY_APID) FOLLOW = false; };
// 버튼은 사람이 직접 누른 것이라 손가락 쉬기(TOUCHING)를 따지지 않는다. 따라갈 구급차가 없는 화면(auto에서 출동 전)이면 전체 보기로
window.followMine = () => {
  EMBED_FOCUS = null;
  if (!ONLY_APID) { window.fitAllNow(); return; }
  FOLLOW = true; TOUCHING = 0;
  followTo(myGps(), 700, true);
};
// 상황판 [전체 보기] — 모든 현장과 이송 병원이 다 보이게
window.fitAllNow = () => { EMBED_USER = false; scheduleFitAll(); EMBED_USER = true; };
// 상황판(embed, apid 없음): 새 사건이 생길 때마다 모든 현장이 다 보이게 맞춘다 — 사건마다 카메라가 튀지 않게 모아서 한 번
let fitAllT = null;
function scheduleFitAll() {
  if (!document.body.classList.contains('embed') || ONLY_APID || EMBED_USER) return;
  clearTimeout(fitAllT);
  fitAllT = setTimeout(() => {
    // 현장과 이송 확정 병원이 다 들어오게(대량사고에서 환자가 흩어져 간 병원까지 한 화면에)
    const pts = myCases().map(casePos).filter(Boolean);
    for (const c of myCases()) { const h = caseConfirmed(c) && hp(caseConfirmed(c).hospitalId); if (h) pts.push({ lat: h.lat, lng: h.lng }); }
    if (pts.length) embedFocus(pts);
  }, 700);
}

function hubWsUrl() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const u = META && META.hubWsUrl;
  if (!u) return `${proto}://${location.host}/ws/dashboard`;   // 같은 호스트 — 터널이 /ws/dashboard 를 hub로 보낸다
  try {
    const x = new URL(u);
    // start-all이 로컬 모드로 준 127.0.0.1은 이 맥북 기준이다 — 아이패드가 LAN으로 열었으면 자기 접속 호스트로 바꾼다
    if ((x.hostname === '127.0.0.1' || x.hostname === 'localhost') && !['127.0.0.1', 'localhost'].includes(location.hostname)) x.hostname = location.hostname;
    return x.toString();
  } catch (e) { return u; }
}
function hubConnect() {
  hubWanted = true;
  if (hubWs) return;
  const url = hubWsUrl(); HUB.url = url;
  let ws;
  try { ws = new WebSocket(url); } catch (e) { HUB.lastErr = String(e); hubScheduleRetry(); onHubChange(true); return; }
  hubWs = ws;
  ws.onopen = () => { HUB.connected = true; HUB.lastErr = null; ws.send(JSON.stringify({ type: 'identify', role: 'monitor', id: 'spider' })); onHubChange(true); };
  ws.onmessage = ev => { let m; try { m = JSON.parse(ev.data); } catch (e) { return; } handleHub(m); };
  ws.onclose = () => { HUB.connected = false; hubWs = null; onHubChange(true); if (hubWanted) hubScheduleRetry(); };
  ws.onerror = () => { HUB.lastErr = '연결 실패 — hub가 떠 있는지, 주소가 맞는지 확인'; };
}
function hubScheduleRetry() { clearTimeout(hubRetry); hubRetry = setTimeout(() => { if (hubWanted && !hubWs) hubConnect(); }, 3000); }
function hubDisconnect() { hubWanted = false; clearTimeout(hubRetry); if (hubWs) { hubWs.close(); hubWs = null; } HUB.connected = false; }

function handleHub(m) {
  let caseChanged = true;
  switch (m.type) {
    case 'map_overview': applyOverview(m); break;
    case 'case_meta': {
      const c = HUB.cases[m.caseId] || { caseId: m.caseId, hospitals: [], events: [] };
      Object.assign(c, { num: m.num, startedAt: m.startedAt, symptom: m.symptom ?? c.symptom, severityTag: m.severity || c.severityTag,
        apid: m.apid || c.apid, ambulanceName: m.ambulanceName || c.ambulanceName, events: m.events || c.events, pre: true });
      HUB.cases[m.caseId] = c; scheduleFitAll(); break;
    }
    case 'case_overview': {
      const prev = HUB.cases[m.caseId] || {}; HUB.cases[m.caseId] = { ...prev, ...m, pre: false };
      // 패널이 없는 아이패드 WebView(embed)에선 새 사건이 매칭될 때 카메라를 그 현장으로 — 사람이 잡고 있으면 건드리지 않는다
      // (매칭 전 case_meta로 먼저 생긴 사건도 "처음 매칭"으로 본다)
      if (!ONLY_APID && prev.caseId && !prev.pre && (caseConfirmed(prev) || {}).hospitalId !== (caseConfirmed(m) || {}).hospitalId) scheduleFitAll();
      if ((!prev.caseId || prev.pre) && document.body.classList.contains('embed')) {
        if (!ONLY_APID) scheduleFitAll();   // 구급차 화면은 내 구급차를 따라가므로 따로 맞추지 않는다
      }
      break;
    }
    case 'case_closed': {
      const c = HUB.cases[m.caseId];
      if (c) { HUB.log.push({ t: new Date().toISOString(), kind: m.reason === 'done' ? 'd' : 'c', text: `<b>#${c.num ?? '?'}</b> 사건 종료 (${m.reason})` }); delete HUB.cases[m.caseId]; delete HUB.suggest[m.caseId]; }
      break;
    }
    case 'case_sync': { const keep = new Set(m.caseIds || []); for (const id of Object.keys(HUB.cases)) if (!keep.has(id)) { delete HUB.cases[id]; delete HUB.suggest[id]; } break; }
    case 'ambulance_phase': {
      HUB.sims[m.apid] = { ...m };
      if (ONLY_APID && m.apid === ONLY_APID) followTo(m.gps, 700);   // 내 구급차가 화면 가운데
      break;
    }
    case 'ambulance_position': { const p = HUB.sims[m.apid] || {}; HUB.sims[m.apid] = { ...p, ...m, path: m.path || p.path || null }; if (ONLY_APID && m.apid === ONLY_APID) followTo(m.gps, 950); caseChanged = false; break; }
    default: return;
  }
  if (caseChanged) hubCaseTick++;
  onHubChange(caseChanged);
}
// 병원 전체 목록(관제 지도와 같은 것) — spider 병원 목록(E-Gen 스냅샷)의 응급실 가용을 hub 현재값으로 덮어 만실 색이 실시간이 되게
// 하고, spider 목록에 없는 병원은 등급만으로 추가한다(z = 등급). 새 배열로 바꿔야 deck.gl이 색을 다시 계산한다.
function applyOverview(m) {
  HUB.overview = m;
  for (const mh of m.hospitals || []) {
    let h = HMAP.get(mh.hospitalId);
    if (!h) {
      const g = LEVEL_G[mh.emergencyLevel] || 1;
      h = { hpid: mh.hospitalId, name: mh.name, lat: mh.gps.lat, lng: mh.gps.lng, grade: mh.emergencyLevel || '(등급 없음)', g, z: g, severeY: 0, severeNo: 0,
        hvec: null, er_cap: null, icu: null, op: null, ct: null, angio: null, hasBeds: true, hasSevere: false, em: null, fromHub: true };
      H.push(h); HMAP.set(h.hpid, h);
    }
    h.hasBeds = true;
    h.hvec = mh.bedCountUnknown ? null : mh.availableBedCount;
    h.inFlight = mh.inFlightCount || 0;
  }
  LIVE = H.filter(h => h.hasBeds); DEAD = H.filter(h => !h.hasBeds);
}

// ── 사건 → 화면 재료 ──
const caseK = c => [1, 2, 3, 4, 5].includes(+c.ktasLevel) ? +c.ktasLevel : (SEV_K[c.severityTag] || 3);
function casePos(c) {
  const sim = c.apid ? HUB.sims[c.apid] : null;
  if (sim && sim.incident) return sim.incident;
  if (c.ambulanceGps) return c.ambulanceGps;
  return null;
}
const caseConfirmed = c => (c.hospitals || []).find(h => h.status === 'confirmed') || null;
// 지금 이 환자를 실제로 보낼 수 있는 승인 병원인가(2026-10-15) — 수용 승인을 눌렀어도 그 뒤 응급실 병상 0이 확인됐거나(E-Gen,
// 이송 확정 차감 반영 — 미상·1일 넘은 값은 막지 않음), 이 사건에서 제외됐거나(이송 중 철회·도착 후 수용 불가), 병원 공지로 이 질환군을
// 막았으면 초록 '최적' 줄을 긋지 않는다. 예전엔 hub 순위의 첫 승인 병원을 그대로 써서 병상 없는 병원이 '최적'으로 보였다.
function transportable(ch) {
  if (ch.status !== 'approved') return false;
  if (ch.unavailableReason || ch.excluded) return false;
  if ((ch.demoteReasons || []).some(r => r === 'beds_full' || r === 'severe_blocked')) return false;
  if (!ch.bedCountUnknown && !ch.bedDataStale && ch.availableBedCount != null && ch.availableBedCount <= 0) return false;
  return true;
}
function caseLabel(c) { return `#${c.num ?? '?'} K${caseK(c)}`; }
// 경로 위에서 지금 위치에 가장 가까운 꼭짓점 — 지난 구간(회색)과 남은 구간(색)을 나눈다
function splitPath(path, gps) {
  if (!path || !path.length || !gps) return { done: [], left: [] };
  let bi = 0, bd = Infinity;
  for (let i = 0; i < path.length; i++) { const d = (path[i][0] - gps.lat) ** 2 + ((path[i][1] - gps.lng) * 0.79) ** 2; if (d < bd) { bd = d; bi = i; } }
  const ll = p => [p[1], p[0], 0];
  return { done: [...path.slice(0, bi + 1).map(ll), [gps.lng, gps.lat, 0]], left: [[gps.lng, gps.lat, 0], ...path.slice(bi + 1).map(ll)] };
}

// ── 이름표 겹침 줄이기(2026-10-15) ──
// 대량사고는 한 지점에서 일어나 구급대·환자 이름표가 같은 자리에 겹쳐 읽을 수 없었다. 화면에서 가까운(이름표 한 칸 안) 것끼리
// 묶어 이름표를 하나만 그린다 — "구급대 5대 · 이송 3 · 현장 2"처럼. 확대해 떨어지면 다시 하나씩 보인다.
function screenCells(lat, cellPxW, cellPxH) {
  const mpp = 78271.517 * Math.cos(lat * Math.PI / 180) / Math.pow(2, VIEW.zoom);   // deck(512px 타일) 기준 1px당 미터
  return { w: cellPxW * mpp / (111320 * Math.cos(lat * Math.PI / 180)), h: cellPxH * mpp / 110540 };   // 도(°) 단위 칸 크기
}
function groupByScreen(items, cellPxW, cellPxH) {
  if (!items.length) return [];
  // 지도가 실제로 그리는 화면 좌표로 묶는다 — 기울인(pitch) 지도에선 위도·경도 거리와 화면 거리가 달라 칸 나누기로는 덜 묶였다
  // 지도 준비 전(첫 그리기)엔 deck이 viewport를 아직 안 갖고 있어 getViewports가 assert로 멈춘다 — 그땐 칸 계산으로 대신
  let vp = null;
  try { vp = (deckgl.viewManager && deckgl.getViewports()[0]) || null; } catch (e) { vp = null; }
  const c = vp ? null : screenCells(items[0].pos[1], cellPxW, cellPxH);
  const pts = items.map(it => {
    const p = vp ? vp.project([it.pos[0], it.pos[1], it.pos[2] || 0]) : [it.pos[0] / c.w * cellPxW, -it.pos[1] / c.h * cellPxH];
    return { it, x: p[0], y: p[1] };
  });
  // 가까운 것끼리 차례로 붙인다(이름표 한 칸 안이면 같은 묶음)
  const groups = [];
  for (const p of pts) {
    const g = groups.find(g => Math.abs(g.x - p.x) < cellPxW && Math.abs(g.y - p.y) < cellPxH);
    if (g) { g.items.push(p.it); g.x = (g.x * (g.items.length - 1) + p.x) / g.items.length; g.y = (g.y * (g.items.length - 1) + p.y) / g.items.length; }
    else groups.push({ items: [p.it], x: p.x, y: p.y });
  }
  return groups.map(g => ({ items: g.items, pos: [g.items.reduce((a, b) => a + b.pos[0], 0) / g.items.length, g.items.reduce((a, b) => a + b.pos[1], 0) / g.items.length, g.items[0].pos[2] || 0] }));
}
const shortUnit = n => String(n || '').replace(/119안전센터\s*/, ' ').replace(/\s+/g, ' ').trim();
const PHASE_SHORT = { dispatching: '출동', on_scene: '현장', transporting: '이송', at_hospital: '도착', rerouting: '재선택', returning: '복귀' };

function liveLayers(t) {
  const LK = zoomK();   // 연결선 굵기 배율 — 확대하면 가늘게, 축소하면 굵게(공중 노드와 같은 배율)
  const hs = HS(), pulse = 0.5 + 0.5 * Math.sin(performance.now() / 350), air = $('air').checked;
  const lines = [], airLines = [], lights = [], airLights = [], stems = [], ups = [], occ = [], ambs = [], paths = [], donePaths = [], sugLines = [], sugTexts = [], ambTexts = [], bestTexts = [];
  const top = h => [h.lng, h.lat, ZH(h.z) * hs];
  for (const c of myCases()) {
    const pos = casePos(c); if (!pos) continue;
    const k = caseK(c), kc = kCol(k).slice(0, 3), pz = KTAS_Z[k];
    const sim = c.apid ? HUB.sims[c.apid] : null;
    const confirmed = caseConfirmed(c);
    const arrived = sim && (sim.phase === 'at_hospital' || sim.phase === 'returning') && confirmed;
    if (!arrived) {
      lights.push({ pos: [pos.lng, pos.lat, 0], k, label: caseLabel(c) });
      if (air) { airLights.push({ pos: [pos.lng, pos.lat, ZH(pz) * hs], k }); stems.push({ a: [pos.lng, pos.lat, 0], b: [pos.lng, pos.lat, ZH(pz) * hs], k }); }
    }
    // 줄은 "이 환자가 어디로 가나"만 보이게(2026-10-15): 확정되면 확정 병원 하나, 확정 전엔 수용 승인한 병원 중 hub 순위
    // 1위(=구급차 화면의 '추천', 이송 중 부하·포화·중증도 가산이 반영된 최적) 하나. 아직 승인한 곳이 없으면 요청이 나간 병원에
    // 아주 옅은 줄만(동시 전달 중이라는 표시). 예전엔 요청한 병원 전부에 줄이 그려져 어느 줄이 최적인지 알 수 없었다.
    // 승인 병원이 있어도 지금 보낼 수 없는 곳(병상 0 확인·제외·차단)은 건너뛴다 — 보낼 수 있는 승인 병원이 하나도 없으면 아직 응답을
    // 기다리는 병원(판단 대기)에만 옅은 줄. 아이패드 상황판(embed, apid 없음)은 '최적' 이름표를 달지 않는다(사건이 몰리면 이름표가 겹친다 — 자리 재검토 중).
    const best = confirmed || (c.hospitals || []).find(transportable) || null;
    if (best && !confirmed && !arrived && (ONLY_APID || !document.body.classList.contains('embed'))) { const bh = hp(best.hospitalId); if (bh) bestTexts.push({ pos: top(bh), text: `${caseLabel(c)} 최적 · ${shortName(bh.name)}` }); }
    for (const ch of c.hospitals || []) {
      const h = hp(ch.hospitalId); if (!h) continue;
      const st = ch.status;
      if (best ? ch.hospitalId !== best.hospitalId : (st !== 'pending' || ch.unavailableReason || ch.excluded)) continue;
      let col, w, a;
      if (st === 'confirmed') { col = kc; w = 3; a = 240; }
      else if (st === 'approved') { col = OK_COL; w = 3; a = 235; }
      else { col = kc; w = 1; a = 45; }
      if (st === 'confirmed' && sim && sim.path && (sim.phase === 'transporting' || sim.phase === 'at_hospital')) {
        // 확정 병원으로는 hub(카카오 내비)가 준 실제 이송 경로를 그린다 — 지나온 구간 회색, 남은 구간 KTAS 색
        const sp = splitPath(sim.path, sim.gps || pos);
        if (sp.done.length > 1) donePaths.push({ path: sp.done });
        if (sp.left.length > 1) paths.push({ path: sp.left, col });
      } else if (!arrived) {
        lines.push({ a: [pos.lng, pos.lat, 0], b: [h.lng, h.lat, 0], col: [...col, a], w });
      }
      if (air && !arrived) {
        airLines.push({ a: [pos.lng, pos.lat, ZH(pz) * hs], b: top(h), col: [...col, st === 'pending' ? 35 : a], w: st === 'pending' ? 0.8 : w });
      }
      if (st === 'confirmed' || st === 'approved') ups.push({ a: [h.lng, h.lat, 0], b: top(h), col: [...col, 160] });
      if (arrived && st === 'confirmed') occ.push({ h, label: sim.phase === 'at_hospital' ? `${caseLabel(c)} 도착 · 수용 대기` : `${caseLabel(c)} 수용 완료` });
    }
    // 거미줄 모델의 제안(비교용) — hub의 선택과 다른 병원이면 민트색 줄
    const sug = HUB.suggest[c.caseId];
    if (sug && $('suggest').checked && !arrived) {
      const h = hp(sug.hpid);
      if (h) {
        sugLines.push({ a: [pos.lng, pos.lat, 0], b: [h.lng, h.lat, 0] });
        if (air) airLines.push({ a: [pos.lng, pos.lat, ZH(pz) * hs], b: top(h), col: [...SUG_COL, 150], w: 1.5 });
        // 상황판(apid 없음)에선 이름표를 달지 않는다 — 대량사고 현장에 사건마다 하나씩 붙어 구급차 노드를 가렸다(줄만, 2026-10-15)
        if (ONLY_APID || !document.body.classList.contains('embed')) sugTexts.push({ pos: [(pos.lng + h.lng) / 2, (pos.lat + h.lat) / 2, 0], text: `거미줄 제안 → ${shortName(h.name)}${confirmed && confirmed.hospitalId !== sug.hpid ? ' (hub와 다름)' : ''}` });
      }
    }
  }
  // 구급차: 출동 중·이송 중·재선택·복귀 중인 것만(기지 대기는 관제 지도의 몫)
  for (const sim of mySims()) {
    // 아이패드 구급차 화면(apid)에선 기지 대기 중인 내 구급차도 보인다 — 어디 있는지가 기준점이다
    if (!sim.gps || !sim.phase || (sim.phase === 'idle' && !(ONLY_APID && sim.apid === ONLY_APID))) continue;
    const c = sim.caseId ? HUB.cases[sim.caseId] : null;
    const k = c ? caseK(c) : 5, kc = c ? kCol(k).slice(0, 3) : [200, 200, 200];
    ambs.push({ pos: [sim.gps.lng, sim.gps.lat, 0], col: sim.phase === 'returning' ? GRAY : kc, me: !!ONLY_APID && sim.apid === ONLY_APID });
    const name = (HUB.overview && (HUB.overview.ambulances.find(a => a.apid === sim.apid) || {}).name) || sim.apid;
    ambTexts.push({ pos: [sim.gps.lng, sim.gps.lat, 0], name: shortUnit(name), phase: sim.phase, paused: sim.paused, me: !!ONLY_APID && sim.apid === ONLY_APID });
    if (sim.path && (sim.phase === 'dispatching' || sim.phase === 'returning' || sim.phase === 'rerouting')) {
      const sp = splitPath(sim.path, sim.gps);
      if (sp.left.length > 1) paths.push({ path: sp.left, col: sim.phase === 'dispatching' ? [242, 241, 236] : GRAY, thin: true });
    }
  }
  // 이름표 묶기 — 구급대(이름표 폭 약 170px), 환자 번호(약 70px), 병원 도착(병원별)
  const ambLabels = groupByScreen(ambTexts, 180, 34).map(g => {
    if (g.items.length === 1) { const a = g.items[0]; return { pos: g.pos, text: `🚑 ${ONLY_APID && a.me ? '내 구급차' : a.name} · ${PHASE_LABEL[a.phase] || a.phase}${a.paused ? ' (정지)' : ''}` }; }
    const cnt = {}; g.items.forEach(a => { cnt[a.phase] = (cnt[a.phase] || 0) + 1; });
    return { pos: g.pos, text: `🚑 구급대 ${g.items.length}대 · ` + Object.entries(cnt).map(([p, n]) => `${PHASE_SHORT[p] || p} ${n}`).join(' · ') };
  });
  const lightLabels = groupByScreen(lights, 90, 30).map(g => {
    if (g.items.length === 1) return { pos: g.pos, text: g.items[0].label, k: g.items[0].k };
    const ids = g.items.map(i => i.label.split(' ')[0]);
    const worst = Math.min(...g.items.map(i => i.k));
    return { pos: g.pos, text: `${ids.slice(0, 4).join('·')}${ids.length > 4 ? ` 외 ${ids.length - 4}` : ''} · 환자 ${g.items.length}명`, k: worst };
  });
  const occByH = new Map();
  for (const o of occ) { const e = occByH.get(o.h.hpid); if (e) e.labels.push(o.label); else occByH.set(o.h.hpid, { h: o.h, labels: [o.label] }); }
  const occLabels = [...occByH.values()].map(e => ({ h: e.h, label: e.labels.length === 1 ? e.labels[0] : `환자 ${e.labels.length}명 · ${e.labels.map(l => l.split(' ')[0]).join('·')} 도착` }));
  const L = [];
  L.push(new LineLayer({ id: 'lv-lines', widthScale: LK, data: lines, getSourcePosition: d => d.a, getTargetPosition: d => d.b, getColor: d => d.col, getWidth: d => d.w, widthUnits: 'pixels', parameters: { depthTest: false } }));
  L.push(new PathLayer({ id: 'lv-done', widthScale: LK, data: donePaths, getPath: d => d.path, getColor: [124, 123, 116, 120], getWidth: 1.5, widthUnits: 'pixels', parameters: { depthTest: false } }));
  L.push(new PathLayer({ id: 'lv-paths', widthScale: LK, data: paths, getPath: d => d.path, getColor: d => [...d.col, d.thin ? 110 : 220], getWidth: d => d.thin ? 1.5 : 3, widthUnits: 'pixels', parameters: { depthTest: false }, updateTriggers: { getPath: [hubCaseTick, performance.now() | 0] } }));
  L.push(new LineLayer({ id: 'lv-sug', widthScale: LK, data: sugLines, getSourcePosition: d => d.a, getTargetPosition: d => d.b, getColor: [...SUG_COL, 200], getWidth: 2, widthUnits: 'pixels', parameters: { depthTest: false } }));
  L.push(new TextLayer({ id: 'lv-sug-txt', data: sugTexts, getPosition: d => d.pos, getText: d => d.text, getSize: 11, characterSet: 'auto', getColor: [...SUG_COL, 255], fontFamily: css('--font'), background: true, getBackgroundColor: [10, 16, 36, 170], backgroundPadding: [4, 2], parameters: { depthTest: false } }));
  L.push(new TextLayer({ id: 'lv-best-txt', data: bestTexts, getPosition: d => d.pos, getText: d => d.text, getSize: 11, characterSet: 'auto', getColor: [94, 227, 127, 255], getPixelOffset: [0, -22], fontFamily: css('--font'), background: true, getBackgroundColor: [10, 16, 36, 180], backgroundPadding: [4, 2], parameters: { depthTest: false } }));
  L.push(new LineLayer({ id: 'lv-air-glow', widthScale: LK, data: airLines, getSourcePosition: d => d.a, getTargetPosition: d => d.b, getColor: d => [d.col[0], d.col[1], d.col[2], 60], getWidth: 8, widthUnits: 'pixels', parameters: ADD }));
  L.push(new LineLayer({ id: 'lv-air', widthScale: LK, data: airLines, getSourcePosition: d => d.a, getTargetPosition: d => d.b, getColor: d => d.col, getWidth: d => d.w, widthUnits: 'pixels', parameters: { depthTest: false } }));
  L.push(new LineLayer({ id: 'lv-stems', widthScale: LK, data: stems, getSourcePosition: d => d.a, getTargetPosition: d => d.b, getColor: d => [...kCol(d.k).slice(0, 3), 130], getWidth: 1.5, widthUnits: 'pixels', parameters: ADD }));
  L.push(new LineLayer({ id: 'lv-ups', widthScale: LK, data: ups, getSourcePosition: d => d.a, getTargetPosition: d => d.b, getColor: d => d.col, getWidth: 2, widthUnits: 'pixels', parameters: ADD }));
  L.push(new ScatterplotLayer({ id: 'lv-air-light-glow', data: airLights, radiusUnits: 'meters', getRadius: 200 + pulse * 50, getPosition: d => d.pos, getFillColor: d => [...kCol(d.k).slice(0, 3), 100], parameters: ADD, updateTriggers: { getRadius: [animTick] } }));
  L.push(new ScatterplotLayer({ id: 'lv-air-light', data: airLights, radiusUnits: 'meters', getRadius: 55, radiusMinPixels: 5, getPosition: d => d.pos, getFillColor: [255, 255, 255, 245], stroked: true, getLineColor: d => kCol(d.k), lineWidthMinPixels: 2, parameters: { depthTest: false } }));
  L.push(new ScatterplotLayer({ id: 'lv-occ', data: occ, radiusUnits: 'meters', getRadius: 290 + pulse * 60, getPosition: d => top(d.h), getFillColor: [79, 209, 255, 0], stroked: true, getLineColor: [79, 209, 255, 200], lineWidthMinPixels: 2, parameters: { depthTest: false }, updateTriggers: { getRadius: [animTick] } }));
  L.push(new TextLayer({ id: 'lv-occ-txt', data: occLabels, getPosition: d => top(d.h), getText: d => d.label, getSize: 12, characterSet: 'auto', getColor: [79, 209, 255, 255], getPixelOffset: [0, -36], fontFamily: css('--font'), background: true, getBackgroundColor: [10, 16, 36, 170], backgroundPadding: [4, 2], parameters: { depthTest: false } }));
  L.push(new ScatterplotLayer({ id: 'lv-light-glow', data: lights, radiusUnits: 'meters', getRadius: 160 + pulse * 40, getPosition: d => d.pos, getFillColor: d => [...kCol(d.k).slice(0, 3), 90], parameters: ADD, updateTriggers: { getRadius: [animTick] } }));
  L.push(new ScatterplotLayer({ id: 'lv-light', data: lights, radiusUnits: 'meters', getRadius: 45, radiusMinPixels: 4, getPosition: d => d.pos, getFillColor: d => kCol(d.k), stroked: true, getLineColor: [255, 255, 255, 230], lineWidthMinPixels: 1.5, parameters: { depthTest: false } }));
  L.push(new TextLayer({ id: 'lv-light-txt', data: lightLabels, getPosition: d => d.pos, getText: d => d.text, getSize: 12, characterSet: 'auto', getColor: [242, 241, 236, 255], getPixelOffset: [0, -16], fontFamily: css('--mono'), background: true, getBackgroundColor: [10, 16, 36, 170], backgroundPadding: [4, 2], parameters: { depthTest: false } }));
  // 구급차는 화면 픽셀 크기(축소해도 보이게). 내 구급차는 크게 + 맥박 고리
  const NK = zoomK();
  L.push(new ScatterplotLayer({ id: 'lv-amb-glow', data: ambs, radiusUnits: 'pixels', getRadius: d => (d.me ? 22 : 11) * (1 + 0.25 * pulse), getPosition: d => d.pos, getFillColor: d => d.me ? [79, 209, 255, 110] : [...d.col, 110], parameters: ADD, updateTriggers: { getRadius: [animTick], getPosition: [performance.now() | 0] } }));
  L.push(new ScatterplotLayer({ id: 'lv-amb-ring', data: ambs.filter(d => d.me), radiusUnits: 'pixels', getRadius: 13 + 10 * pulse, getPosition: d => d.pos, getFillColor: [0, 0, 0, 0], stroked: true, getLineColor: [79, 209, 255, Math.round(230 * (1 - pulse))], lineWidthUnits: 'pixels', getLineWidth: 2, parameters: { depthTest: false }, updateTriggers: { getRadius: [animTick], getLineColor: [animTick], getPosition: [performance.now() | 0] } }));
  L.push(new ScatterplotLayer({ id: 'lv-amb', data: ambs, radiusUnits: 'pixels', getRadius: d => (d.me ? 9 : 5.5) * Math.max(0.8, NK), getPosition: d => d.pos, getFillColor: [255, 255, 255, 255], stroked: true, getLineColor: d => d.me ? [79, 209, 255, 255] : [...d.col, 255], lineWidthUnits: 'pixels', getLineWidth: d => d.me ? 3.5 : 2.5, parameters: { depthTest: false }, updateTriggers: { getRadius: [Math.round(VIEW.zoom * 10)], getPosition: [performance.now() | 0] } }));
  L.push(new TextLayer({ id: 'lv-amb-txt', data: ambLabels, getPosition: d => d.pos, getText: d => d.text, getSize: 11, characterSet: 'auto', getColor: [242, 241, 236, 255], getPixelOffset: [0, 16], fontFamily: css('--font'), background: true, getBackgroundColor: [10, 16, 36, 170], backgroundPadding: [4, 2], parameters: { depthTest: false }, updateTriggers: { getPosition: [performance.now() | 0] } }));
  return L;
}

// ── 패널 ──
function onHubChange(caseChanged) {
  if (MODE !== 'live') return;
  if (caseChanged) { renderLivePanel(); renderLiveSide(); scheduleSuggest(); }
}
function caseStatusCounts(c) {
  const n = { pending: 0, approved: 0, rejected: 0, confirmed: 0 };
  for (const h of c.hospitals || []) n[h.status] = (n[h.status] || 0) + 1;
  return n;
}
function renderLivePanel() {
  const st = $('livestatus');
  st.innerHTML = HUB.connected
    ? `<span style="color:var(--ok)">● hub 연결됨</span> <span class="st">${HUB.url}</span>`
    : `<span style="color:var(--k1)">○ hub 연결 안 됨 — 3초마다 재시도</span> <span class="st">${HUB.url || ''}${HUB.lastErr ? ' · ' + HUB.lastErr : ''}</span>`;
  const box = $('livecases'); box.innerHTML = '';
  const cases = myCases().sort((a, b) => (a.num ?? 1e9) - (b.num ?? 1e9));
  if (!cases.length) { box.innerHTML = `<p class="note" style="margin:0">진행 중인 사건이 없습니다. 구급차 대시보드에서 [이동] → 현장 도착 → 휴대폰 전화 앱으로 통화하면 여기에 뜹니다.</p>`; return; }
  for (const c of cases) {
    const k = caseK(c), sim = c.apid ? HUB.sims[c.apid] : null, confirmed = caseConfirmed(c), n = caseStatusCounts(c), sug = HUB.suggest[c.caseId];
    const div = document.createElement('div'); div.className = 'lcase';
    const phase = sim ? (PHASE_LABEL[sim.phase] || sim.phase) : (c.pre ? '매칭 전' : '요청 중');
    div.innerHTML = `
      <div class="hd"><span class="pill k" style="--c:var(--k${k})">K${k}</span><span>#${c.num ?? '?'}</span><span class="st">${SEV_LABEL[c.severityTag] || ''}${c.ktasLevel ? '' : ' (KTAS 추정)'}</span><span class="st" style="margin-left:auto">${phase}${c.paused ? ' · 정지' : ''}</span></div>
      <div>${c.expectedDiagnosis || c.symptom || '증상 정보 없음'}${c.chiefComplaint ? ` <span class="st">· ${c.chiefComplaint}</span>` : ''}</div>
      <div class="st">${c.patient ? c.patient + ' · ' : ''}${c.requiredDepartment ? '필요 진료과 ' + c.requiredDepartment + ' · ' : ''}${c.ambulanceName || c.apid || ''}${c.confirmedBy ? ' · ' + (c.confirmedBy === 'paramedic' ? '구급대원 확인' : 'AI 요약(확인 전)') : ''}</div>
      <div class="st">${c.pre ? '병원 요청 전' : `존 ${(c.zoneActive || []).length} · 대기 ${n.pending} · <span style="color:var(--ok)">승인 ${n.approved}</span> · 불가 ${n.rejected}`}${confirmed ? ` · <b style="color:var(--k${k})">확정 ${confirmed.name}</b>` : ''}</div>
      ${sug ? `<div class="st" style="color:var(--sug)">거미줄 제안: ${hp(sug.hpid) ? hp(sug.hpid).name : sug.hpid} · 줄 길이 ${sug.len.toFixed(1)} (도로 ${sug.road.toFixed(1)}분)${confirmed ? (confirmed.hospitalId === sug.hpid ? ' · hub와 같음' : ' · hub와 다름') : ''}</div>` : ''}
      <div style="display:flex;gap:6px"><button data-go="${c.caseId}">보기</button></div>`;
    div.querySelector('[data-go]').onclick = () => { const p = casePos(c); if (p) { spinning = false; goCam({ longitude: p.lng, latitude: p.lat, zoom: 12.3, pitch: 60, bearing: -20 }); } };
    box.appendChild(div);
  }
}
const LIVE_KIND_CLASS = { p: '', s: 's', r: 'y', x: 'c', a: 'a', t: 'w', c: 'f', d: 'o' };
function renderLiveSide() {
  const rows = [];
  for (const c of myCases()) for (const e of c.events || []) rows.push({ t: e.t, kind: e.kind, text: `<b>#${c.num ?? '?'}</b> ${e.text}` });
  for (const e of HUB.log) rows.push(e);
  rows.sort((a, b) => (a.t < b.t ? -1 : a.t > b.t ? 1 : 0));
  const cases = myCases(), moving = mySims().filter(s => s.phase === 'transporting').length;
  $('sum').textContent = `실시간 · 사건 ${cases.length}건 · 이송 중 ${moving}대 · 병원 ${LIVE.length}곳${HUB.connected ? '' : ' · hub 연결 안 됨'}`;
  const L = $('log'); L.innerHTML = '';
  for (const r of rows.slice(-200)) {
    const v = document.createElement('div'); v.className = 'ev ' + (LIVE_KIND_CLASS[r.kind] ?? '');
    const hhmm = r.t ? new Date(r.t).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) : '';
    v.innerHTML = `<span class="tm">${hhmm}</span><span>${r.text}</span>`; L.appendChild(v);
  }
  if (L.lastChild) L.lastChild.scrollIntoView({ block: 'nearest' });
}
// ── 거미줄 모델 제안: 실제 사건을 그대로 환자로 넣어 서버 엔진에 묻는다(hub 결정과 비교용, hub엔 안 보낸다) ──
function scheduleSuggest() { clearTimeout(suggestTimer); suggestTimer = setTimeout(refreshSuggest, 800); }
async function condFor(c) {
  const key = c.caseId + '|' + (c.expectedDiagnosis || '');
  if (HUB.cond[key]) return HUB.cond[key];
  // 질환군 규칙은 서버의 voice_to_patient.py 하나 — 예상 병명 문장을 의심 진단으로 넣어 같은 규칙을 태운다
  try { const v = await api('api/voice', { summary: { ktas_level: caseK(c), suspected_diagnosis: [{ text: c.expectedDiagnosis || '' }], incidents: [] } }); HUB.cond[key] = v.cond; }
  catch (e) { HUB.cond[key] = 'general'; }
  return HUB.cond[key];
}
async function refreshSuggest() {
  if (MODE !== 'live' || !$('suggest').checked) return;
  const cases = myCases().filter(c => casePos(c));
  if (!cases.length) { HUB.suggest = {}; renderLivePanel(); return; }
  const seq = ++suggestSeq;
  const patients = [];
  // 수용할 수 없는 병원은 제안하지 않는다(2026-10-15): ① 병상은 서버 스냅샷이 아니라 hub가 지금 아는 값(이송 확정 차감 반영)으로
  // ② 이 사건에서 hub가 수용 불가로 본 병원(병원 불가·E-Gen 병상 0·제외·차단·승인 뒤 병상 0 확인)은 그 환자 후보에서 뺀다
  const liveBeds = {};
  for (const mh of (HUB.overview && HUB.overview.hospitals) || []) liveBeds[mh.hospitalId] = mh.bedCountUnknown ? null : mh.availableBedCount;
  const exclude = c => (c.hospitals || []).filter(ch => ch.status !== 'confirmed' && (ch.status === 'rejected' || ch.unavailableReason || ch.excluded
    || (ch.demoteReasons || []).some(r => r === 'beds_full' || r === 'severe_blocked' || r === 'declared_no')
    || (ch.status === 'approved' && !transportable(ch)))).map(ch => ch.hospitalId);
  for (const [i, c] of cases.entries()) { const p = casePos(c), k = caseK(c); patients.push({ id: i + 1, site: `#${c.num ?? '?'}`, k, t0: 0, lat: p.lat, lng: p.lng, z: KTAS_Z[k], cond: await condFor(c), exclude: exclude(c), group: c.diseaseGroup || null }); }
  // hub: true — 서버가 hub /hospital-features(E-Gen 실시간·심평원·질환군 신고·병상 정보 신뢰도)로 병원 값을 덮어 계산한다
  let j; try { j = await api('api/solve', { patients, params: readParams(), liveBeds, hub: true }); } catch (e) { return; }
  if (seq !== suggestSeq) return;
  const out = {};
  cases.forEach((c, i) => { const idx = j.cur[String(i + 1)]; const seg = idx != null ? j.hist[String(i + 1)][idx] : null; if (seg) out[c.caseId] = { hpid: seg.hpid, len: seg.len, road: seg.road }; });
  HUB.suggest = out; renderLivePanel();
}
