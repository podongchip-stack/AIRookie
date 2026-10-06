// 정보의 유효기간 — 병상 정보 신뢰도(infosurv) 기술 설명 필름
// 순수 Canvas2D, 결정적 렌더: draw(t)는 t만 보고 프레임을 그린다(난수는 전부 시드 고정).
// 논리 좌표 1920x1080, ?scale=2 이면 3840x2160 픽셀로 그린다.
(() => {
'use strict';
const W = 1920, H = 1080;
const Q = new URLSearchParams(location.search);
const S = Number(Q.get('scale') || 1);
if (Q.has('render')) document.body.classList.add('render');
const cv = document.getElementById('c');
cv.width = W * S; cv.height = H * S;
const ctx = cv.getContext('2d');

const SANS = '"Apple SD Gothic Neo","Noto Sans KR",sans-serif';
const MONO = 'Menlo,"SF Mono",monospace';

// ── 수학 도구 ─────────────────────────────────────────────
const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));
const lerp = (a, b, k) => a + (b - a) * k;
const prog = (t, a, b) => clamp((t - a) / (b - a));
const eOutExpo = k => k >= 1 ? 1 : 1 - Math.pow(2, -10 * k);
const eInOut = k => k < .5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
const eOutBack = k => { const c = 1.70158, c3 = c + 1; return 1 + c3 * Math.pow(k - 1, 3) + c * Math.pow(k - 1, 2); };
const eIn = k => k * k * k;
function rng(seed) { let a = seed >>> 0; return () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
function erf(x) { const s = Math.sign(x); x = Math.abs(x); const t = 1 / (1 + .3275911 * x); const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - .284496736) * t + .254829592) * t * Math.exp(-x * x); return s * y; }
// 로그정규 AFT 생존함수 S(t) = 1 - Φ((ln t - μ)/σ)
const surv = (t, mu, sg) => t <= 0 ? 1 : .5 * (1 - erf((Math.log(t) - mu) / (sg * Math.SQRT2)));
// 진입·퇴장 엔벨로프
const env = (t, d, fi = .6, fo = .6) => Math.min(prog(t, 0, fi), 1 - prog(t, d - fo, d));
const fmt = n => n.toLocaleString('en-US');

// ── 그리기 도구 ───────────────────────────────────────────
function font(size, weight = 700, fam = SANS) { ctx.font = `${weight} ${size}px ${fam}`; }
function txt(s, x, y, size, o = {}) {
  ctx.save();
  font(size, o.w ?? 700, o.f ?? SANS);
  ctx.textAlign = o.a ?? 'center'; ctx.textBaseline = o.b ?? 'middle';
  ctx.letterSpacing = (o.ls ?? 0) + 'px';
  ctx.globalAlpha *= o.al ?? 1;
  ctx.fillStyle = o.c ?? '#fff';
  ctx.fillText(s, x, y);
  ctx.restore();
}
function tw(s, size, w = 700, fam = SANS, ls = 0) { ctx.save(); font(size, w, fam); ctx.letterSpacing = ls + 'px'; const m = ctx.measureText(s).width; ctx.restore(); return m; }

// 글자 단위 키네틱 등장/퇴장. t = 등장 시작 기준 로컬 시간, out = 퇴장 시작 로컬 시간
function ktext(s, x, y, size, t, o = {}) {
  if (t < 0) return;
  const w = o.w ?? 700, fam = o.f ?? SANS, ls = o.ls ?? 0;
  const st = o.st ?? .028, du = o.du ?? .7, out = o.out ?? Infinity, odu = o.odu ?? .5;
  const chars = [...s]; const total = tw(s, size, w, fam, ls);
  let x0 = (o.a ?? 'center') === 'center' ? x - total / 2 : (o.a === 'right' ? x - total : x);
  const base = ctx.globalAlpha;
  ctx.save(); font(size, w, fam); ctx.letterSpacing = ls + 'px'; ctx.textBaseline = 'middle'; ctx.textAlign = 'left';
  let acc = '';
  chars.forEach((ch, i) => {
    const cx = x0 + ctx.measureText(acc).width; acc += ch;
    const k = eOutExpo(prog(t - i * st, 0, du));
    const ko = eIn(prog(t - out - i * st * .5, 0, odu));
    const al = k * (1 - ko) * (o.al ?? 1);
    if (al <= .001) return;
    const dy = (1 - k) * size * (o.rise ?? .55) - ko * size * .4;
    ctx.globalAlpha = base * al;
    ctx.fillStyle = o.c ?? '#fff';
    if (o.blur && k < 1) ctx.filter = `blur(${(1 - k) * size * .08 * S}px)`; else ctx.filter = 'none';
    ctx.fillText(ch, cx, y + dy);
  });
  ctx.restore();
}
// 타자기
function typer(s, x, y, size, t, cps, o = {}) {
  const n = Math.floor(clamp(t * cps, 0, s.length));
  const shown = s.slice(0, n);
  txt(shown, x, y, size, { ...o, a: 'left' });
  if (o.cursor !== false && t >= 0) {
    const blink = (n < s.length) || (Math.floor(t * 2.2) % 2 === 0);
    if (blink) { const cw = tw(shown, size, o.w ?? 700, o.f ?? SANS, o.ls ?? 0); ctx.save(); ctx.globalAlpha *= o.al ?? 1; ctx.fillStyle = '#fff'; ctx.fillRect(x + cw + 6, y - size * .5, size * .06 + 2, size * 1.0); ctx.restore(); }
  }
}
function line(x1, y1, x2, y2, w = 2, al = 1, dash) { ctx.save(); ctx.globalAlpha *= al; ctx.strokeStyle = '#fff'; ctx.lineWidth = w; if (dash) ctx.setLineDash(dash); ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke(); ctx.restore(); }
function circle(x, y, r, fill = true, al = 1, w = 2) { ctx.save(); ctx.globalAlpha *= al; ctx.beginPath(); ctx.arc(x, y, Math.max(0, r), 0, Math.PI * 2); if (fill) { ctx.fillStyle = '#fff'; ctx.fill(); } else { ctx.strokeStyle = '#fff'; ctx.lineWidth = w; ctx.stroke(); } ctx.restore(); }
function rrect(x, y, w, h, r) { ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); }
function cross(x, y, r, w = 3, al = 1) { line(x - r, y - r, x + r, y + r, w, al); line(x - r, y + r, x + r, y - r, w, al); }
function glow(x, y, r, al) { ctx.save(); const g = ctx.createRadialGradient(x, y, 0, x, y, r); g.addColorStop(0, `rgba(255,255,255,${al})`); g.addColorStop(1, 'rgba(255,255,255,0)'); ctx.fillStyle = g; ctx.fillRect(x - r, y - r, r * 2, r * 2); ctx.restore(); }
// 경로를 진행률 k만큼만 그린다
function partialPath(pts, k, w = 3, al = 1) {
  if (k <= 0 || pts.length < 2) return null;
  let L = 0; const seg = []; for (let i = 1; i < pts.length; i++) { const d = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]); seg.push(d); L += d; }
  let rem = L * clamp(k); ctx.save(); ctx.globalAlpha *= al; ctx.strokeStyle = '#fff'; ctx.lineWidth = w; ctx.lineJoin = 'round'; ctx.lineCap = 'round'; ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]);
  let head = pts[0];
  for (let i = 1; i < pts.length; i++) { if (rem >= seg[i - 1]) { ctx.lineTo(pts[i][0], pts[i][1]); rem -= seg[i - 1]; head = pts[i]; } else { const f = rem / seg[i - 1]; head = [lerp(pts[i - 1][0], pts[i][0], f), lerp(pts[i - 1][1], pts[i][1], f)]; ctx.lineTo(head[0], head[1]); break; } }
  ctx.stroke(); ctx.restore(); return head;
}

// 미리 만든 그레인 타일
const grain = document.createElement('canvas'); grain.width = grain.height = 256;
{ const g = grain.getContext('2d'), im = g.createImageData(256, 256), r = rng(7); for (let i = 0; i < im.data.length; i += 4) { const v = r() * 255; im.data[i] = im.data[i + 1] = im.data[i + 2] = v; im.data[i + 3] = 255; } g.putImageData(im, 0, 0); }

// "12" 글자 모양에서 입자 위치를 샘플링(장면 4)
const P12 = (() => {
  const c = document.createElement('canvas'); c.width = 520; c.height = 300; const g = c.getContext('2d');
  g.fillStyle = '#fff'; g.font = `800 260px ${SANS}`; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText('12', 260, 160);
  const d = g.getImageData(0, 0, 520, 300).data, pts = [];
  for (let y = 0; y < 300; y += 7) for (let x = 0; x < 520; x += 7) if (d[(y * 520 + x) * 4 + 3] > 140) pts.push([x - 260, y - 160]);
  return pts;
})();

// ── 장면 ──────────────────────────────────────────────────
const SCENES = [];
const scene = (name, dur, fn) => SCENES.push({ name, dur, fn });

// 01 훅 — 2,457일 묵은 "가용 병상 30"
scene('', 11, (t, d) => {
  const a = env(t, d, .3, .8); ctx.globalAlpha = a;
  const zoom = lerp(1, .78, eInOut(prog(t, 3.2, 5.0)));
  ctx.save(); ctx.translate(W / 2, H / 2); ctx.scale(zoom, zoom); ctx.translate(-W / 2, -H / 2);
  // 라벨 + LIVE
  const live = t < 6.2;
  ktext('응급실 가용 병상', W / 2 - 40, 250, 40, t - .3, { w: 500, ls: 6 });
  const pulse = live ? .5 + .5 * Math.sin(t * 7) : 0;
  if (t > .6) { circle(W / 2 + 175, 250, 9, true, (live ? .4 + .6 * pulse : .25) * prog(t, .6, 1)); txt('LIVE', W / 2 + 230, 251, 22, { f: MONO, w: 700, ls: 3, al: (live ? 1 : .3) * prog(t, .6, 1) }); if (!live) line(W / 2 + 195, 251, W / 2 + 268, 251, 2, .8 * prog(t, 6.2, 6.5)); }
  // 숫자 30 (글리치 → 파편)
  const n = Math.round(30 * eOutExpo(prog(t, .5, 2.2)));
  const g = prog(t, 5.8, 7.2), sh = prog(t, 7.2, 8.4);
  if (t > .5 && sh < 1) {
    const strips = 18, top = 340, hgt = 440, r = rng(Math.floor(t * 24) + 3), r2 = rng(99);
    for (let i = 0; i < strips; i++) {
      const y0 = top + i * hgt / strips;
      const jit = g > 0 ? (r() - .5) * 120 * g * g : 0;
      const dir = r2() - .5, fall = eIn(sh) * (300 + r2() * 700);
      ctx.save(); ctx.beginPath(); ctx.rect(0, y0, W, hgt / strips + .6); ctx.clip();
      ctx.translate(jit + dir * 900 * eIn(sh), fall * (dir > 0 ? 1 : -1) * .6);
      ctx.globalAlpha = a * (1 - sh) * prog(t, .5, .9);
      txt(String(n), W / 2, 560, 400, { w: 800 });
      ctx.restore();
    }
    if (g > 0 && sh === 0) { const rr = rng(Math.floor(t * 30)); for (let i = 0; i < 5; i++) line(W / 2 - 400 + rr() * 800, 340 + rr() * 440, W / 2 - 300 + rr() * 900, 340 + rr() * 440, 1 + rr() * 2, g * .5); }
  }
  // 마지막 갱신 n일 전
  if (t > 3.6) {
    const days = Math.round(2457 * eOutExpo(prog(t, 3.8, 5.6)));
    const al = prog(t, 3.6, 4.0) * (1 - sh * .2);
    txt('마지막 갱신', W / 2, 840, 34, { w: 400, al: al * .7, ls: 4 });
    txt(fmt(days) + '일 전', W / 2, 920, 84, { w: 800, al });
  }
  ctx.restore();
  // 캡션
  ctx.globalAlpha = a;
  ktext('전국 가용 병상 1위의 값.', W / 2, 470, 64, t - 8.2, { w: 700, blur: true });
  ktext('약 6.7년 전에 멈춘 숫자였습니다.', W / 2, 570, 64, t - 8.9, { w: 300, blur: true });
  ctx.globalAlpha = 1;
});

// 02 문제 — 443개의 갱신 리듬 vs 고정 TTL
const DOTS = (() => { const r = rng(42), out = []; const cols = 27, rows = 17, sp = 50, ox = W / 2 - (cols - 1) * sp / 2, oy = 610 - (rows - 1) * sp / 2;
  for (let j = 0; j < rows; j++) for (let i = 0; i < cols; i++) { if (out.length >= 443) break; const P = Math.exp(lerp(Math.log(.45), Math.log(5), r())); out.push({ x: ox + i * sp + (r() - .5) * 10, y: oy + j * sp + (r() - .5) * 10, P, ph: r() * P, d: Math.hypot(i - cols / 2, j - rows / 2) }); }
  return out; })();
scene('문제', 16, (t, d) => {
  const a = env(t, d, .4, .8); ctx.globalAlpha = a;
  const ttl = prog(t, 7, 7.8); const ttlP = 2.2; // 화면상 TTL 주기
  const dim = prog(t, 11, 11.8);
  DOTS.forEach(o => {
    const app = eOutBack(prog(t - o.d * .05, 0, .6)); if (app <= 0) return;
    const ph = ((t + o.ph) % o.P) / o.P; const fl = Math.exp(-ph * o.P * 5);
    ctx.globalAlpha = a * (1 - dim * .75);
    circle(o.x, o.y, (3 + 5 * fl) * app, true, .35 + .65 * fl);
    if (fl > .05) circle(o.x, o.y, 4 + ph * o.P * 26, false, fl * .5, 1.2);
    if (ttl > 0) {
      const tp = ((t - 7) % ttlP) / ttlP;
      ctx.save(); ctx.globalAlpha = a * ttl * .55 * (1 - dim * .75); ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.arc(o.x, o.y, 15, -Math.PI / 2, -Math.PI / 2 + tp * Math.PI * 2); ctx.stroke(); ctx.restore();
      // 타이머 주기 안에 값이 바뀐(=TTL이 놓친) 병원은 ✕
      if (o.P < ttlP && t > 8.6) { const k = prog(t - 8.6 - o.d * .04, 0, .3); ctx.globalAlpha = a * (1 - dim * .75); cross(o.x, o.y, 9 * k, 2.4, k); }
    }
  });
  ctx.globalAlpha = a;
  const out1 = 6.6;
  ktext('443개 병원, 정보를 고치는 속도가 다 다르다', W / 2, 95, 56, t - 1.0, { w: 800, out: out1 - 1.0 });
  ktext('병상 숫자는 보통 20분이면 바뀌고, 병원마다 최대 8배 차이', W / 2, 160, 28, t - 2.6, { w: 400, out: out1 - 2.6, al: .75 });
  ktext('모든 병원 숫자를 똑같이 "10분간 믿자"고 정하면', W / 2, 95, 56, t - 7.2, { w: 800, out: 10.6 - 7.2 });
  ktext('자주 바뀌는 병원(✕)은 10분이 지나기도 전에 숫자가 이미 바뀌어 있다', W / 2, 160, 28, t - 8.8, { w: 400, out: 10.6 - 8.8, al: .75 });
  if (t > 8.6 && t < 11.2) { const miss = DOTS.filter(o => o.P < ttlP).length; txt(`✕ 10분 안에 숫자가 바뀐 병원  ${Math.round(miss * prog(t, 8.6, 10))}곳`, 1700, 1020, 30, { f: SANS, w: 700, al: prog(t, 8.6, 9) * (1 - prog(t, 10.6, 11.2)), a: 'right' }); }
  ktext('똑같은 유효기간은 추측이다.', W / 2, 520, 92, t - 11.5, { w: 800, blur: true });
  ktext('병원이 고쳐 온 기록은 증거다.', W / 2, 650, 92, t - 12.6, { w: 300, blur: true });
  ctx.globalAlpha = 1;
});

// 03 질문
scene('질문', 9, (t, d) => {
  const a = env(t, d, .3, .7); ctx.globalAlpha = a;
  const x = 260;
  typer('마지막으로 숫자를 고친 지', x, 330, 64, t - .3, 14, { w: 300, cursor: t < 1.9 });
  if (t > 1.6) {
    const m = Math.floor(lerp(0, 47, eOutExpo(prog(t, 1.7, 4.5))));
    const k = eOutBack(prog(t, 1.6, 2.2));
    ctx.save(); ctx.translate(x, 520); ctx.scale(k, k);
    txt('', 0, 0, 220, { w: 300, a: 'left', f: '"Times New Roman",serif' });
    txt('', 160, 0, 120, { w: 200, a: 'left', al: .5 });
    txt(String(m).padStart(2, '0'), 0, 0, 220, { w: 800, a: 'left', f: MONO });
    txt('분', 300, 30, 80, { w: 400, a: 'left' });
    ctx.restore();
  }
  typer('이 숫자는 아직 유효한가?', x, 740, 92, t - 3.6, 12, { w: 800, cursor: true });
  // 오른쪽 장식: 시계 링
  if (t > 1) { const k = prog(t, 1, 2); const cx = 1500, cy = 540; circle(cx, cy, 230, false, .15 * k, 1.5); for (let i = 0; i < 60; i++) { const an = i / 60 * Math.PI * 2, L = i % 5 ? 10 : 24; ctx.globalAlpha = a * k * (i % 5 ? .3 : .7); line(cx + Math.cos(an) * (230 - L), cy + Math.sin(an) * (230 - L), cx + Math.cos(an) * 230, cy + Math.sin(an) * 230, 2); }
    ctx.globalAlpha = a; const sw = -Math.PI / 2 + (t - 1) * 1.6; ctx.save(); ctx.globalAlpha = a * k; ctx.strokeStyle = '#fff'; ctx.lineWidth = 6; ctx.lineCap = 'round'; ctx.beginPath(); ctx.arc(cx, cy, 190, -Math.PI / 2, sw); ctx.stroke(); ctx.restore(); line(cx, cy, cx + Math.cos(sw) * 170, cy + Math.sin(sw) * 170, 3, k); circle(cx, cy, 7, true, k); glow(cx + Math.cos(sw) * 190, cy + Math.sin(sw) * 190, 40, .6 * k); }
  ctx.globalAlpha = 1;
});

// 04 아이디어 — 값은 버리고, 고친 흔적을 읽는다
const TICKS = (() => { const r = rng(5), ts = []; let x = 0; while (ts.length < 26) { x += r() < .35 ? 8 + r() * 14 : 30 + r() * 70; ts.push(x); } const m = ts[ts.length - 1]; return ts.map(v => 380 + v / m * 1160); })();
const FEATS = [
  ['수정 횟수', '자주 고쳐지는 값인가'], ['지난 값의 수명', '지난번엔 얼마나 버텼나'], ['평소 갱신 주기', '보통 몇 분마다 고치나'], ['지금 값의 나이', '고친 지 얼마나 지났나'],
  ['최근 수정 간격', '요즘 얼마나 바쁘게 고치나'], ['변화 폭', '한 번에 얼마나 크게 바꿨나'], ['시각 · 요일', '아침 병상 정리 시간인가'],
];
scene('아이디어', 17, (t, d) => {
  const a = env(t, d, .4, .8); ctx.globalAlpha = a;
  const cx = W / 2, cy = 470;
  // 카드
  const cardOut = prog(t, 2.0, 2.6);
  if (cardOut < 1) {
    const k = eOutBack(prog(t, .2, .9));
    ctx.save(); ctx.globalAlpha = a * (1 - cardOut); ctx.translate(cx, cy); ctx.scale(k, k);
    ctx.strokeStyle = 'rgba(255,255,255,.35)'; ctx.lineWidth = 2; rrect(-330, -230, 660, 460, 28); ctx.stroke();
    txt('A 병원 · 응급실 가용 병상', 0, -170, 28, { w: 500, al: .7, ls: 2 });
    ctx.restore();
  }
  // "12" → 입자 → 수정 이력 눈금
  const ty = 760;
  const disp = prog(t, 2.0, 4.6);
  const r = rng(11);
  P12.forEach((p, i) => {
    const rr = r(), rr2 = r();
    const tick = TICKS[i % TICKS.length];
    const k = eInOut(clamp((disp - rr * .35) / .65));
    const sx = cx + p[0], sy = cy + 30 + p[1];
    const mx = lerp(sx, tick, k) + Math.sin(k * Math.PI) * (rr2 - .5) * 400;
    const my = lerp(sy, ty - 30 + rr2 * 60, k) - Math.sin(k * Math.PI) * 180 * rr;
    const al = t < 2 ? prog(t, .3, .9) : 1 - prog(disp, .8, 1);
    if (al <= 0) return;
    ctx.globalAlpha = a * al; ctx.fillStyle = '#fff'; const s = lerp(6.2, 2.2, k); ctx.fillRect(mx - s / 2, my - s / 2, s, s);
  });
  // 타임라인
  const tl = prog(t, 3.6, 4.8);
  if (tl > 0) {
    ctx.globalAlpha = a;
    line(360, ty, lerp(360, 1560, eInOut(tl)), ty, 2, .5);
    TICKS.forEach((x, i) => { const k = eOutBack(prog(t - 3.9 - i * .03, 0, .4)); if (k > 0) line(x, ty - 34 * k, x, ty + 34 * k, 3, .95); });
    txt('수정 이력 — 값은 버리고, 고친 시각만 남긴다', 360, ty + 80, 26, { a: 'left', w: 400, al: .6 * prog(t, 4.4, 5) });
    txt('시간 →', 1560, ty + 80, 22, { a: 'right', f: MONO, w: 400, al: .5 * prog(t, 4.4, 5) });
  }
  const outH = 8.2;
  ktext('내용이 아니라,', cx, 330, 76, t - 4.8, { w: 300, out: outH - 4.8, blur: true });
  ktext('고친 흔적을 읽는다.', cx, 450, 100, t - 5.5, { w: 800, out: outH - 5.5, blur: true });
  // 행동 특징 7개
  if (t > 8.6) {
    const cols = [4, 3]; let idx = 0;
    cols.forEach((n, row) => { for (let j = 0; j < n; j++, idx++) {
      const f = FEATS[idx]; const k = eOutExpo(prog(t - 8.8 - idx * .18, 0, .8));
      const bx = cx + (j - (n - 1) / 2) * 400, by = 270 + row * 200;
      const src = TICKS[(idx * 4 + 2) % TICKS.length];
      const x = lerp(src, bx, k), y = lerp(ty, by, k);
      ctx.globalAlpha = a * prog(t - 8.8 - idx * .18, 0, .3);
      line(src, ty - 34, x, y + 60, 1, .25 * k, [4, 6]);
      ctx.save(); ctx.globalAlpha = a * k; ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.6; rrect(x - 180, y - 60, 360, 120, 16); ctx.stroke(); ctx.restore();
      ctx.globalAlpha = a * k;
      txt(f[0], x, y - 18, 34, { w: 800 });
      txt(f[1], x, y + 28, 24, { w: 400, al: .7 });
    } });
    ktext('AI가 보는 단서 7가지', cx, 120, 50, t - 8.6, { w: 800 });
  }
  ctx.globalAlpha = a;
  ktext('필요한 건 "언제 고쳤나" 기록뿐  ·  환자 정보는 쓰지 않는다', cx, 1000, 26, t - 12.6, { w: 400, al: .7 });
  ctx.globalAlpha = 1;
});

// 05 정식화 — 버전, 무효(θ), 대체(중도절단) → 생존곡선
scene('판정 기준', 18, (t, d) => {
  const a = env(t, d, .4, .8); ctx.globalAlpha = a;
  const X0 = 260, X1 = 1660, Y0 = 820, vy = v => Y0 - v * 42;
  const part1 = 1 - prog(t, 9.4, 10.2);
  if (part1 > 0) {
    ctx.globalAlpha = a * part1;
    // 축
    line(X0, Y0, lerp(X0, X1, eInOut(prog(t, .3, 1.2))), Y0, 2, .5);
    line(X0, Y0, X0, lerp(Y0, 240, eInOut(prog(t, .3, 1.2))), 2, .5);
    txt('가용 병상', X0, 210, 24, { w: 400, al: .6 });
    txt('시간', X1, Y0 + 40, 24, { w: 400, al: .6, a: 'right' });
    // 버전들
    const V = [[260, 12], [620, 11], [980, 8], [1400, 8.0]];
    const steps = [[260, vy(12)], [620, vy(12)], [620, vy(11)], [980, vy(11)], [980, vy(8)], [1400, vy(8)]];
    const head = partialPath(steps, prog(t, 1.2, 6.2), 4);
    if (head) glow(head[0], head[1], 40, .8);
    const vt = [[1.2, '', 260, 12], [3.0, '', 620, 11], [4.7, '', 980, 8]];
    vt.forEach(([s, n, x, v]) => { if (t > s) { txt(n, x + 20, vy(v) - 34, 26, { a: 'left', f: MONO, al: prog(t, s, s + .3) }); txt(String(v), x + 20, vy(v) + 40, 22, { a: 'left', f: MONO, w: 400, al: .55 * prog(t, s, s + .3) }); } });
    // θ 밴드 (v1 기준 ±3)
    const bk = prog(t, 1.8, 2.6) * (1 - prog(t, 4.4, 4.9));
    if (bk > 0) { ctx.save(); ctx.globalAlpha = a * part1 * bk * .12; ctx.fillStyle = '#fff'; ctx.fillRect(260, vy(15), 720, vy(9) - vy(15)); ctx.restore(); ctx.globalAlpha = a * part1 * bk; line(260, vy(15), 980, vy(15), 1.2, .6, [6, 6]); line(260, vy(9), 980, vy(9), 1.2, .6, [6, 6]); txt('허용 범위 ±3석', 1000, vy(15), 24, { a: 'left', f: MONO, w: 700 }); }
    // v1→v2 : 대체(중도절단)
    ctx.globalAlpha = a * part1;
    if (t > 3.0) { const k = eOutBack(prog(t, 3.0, 3.5)); circle(620, vy(12), 14 * k, false, 1, 3);
      txt('1석 차이  →  아직 맞다', 650, vy(12) - 90, 30, { a: 'left', w: 800, al: prog(t, 3.2, 3.6) });
      txt('허용 범위 안의 작은 변화', 650, vy(12) - 52, 24, { a: 'left', w: 400, al: .7 * prog(t, 3.4, 3.8) }); }
    // v2→v3 : 무효
    if (t > 4.7) { const k = eOutBack(prog(t, 4.7, 5.2)); ctx.globalAlpha = a * part1; cross(980, vy(11), 16 * k, 4); glow(980, vy(11), 90 * k, .35 * (1 - prog(t, 5.2, 6.5)));
      txt('3석 차이  →  틀렸다', 1010, vy(8) + 110, 30, { a: 'left', w: 800, al: prog(t, 4.9, 5.3) });
      txt('실제와 크게 어긋났다고 드러난 순간', 1010, vy(8) + 148, 24, { a: 'left', w: 400, al: .7 * prog(t, 5.1, 5.5) }); }
    ktext('숫자가 바뀔 때마다 기록한다.', W / 2, 110, 40, t - .6, { w: 700, out: 6.6 - .6 });
    ktext('조금 바뀐 건 괜찮다. 크게 바뀌어야 "틀렸다".', W / 2, 110, 40, t - 7.0, { w: 700 });
  }
  // 생존곡선
  if (t > 9.6) {
    ctx.globalAlpha = a;
    const k0 = prog(t, 9.8, 10.8);
    const GX0 = 360, GX1 = 1600, GY0 = 860, GY1 = 260, tm = 60;
    const gx = m => GX0 + m / tm * (GX1 - GX0), gy = p => GY0 - p * (GY0 - GY1);
    line(GX0, GY0, lerp(GX0, GX1, eInOut(k0)), GY0, 2, .5); line(GX0, GY0, GX0, lerp(GY0, GY1 - 20, eInOut(k0)), 2, .5);
    [0, .25, .5, .75, 1].forEach(p => { txt(Math.round(p * 100) + '%', GX0 - 20, gy(p), 22, { a: 'right', f: MONO, w: 400, al: .5 * k0 }); line(GX0, gy(p), GX1, gy(p), 1, .08 * k0); });
    [0, 10, 20, 30, 40, 50, 60].forEach(m => txt(m + '분', gx(m), GY0 + 34, 22, { f: MONO, w: 400, al: .5 * k0 }));
    txt('아직 맞을 확률', GX0, GY1 - 50, 26, { a: 'left', w: 700, al: k0 });
    txt('마지막 수정 후 지난 시간', GX1, GY0 + 74, 24, { a: 'right', w: 400, al: .6 * k0 });
    const mu = Math.log(22), sg = .85; const pts = [];
    for (let m = 0; m <= tm; m += .25) pts.push([gx(m), gy(surv(m, mu, sg))]);
    const ck = eInOut(prog(t, 10.6, 13.4)); const head = partialPath(pts, ck, 5);
    if (head) { glow(head[0], head[1], 50, .9); circle(head[0], head[1], 7); }
    if (t > 13.6) { const k = prog(t, 13.6, 14.2), m = 20, p = surv(m, mu, sg);
      line(gx(m), GY0, gx(m), gy(p), 1.5, .7 * k, [6, 6]); line(GX0, gy(p), gx(m), gy(p), 1.5, .7 * k, [6, 6]); circle(gx(m), gy(p), 10 * eOutBack(k));
      txt(`20분 뒤 ${Math.round(p * 100)}%`, gx(m) + 30, gy(p) - 40, 40, { a: 'left', w: 800, al: k }); }
    ktext('AI는 "맞다/틀리다" 대신 "지금 맞을 확률"을 알려준다', W / 2, 120, 44, t - 10.4, { w: 700 });
  }
  ctx.globalAlpha = 1;
});

// 06 모델 — XGBoost AFT, 같은 20분 다른 확률
function tree(x, y, s, depth, r, al) { if (depth === 0) { circle(x, y, 3 * s, true, al); return; } const dx = 26 * s * depth * .55, dy = 30 * s; [-1, 1].forEach(sd => { if (depth > 1 || r() > .2) { line(x, y, x + sd * dx, y + dy, 1.4, al * .7); tree(x + sd * dx, y + dy, s, depth - 1, r, al); } }); circle(x, y, 4 * s, false, al, 1.4); }
scene('AI', 16, (t, d) => {
  const a = env(t, d, .4, .8); ctx.globalAlpha = a;
  const cx = W / 2;
  const merge = eInOut(prog(t, 3.4, 4.6));
  if (merge < 1) {
    for (let i = 0; i < 18; i++) {
      const col = i % 6, row = Math.floor(i / 6);
      const bx = 330 + col * 252, by = 330 + row * 190;
      const k = eOutBack(prog(t - .3 - i * .07, 0, .5));
      if (k <= 0) continue;
      const x = lerp(bx, cx, merge), y = lerp(by, 540, merge), s = lerp(1, .2, merge) * k;
      ctx.globalAlpha = a * (1 - merge * .9) * prog(t - .3 - i * .07, 0, .2);
      tree(x, y - 40, s, 3, rng(i + 1), 1);
    }
    ctx.globalAlpha = a;
    ktext('수백 개의 판단 규칙이 단서를 나눠 본다', cx, 130, 44, t - .4, { w: 700, out: 3.3 - .4 });
  }
  if (t > 4.2 && t < 8.4) {
    const k = eOutBack(prog(t, 4.2, 4.9)), o = 1 - prog(t, 7.8, 8.4);
    ctx.globalAlpha = a * o; glow(cx, 540, 260 * k, .25);
    txt('단서 7가지  →  이 숫자가 버틸 시간', cx, 500, 70 * k, { w: 800 });
    ktext('전국 443개 병원, 숫자 21만 개가 얼마나 버텼는지로 학습', cx, 620, 30, t - 4.8, { w: 400, al: .75 });
    ktext('일반 컴퓨터로 몇 분이면 학습  ·  데이터는 병원 밖으로 나가지 않는다', cx, 680, 26, t - 5.6, { w: 400, al: .55, f: MONO });
  }
  if (t > 8.2) {
    ctx.globalAlpha = a;
    const GX0 = 300, GX1 = 1380, GY0 = 880, GY1 = 280, tm = 60;
    const gx = m => GX0 + m / tm * (GX1 - GX0), gy = p => GY0 - p * (GY0 - GY1);
    const k0 = prog(t, 8.2, 8.9);
    line(GX0, GY0, GX1, GY0, 2, .5 * k0); line(GX0, GY0, GX0, GY1 - 20, 2, .5 * k0);
    [0, 20, 40, 60].forEach(m => txt(m + '분', gx(m), GY0 + 34, 22, { f: MONO, w: 400, al: .5 * k0 }));
    const H3 = [['병원 A', '평소 4분마다 꼼꼼히 갱신', Math.log(77), 1.0], ['병원 B', '평소 11분마다 갱신', Math.log(29), 1.0], ['병원 C', '3분 새 4번 수정 · 들쭉날쭉', Math.log(9.6), 1.0]];
    const sweep = 20 * eInOut(prog(t, 10.6, 12.2));
    H3.forEach(([n, why, mu, sg], i) => {
      const pts = []; for (let m = 0; m <= tm; m += .25) pts.push([gx(m), gy(surv(m, mu, sg))]);
      const head = partialPath(pts, eInOut(prog(t - 8.6 - i * .35, 0, 1.6)), i === 2 ? 3 : 4, [1, .7, .45][i] + .0);
      if (t > 10.6) { const p = surv(sweep, mu, sg); circle(gx(sweep), gy(p), 9); }
      if (t > 12.2) { const p = surv(20, mu, sg), k = prog(t - 12.2 - i * .25, 0, .4);
        const ly = [330, 520, 760][i];
        line(gx(20) + 12, gy(p), 1480, ly, 1, .35 * k, [4, 5]);
        txt(Math.round(p * 100) + '%', 1500, ly, 72, { a: 'left', w: 800, al: k, f: MONO });
        txt(n, 1700, ly - 18, 28, { a: 'left', w: 700, al: k });
        txt(why, 1700, ly + 20, 20, { a: 'left', w: 400, al: .6 * k }); }
    });
    if (t > 10.6) { ctx.globalAlpha = a; line(gx(sweep), GY0, gx(sweep), GY1 - 20, 2, .8); txt(`${sweep.toFixed(0)}분 경과`, gx(sweep), GY1 - 44, 26, { f: MONO, w: 700 }); }
    ktext('같은 20분, 다른 확률.', GX0, 150, 72, t - 12.8, { w: 800, a: 'left', blur: true });
  }
  ctx.globalAlpha = 1;
});

// 07 검증
scene('검증', 21, (t, d) => {
  const a = env(t, d, .4, .8); ctx.globalAlpha = a;
  const cx = W / 2;
  // A. C-index
  const oa = 1 - prog(t, 7.2, 7.8);
  if (oa > 0) {
    ctx.globalAlpha = a * oa;
    ktext('먼저 틀릴 숫자를 알아맞히나', cx, 120, 56, t - .2, { w: 800 });
    ktext('둘 중 먼저 틀릴 쪽 맞히기  ·  50%는 동전 던지기 수준', cx, 185, 26, t - .7, { w: 400, al: .65 });
    const BY = 900, sc = v => (v - .5) / .5 * 560; // 0.5~1.0 → 0~560px
    line(260, BY, 1660, BY, 2, .5);
    txt('50%', 230, BY, 22, { a: 'right', f: MONO, w: 400, al: .5 });
    const G = [['2석 이상 어긋남', .646, .691], ['3석 이상', .701, .764], ['5석 이상', .740, .829]];
    G.forEach(([lab, b, m], i) => {
      const gx = 540 + i * 420, k1 = eOutExpo(prog(t - 1.2 - i * .3, 0, 1.4)), k2 = eOutExpo(prog(t - 1.8 - i * .3, 0, 1.6));
      const hb = sc(b) * k1, hm = sc(m) * k2;
      ctx.save(); ctx.globalAlpha = a * oa; ctx.strokeStyle = 'rgba(255,255,255,.5)'; ctx.lineWidth = 2; ctx.setLineDash([6, 5]); ctx.strokeRect(gx - 120, BY - hb, 100, hb); ctx.restore();
      ctx.save(); ctx.globalAlpha = a * oa; ctx.fillStyle = '#fff'; ctx.fillRect(gx + 10, BY - hm, 110, hm); ctx.restore();
      ctx.globalAlpha = a * oa;
      txt(((.5 + (b - .5) * k1) * 100).toFixed(1) + '%', gx - 70, BY - hb - 30, 24, { f: MONO, w: 400, al: .6 });
      txt(((.5 + (m - .5) * k2) * 100).toFixed(1) + '%', gx + 65, BY - hm - 34, 36, { f: MONO, w: 800 });
      txt(lab, gx, BY + 40, 26, { w: 700 });
    });
    ctx.globalAlpha = a * oa;
    const lk = prog(t, 3.6, 4.2);
    ctx.save(); ctx.globalAlpha = a * oa * lk; ctx.strokeStyle = 'rgba(255,255,255,.6)'; ctx.setLineDash([6, 5]); ctx.lineWidth = 2; ctx.strokeRect(1500, 300, 30, 20); ctx.restore();
    txt('평소 갱신 주기만 보는 방법', 1550, 310, 22, { a: 'left', w: 400, al: .7 * lk });
    ctx.save(); ctx.globalAlpha = a * oa * lk; ctx.fillStyle = '#fff'; ctx.fillRect(1500, 345, 30, 20); ctx.restore();
    txt('우리 AI (단서 7가지)', 1550, 355, 22, { a: 'left', w: 700, al: lk });
    ktext('크게 어긋날수록, 더 잘 맞힌다.', cx, 300, 44, t - 4.6, { w: 800, blur: true });
  }
  // B. 라이브 채점 보드
  if (t > 7.6) {
    const ob = 1 - prog(t, 14.6, 15.2); ctx.globalAlpha = a * ob;
    ktext('실제 48시간 채점  ·  전국 병원의 모든 기록으로', cx, 130, 34, t - 7.8, { w: 700 });
    ktext('도착했을 때 병상 수가 3석 이상 안 바뀌었으면 "맞음"', cx, 190, 24, t - 8.3, { w: 400, al: .6 });
    const L = 520, R = 1640, sx = v => L + (v - 60) / 40 * (R - L);
    [60, 70, 80, 90, 100].forEach(v => { line(sx(v), 300, sx(v), 820, 1, .12); txt(v + '%', sx(v), 850, 22, { f: MONO, w: 400, al: .45 }); });
    const rows = [['그냥 믿으면', 94.0, '전체 평균', .6], ['엔진이 "믿어도 된다"', 97.9, 'AI가 80% 이상 확신', 1], ['엔진이 "의심하라"', 69.0, 'AI가 50% 미만이라 경고', .85]];
    rows.forEach(([lab, v, sub, al], i) => {
      const y = 380 + i * 170, k = eOutExpo(prog(t - 8.8 - i * .45, 0, 2.2));
      const x = lerp(sx(60), sx(v), k);
      ctx.globalAlpha = a * ob * prog(t - 8.8 - i * .45, 0, .3);
      txt(lab, L - 30, y - 12, 30, { a: 'right', w: 700, al });
      txt(sub, L - 30, y + 26, 20, { a: 'right', w: 400, al: .55 });
      ctx.save(); ctx.globalAlpha = a * ob * al; ctx.fillStyle = '#fff'; if (i === 2) { ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.strokeRect(L, y - 22, x - L, 44); } else ctx.fillRect(L, y - 22, x - L, 44); ctx.restore();
      glow(x, y, 50, .5 * k * (1 - prog(t - 8.8 - i * .45, 2, 3)));
      txt((60 + (v - 60) * k).toFixed(1) + '%', x + 20, y, 44, { a: 'left', f: MONO, w: 800 });
    });
    ktext('경고한 값은 실제로 세 번 중 한 번 틀렸다.', cx, 960, 34, t - 12.2, { w: 700 });
  }
  // C. IBS
  if (t > 15.2) {
    ctx.globalAlpha = a;
    const k = prog(t, 15.2, 16.6), n = Math.round(34 * eOutExpo(k));
    ktext('확률 예측 오차', cx, 260, 40, t - 15.3, { w: 400, al: .7 });
    ctx.save(); ctx.translate(cx, 520); const sc = lerp(1.6, 1, eOutExpo(k)); ctx.scale(sc, sc); txt(n + '×', 0, 0, 300, { w: 800, al: prog(t, 15.2, 15.6) }); ctx.restore();
    glow(cx, 520, 500, .12 * k);
    ktext('"자주 고치는 병원일수록 빨리 낡는다"는 단순 계산보다 34배 정확', cx, 760, 30, t - 16.4, { w: 700 });
    ktext('AI가 "87%"라고 하면, 실제로도 87% 맞도록 맞춰 놓았다', cx, 820, 24, t - 17.0, { w: 400, al: .65 });
  }
  ctx.globalAlpha = 1;
});

// 08 적용 — 골든링크 안에서
scene('적용', 18, (t, d) => {
  const a = env(t, d, .4, 1.2); ctx.globalAlpha = a;
  const om = 1 - prog(t, 9.6, 10.4);
  if (om > 0) {
    ctx.globalAlpha = a * om;
    const AX = 330, AY = 560;
    const HS = [['병원 A', 1080, 300, '9분', '병상 7', '도착 시 유효 91%', true], ['병원 B', 1200, 500, '12분', '병상 5', '도착 시 유효 74%'], ['병원 C', 1110, 700, '8분', '병상 3', '도착 시 유효 31%', false, true], ['병원 D', 1230, 900, '15분', '병상 미상', '숫자 없음 · 후보 유지']];
    // 구급차
    const ka = eOutBack(prog(t, .2, .8)); ctx.save(); ctx.translate(AX, AY); ctx.scale(ka, ka); ctx.strokeStyle = '#fff'; ctx.lineWidth = 3; ctx.strokeRect(-46, -46, 92, 92); line(-18, 0, 18, 0, 6); line(0, -18, 0, 18, 6); ctx.restore();
    txt('구급차', AX, AY + 90, 26, { w: 700, al: prog(t, .5, .9) });
    HS.forEach(([n, x, y, eta, beds, rel, best, warn], i) => {
      const s = .8 + i * .35;
      const lk = eInOut(prog(t - s, 0, .9));
      const head = partialPath([[AX + 50, AY], [lerp(AX + 50, x - 40, .5), lerp(AY, y, .2)], [x - 28, y]], lk, 2, .5);
      if (head && lk < 1) glow(head[0], head[1], 30, .8);
      const kh = eOutBack(prog(t - s - .7, 0, .5)); if (kh <= 0) return;
      circle(x, y, 26 * kh, false, 1, 3); circle(x, y, 8 * kh);
                  // 칩
      const kc = eOutExpo(prog(t - 3.4 - i * .3, 0, .7));
      if (kc > 0) {
        const cx0 = x + 50, w = 380;
        ctx.save(); ctx.globalAlpha = a * om * kc; ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.6; rrect(cx0, y - 40, w * kc, 80, 14); ctx.stroke(); ctx.restore();
        ctx.save(); ctx.beginPath(); ctx.rect(cx0, y - 40, w * kc, 80); ctx.clip();
        txt(`${n}  ·  이동 ${eta}  ·  ${beds}`, cx0 + 22, y - 14, 22, { a: 'left', w: 400, al: .65 });
        txt(rel, cx0 + 22, y + 16, 28, { a: 'left', w: 800, f: SANS });
        ctx.restore();
      }
    });
    ctx.globalAlpha = a * om;
    ktext('도착 시점에도 이 숫자가 맞을 확률', 120, 150, 52, t - 1.0, { w: 800, a: 'left' });
    ktext('가는 동안 바뀔 가능성까지 계산  ·  병원 순위는 바꾸지 않고 참고로만', 120, 212, 26, t - 1.6, { w: 400, a: 'left', al: .65 });
  }
  if (t > 10.3) {
    ctx.globalAlpha = a;
    const o2 = 14.2;
    ktext('AI는 판단하지 않는다.', W / 2, 460, 80, t - 10.4, { w: 300, blur: true, out: o2 - 10.4 });
    ktext('숫자를 얼마나 믿어도 되는지 알려줄 뿐.', W / 2, 590, 80, t - 11.4, { w: 800, blur: true, out: o2 - 11.4 });
  }
  if (t > 14.6) {
    ctx.globalAlpha = a;
    const k = eOutExpo(prog(t, 14.6, 16));
    txt('GOLDENLINK', W / 2, 500, 110, { w: 800, ls: lerp(80, 26, k), al: prog(t, 14.6, 15.2) });
    line(W / 2 - 300 * k, 590, W / 2 + 300 * k, 590, 2, .6);
    ktext('병상 정보 신뢰도 엔진', W / 2, 650, 34, t - 15.2, { w: 400, ls: 8, al: .8 });
    ktext('정답 기준: 병원이 나중에 스스로 고친 값  ·  응급의료포털(E-Gen) 전국 443곳 기록으로 학습', W / 2, 1000, 20, t - 15.8, { w: 400, al: .4, f: SANS });
  }
  ctx.globalAlpha = 1;
});

// ── v5(v4 기반) — 쉬운 말 버전(v3 문구)에서 필요한 구간만 잘라 빠르게 재생 ──
// ── v6: 04 학습 — 03의 단서 카드 7장이 그대로 이어져, 과거 기록에서 패턴을 배우고 "버틸 시간"을 예측한다 ──
const bez = (p0, p1, p2, p3, k) => { const u = 1 - k; return [u * u * u * p0[0] + 3 * u * u * k * p1[0] + 3 * u * k * k * p2[0] + k * k * k * p3[0], u * u * u * p0[1] + 3 * u * u * k * p1[1] + 3 * u * k * k * p2[1] + k * k * k * p3[1]]; };
function bezPath(p0, p1, p2, p3, k0, k1, w, al, dash, off = 0) {
  if (al <= 0 || k1 <= k0) return;
  ctx.save(); ctx.globalAlpha *= al; ctx.strokeStyle = '#fff'; ctx.lineWidth = w; ctx.lineCap = 'round';
  if (dash) { ctx.setLineDash(dash); ctx.lineDashOffset = off; }
  ctx.beginPath(); for (let i = 0; i <= 40; i++) { const p = bez(p0, p1, p2, p3, lerp(k0, k1, i / 40)); i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]); } ctx.stroke(); ctx.restore();
}
function chip(x, y, w, h, name, sub, subAl, nameSize, hi = 0, al = 1) {
  ctx.save(); ctx.globalAlpha *= al;
  if (hi > 0) { glow(x, y, w * .7, .18 * hi); ctx.save(); ctx.globalAlpha *= .14 * hi; ctx.fillStyle = '#fff'; rrect(x - w / 2, y - h / 2, w, h, 16); ctx.fill(); ctx.restore(); }
  ctx.save(); ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.6 + 1.6 * hi; ctx.globalAlpha *= .75 + .25 * hi; rrect(x - w / 2, y - h / 2, w, h, 16); ctx.stroke(); ctx.restore();
  const dy = lerp(0, -18, subAl);
  txt(name, x, y + dy, nameSize, { w: 800 });
  if (subAl > 0) txt(sub, x, y + 28, 24, { w: 400, al: .7 * subAl });
  ctx.restore();
}
const LCX = 900, LCY = 560;               // 학습 코어
const COLX = 360, COLW = 300, COLH = 74;  // 왼쪽 단서 열
const colY = i => 250 + i * 100;
const PATTERNS = [
  { at: 5.2, f: [2, 4], rule: '평소 자주 고치는 병원  +  요즘 더 바쁘게 고침', out: '곧 바뀐다', min: 5 },
  { at: 7.0, f: [1, 0], rule: '지난번엔 오래 버팀  +  고친 횟수가 적음', out: '오래 간다', min: 60 },
  { at: 8.8, f: [6, 5], rule: '아침 병상 정리 시간  +  크게 바꾸는 중', out: '곧 크게 바뀐다', min: 10 },
];
const ROWY = [320, 480, 640], OUTX = 1240, BARW = 560;
const NOW_VALS = ['4번째', '6분', '5분', '2분', '1분', '4석', '토 09:40'];
const REC = (() => { const r = rng(77), out = []; for (let i = 0; i < 140; i++) out.push({ tl: 2.2 + i * .021 + r() * .05, y: 200 + r() * 760, bars: Array.from({ length: 7 }, () => .2 + r() * .8), curve: (r() - .5) * 300 }); return out; })();
function learnFn(t, d) {
  const cx = W / 2;
  ctx.globalAlpha = 1;
  // 03에서 넘어온 요소들(제목·타임라인·각주)이 빠지며 무대를 비운다
  const gone = prog(t, .1, .8);
  if (gone < 1) {
    ctx.globalAlpha = 1 - gone;
    txt('AI가 보는 단서 7가지', cx, 120 - 30 * eIn(gone), 50, { w: 800 });
    line(360, 760, 1560, 760, 2, .5);
    TICKS.forEach(x => line(x, 760 - 34, x, 760 + 34, 3, .95 * (1 - gone)));
    txt('수정 이력 — 값은 버리고, 고친 시각만 남긴다', 360, 840, 26, { a: 'left', w: 400, al: .6 });
    txt('필요한 건 "언제 고쳤나" 기록뿐  ·  환자 정보는 쓰지 않는다', cx, 1000, 26, { w: 400, al: .7 });
    FEATS.forEach((f, idx) => { const row = idx < 4 ? 0 : 1, j = row ? idx - 4 : idx, n = row ? 3 : 4; line(TICKS[(idx * 4 + 2) % TICKS.length], 760 - 34, cx + (j - (n - 1) / 2) * 400, 270 + row * 200 + 60, 1, .25, [4, 6]); });
    ctx.globalAlpha = 1;
  }
  // 코어
  const coreIn = eOutBack(prog(t, 1.6, 2.4));
  const hits = REC.reduce((s, r) => { const dt = t - (r.tl + .9); return s + (dt > 0 && dt < .35 ? 1 - dt / .35 : 0); }, 0);
  const synth = prog(t, 11.4, 11.9), synthFlash = Math.exp(-Math.max(0, t - 11.9) * 3) * (t > 11.9 ? 1 : 0);
  const patPulse = PATTERNS.reduce((s, p) => { const dt = t - (p.at + .7); return s + (dt > 0 && dt < .5 ? 1 - dt / .5 : 0); }, 0);
  if (coreIn > 0) {
    const pulse = Math.min(1, hits * .12 + patPulse + synthFlash);
    glow(LCX, LCY, 230 * coreIn, .1 + .25 * pulse);
    ctx.save(); ctx.translate(LCX, LCY); ctx.scale(coreIn, coreIn);
    [[78, .9, 1.4, 2.5], [108, -.6, 1.0, 1.6], [138, .35, .6, 4.2]].forEach(([r, sp, w, arcLen]) => {
      ctx.save(); ctx.rotate(t * sp); ctx.strokeStyle = '#fff'; ctx.globalAlpha *= .35 + .5 * pulse; ctx.lineWidth = w * 2; ctx.beginPath(); ctx.arc(0, 0, r, 0, arcLen); ctx.stroke();
      ctx.beginPath(); ctx.arc(0, 0, r, Math.PI, Math.PI + arcLen * .4); ctx.stroke(); ctx.restore();
    });
    for (let i = 0; i < 24; i++) { const an = i / 24 * Math.PI * 2 - t * .2; ctx.save(); ctx.globalAlpha *= .3; ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(Math.cos(an) * 152, Math.sin(an) * 152); ctx.lineTo(Math.cos(an) * 162, Math.sin(an) * 162); ctx.stroke(); ctx.restore(); }
    circle(0, 0, 16 + 10 * pulse, true, 1);
    ctx.restore();
    txt('AI', LCX, LCY + 205, 26, { w: 800, ls: 6, al: coreIn * .8 });
  }
  // 단서 카드: 03의 자리 → 왼쪽 열
  const fly = eInOut(prog(t, .8, 2.2));
  const hiOf = idx => {
    let h = 0;
    PATTERNS.forEach(p => { if (p.f.includes(idx)) h = Math.max(h, prog(t, p.at, p.at + .3) * (1 - prog(t, p.at + 1.5, p.at + 1.8))); });
    return Math.max(h, synth * (1 - prog(t, 12.6, 13.2)) * .9);
  };
  FEATS.forEach((f, idx) => {
    const row = idx < 4 ? 0 : 1, j = row ? idx - 4 : idx, n = row ? 3 : 4;
    const k = eInOut(prog(t - .8 - idx * .06, 0, 1.4));
    const x = lerp(cx + (j - (n - 1) / 2) * 400, COLX, k), y = lerp(270 + row * 200, colY(idx), k);
    const w = lerp(360, COLW, k), h = lerp(120, COLH, k);
    const hi = hiOf(idx);
    // 단서 → 코어 연결선(흐르는 점선)
    const p0 = [COLX + COLW / 2, colY(idx)], p1 = [COLX + COLW / 2 + 220, colY(idx)], p2 = [LCX - 300, LCY], p3 = [LCX - 150, LCY];
    const lk = eInOut(prog(t - 2.0 - idx * .05, 0, .8));
    if (lk > 0) {
      bezPath(p0, p1, p2, p3, 0, lk, 1.2, .22 + .6 * hi, [3, 9], -t * 40);
      if (hi > .05) bezPath(p0, p1, p2, p3, 0, lk, 2.5, .8 * hi);
    }
    // 패턴 순간: 단서에서 코어로 빛이 흐른다
    PATTERNS.forEach(p => { if (!p.f.includes(idx)) return; const pk = prog(t, p.at + .15, p.at + .75); if (pk > 0 && pk < 1) { const q = bez(p0, p1, p2, p3, eInOut(pk)); glow(q[0], q[1], 36, .9); circle(q[0], q[1], 6); } });
    if (t > 11.9) { const pk = prog(t, 11.95 + idx * .04, 12.6 + idx * .04); if (pk > 0 && pk < 1) { const q = bez(p0, p1, p2, p3, eInOut(pk)); glow(q[0], q[1], 30, .9); circle(q[0], q[1], 5); } }
    chip(x, y, w, h, f[0], f[1], 1 - prog(t, .8, 1.5), lerp(34, 28, k), hi);
    // 지금 이 숫자의 값
    const vk = eOutBack(prog(t - 11.0 - idx * .07, 0, .5));
    if (vk > 0) { ctx.save(); ctx.globalAlpha = 1 - prog(t, 13.6, 14); txt(NOW_VALS[idx], COLX - COLW / 2 - 24, y, 26 * vk, { a: 'right', w: 800, f: SANS }); ctx.restore(); }
  });
  // 과거 기록이 코어로 쏟아진다
  REC.forEach(r => {
    const k = prog(t, r.tl, r.tl + .9); if (k <= 0 || k >= 1) return;
    const e = eIn(k), x = lerp(1960, LCX + 40, e), y = lerp(r.y, LCY, e) + Math.sin(e * Math.PI) * r.curve * .3, s = lerp(1, .25, e);
    ctx.save(); ctx.globalAlpha = (1 - prog(k, .75, 1)) * .9; ctx.translate(x, y); ctx.scale(s, s);
    ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5; ctx.strokeRect(-36, -14, 72, 28);
    ctx.fillStyle = '#fff'; r.bars.forEach((b, i) => ctx.fillRect(-30 + i * 6.4, 10 - 20 * b, 4, 20 * b));
    ctx.fillRect(16, -2, 14 * r.bars[0], 4);
    ctx.restore();
  });
  if (t > 2.2) {
    const k = prog(t, 2.2, 5.0), oa = 1 - prog(t, 5.0, 5.4);
    ctx.save(); ctx.globalAlpha = prog(t, 2.2, 2.5) * oa;
    txt(fmt(Math.round(217401 * eOutExpo(k))) + '개', LCX, 880, 60, { f: MONO, w: 800 });
    txt('숫자마다 "그때의 단서 7가지 + 실제로 버틴 시간"을 본다', LCX, 940, 26, { w: 400, al: .7 });
    ctx.restore();
    // 기록 한 장의 범례
    ctx.save(); ctx.globalAlpha = prog(t, 2.6, 3.0) * oa; ctx.translate(LCX - 290, 880); ctx.scale(1.4, 1.4);
    ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.2; ctx.strokeRect(-36, -14, 72, 28); ctx.fillStyle = '#fff';
    [.5, .8, .3, .6, .9, .4, .7].forEach((b, i) => ctx.fillRect(-30 + i * 6.4, 10 - 20 * b, 4, 20 * b)); ctx.fillRect(16, -2, 10, 4); ctx.restore();
    
  }
  // 배운 패턴 → 버틸 시간
  const rowsDim = 1 - .7 * prog(t, 11.2, 11.7), rowsOut = 1 - prog(t, 12.4, 12.9);
  if (t > 5.0) txt('배운 패턴', OUTX, 240, 24, { a: 'left', w: 700, ls: 3, al: .6 * prog(t, 5.0, 5.4) * rowsOut });
  PATTERNS.forEach((p, i) => {
    const y = ROWY[i], k = prog(t, p.at + .6, p.at + 1.0); if (k <= 0) return;
    ctx.save(); ctx.globalAlpha = rowsDim * rowsOut;
    const q0 = [LCX + 150, LCY], q3 = [OUTX - 20, y + 10];
    const lk = eInOut(prog(t, p.at + .6, p.at + 1.0));
    bezPath(q0, [LCX + 300, LCY], [OUTX - 160, y + 10], q3, 0, lk, 2, .7);
    if (lk < 1) { const q = bez(q0, [LCX + 300, LCY], [OUTX - 160, y + 10], q3, lk); glow(q[0], q[1], 34, .9); }
    ktext(p.rule, OUTX, y - 26, 24, t - p.at - .8, { w: 400, a: 'left', al: .75, st: .012 });
    const bk = eOutExpo(prog(t, p.at + 1.0, p.at + 1.8)), bw = BARW * p.min / 60 * bk;
    ctx.fillStyle = '#fff'; ctx.fillRect(OUTX, y + 2, Math.max(2, bw), 16);
    ctx.globalAlpha *= .25; ctx.fillRect(OUTX, y + 9, BARW, 2); ctx.globalAlpha /= .25;
    txt(`${p.out}  ·  약 ${p.min === 60 ? '1시간' : p.min + '분'}`, OUTX, y + 50, 28, { a: 'left', w: 800, al: prog(t, p.at + 1.2, p.at + 1.6) });
    ctx.restore();
  });
  if (t > 5.4) txt('버틸 시간 →', OUTX + BARW, 750, 20, { a: 'right', f: SANS, w: 400, al: .45 * prog(t, 5.4, 5.8) * rowsOut });
  // 지금 이 숫자 → 예측
  if (t > 12.3) {
    const k = eOutExpo(prog(t, 12.3, 13.0)), mins = Math.round(9 * eOutExpo(prog(t, 12.4, 13.2)));
    const q0 = [LCX + 150, LCY], q3 = [OUTX - 20, 470];
    bezPath(q0, [LCX + 300, LCY], [OUTX - 160, 470], q3, 0, eInOut(prog(t, 12.0, 12.5)), 3, .9);
    txt('이 숫자가 버틸 시간', OUTX, 380, 34, { a: 'left', w: 400, al: k * .8 });
    txt(`약 ${mins}분`, OUTX - 8 + 40 * (1 - k), 490, 150, { a: 'left', w: 800, al: k });
    // 확률 곡선 미리보기 → 다음 장면으로
    const ck = eInOut(prog(t, 13.1, 14.2)), gx0 = OUTX, gx1 = OUTX + 520, gy0 = 860, gy1 = 640, mu = Math.log(9), pts = [];
    for (let m = 0; m <= 40; m += .25) pts.push([lerp(gx0, gx1, m / 40), lerp(gy0, gy1, surv(m, mu, .9))]);
    if (ck > 0) { line(gx0, gy0, gx1, gy0, 1.5, .4 * ck); line(gx0, gy0, gx0, gy1 - 10, 1.5, .4 * ck); const hd = partialPath(pts, ck, 3.5); if (hd) glow(hd[0], hd[1], 30, .8);
      txt('→ 시간이 지날수록 "아직 맞을 확률"이 줄어든다', gx0, gy0 + 40, 22, { a: 'left', w: 400, al: .7 * prog(t, 13.4, 13.8) }); }
  }
  // 제목
  ktext('과거 기록 21만 개에서 패턴을 배운다', cx, 120, 50, t - 1.5, { w: 800, out: 11.0 - 1.5 });
  ktext('지금 이 숫자에 적용하면', cx, 120, 50, t - 11.3, { w: 800 });
  ctx.globalAlpha = 1;
}

const OLD = SCENES.slice(); SCENES.length = 0;
function cut(name, src, segs, opt = {}) {
  const parts = []; let d = 0;
  for (const [a, b, sp] of segs) { const len = (b - a) / sp; parts.push({ s: d, len, a, sp }); d += len; }
  SCENES.push({ name, dur: d, fade: true, ...opt, fn: t => { let p = parts[parts.length - 1]; for (const q of parts) if (t < q.s + q.len) { p = q; break; } src.fn(p.a + (t - p.s) * p.sp, src.dur); } });
}
// v5: 템포 완화(약 90초) — 장면 안에서 건너뛰지 않고 거의 원래 속도로 이어 재생
// v7: 텍스트를 읽을 시간을 주려고 전체를 0.99배속으로 재생하고,
//  - 글자가 다 나온 직후~사라지기 직전은 SLOW(0.3배속)로 흘려 읽을 시간을 주고
//  - 한 화면이 빠지고 다음 화면이 들어오는 장면 안 전환은 EASE(0.5배속)로 늦춘다 (약 120초)
const SP = 0.99, SLOW = .3, EASE = .5;
cut('', OLD[0], [[0, 9.9, SP], [9.9, 10.2, SLOW], [10.2, 11, SP]]);
cut('문제', OLD[1], [[0, 6.5, SP], [6.5, 7.6, EASE], [7.6, 10.2, SP], [10.2, 10.5, SLOW], [10.5, 16, SP]]);
cut('질문', OLD[2], [[0.2, 8.5, SP]]);
cut('아이디어', OLD[3], [[0, 7.8, SP], [7.8, 8.15, SLOW], [8.15, 10.2, EASE], [10.2, 15.6, SP]], { fo: 0 });
cut('AI 학습', { fn: learnFn, dur: 14.6 }, [[0, .7, SP], [.7, 2.4, EASE], [2.4, 10.9, SP], [10.9, 11.6, EASE], [11.6, 14.6, SP]], { fi: 0, z0: 1.025 });
cut('AI 예측', OLD[5], [[8.4, 15.0, SP], [15.0, 15.3, SLOW], [15.3, 16, SP]]);
cut('검증', OLD[6], [[7.8, 14.2, SP], [14.2, 14.5, SLOW], [14.5, 15.7, EASE], [15.7, 19.9, SP], [19.9, 20.2, SLOW], [20.2, 21, SP]]);
cut('적용', OLD[7], [[0, 9.1, SP], [9.1, 9.4, SLOW], [9.4, 10.6, EASE], [10.6, 13.8, SP], [13.8, 14.1, SLOW], [14.1, 15.2, EASE], [15.2, 18, SP]]);

// ── 타임라인 ──────────────────────────────────────────────
let acc = 0; SCENES.forEach((s, i) => { s.start = acc; acc += s.dur; s.idx = i; });
const DURATION = acc;

function hud(t, s, lt) {
  if (!s.name) return;
  const a = env(lt, s.dur, .6, .6);
  ctx.globalAlpha = a;
  txt(String(s.idx).padStart(2, '0'), 80, 72, 34, { a: 'left', f: MONO, w: 700 });
  line(144, 72, 144 + 48 * prog(lt, 0, .8), 72, 2, .8);
  txt(s.name, 212, 72, 34, { a: 'left', w: 800, ls: 2 });
  txt('정보의 유효기간', W - 80, 72, 26, { a: 'right', w: 500, al: .75, ls: 2 });
  ctx.globalAlpha = 1;
}

function draw(t) {
  ctx.setTransform(S, 0, 0, S, 0, 0);
  ctx.globalAlpha = 1; ctx.filter = 'none';
  ctx.fillStyle = '#000'; ctx.fillRect(0, 0, W, H);
  const hudQ = [];
  // 장면 경계에서 살짝 겹쳐 그린다(크로스 디졸브)
  for (const s of SCENES) {
    const lt = t - s.start;
    if (lt < 0 || lt > s.dur || (lt === s.dur && s !== SCENES[SCENES.length - 1])) continue;
    // 장면 전체 카메라: 천천히 밀려 들어가는 느낌
    ctx.save();
    const z = (s.z0 ?? 1) + .025 * prog(lt, 0, s.dur);
    ctx.translate(W / 2, H / 2); ctx.scale(z, z); ctx.translate(-W / 2, -H / 2);
    s.fn(lt, s.dur);
    ctx.restore();
    if (s.fade) { ctx.save(); ctx.setTransform(S, 0, 0, S, 0, 0); const fi = s.fi ?? .6, fo = s.fo ?? .6; ctx.globalAlpha = 1 - Math.min(fi > 0 ? prog(lt, 0, fi) : 1, fo > 0 ? 1 - prog(lt, s.dur - fo, s.dur) : 1); ctx.fillStyle = '#000'; ctx.fillRect(0, 0, W, H); ctx.restore(); }
    hudQ.push([s, lt]);
  }
  // 비네트
  const g = ctx.createRadialGradient(W / 2, H / 2, H * .35, W / 2, H / 2, H * .95);
  g.addColorStop(0, 'rgba(0,0,0,0)'); g.addColorStop(1, 'rgba(0,0,0,.65)');
  ctx.globalAlpha = 1; ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  for (const [s, lt] of hudQ) hud(t, s, lt);
  // 그레인
  const fr = Math.floor(t * 24), r = rng(fr + 1);
  ctx.save(); ctx.globalAlpha = .045; ctx.globalCompositeOperation = 'screen';
  const ox = -r() * 256, oy = -r() * 256;
  for (let y = oy; y < H; y += 256) for (let x = ox; x < W; x += 256) ctx.drawImage(grain, x, y);
  ctx.restore();
  // 진행 막대
  ctx.globalAlpha = .25; ctx.fillStyle = '#fff'; ctx.fillRect(0, H - 3, W * t / DURATION, 3); ctx.globalAlpha = 1;
}

// ── 재생 제어 ─────────────────────────────────────────────
let cur = 0, playing = false, last = 0;
const scrub = document.getElementById('scrub'), tc = document.getElementById('tc'), btn = document.getElementById('play');
function seek(t) { cur = clamp(t, 0, DURATION); draw(cur); scrub.value = Math.round(cur / DURATION * 1000); tc.textContent = cur.toFixed(2) + ' / ' + DURATION.toFixed(0) + 's'; }
function loop(now) { if (!playing) return; cur += (now - last) / 1000; last = now; if (cur >= DURATION) { cur = DURATION; playing = false; btn.textContent = '▶ 재생'; } seek(cur); requestAnimationFrame(loop); }
btn.onclick = () => { playing = !playing; btn.textContent = playing ? '❚❚ 정지' : '▶ 재생'; if (cur >= DURATION) cur = 0; last = performance.now(); requestAnimationFrame(loop); };
scrub.oninput = () => { playing = false; btn.textContent = '▶ 재생'; seek(scrub.value / 1000 * DURATION); };
addEventListener('keydown', e => { if (e.code === 'Space') { e.preventDefault(); btn.click(); } });
if (Q.has('t')) seek(Number(Q.get('t'))); else seek(0);
window.Film = { duration: DURATION, seek, ready: true, frame: (q = .95) => cv.toDataURL('image/jpeg', q), scenes: SCENES.map(s => [s.name, s.start, s.dur]) };
})();
