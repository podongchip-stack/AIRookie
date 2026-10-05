// [demo 브랜치] 시나리오 진행기 + 녹화 — 시나리오 하나를 시연 무대(demo-stage.html)에서 자동으로 재생하고, 원하면
// 영상으로 남긴다. ⚠ develop에 병합하지 않는다.
//
//   node demo/player/play.mjs <시나리오 번호|파일> [--record] [--out demo/out]
//
// 환경변수: DEMO_DASH(대시보드 주소, 기본 http://localhost:3100) · DEMO_HUB(시연용 hub, 기본 http://127.0.0.1:5101)
//          DEMO_VOICE(대본 구조화에 쓸 voice, 기본 http://127.0.0.1:6000) · DEMO_HEADLESS=1(창 없이)
//
// 진행: 소개 카드 → 출동 → 현장 도착 → 대원 휴대폰으로 병원 선택·통화(대본을 사람 말 속도로 자막에 띄움) →
// 통화 종료 → 실제 MF_BERT가 대본을 구조화(걸린 시간 그대로) → 후보 병원 동시 전달 → 병원별 수용 불가·가능 →
// 이송 승인 → 이송 → 도착·수용(또는 도착 후 수용 불가 → 재선택) → 복귀. 구급차 여러 대면 동시에 진행한다.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { chromium } from "playwright-core";
import ffmpegStatic from "ffmpeg-static";
import { HubLink } from "./hub.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DEMO = path.resolve(HERE, "..");
const DASH = (process.env.DEMO_DASH || "http://localhost:3100").replace(/\/$/, "");
const HUB = (process.env.DEMO_HUB || "http://127.0.0.1:5101").replace(/\/$/, "");
const VOICE = (process.env.DEMO_VOICE || "http://127.0.0.1:6000").replace(/\/$/, "");

const REASON_LABEL = {
  BEDS_FULL: "응급실 병상 없음", OR_OCCUPIED: "수술실 사용 중", STAFF_BUSY: "의료진 처치 중",
  NO_WARD: "해당 병동 없음", NO_DEPARTMENT: "해당 진료과 없음", NO_EQUIPMENT: "필요 장비 없음",
  ON_CALL_MISMATCH: "당직 진료과 불일치", NIGHT_UNAVAILABLE: "야간 진료 불가",
  SEVERITY_EXCEEDED: "중증도 감당 불가", AGE_LIMIT: "연령 제한(소아 등)", UNSPECIFIED: "사유 미기재",
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ── 작동 원리 설명(--explain, 합본 영상용) ──
// 설명 모드는 진행을 PACE배로 빠르게(기다림·자막 속도) 하고, 설명 상자는 읽을 만큼만(EXPLAIN_MIN_MS) 보장한다 —
// 장면이 원래 길면(통화 등) 더 기다리지 않는다. 설명이 없는 장면은 상자를 내린다.
const EXPLAIN = process.argv.includes("--explain");
// 차분한 모드(--calm, 설명 모드는 자동): 썸네일 없음 · 관제 지도로 넘어가지 않음 · 자막 한 줄 — 합본 영상용
// 카드 모드(--dh): 차분한 모드 + 장면마다 중요한 카드만 확대해 보여 준다(CARDS). 구급차 1대 시나리오용
const DH = process.argv.includes("--dh");
const CALM = EXPLAIN || DH || process.argv.includes("--calm");
const SUFFIX = EXPLAIN ? "_explain" : DH ? "_dh" : CALM ? "_calm" : "";
const PACE = EXPLAIN ? 0.55 : 1;
const EXPLAIN_MIN_MS = 5200;
const pace = (ms) => sleep(ms * PACE);
const EX = {
  arrive: { title: "AI 첫 통화 추천", lines: [
    "<b>빈 병상 · 병상 정보 신뢰도(AI) · 도착 시간</b>을 함께 따져 한 곳을 추천",
    "틀려도 괜찮다 — 통화 내용은 모든 후보에게 간다",
  ] },
  call: { title: "통화가 곧 자막", lines: [
    "말이 끊길 때마다 그 문장을 바로 음성 인식(<b>Qwen3-ASR</b>)",
    "시연은 음성 대신 대본을 같은 속도로 재생",
  ] },
  structuring: { title: "AI 구조화 — MF_BERT", lines: [
    "통화 전문에서 <b>17개 항목</b>(KTAS·활력징후·의식…)을 고른다",
    "<b>생성형이 아니다</b> — 없는 말을 지어내지 않는다",
  ] },
  broadcast: { title: "동시 전달 · 규칙 순위", lines: [
    "5km 존 안 후보 병원 <b>전부에 한 번에</b>",
    "순위 = 진료과 일치 + 이동 시간 + 병상(<b>공개된 규칙</b>)",
  ] },
  reject: { title: "거절 사유가 바로 보인다", lines: [
    "사유는 4축으로 기록 — 일시적 사정으로 병원을 영구히 밀어내지 않는다",
    "거절이 <b>40%</b>를 넘으면 존 자동 확장",
  ] },
  approve: { title: "병원 승인 = 후보 등록", lines: ["최종 확정은 <b>구급대원</b>"] },
  zone: { title: "존 자동 확장", lines: ["시간이 아니라 <b>거절 비율</b>로 넓힌다"] },
  confirm: { title: "최종 결정은 사람", lines: ["이송 승인은 <b>구급대원만</b> — AI는 판단을 대체하지 않는다"] },
  refuse: { title: "도착 후 수용 불가", lines: ["확정 해제 · 그때 상황을 <b>정답 데이터</b>로 기록"] },
  reselect: { title: "재선택", lines: ["이미 승인한 병원으로 — <b>다시 전화하지 않는다</b>"] },
  arrival: { title: "의사결정 블랙박스", lines: ["모든 결정이 <b>시각 + 해시 체인</b>으로 기록 — 위변조 검증"] },
};

// ── 카드 모드의 장면별 카드: 장면 키(caption.ex) → { 창 종류: 찾기 }. 찾기 문법은 demo-stage.html의 카드 모드 참고.
// 창 종류: amb(구급차 대시보드) · phone(대원 휴대폰) · hosp(지금 응답하는 병원 대시보드). 카드가 아직 안 나타나면 창 전체를 보여 주다 나타나면 따라간다.
const PHONE = { css: "html" };
const CAND = { panel: "병원 후보", vh: 760 };
const MAP = { panel: "지도", vh: 760 };
// 지도가 안 뜨는 환경(카카오 키·도메인 미등록)에선 오류 문구가 그대로 찍히므로 출동 상태 패널(단계 문구가 바뀐다)로 대신 보여 준다
const DISPATCH = { any: ["기지 대기", "현장으로 출동 중", "병원으로 이송 중", "병원 도착 — 수용 결과 대기", "재선택 대기 (", "기지 복귀 중"].map((t) => ({ tag: "span", has: t, up: "section" })), vh: 760 };
const NO_MAP = { dispatch: { amb: DISPATCH }, transport: { amb: DISPATCH } };
const SUMMARY = { panel: "통화 요약" };
const REQUEST = { panel: "구급차 수용 요청", vh: 1000 };
const CARDS = {
  dispatch: { amb: MAP },
  arrive: { phone: PHONE, amb: { tag: "li", has: "첫 연락 추천" } },
  call: { phone: PHONE, amb: { css: "h2", has: "통화 현황", up: "section" } },
  structuring: { amb: SUMMARY },
  structured: { amb: SUMMARY },
  broadcast: { amb: CAND },
  reject: { hosp: REQUEST, amb: CAND },
  approve: { hosp: REQUEST, amb: CAND },
  zone: { amb: CAND },
  confirm: { amb: CAND },
  transport: { amb: MAP },
  refuse: { hosp: REQUEST, amb: CAND },
  reselect: { amb: CAND },
  arrival: { hosp: REQUEST }, // 수용 완료로 사건이 닫혀도 카드는 직전 영역을 유지한다
};

// ── 고프레임 녹화(--dh): Playwright 내장 녹화는 25fps 고정이라 쓰지 않고, 크롬이 보내 주는 화면 프레임을 받아 일정한 간격(fps)으로
// ffmpeg에 넣어 mp4를 바로 만든다. 새 프레임이 없는 동안(정지 화면)에는 직전 프레임을 반복한다. 크롬이 실제로 그려 주는 프레임은
// 환경에 따라 60fps 안팎이 한계라, fps를 그 이상 올리면 같은 장면이 반복될 뿐 더 부드러워지지는 않는다.
async function startRecorder(page, out, fps) {
  const cdp = await page.context().newCDPSession(page);
  const ff = spawn(ffmpegStatic, ["-v", "error", "-y", "-f", "image2pipe", "-framerate", String(fps), "-c:v", "mjpeg", "-i", "-",
    "-c:v", "libx264", "-preset", "fast", "-crf", "17", "-pix_fmt", "yuv420p", "-r", String(fps), "-movflags", "+faststart", out], { stdio: ["pipe", "inherit", "inherit"] });
  const exited = once(ff, "exit");
  ff.stdin.on("error", () => {});
  let last = null, stopped = false, gotFirst;
  const first = new Promise((r) => (gotFirst = r));
  cdp.on("Page.screencastFrame", (e) => {
    last = Buffer.from(e.data, "base64");
    gotFirst();
    cdp.send("Page.screencastFrameAck", { sessionId: e.sessionId }).catch(() => {});
  });
  await cdp.send("Page.startScreencast", { format: "jpeg", quality: 92, maxWidth: 1920, maxHeight: 1080, everyNthFrame: 1 });
  await first;
  const t0 = process.hrtime.bigint();
  const loop = (async () => {
    for (let n = 0; !stopped; n++) {
      const due = t0 + BigInt(Math.round((n * 1e9) / fps));
      const wait = Number(due - process.hrtime.bigint()) / 1e6;
      if (wait > 2) await sleep(wait - 1);
      if (!ff.stdin.write(last)) await once(ff.stdin, "drain");
    }
  })();
  return {
    t0Ms: Date.now(),
    async stop() {
      stopped = true;
      await loop;
      await cdp.send("Page.stopScreencast").catch(() => {});
      ff.stdin.end();
      await exited;
    },
  };
}

function loadScenario(arg) {
  const file = fs.existsSync(arg) ? arg : path.join(DEMO, "scenarios", `${String(arg).padStart(2, "0")}.json`);
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

// ── 연출: 무대의 큰 화면·자막은 한 번에 한 장면만. 구급차 여러 대가 동시에 진행돼도 장면은 차례로 보인다 ──
class Director {
  constructor(page) {
    this.page = page;
    this.panes = {}; // 카드 모드에서 창 종류(amb·phone·hosp) → 창 id
    this.chain = Promise.resolve();
  }
  // 구급차 대시보드의 지도가 오류 문구로 떠 있는지(카카오 키·도메인 미등록)
  mapBroken() {
    return this.page.evaluate((id) => {
      const f = document.getElementById("frame-" + id);
      return !!f?.contentDocument?.body?.innerText.includes("KAKAO_MAP_APP_KEY");
    }, this.panes.amb);
  }
  stage(fn, ...args) {
    return this.page.evaluate(([f, a]) => window.stage[f](...a), [fn, args]);
  }
  // 장면: 포커스·자막을 바꾸고 body를 실행한 뒤 holdMs만큼 보여 준다. 다른 장면은 이게 끝날 때까지 기다린다.
  scene(focus, caption, body = async () => {}, holdMs = 2500) {
    const run = async () => {
      const ex = EXPLAIN && caption.ex ? EX[caption.ex] : null;
      const cards = DH && caption.ex && ((NO_MAP[caption.ex] && (await this.mapBroken())) ? NO_MAP[caption.ex] : CARDS[caption.ex]);
      if (cards) {
        const map = {};
        for (const [kind, find] of Object.entries(cards)) if (this.panes[kind]) map[this.panes[kind]] = find;
        await this.stage("cards", map);
      } else {
        if (DH) await this.stage("cards", {});
        await this.stage("focus", focus);
      }
      await this.stage("caption", caption.step, caption.text, CALM ? "" : caption.sub || "", caption.tone || "");
      await this.stage("explain", ex ? ex.title : null, ex ? ex.lines : []);
      const t0 = Date.now();
      await body();
      // 원래 보여 주던 시간(PACE배), 설명이 있으면 읽을 만큼은 보장
      const left = ex ? EXPLAIN_MIN_MS - (Date.now() - t0) : 0;
      // 수용 완료 직후엔 사건이 닫혀 카드가 비므로 카드 모드에선 오래 붙잡지 않는다
      await sleep(Math.max((DH && caption.ex === "arrival" ? Math.min(holdMs, 300) : holdMs) * PACE, left));
    };
    const p = this.chain.then(run, run);
    this.chain = p.catch(() => {});
    return p;
  }
}

async function structure(caseId, lines, durationSec) {
  const r = await fetch(VOICE + "/demo/structure", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ caseId, lines, durationSec }),
  });
  if (!r.ok) throw new Error(`voice ${VOICE}/demo/structure ${r.status} — demo 브랜치 voice가 떠 있는지 확인하세요`);
  return r.json();
}

function summaryLine(summary) {
  const parts = [];
  if (summary.ktas_level) parts.push(`KTAS ${summary.ktas_level}`);
  const cc = summary.chief_complaint;
  if (cc?.minor || cc?.major) parts.push(`주 호소: ${cc.minor || cc.major}`);
  const v = (summary.vitals || []).at(-1);
  if (v?.sbp) parts.push(`혈압 ${v.sbp}/${v.dbp ?? "?"}`);
  if (v?.spo2) parts.push(`SpO₂ ${v.spo2}%`);
  if (summary.age?.years) parts.push(`${summary.age.years}세${summary.sex ? " " + summary.sex : ""}`);
  return parts.join(" · ");
}

// 매칭 결과에서 응답할 병원 고르기 — "top": 아직 응답 안 한 상위 병원(승인이면 병상 없음·이미 거절 제외),
// {rank:n}: n번째, "called": 휴대폰으로 전화한 병원, "taken": 같은 시나리오의 다른 구급차가 이미 이송을 확정한 병원
function pickHospital(match, rule, responded, forApprove, calledId, taken) {
  const list = match.hospitals;
  const ok = (h) => !responded.has(h.hospitalId) && h.status === "pending" && (!forApprove || h.unavailableReason !== "beds_full");
  if (rule === "taken") return list.find((x) => taken.has(x.hospitalId) && ok(x)) || null;
  if (rule === "called") {
    const h = list.find((x) => x.hospitalId === calledId);
    if (h && ok(h)) return h;
  }
  if (rule && typeof rule === "object" && rule.rank) {
    const h = list[rule.rank - 1];
    if (h && ok(h)) return h;
  }
  return list.find(ok) || null;
}

async function runAmbulance(ctx, spec, idx) {
  const { page, dir, scenario } = ctx;
  const link = new HubLink(HUB, spec.apid);
  await link.open();
  const ambName = spec.name || spec.apid;
  const caseId = `demo-${scenario.id}-${spec.apid}-${Date.now().toString(36)}`;
  const amb = `amb-${spec.apid}`;
  const phone = `phone-${spec.apid}`;
  Object.assign(dir.panes, { amb, phone });
  const frame = (id) => page.frameLocator(`#frame-${id}`);
  await sleep((spec.startDelaySec || 0) * 1000);

  // 1. 출동
  const overview = CALM ? [amb] : ["map"];
  await dir.scene(overview, { step: `${ambName} · 출동`, ex: "dispatch", text: `${spec.incident.label} — ${ambName} 출동`, sub: spec.incident.note || "" }, async () => {
    link.dispatch(caseId, { lat: spec.incident.lat, lng: spec.incident.lng });
  }, 1500);
  await link.waitFor(() => link.phase?.caseId === caseId && link.phase.phase === "on_scene", 90000, "현장 도착");

  // 2. 현장 도착 → 휴대폰으로 첫 병원 선택
  const scene = await link.waitFor(() => link.scene[caseId], 30000, "현장 후보");
  const pickRule = spec.call || "recommended";
  const target =
    (pickRule === "recommended" && scene.hospitals.find((h) => h.firstCallRecommended)) ||
    (typeof pickRule === "object" && scene.hospitals[pickRule.rank - 1]) ||
    scene.hospitals[0];
  await dir.stage("setVisible", phone, true);
  await dir.scene([phone, amb], {
    step: `${ambName} · 현장 도착`, ex: "arrive",
    text: `대원 휴대폰 — 가까운 병원 ${scene.hospitals.length}곳 중 ${target.name}에 전화`,
    sub: target.firstCallRecommended ? "첫 통화 추천: 빈 병상 확인 + 도착 시점 유효 확률(AI) 최고" : "도착 시간순(규칙 기반)",
  }, async () => {
    await pace(1800);
    await frame(phone).locator("li button", { hasText: target.name }).first().dispatchEvent("click");
  }, 500);

  // 3. 통화 — 대본을 사람이 말하는 속도로(줄 길이에 비례) 자막에 띄운다
  await link.waitFor(() => link.call[caseId]?.state === "calling", 20000, "통화 연결");
  const lines = [];
  let t = 0.6;
  await dir.scene([phone, amb], {
    step: `${ambName} · 통화 중`, ex: "call",
    text: `${target.name} 응급실과 통화 — 실시간 자막`,
    sub: "시연용 대본을 자막으로 재생(음성 인식 대신) · 통화가 끝나면 이 내용이 실제 AI 구조화로 들어갑니다",
  }, async () => {
    ctx.mark("callStart");
    for (const text of spec.script) {
      const dur = EXPLAIN ? Math.max(1.3, text.length / 12) : Math.max(1.8, text.length / 8);
      await sleep(dur * 1000);
      lines.push({ start: +t.toFixed(1), end: +(t + dur).toFixed(1), text });
      await link.utterance(caseId, t, t + dur, text);
      t += dur + 0.5;
      await pace(500);
    }
    await pace(800);
    await frame(phone).getByRole("button", { name: "통화 종료" }).first().dispatchEvent("click");
    ctx.mark("callEnd");
    await link.waitFor(() => link.call[caseId]?.state === "ended", 15000, "통화 종료 반영");
  }, 600);

  // 4. 실제 MF_BERT 구조화 — 걸린 시간을 그대로 보여 준다
  let structured;
  await dir.scene([amb], { step: `${ambName} · AI 구조화`, ex: "structuring", text: "통화 내용 구조화 중 — MF_BERT(KLUE RoBERTa-large)", sub: "KTAS·주 호소·활력징후·의식·처치 등 17개 항목", tone: "ai" }, async () => {
    structured = await structure(caseId, lines, t);
  }, 300);
  await dir.scene([amb], {
    step: `${ambName} · AI 구조화 완료 (${structured.extractSec.toFixed(2)}초)`, ex: "structured",
    text: summaryLine(structured.message.summary) || "구조화 완료",
    sub: "AI는 정보 구조화만 — 병원 매칭·순위는 규칙 기반 엔진",
    tone: "ai",
  }, async () => {
    await link.summary(structured.message);
  }, 2500);
  await dir.stage("setVisible", phone, false);

  // 5. 후보 병원 동시 전달
  const match = await link.waitFor(() => link.match[caseId], 60000, "매칭 결과");
  await dir.scene([amb], {
    step: `${ambName} · 병원 동시 전달`, ex: "broadcast",
    text: `존 안 후보 병원 ${match.hospitals.length}곳에 환자 정보를 한 번에 전달`,
    sub: "순차 전화(뺑뺑이) 대신 동시 전달 — 순위: 이동 시간·진료과·병상(규칙 기반)",
  }, async () => {}, 3000);

  // 6. 병원 응답들
  const responded = new Set();
  let approved = null;
  const approvedAll = [];
  const respond = async (list) => {
    for (const r of list) {
      if (r.onlyIfNeeded && approved) continue; // 앞에서 이미 승인 병원이 나왔으면 건너뛴다
      if (r.who === "taken") {
        // 앞 구급차가 병원을 확정할 때까지 기다린다(대량사고: "앞 차가 마지막 병상을 가져갔다")
        await link.waitFor(() => ctx.confirmed.size > 0, 240000, "다른 구급차의 이송 확정");
      }
      const m = link.match[caseId];
      const h = pickHospital(m, r.who || "top", responded, r.action === "approve", target.hospitalId, ctx.confirmed);
      if (!h) continue;
      responded.add(h.hospitalId);
      const hp = `h-${h.hospitalId}`;
      dir.panes.hosp = hp;
      await dir.stage("addPane", hp, { url: `${DASH}/hospital?id=${encodeURIComponent(h.hospitalId)}`, label: `병원 · ${h.name}` });
      await pace(1800);
      const reject = r.action === "reject";
      await dir.scene([hp], {
        step: `${h.name} · ${reject ? "수용 불가" : "수용 가능"}`, ex: reject ? "reject" : "approve",
        text: reject ? `${h.name}: 수용 불가 — ${REASON_LABEL[r.reason] || r.reason || "사유 미기재"}` : `${h.name}: 수용 가능 (승인)`,
        sub: reject ? "거절 사유가 구급대 화면에 바로 표시 · 거절이 쌓이면 존 확장" : "병원 승인은 후보 등록 — 최종 확정은 구급대원",
        tone: reject ? "reject" : "",
      }, async () => {
        await pace(r.delaySec != null ? r.delaySec * 1000 : 2200);
        link.action(caseId, reject ? "hospital_reject" : "hospital_approve", h.hospitalId, "hospital", reject ? r.reason : undefined);
        await link.waitFor(() => link.match[caseId]?.hospitals.find((x) => x.hospitalId === h.hospitalId)?.status !== "pending", 15000, "병원 응답 반영");
      }, 2500);
      if (!reject) {
        approvedAll.push(h);
        if (!approved) approved = h;
      }
      const zones = link.match[caseId].zoneActive?.length || 1;
      if (zones > (m.zoneActive?.length || 1)) {
        await dir.scene([amb], { step: `${ambName} · 존 확장`, ex: "zone", text: `거절이 쌓여 요청 범위를 ${zones * 5}km까지 넓혔습니다`, sub: "거절 비율 40% 이상이면 다음 존으로 자동 확장(규칙 기반)", tone: "reject" }, async () => {}, 3000);
      }
    }
  };
  await respond(spec.responses || [{ action: "approve" }]);
  if (!approved) throw new Error(`[${spec.apid}] 승인한 병원이 없어 이송할 수 없습니다(시나리오 응답 확인)`);

  // 7. 이송 승인 → 이송 → 도착
  const trail = [];
  const confirmAndGo = async (h) => {
    trail.push(`${h.name} 이송 확정`);
    await dir.scene([amb], { step: `${ambName} · 이송 승인`, ex: "confirm", text: `구급대원 최종 선택: ${h.name}`, sub: "AI는 판단을 대체하지 않습니다 — 이송 결정은 구급대원" }, async () => {
      await pace(1500);
      link.action(caseId, "final_approval", h.hospitalId, "paramedic");
      await link.waitFor(() => link.match[caseId]?.hospitals.find((x) => x.hospitalId === h.hospitalId)?.status === "confirmed", 15000, "이송 확정");
      ctx.confirmed.add(h.hospitalId);
    }, 2000);
    await dir.scene(overview, { step: `${ambName} · 이송 중`, ex: "transport", text: `${h.name}(으)로 이송 중`, sub: "관제 지도: 구급차 위치·요청 현황 실시간" }, async () => {}, 1500);
    await link.waitFor(() => link.phase?.caseId === caseId && link.phase.phase === "at_hospital", 90000, "병원 도착");
  };
  await confirmAndGo(approved);

  // 8. 도착 → 수용(또는 도착 후 수용 불가 → 재선택)
  let dest = approved;
  if (spec.arrival && spec.arrival.refuse) {
    dir.panes.hosp = `h-${dest.hospitalId}`;
    trail.push(`도착 후 수용 불가(${REASON_LABEL[spec.arrival.refuse] || spec.arrival.refuse})`);
    await dir.scene([`h-${dest.hospitalId}`], {
      step: `${dest.name} · 도착 후 수용 불가`, ex: "refuse",
      text: `${dest.name}: 도착했지만 수용 불가 — ${REASON_LABEL[spec.arrival.refuse] || spec.arrival.refuse}`,
      sub: "확정 해제 → 같은 환자 정보로 그 자리에서 재선택(재통화 없음)",
      tone: "reject",
    }, async () => {
      await pace(2000);
      link.action(caseId, "arrival_refused", dest.hospitalId, "hospital", spec.arrival.refuse);
      await link.waitFor(() => link.phase?.phase === "rerouting", 20000, "재선택 대기");
    }, 2500);
    // 이미 승인한 다른 병원이 있으면 그 병원으로 재선택(재통화 없음), 없으면 남은 병원들에 다시 응답을 받는다
    const refusedId = dest.hospitalId;
    const other = approvedAll.find(
      (h) => h.hospitalId !== refusedId && link.match[caseId]?.hospitals.find((x) => x.hospitalId === h.hospitalId)?.status === "approved",
    );
    approved = other || null;
    if (!approved) await respond(spec.arrival.then || [{ action: "approve" }]);
    if (!approved) throw new Error(`[${spec.apid}] 재선택할 승인 병원이 없습니다`);
    dest = approved;
    await dir.scene([amb], { step: `${ambName} · 재선택`, ex: "reselect", text: `그 자리에서 ${dest.name}(으)로 재선택`, sub: other ? "이미 수용 가능이라고 답한 다른 병원 — 다시 전화 돌리지 않는다" : "남은 후보 병원의 응답으로 재선택" }, async () => {}, 2000);
    await confirmAndGo(dest);
  }
  dir.panes.hosp = `h-${dest.hospitalId}`;
  await dir.scene([`h-${dest.hospitalId}`], { step: `${dest.name} · 환자 도착`, ex: "arrival", text: `${dest.name}: 환자 수용 완료`, sub: "모든 의사결정은 시각·해시로 기록(의사결정 블랙박스)" }, async () => {
    await pace(1800);
    link.action(caseId, "arrival_accepted", dest.hospitalId, "hospital");
    await link.waitFor(() => link.phase?.caseId !== caseId || link.phase.phase === "returning", 20000, "수용 반영");
  }, 2500);
  link.close();
  trail.push(`${dest.name} 수용 완료`);
  return { apid: spec.apid, name: ambName, dest: dest.name, trail };
}

async function main() {
  const args = process.argv.slice(2);
  const scenario = loadScenario(args[0] || "01");
  const record = args.includes("--record");
  const outDir = path.resolve(args[args.indexOf("--out") + 1] && args.includes("--out") ? args[args.indexOf("--out") + 1] : path.join(DEMO, "out"));
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await chromium.launch({
    channel: "chrome",
    headless: process.env.DEMO_HEADLESS === "1" || (record && DH && process.env.DEMO_HEADLESS !== "0"),
    args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required", "--window-size=1920,1120"],
  });
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 1,
    permissions: ["microphone"],
    ...(record && !DH ? { recordVideo: { dir: outDir, size: { width: 1920, height: 1080 } } } : {}),
  });
  const page = await context.newPage();
  let videoT0 = Date.now(); // 녹화는 페이지가 생길 때 시작된다 — 구간 시각의 기준
  await page.goto(`${DASH}/demo-stage.html`);
  let recorder = null;
  const outBase = path.join(outDir, `scenario_${scenario.id}${SUFFIX}`);
  if (record && DH) {
    const fpsArg = args.indexOf("--fps");
    recorder = await startRecorder(page, `${outBase}.mp4`, fpsArg >= 0 ? Number(args[fpsArg + 1]) || 60 : 60);
    videoT0 = recorder.t0Ms;
  }
  const dir = new Director(page);
  const marks = {};
  const ctx = { page, dir, scenario, confirmed: new Set(), mark: (k) => { if (!(k in marks)) marks[k] = +((Date.now() - videoT0) / 1000).toFixed(2); } };

  // 창 준비(소개 카드가 떠 있는 동안 뒤에서 대시보드를 띄운다)
  await dir.stage("setScenario", scenario.id, scenario.title);
  await dir.stage("intro", { no: scenario.id, title: scenario.title, lines: scenario.intro || [], tags: scenario.tags || [] }, true);
  const loads = [dir.stage("addPane", "map", { url: `${DASH}/map`, label: "관제 지도" })];
  for (const a of scenario.ambulances) {
    loads.push(dir.stage("addPane", `amb-${a.apid}`, { url: `${DASH}/ambulance?id=${a.apid}`, label: `구급차 · ${a.name || a.apid}` }));
    loads.push(dir.stage("addPane", `phone-${a.apid}`, { url: `${DASH}/phone?id=${a.apid}`, kind: "phone", label: `대원 휴대폰 · ${a.name || a.apid}`, visible: false }));
  }
  await Promise.all(loads);
  const home = CALM ? [`amb-${scenario.ambulances[0].apid}`] : ["map"];
  if (CALM) await dir.stage("configure", { thumbs: false, wide: !EXPLAIN });
  await dir.stage("focus", home);
  await sleep(Math.max(0, (scenario.introSec || (EXPLAIN || DH ? 5 : 8)) * 1000 - 1000));
  await dir.stage("intro", {}, false);
  await pace(800);

  const results = await Promise.all(scenario.ambulances.map((a, i) => runAmbulance(ctx, a, i)));
  if (DH) {
    await dir.stage("explain", null, []);
    await dir.stage("caption", "", "", "", "");
    await dir.stage("intro", { no: scenario.id, title: scenario.title, lines: results.length === 1 ? results[0].trail.map((t, i) => `${i + 1}. ${t}`) : results.map((r) => `${r.name}: ${r.trail.join(" → ")}`), tags: scenario.tags || [] }, true);
    await sleep(5000);
  } else {
    await dir.scene(home, { step: "시나리오 완료", text: results.map((r) => `${r.apid} → ${r.dest}`).join(" · "), sub: scenario.outro || "" }, async () => {}, 4000);
  }

  if (recorder) {
    await recorder.stop();
    fs.writeFileSync(`${outBase}.marks.json`, JSON.stringify(marks, null, 2));
    console.log(`녹화: ${outBase}.mp4`);
  }
  const video = page.video();
  await context.close();
  await browser.close();
  if (video) {
    const raw = await video.path();
    const out = path.join(outDir, `scenario_${scenario.id}${SUFFIX}.webm`);
    fs.renameSync(raw, out);
    fs.writeFileSync(out.replace(/\.webm$/, ".marks.json"), JSON.stringify(marks, null, 2));
    console.log(`녹화: ${out}`);
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
