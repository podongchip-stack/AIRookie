// 정보 전달 연출 전용. 병원 선정은 hub가 수행하며 이 모듈은 전달 대상·시간·곡선만 다룬다.
(function (root) {
  const DURATION = 1800, HOLD = 9000, STEPS = 40;
  function eligible(c, h) {
    const k = c.ktasLevel;
    const suitability = h.ktasSuitability;
    if (suitability && Number.isFinite(k)) {
      const hospitalKtas = suitability.hospitalKtas;
      if (suitability.eligible === false || (Number.isFinite(hospitalKtas) && hospitalKtas !== k)) return false;
      if (suitability.effectiveCapacity < suitability.requiredCapacity) return false;
    }
    return !c.pre && !(c.hospitals || []).some(x => x.status === 'confirmed') &&
      (c.zoneActive || []).includes(h.zone) && ['pending', 'approved'].includes(h.status) &&
      !h.excluded && !h.notSelected && !h.unavailableReason &&
      !(h.bedCountUnknown === false && h.availableBedCount === 0);
  }
  function curve(a, b, progress) {
    const p = Math.max(0, Math.min(1, progress));
    const dx = b[0] - a[0], dy = b[1] - a[1];
    const lift = Math.min(120, Math.hypot(dx, dy) * 2200);
    const count = Math.max(2, Math.ceil(STEPS * p) + 1);
    return Array.from({ length: count }, (_, i) => {
      const t = p * i / (count - 1), bend = Math.sin(Math.PI * t) * .045;
      return [a[0] + dx * t - dy * bend, a[1] + dy * t + dx * bend,
        a[2] + (b[2] - a[2]) * t + Math.sin(Math.PI * t) * lift];
    });
  }
  class Tracker {
    constructor() { this.cases = new Map(); }
    sync(cases, now) {
      const alive = new Set(cases.map(c => c.caseId));
      for (const id of this.cases.keys()) if (!alive.has(id)) this.cases.delete(id);
      for (const c of cases) {
        let state = this.cases.get(c.caseId);
        if (!state) { state = new Map(); this.cases.set(c.caseId, state); }
        const targets = (c.hospitals || []).filter(h => eligible(c, h));
        const ids = new Set(targets.map(h => h.hospitalId));
        for (const id of state.keys()) if (!ids.has(id)) state.delete(id);
        targets.forEach((h, i) => {
          if (!state.has(h.hospitalId)) state.set(h.hospitalId, { start: now + i * 95 });
        });
      }
    }
    frame(c, origin, targetOf, now, reducedMotion) {
      const states = this.cases.get(c.caseId), out = [];
      if (!states || !origin) return out;
      for (const h of c.hospitals || []) {
        const state = states.get(h.hospitalId), end = targetOf(h.hospitalId);
        if (!state || !end || !eligible(c, h)) continue;
        const age = now - state.start;
        if (age < 0) continue;
        const progress = reducedMotion ? 1 : Math.min(1, age / DURATION);
        const settled = age >= DURATION;
        // 고정된 가는 줄은 병원 응답을 기다리는 동안 유지. 발광·도착 파동은 한 번만 재생한다.
        out.push({ hospitalId: h.hospitalId, age, path: curve(origin, end, progress), end,
          progress, settled, active: !reducedMotion && age < HOLD,
          arrival: !reducedMotion && settled ? Math.min(1, (age - DURATION) / 1100) : null });
      }
      return out;
    }
  }
  function packetProgress(age) {
    const progress = age / DURATION;
    return progress > 0 && progress < 1 ? progress : null;
  }
  const api = { Tracker, eligible, curve, DURATION, packetProgress };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.GoldenTransmission = api;
})(typeof window !== 'undefined' ? window : globalThis);
