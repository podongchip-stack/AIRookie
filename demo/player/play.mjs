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
import { chromium } from "playwright-core";
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

function loadScenario(arg) {
  const file = fs.existsSync(arg) ? arg : path.join(DEMO, "scenarios", `${String(arg).padStart(2, "0")}.json`);
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

// ── 연출: 무대의 큰 화면·자막은 한 번에 한 장면만. 구급차 여러 대가 동시에 진행돼도 장면은 차례로 보인다 ──
class Director {
  constructor(page) {
    this.page = page;
    this.chain = Promise.resolve();
  }
  stage(fn, ...args) {
    return this.page.evaluate(([f, a]) => window.stage[f](...a), [fn, args]);
  }
  // 장면: 포커스·자막을 바꾸고 body를 실행한 뒤 holdMs만큼 보여 준다. 다른 장면은 이게 끝날 때까지 기다린다.
  scene(focus, caption, body = async () => {}, holdMs = 2500) {
    const run = async () => {
      await this.stage("focus", focus);
      await this.stage("caption", caption.step, caption.text, caption.sub || "", caption.tone || "");
      await body();
      await sleep(holdMs);
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
// {rank:n}: n번째, "called": 휴대폰으로 전화한 병원
function pickHospital(match, rule, responded, forApprove, calledId) {
  const list = match.hospitals;
  const ok = (h) => !responded.has(h.hospitalId) && h.status === "pending" && (!forApprove || h.unavailableReason !== "beds_full");
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
  const frame = (id) => page.frameLocator(`#frame-${id}`);
  await sleep((spec.startDelaySec || 0) * 1000);

  // 1. 출동
  await dir.scene(["map"], { step: `${ambName} · 출동`, text: `${spec.incident.label} — ${ambName} 출동`, sub: spec.incident.note || "" }, async () => {
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
    step: `${ambName} · 현장 도착`,
    text: `대원 휴대폰 — 가까운 병원 ${scene.hospitals.length}곳 중 ${target.name}에 전화`,
    sub: target.firstCallRecommended ? "첫 통화 추천: 빈 병상 확인 + 도착 시점 유효 확률(AI) 최고" : "도착 시간순(규칙 기반)",
  }, async () => {
    await sleep(1800);
    await frame(phone).locator("li button", { hasText: target.name }).first().dispatchEvent("click");
  }, 500);

  // 3. 통화 — 대본을 사람이 말하는 속도로(줄 길이에 비례) 자막에 띄운다
  await link.waitFor(() => link.call[caseId]?.state === "calling", 20000, "통화 연결");
  const lines = [];
  let t = 0.6;
  await dir.scene([phone, amb], {
    step: `${ambName} · 통화 중`,
    text: `${target.name} 응급실과 통화 — 실시간 자막`,
    sub: "시연용 대본을 자막으로 재생(음성 인식 대신) · 통화가 끝나면 이 내용이 실제 AI 구조화로 들어갑니다",
  }, async () => {
    for (const text of spec.script) {
      const dur = Math.max(1.8, text.length / 8);
      await sleep(dur * 1000);
      lines.push({ start: +t.toFixed(1), end: +(t + dur).toFixed(1), text });
      await link.utterance(caseId, t, t + dur, text);
      t += dur + 0.5;
      await sleep(500);
    }
    await sleep(800);
    await frame(phone).getByRole("button", { name: "통화 종료" }).first().dispatchEvent("click");
    await link.waitFor(() => link.call[caseId]?.state === "ended", 15000, "통화 종료 반영");
  }, 600);

  // 4. 실제 MF_BERT 구조화 — 걸린 시간을 그대로 보여 준다
  let structured;
  await dir.scene([amb], { step: `${ambName} · AI 구조화`, text: "통화 내용 구조화 중 — MF_BERT(KLUE RoBERTa-large)", sub: "KTAS·주 호소·활력징후·의식·처치 등 17개 항목", tone: "ai" }, async () => {
    structured = await structure(caseId, lines, t);
  }, 300);
  await dir.scene([amb], {
    step: `${ambName} · AI 구조화 완료 (${structured.extractSec.toFixed(2)}초)`,
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
    step: `${ambName} · 병원 동시 전달`,
    text: `존 안 후보 병원 ${match.hospitals.length}곳에 환자 정보를 한 번에 전달`,
    sub: "순차 전화(뺑뺑이) 대신 동시 전달 — 순위: 이동 시간·진료과·병상(규칙 기반)",
  }, async () => {}, 3000);

  // 6. 병원 응답들
  const responded = new Set();
  let approved = null;
  const respond = async (list) => {
    for (const r of list) {
      const m = link.match[caseId];
      const h = pickHospital(m, r.who || "top", responded, r.action === "approve", target.hospitalId);
      if (!h) continue;
      responded.add(h.hospitalId);
      const hp = `h-${h.hospitalId}`;
      await dir.stage("addPane", hp, { url: `${DASH}/hospital?id=${encodeURIComponent(h.hospitalId)}`, label: `병원 · ${h.name}` });
      await sleep(1800);
      const reject = r.action === "reject";
      await dir.scene([hp], {
        step: `${h.name} · ${reject ? "수용 불가" : "수용 가능"}`,
        text: reject ? `${h.name}: 수용 불가 — ${REASON_LABEL[r.reason] || r.reason || "사유 미기재"}` : `${h.name}: 수용 가능 (승인)`,
        sub: reject ? "거절 사유가 구급대 화면에 바로 표시 · 거절이 쌓이면 존 확장" : "병원 승인은 후보 등록 — 최종 확정은 구급대원",
        tone: reject ? "reject" : "",
      }, async () => {
        await sleep(r.delaySec != null ? r.delaySec * 1000 : 2200);
        link.action(caseId, reject ? "hospital_reject" : "hospital_approve", h.hospitalId, "hospital", reject ? r.reason : undefined);
        await link.waitFor(() => link.match[caseId]?.hospitals.find((x) => x.hospitalId === h.hospitalId)?.status !== "pending", 15000, "병원 응답 반영");
      }, 2500);
      if (!reject && !approved) approved = h;
      const zones = link.match[caseId].zoneActive?.length || 1;
      if (zones > (m.zoneActive?.length || 1)) {
        await dir.scene([amb], { step: `${ambName} · 존 확장`, text: `거절이 쌓여 요청 범위를 ${zones * 5}km까지 넓혔습니다`, sub: "거절 비율 40% 이상이면 다음 존으로 자동 확장(규칙 기반)", tone: "reject" }, async () => {}, 3000);
      }
    }
  };
  await respond(spec.responses || [{ action: "approve" }]);
  if (!approved) throw new Error(`[${spec.apid}] 승인한 병원이 없어 이송할 수 없습니다(시나리오 응답 확인)`);

  // 7. 이송 승인 → 이송 → 도착
  const confirmAndGo = async (h) => {
    await dir.scene([amb], { step: `${ambName} · 이송 승인`, text: `구급대원 최종 선택: ${h.name}`, sub: "AI는 판단을 대체하지 않습니다 — 이송 결정은 구급대원" }, async () => {
      await sleep(1500);
      link.action(caseId, "final_approval", h.hospitalId, "paramedic");
      await link.waitFor(() => link.match[caseId]?.hospitals.find((x) => x.hospitalId === h.hospitalId)?.status === "confirmed", 15000, "이송 확정");
    }, 2000);
    await dir.scene(["map"], { step: `${ambName} · 이송 중`, text: `${h.name}(으)로 이송 중`, sub: "관제 지도: 구급차 위치·요청 현황 실시간" }, async () => {}, 1500);
    await link.waitFor(() => link.phase?.caseId === caseId && link.phase.phase === "at_hospital", 90000, "병원 도착");
  };
  await confirmAndGo(approved);

  // 8. 도착 → 수용(또는 도착 후 수용 불가 → 재선택)
  let dest = approved;
  if (spec.arrival && spec.arrival.refuse) {
    await dir.scene([`h-${dest.hospitalId}`], {
      step: `${dest.name} · 도착 후 수용 불가`,
      text: `${dest.name}: 도착했지만 수용 불가 — ${REASON_LABEL[spec.arrival.refuse] || spec.arrival.refuse}`,
      sub: "확정 해제 → 같은 환자 정보로 그 자리에서 재선택(재통화 없음)",
      tone: "reject",
    }, async () => {
      await sleep(2000);
      link.action(caseId, "arrival_refused", dest.hospitalId, "hospital", spec.arrival.refuse);
      await link.waitFor(() => link.phase?.phase === "rerouting", 20000, "재선택 대기");
    }, 2500);
    approved = null;
    await respond(spec.arrival.then || [{ action: "approve" }]);
    if (!approved) throw new Error(`[${spec.apid}] 재선택할 승인 병원이 없습니다`);
    dest = approved;
    await confirmAndGo(dest);
  }
  await dir.scene([`h-${dest.hospitalId}`], { step: `${dest.name} · 환자 도착`, text: `${dest.name}: 환자 수용 완료`, sub: "모든 의사결정은 시각·해시로 기록(의사결정 블랙박스)" }, async () => {
    await sleep(1800);
    link.action(caseId, "arrival_accepted", dest.hospitalId, "hospital");
    await link.waitFor(() => link.phase?.caseId !== caseId || link.phase.phase === "returning", 20000, "수용 반영");
  }, 2500);
  link.close();
  return { apid: spec.apid, dest: dest.name };
}

async function main() {
  const args = process.argv.slice(2);
  const scenario = loadScenario(args[0] || "01");
  const record = args.includes("--record");
  const outDir = path.resolve(args[args.indexOf("--out") + 1] && args.includes("--out") ? args[args.indexOf("--out") + 1] : path.join(DEMO, "out"));
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await chromium.launch({
    channel: "chrome",
    headless: process.env.DEMO_HEADLESS === "1",
    args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required", "--window-size=1920,1120"],
  });
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 1,
    permissions: ["microphone"],
    ...(record ? { recordVideo: { dir: outDir, size: { width: 1920, height: 1080 } } } : {}),
  });
  const page = await context.newPage();
  await page.goto(`${DASH}/demo-stage.html`);
  const dir = new Director(page);
  const ctx = { page, dir, scenario };

  // 창 준비(소개 카드가 떠 있는 동안 뒤에서 대시보드를 띄운다)
  await dir.stage("setScenario", scenario.id, scenario.title);
  await dir.stage("intro", { no: scenario.id, title: scenario.title, lines: scenario.intro || [], tags: scenario.tags || [] }, true);
  const loads = [dir.stage("addPane", "map", { url: `${DASH}/map`, label: "관제 지도" })];
  for (const a of scenario.ambulances) {
    loads.push(dir.stage("addPane", `amb-${a.apid}`, { url: `${DASH}/ambulance?id=${a.apid}`, label: `구급차 · ${a.name || a.apid}` }));
    loads.push(dir.stage("addPane", `phone-${a.apid}`, { url: `${DASH}/phone?id=${a.apid}`, kind: "phone", label: `대원 휴대폰 · ${a.name || a.apid}`, visible: false }));
  }
  await Promise.all(loads);
  await dir.stage("focus", ["map"]);
  await sleep(Math.max(0, (scenario.introSec || 8) * 1000 - 1000));
  await dir.stage("intro", {}, false);
  await sleep(800);

  const results = await Promise.all(scenario.ambulances.map((a, i) => runAmbulance(ctx, a, i)));
  await dir.scene(["map"], { step: "시나리오 완료", text: results.map((r) => `${r.apid} → ${r.dest}`).join(" · "), sub: scenario.outro || "" }, async () => {}, 4000);

  const video = page.video();
  await context.close();
  await browser.close();
  if (video) {
    const raw = await video.path();
    const out = path.join(outDir, `scenario_${scenario.id}.webm`);
    fs.renameSync(raw, out);
    console.log(`녹화: ${out}`);
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
