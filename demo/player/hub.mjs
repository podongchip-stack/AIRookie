// [demo 브랜치] 시연용 hub 접속 — 구급차 한 대의 "보이지 않는 탭"처럼 붙어서 그 구급차의 상태를 받고, 대시보드
// 사용자가 보내는 것과 같은 메시지(출동·승인·거절·이송 승인·수용)를 대신 보낸다. ⚠ develop에 병합하지 않는다.

export class HubLink {
  constructor(hubHttp, apid) {
    this.http = hubHttp;
    this.apid = apid;
    this.phase = null; // ambulance_phase 최신
    this.scene = {}; // caseId -> scene_candidates
    this.match = {}; // caseId -> match_result
    this.call = {}; // caseId -> call_status
    this.waiters = [];
  }

  open() {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(this.http.replace(/^http/, "ws") + "/ws/dashboard");
      this.ws = ws;
      ws.onopen = () => {
        ws.send(JSON.stringify({ type: "identify", role: "ambulance", id: this.apid }));
        resolve();
      };
      ws.onerror = (e) => reject(e);
      ws.onmessage = (ev) => {
        let m;
        try {
          m = JSON.parse(ev.data);
        } catch {
          return;
        }
        if (m.type === "ambulance_phase" || m.type === "ambulance_position") {
          if (m.apid === this.apid) this.phase = { ...this.phase, ...m };
        } else if (m.type === "scene_candidates") this.scene[m.caseId] = m;
        else if (m.type === "match_result" || (m.caseId && m.hospitals && !m.type)) this.match[m.caseId] = m;
        else if (m.type === "call_status") this.call[m.caseId] = m;
        this.waiters = this.waiters.filter((w) => !w.check());
      };
    });
  }

  // 조건이 참이 될 때까지 기다린다(메시지가 올 때마다 다시 본다)
  waitFor(cond, timeoutMs = 60000, what = "조건") {
    return new Promise((resolve, reject) => {
      const w = {
        check: () => {
          const v = cond();
          if (v) {
            clearTimeout(w.timer);
            resolve(v);
            return true;
          }
          return false;
        },
      };
      if (w.check()) return;
      w.timer = setTimeout(() => {
        this.waiters = this.waiters.filter((x) => x !== w);
        reject(new Error(`[${this.apid}] ${what} 대기 시간 초과`));
      }, timeoutMs);
      this.waiters.push(w);
    });
  }

  send(obj) {
    this.ws.send(JSON.stringify({ timestamp: new Date().toISOString(), ...obj }));
  }

  dispatch(caseId, target) {
    this.send({ type: "dispatch", apid: this.apid, caseId, target, targetMode: "map" });
  }

  action(caseId, action, hospitalId, actor, reason) {
    this.send({ caseId, action, hospital_id: hospitalId, actor, ...(reason ? { reason } : {}) });
  }

  async utterance(caseId, start, end, text) {
    await fetch(this.http + "/voice/utterance", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ apid: this.apid, caseId, start, end, text }),
    });
  }

  async summary(message) {
    const r = await fetch(this.http + "/voice/summary", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(message),
    });
    if (!r.ok) throw new Error(`hub /voice/summary ${r.status}: ${await r.text()}`);
  }

  close() {
    this.ws?.close();
  }
}
