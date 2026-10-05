// [demo 브랜치] 대량사고(MCI) 시나리오 진행기 — play.mjs가 시나리오에 "mci"가 있을 때 부른다. ⚠ develop에 병합하지 않는다.
//
// 진행: 구급대 여러 대 동시 출동 → 현장 트리아지(사상자마다 사건 하나, 구급대원 입력) → 존 안 후보 병원 동시 전달 →
// 병원 응답(연출) → hub 자동 분배(실제 plan_mci · mci_allocate: 중증 → 중등증 → 경증, 부하 페널티로 분산) → 동시 이송 → 수용.
// 실제인 것: hub 매칭·순위·분배 계산, 대시보드 화면. 연출인 것: 사상자 구성·트리아지 값, 병원의 승인·불가, 출동 위치.

// 카드 모드의 장면별 카드 · 역할 설명(play.mjs의 CARDS · ROLES에 덧붙인다 — 키는 mci_로 시작해 기존 장면과 겹치지 않는다)
const CONTROL_MAP = { css: "html", vh: 760 };
const CASE_LIST = { tag: "div", has: "진행 중인 사건 ", parents: 2, vh: 760 }; // 관제 지도 왼쪽 "진행 중인 사건 N건" 카드
const REQ_LIST = { any: [0, 1, 2, 3, 4, 5].map((nth) => ({ css: "article", nth })), vh: 1400 }; // 병원 대시보드의 요청 카드 묶음
const REQ_FIRST = { css: "article", nth: 0, vh: 1400 };
export const MCI_CARDS = {
  mci_dispatch: { map: CONTROL_MAP },
  mci_triage: { map: CASE_LIST },
  mci_broadcast: { hosp: REQ_LIST },
  mci_approve: { hosp: REQ_LIST },
  mci_reject: { hosp: REQ_FIRST },
  mci_responses: { map: CONTROL_MAP },
  mci_allocate: { map: CASE_LIST },
  mci_dest: { hosp: REQ_LIST },
  mci_transport: { map: CONTROL_MAP },
  mci_arrival: { map: CONTROL_MAP },
};
export const MCI_ROLES = {
  mci_dispatch: { map: ["관제 지도", "인근 119안전센터 구급대가 동시에 현장으로 간다"] },
  mci_triage: { map: ["진행 중인 사건", "사상자마다 사건 하나, 중증도별로 정렬된다"] },
  mci_broadcast: { hosp: ["병원 대시보드", "사상자 전원의 요청이 한 번에 도착한다"] },
  mci_approve: { hosp: ["병원 대시보드", "병원이 받을 수 있는 환자를 승인한다"] },
  mci_reject: { hosp: ["병원 대시보드", "불가와 사유를 고르면 그 병원은 배정에서 빠진다"] },
  mci_responses: { map: ["병원 응답", "승인한 병원이 늘어나면 분배할 곳이 생긴다"] },
  mci_allocate: { map: ["중증도 기준 자동 분배", "중증부터 순위 1위 병원에, 몰리면 다음 병원으로"] },
  mci_dest: { hosp: ["배정된 병원", "이 병원으로 배정된 환자만 남아 도착을 기다린다"] },
  mci_transport: { map: ["동시 이송", "구급차들이 서로 다른 병원으로 흩어진다"] },
  mci_arrival: { map: ["모두 도착", "사상자마다 배정된 병원에 도착했다"] },
};

const SEV = { high: "중증", medium: "중등증", low: "경증" };
const LEVEL_SHORT = { 권역응급의료센터: "권역센터", 지역응급의료센터: "지역센터", 지역응급의료기관: "지역기관" };

// 관제 쪽 접속(보이지 않는 관제 탭) — 분배 미리 보기(mci_preview → mci_plan)와 분배 확정(mci_allocate → mci_allocated)
class MonitorLink {
  constructor(http) { this.http = http; this.plan = null; this.allocated = null; this.overview = null; this.waiters = []; }
  open() {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(this.http.replace(/^http/, "ws") + "/ws/dashboard");
      this.ws = ws;
      ws.onopen = () => { ws.send(JSON.stringify({ type: "identify", role: "monitor", id: "demo-mci" })); resolve(); };
      ws.onerror = (e) => reject(e);
      ws.onmessage = (ev) => {
        let m;
        try { m = JSON.parse(ev.data); } catch { return; }
        if (m.type === "mci_plan") this.plan = m;
        else if (m.type === "mci_allocated") this.allocated = m;
        else if (m.type === "map_overview") this.overview = m;
        this.waiters = this.waiters.filter((w) => !w());
      };
    });
  }
  waitFor(cond, ms, what) {
    return new Promise((resolve, reject) => {
      const check = () => { const v = cond(); if (v) { clearTimeout(t); resolve(v); return true; } return false; };
      const t = setTimeout(() => { this.waiters = this.waiters.filter((w) => w !== check); reject(new Error(`[관제] ${what} 대기 시간 초과`)); }, ms);
      if (!check()) this.waiters.push(check);
    });
  }
  send(obj) { this.ws.send(JSON.stringify({ timestamp: new Date().toISOString(), ...obj })); }
  close() { this.ws?.close(); }
}

// 사상자 한 명의 현장 트리아지 요약(구급대원 입력 — 시연 콘솔의 현장 확인과 같은 형식)을 hub에 보낸다
async function sendTriage(hub, caseId, c) {
  const body = {
    caseId,
    transcript: { raw_text: c.transcript, filtered_text: c.transcript },
    summary: {
      patient: c.patient, mechanism: c.mechanism, symptoms: c.symptoms, treatment: c.treatment || [],
      severity_tag: c.severity, required_department: c.department, ktas_level: c.ktas, consciousness: c.consciousness || "A",
      onset: "10분 전", chief_complaint: c.label, vitals: [{ sequence: 1, ...c.vitals }],
    },
    source: "ai",
    model_used: { stt: "scenario-triage", llm: "scenario-triage" },
  };
  const r = await fetch(hub + "/voice/summary", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`hub /voice/summary ${r.status}: ${await r.text()}`);
}

export async function runMci(ctx, h) {
  const { page, dir, scenario } = ctx;
  const { HubLink, DASH, HUB, sleep, pace, REASON_LABEL } = h;
  const mci = scenario.mci;
  const units = mci.units; // [{apid, name, casualty:{...}}]
  const tag = Date.now().toString(36);
  const links = [];
  for (const u of units) {
    const link = new HubLink(HUB, u.apid);
    await link.open();
    links.push({ u, link, caseId: `demo-${scenario.id}-${u.apid}-${tag}` });
  }
  const mon = new MonitorLink(HUB);
  await mon.open();
  const caseIds = links.map((l) => l.caseId);
  // 불가 장면은 첫 사상자의 카드로 고정한다(불가를 누르면 카드 순서가 바뀌어 nth로는 다른 카드로 튄다)
  MCI_CARDS.mci_reject.hosp = { css: "article", has: `${units[0].name.split(" ")[0]}119안전센터`, vh: 1400 };
  const short = (n) => String(n).replace(/학교법인\s*/g, "").replace(/의료법인\S*\s*/g, "").replace(/\(.*?\)/g, "").trim();
  const shortAmb = (n) => n.replace(/119안전센터\s*/, " ");
  const caseOf = (id) => links.find((l) => l.caseId === id);

  // 응답할 병원 대시보드는 미리 띄워 둔다(장면이 바뀔 때 빈 화면이 비치지 않게). 병원 id는 매칭 결과에서 이름으로 찾는다
  const hospPane = async (hid, name) => {
    const id = `h-${hid}`;
    await dir.stage("addPane", id, { url: `${DASH}/hospital?id=${encodeURIComponent(hid)}`, label: `병원 · ${name}`, vh: 1400 }); // 요청 카드 6장이 스크롤 없이 다 들어가는 높이
    return id;
  };

  // 1. 동시 출동
  await dir.scene(["map"], { step: `${mci.siteLabel} · 대량사고 접수`, ex: "mci_dispatch", text: `${mci.siteLabel} 다중 추돌 · 인근 119안전센터 구급대 ${units.length}대 동시 출동` }, async () => {
    for (const [i, { u, link, caseId }] of links.entries()) {
      const c = u.casualty;
      // 같은 현장이되 사상자마다 수십 m 간격(시연 콘솔 대량사고와 같은 방식) — 지도 위 구급차가 겹치지 않게
      const target = { lat: mci.site.lat + ((i % 3) - 1) * 0.0007, lng: mci.site.lng + (Math.floor(i / 3) - 0.5) * 0.0009 };
      link.send({ type: "dispatch", apid: u.apid, caseId, target, targetMode: "map", reportedSymptom: "교통사고 다중 추돌", reportedSeverity: c.severity });
      await sleep(200);
    }
    await Promise.all(links.map(({ link, caseId }) => link.waitFor(() => link.phase?.caseId === caseId && link.phase.phase === "on_scene", 90000, "현장 도착")));
  }, 3400);

  // 2. 현장 트리아지 → 사상자마다 존 안 후보 병원에 동시 전달
  const counts = { high: 0, medium: 0, low: 0 };
  for (const { u } of links) counts[u.casualty.severity]++;
  await dir.scene(["map"], {
    step: `${mci.siteLabel} · 현장 트리아지`, ex: "mci_triage",
    text: `사상자 ${units.length}명 분류: 중증 ${counts.high} · 중등증 ${counts.medium} · 경증 ${counts.low}명, 사상자마다 인근 병원에 동시 요청`,
  }, async () => {
    for (const { u, caseId } of links) { await sendTriage(HUB, caseId, u.casualty); await sleep(150); }
    await Promise.all(links.map(({ link, caseId }) => link.waitFor(() => link.match[caseId], 60000, "매칭 결과")));
  }, 5000);

  // 병원 이름 → id (모든 사건의 후보를 합쳐서)
  const byName = new Map();
  for (const { link, caseId } of links) for (const x of link.match[caseId].hospitals) byName.set(x.name, x);
  const find = (needle) => [...byName.values()].find((x) => x.name.includes(needle));
  // 불가는 첫 사상자(가장 위급, 카드 맨 위)를 마지막에 보낸다 — 화면의 그 카드가 끝까지 맨 위에 머물러 확대 영역이 흔들리지 않는다
  const respond = async (hosp, action, reason) => {
    for (const { link, caseId } of action === "hospital_reject" ? [...links].reverse() : links) {
      const x = link.match[caseId].hospitals.find((y) => y.hospitalId === hosp.hospitalId);
      if (!x || x.status !== "pending") continue;
      if (action === "hospital_approve" && x.unavailableReason === "beds_full") continue;
      link.action(caseId, action, hosp.hospitalId, "hospital", reason);
      await sleep(260);
    }
    await Promise.all(links.map(({ link, caseId }) => link.waitFor(() => {
      const y = link.match[caseId]?.hospitals.find((z) => z.hospitalId === hosp.hospitalId);
      return !y || y.status !== "pending" || y.unavailableReason;
    }, 15000, "병원 응답 반영")));
  };

  // 3. 첫 병원 대시보드: 사상자 전원의 요청이 한 번에 → 승인
  const first = find(mci.first.hospital);
  if (!first) throw new Error(`후보에 ${mci.first.hospital}이(가) 없습니다`);
  const firstPane = await hospPane(first.hospitalId, first.name);
  await pace(1200);
  dir.panes.hosp = firstPane;
  const nReq = links.filter(({ link, caseId }) => link.match[caseId].hospitals.some((x) => x.hospitalId === first.hospitalId)).length;
  await dir.scene([firstPane], { step: `${first.name} · 요청 도착`, ex: "mci_broadcast", text: `${first.name}: 사상자 ${nReq}명의 수용 요청이 한 번에 도착` }, async () => {}, 4200);
  await dir.scene([firstPane], { step: `${first.name} · 수용 가능`, ex: "mci_approve", text: `${first.name}: 수용 가능 (승인) · 최종 배정은 hub가 사상자 전체를 보고 정한다` }, async () => {
    await pace(800);
    await respond(first, "hospital_approve");
  }, 3600);

  // 4. 불가 병원
  if (mci.reject) {
    const rej = find(mci.reject.hospital);
    if (rej) {
      const rp = await hospPane(rej.hospitalId, rej.name);
      await pace(1200);
      dir.panes.hosp = rp;
      await dir.scene([rp], { step: `${rej.name} · 수용 불가`, ex: "mci_reject", tone: "reject", text: `${rej.name}: 수용 불가 · ${REASON_LABEL[mci.reject.reason] || mci.reject.reason}` }, async () => {
        await pace(1200);
        await respond(rej, "hospital_reject", mci.reject.reason);
      }, 2400);
    }
  }

  // 5. 나머지 병원 응답(관제 지도에서)
  const others = (mci.approve || []).map(find).filter(Boolean);
  await dir.scene(["map"], { step: "병원 응답", ex: "mci_responses", text: `${others.map((x) => short(x.name)).join(" · ")}도 수용 가능 (승인)` }, async () => {
    for (const x of others) { await respond(x, "hospital_approve"); await pace(500); }
  }, 3600);

  // 6. hub 자동 분배 — 미리 보기(mci_plan)를 받아 자막에 그대로 쓰고, 같은 계획으로 확정(mci_allocate)
  mon.send({ type: "mci_preview", caseIds });
  const plan = (await mon.waitFor(() => mon.plan, 15000, "분배 계획")).plan;
  const planBy = new Map(plan.map((p) => [p.caseId, p]));
  const hospitals = [...new Set(plan.filter((p) => p.hospitalId).map((p) => p.hospitalId))];
  const highTo = plan.filter((p) => p.severityTag === "high" && p.hospitalId).map((p) => short(p.hospitalName));
  await dir.scene(["map"], {
    step: "hub 자동 분배 · 중증도 기준", ex: "mci_allocate",
    text: `분배 확정: 사상자 ${plan.filter((p) => p.hospitalId).length}명을 병원 ${hospitals.length}곳에, 중증은 ${[...new Set(highTo)].join(" · ")}`,
  }, async () => {
    await pace(300); // 확대가 끝나자마자 확정 — 승인 상태(분배 전)가 자막과 어긋나 보이는 시간을 줄인다
    mon.send({ type: "mci_allocate", caseIds });
    await mon.waitFor(() => mon.allocated, 20000, "분배 확정");
    await Promise.all(links.map(({ link, caseId }) => link.waitFor(() => !planBy.get(caseId)?.hospitalId || link.match[caseId]?.hospitals.some((x) => x.status === "confirmed"), 15000, "이송 확정")));
  }, 4200);

  // 동시 이송(관제 지도) — 확정되자마자 출발한다
  await dir.scene(["map"], { step: "동시 이송", ex: "mci_transport", text: `구급차 ${links.length}대가 병원 ${hospitals.length}곳으로 나뉘어 동시에 이송` }, async () => {
    await Promise.all(links.filter(({ caseId }) => planBy.get(caseId)?.hospitalId).map(({ link, caseId }) =>
      link.waitFor(() => link.phase?.caseId === caseId && link.phase.phase === "at_hospital", 90000, "병원 도착")));
  }, 3400);

  // 7. 배정된 병원 대시보드: 그 병원으로 확정된 환자만 남는다(중증을 받은 병원 → 가장 많이 받은 다른 병원)
  const destHigh = plan.find((p) => p.severityTag === "high" && p.hospitalId);
  const otherDest = hospitals.filter((hid) => hid !== destHigh?.hospitalId)
    .sort((x, y) => plan.filter((p) => p.hospitalId === y).length - plan.filter((p) => p.hospitalId === x).length)[0];
  for (const hid of [destHigh?.hospitalId, otherDest].filter(Boolean)) {
    const mine = plan.filter((p) => p.hospitalId === hid);
    const name = mine[0].hospitalName;
    const dp = await hospPane(hid, name);
    await pace(1000);
    dir.panes.hosp = dp;
    const desc = mine.map((p) => `${SEV[p.severityTag]} ${caseOf(p.caseId).u.casualty.label}`).join(" · ");
    await dir.scene([dp], { step: `${name} · 환자 도착`, ex: "mci_dest", text: `${name}: ${desc} 도착` }, async () => {}, 4000);
  }

  // 8. 모두 도착 — 수용 완료(arrival_accepted)는 보내지 않는다: 사건이 닫힌 직후 복귀 경로를 잡는 몇 초 동안 관제 지도에
  // "병원 요청 전" 임시 사건이 비쳐 헷갈리므로, 도착 상태를 보여 주고 요약 카드로 넘어간다
  await dir.scene(["map"], { step: "모두 도착", ex: "mci_arrival", text: `사상자 ${plan.filter((p) => p.hospitalId).length}명 모두 도착, 병원 ${hospitals.length}곳에 나뉘어 수용 대기` }, async () => {}, 4200);

  for (const { link } of links) link.close();
  mon.close();

  // 요약 카드: 병원별로 누가 갔는지(실제 분배 결과 그대로)
  const lines = hospitals.map((hid) => {
    const mine = plan.filter((p) => p.hospitalId === hid);
    const level = LEVEL_SHORT[byName.get(mine[0].hospitalName)?.emergencyLevel] || "";
    const who = ["high", "medium", "low"].map((s) => { const n = mine.filter((p) => p.severityTag === s).length; return n ? `${SEV[s]} ${n}` : ""; }).filter(Boolean).join(" · ");
    return `${short(mine[0].hospitalName)}${level ? ` (${level})` : ""} ← ${who}`;
  });
  const skipped = plan.filter((p) => !p.hospitalId).length;
  if (skipped) lines.push(`배정 보류 ${skipped}명`);
  const most = Math.max(...hospitals.map((hid) => plan.filter((p) => p.hospitalId === hid).length));
  lines.push(`사상자 ${plan.length - skipped}명을 병원 ${hospitals.length}곳에 분산 · 한 병원 최대 ${most}명`);
  console.log("[대량사고] 분배 결과", JSON.stringify(plan.map((p) => ({ sev: p.severityTag, to: p.hospitalName, load: p.loadPenaltyMin }))));
  return { lines, tags: [] };
}
