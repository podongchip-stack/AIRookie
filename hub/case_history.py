"""관제 지도용 사건 기록(2026-10-04) — 사건 번호·시작 시각·증상·병원별 응답 시각·진행 과정, 오늘 종료된 사건.

관제 지도 개편(사건 목록·선택 사건의 병원별 응답 시각·지난 사건 모달·진행 과정 타임라인)에 필요한 값은
매칭 결과(HubMatchResult)에 없다 — 결과는 "지금 상태"만 담고 언제 무엇이 바뀌었는지는 담지 않는다.
그래서 hub가 매칭 결과를 보낼 때마다 직전 결과와 비교해(diff) 사건 이벤트를 만든다. 승인 처리·존 확장
코드 곳곳에 기록 호출을 박지 않아도 되고, 결과가 바뀌는 모든 경로(승인·거절·재선택·존 확장·60초
재계산)가 한 곳으로 모인다. 규칙 기반(source: "rule") — 판단은 하지 않고 기록만 한다.

환자 상세(통화 전문·활력징후)는 담지 않는다 — 관제 지도와 같은 원칙. 증상은 신고 1차 증상이나
구조화된 주 호소 한 줄뿐이다.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

KST = timezone(timedelta(hours=9))
HISTORY_LIMIT = 50

# 사건이 닫힌 이유 → (결과, 타임라인 문구)
CLOSE_REASONS: dict[str, tuple[str, str]] = {
    "arrival_accepted": ("done", "이송 완료 · {hospital} 도착(환자 수용)"),
    "scene_ended": ("cancel", "현장 종료 — 이송 없이 상황 취소"),
    "sim_reset": ("cancel", "시연 초기화로 종료"),
    "unresolved_timeout": ("cancel", "확정 없이 오래 방치돼 자동 종료"),
    "retention_expired": ("cancel", "이송 확정 뒤 도착 결과 없이 정리"),
    "hub_restart_sim_reset": ("cancel", "hub 재시작으로 종료"),
}


# 병원이 고른 거절 사유 코드 → 한글(대시보드 lib/rejection.ts와 같은 어휘)
REASON_LABELS = {
    "UNSPECIFIED": "사유 없음", "NO_WARD": "병동 없음", "NO_DEPARTMENT": "해당 진료과 없음",
    "NO_EQUIPMENT": "필요 장비 없음", "ON_CALL_MISMATCH": "당직과 불일치", "NIGHT_UNAVAILABLE": "야간 진료 불가",
    "BEDS_FULL": "병상 만실", "OR_OCCUPIED": "수술실 사용 중", "STAFF_BUSY": "인력 부족",
    "SEVERITY_EXCEEDED": "중증도 초과", "AGE_LIMIT": "연령 제한",
}


def _iso(at: datetime) -> str:
    return at.astimezone(timezone.utc).isoformat(timespec="seconds")


class CaseTracker:
    def __init__(self, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 archive_path: Optional[Path] = None) -> None:
        self._clock = clock
        self._archive_path = archive_path  # 종료 사건을 날짜 제한 없이 쌓는 JSONL — None이면 안 쌓는다(테스트 기본)
        self._lock = threading.Lock()
        self._meta: dict[str, dict] = {}          # caseId -> {num, startedAt, symptom, severity, apid, ambulanceName}
        self._events: dict[str, list[dict]] = {}  # caseId -> [{t, kind, text}]
        self._last: dict[str, dict] = {}          # caseId -> {hospitals: {hid: (status, name, rejected)}, zone, ...}
        self._responded: dict[str, dict[str, str]] = {}  # caseId -> {hospitalId: respondedAt}
        self._expand_cause: dict[str, str] = {}  # caseId -> 다음 확장 이벤트에 붙일 이유(시간 경과·건너뛰기)
        self._history: list[dict] = []
        self._num_day = ""
        self._num = 0

    # ── 시작·메타 ────────────────────────────────────────────────────────────

    def _next_num_locked(self, at: datetime) -> int:
        day = at.astimezone(KST).date().isoformat()
        if day != self._num_day:  # 사건 번호는 하루 단위(KST)로 1번부터
            self._num_day, self._num = day, 0
        self._num += 1
        return self._num

    def start(self, case_id: str, apid: Optional[str] = None, ambulance_name: Optional[str] = None,
              severity: Optional[str] = None, symptom: Optional[str] = None,
              event_text: Optional[str] = None) -> dict:
        """사건을 처음 볼 때 번호·시작 시각을 매긴다(출동·통화 시작·첫 매칭 중 가장 이른 것). 이미 있으면 빈
        값(증상·중증도·이름)만 채운다."""
        now = self._clock()
        with self._lock:
            meta = self._meta.get(case_id)
            if meta is None:
                meta = {"caseId": case_id, "num": self._next_num_locked(now), "startedAt": _iso(now),
                        "symptom": None, "severity": None, "apid": None, "ambulanceName": None}
                self._meta[case_id] = meta
                self._events[case_id] = []
                if event_text:
                    self._events[case_id].append({"t": _iso(now), "kind": "p", "text": event_text})
            for key, value in (("apid", apid), ("ambulanceName", ambulance_name),
                               ("severity", severity), ("symptom", symptom)):
                if value and not meta.get(key):
                    meta[key] = value
            return dict(meta)

    def meta(self, case_id: str) -> Optional[dict]:
        with self._lock:
            meta = self._meta.get(case_id)
            return dict(meta) if meta else None

    def responded(self, case_id: str) -> dict[str, str]:
        with self._lock:
            return dict(self._responded.get(case_id) or {})

    def events(self, case_id: str) -> list[dict]:
        with self._lock:
            return [dict(e) for e in self._events.get(case_id) or []]

    def open_case_ids(self) -> list[str]:
        with self._lock:
            return list(self._meta)

    def note_expand_cause(self, case_id: str, cause: str) -> None:
        with self._lock:
            self._expand_cause[case_id] = cause

    def event(self, case_id: str, kind: str, text: str) -> None:
        with self._lock:
            if case_id in self._events:
                self._events[case_id].append({"t": _iso(self._clock()), "kind": kind, "text": text})

    # ── 매칭 결과 비교 → 이벤트 ──────────────────────────────────────────────

    def observe(self, result: dict) -> None:
        """매칭 결과(HubMatchResult dump)가 나갈 때마다 부른다. 직전과 비교해 이벤트·응답 시각을 남긴다."""
        case_id = result.get("caseId")
        if not case_id:
            return
        patient = result.get("patientInfo") or {}
        symptom = patient.get("chiefComplaint") or patient.get("expectedDiagnosis")
        self.start(case_id, result.get("apid"), result.get("ambulanceName"), patient.get("severityTag"), symptom)
        now = _iso(self._clock())
        hospitals = {
            h["hospitalId"]: (h.get("status", "pending"), h.get("name", h["hospitalId"]), h.get("rejectReason"))
            for h in result.get("hospitals") or []
        }
        zone = max(result.get("zoneActive") or [1])
        with self._lock:
            events = self._events.setdefault(case_id, [])
            responded = self._responded.setdefault(case_id, {})
            last = self._last.get(case_id)
            if last is None:
                events.append({"t": now, "kind": "s", "text": f"수용 요청 시작 · {len(hospitals)}곳"})
            else:
                added = [hid for hid in hospitals if hid not in last["hospitals"]]
                if zone > last["zone"] and added:
                    cause = self._expand_cause.pop(case_id, None)
                    events.append({"t": now, "kind": "x",
                                   "text": (f"{cause} · " if cause else "") + f"존 1~{zone}로 요청 범위 확장 · +{len(added)}곳"})
                first_reject_logged = any(e["kind"] == "r" for e in events)
                for hid, (status, name, reason) in hospitals.items():
                    before = last["hospitals"].get(hid, ("pending", name, None))[0]
                    if status == before:
                        continue
                    if status in ("approved", "rejected", "confirmed"):
                        responded[hid] = now
                    if status == "approved" and before == "pending":
                        events.append({"t": now, "kind": "a", "text": f"{name} 수용 승인"})
                    elif status == "approved" and before == "confirmed":
                        events.append({"t": now, "kind": "c", "text": f"{name} 이송 확정 해제(다른 병원 재선택)"})
                    elif status == "confirmed":
                        events.append({"t": now, "kind": "t", "text": f"{name} 이송 확정 · 이송 시작"})
                    elif status == "rejected" and before == "confirmed":
                        events.append({"t": now, "kind": "r", "text": f"{name} 도착 후 수용 불가"})
                    elif status == "rejected" and not first_reject_logged:
                        # 거절은 첫 건만 타임라인에 — 존 확장 이벤트와 집계 수(수용 불가 N곳)가 나머지를 말한다
                        label = REASON_LABELS.get(reason, reason) if reason else None
                        events.append({"t": now, "kind": "r",
                                       "text": f"{name} 수용 불가" + (f" · {label}" if label else "")})
                        first_reject_logged = True
            self._last[case_id] = {"hospitals": hospitals, "zone": zone}

    # ── 종료 → 지난 사건 ─────────────────────────────────────────────────────

    def close(self, case_id: str, reason: str) -> Optional[dict]:
        """사건이 끝났을 때 부른다. 지난 사건 목록에 요약을 남기고 진행 중 기록은 지운다."""
        now = self._clock()
        with self._lock:
            meta = self._meta.pop(case_id, None)
            events = self._events.pop(case_id, [])
            last = self._last.pop(case_id, None)
            self._responded.pop(case_id, None)
            self._expand_cause.pop(case_id, None)
            if meta is None:
                return None
            hospitals = (last or {}).get("hospitals", {})
            final = next((name for status, name, _ in hospitals.values() if status == "confirmed"), None)
            result, text = CLOSE_REASONS.get(reason, ("cancel", f"사건 종료({reason})"))
            events.append({"t": _iso(now), "kind": "d" if result == "done" else "c",
                           "text": text.format(hospital=final or "병원")})
            item = {
                **meta,
                "endedAt": _iso(now),
                "requested": len(hospitals),
                "rejected": sum(1 for status, _, _ in hospitals.values() if status == "rejected"),
                "zone": (last or {}).get("zone", 0),
                "hospital": final,
                "result": result,
                "reason": reason,
                "events": events,
            }
            self._history.insert(0, item)
            self._archive(item)
            today = now.astimezone(KST).date()
            self._history = [
                h for h in self._history
                if datetime.fromisoformat(h["endedAt"]).astimezone(KST).date() == today
            ][:HISTORY_LIMIT]
            return dict(item)

    def _archive(self, item: dict) -> None:
        """종료 사건 한 건을 영구 기록에 덧붙인다(2026-11-01). 실패해도 사건 종료는 막지 않는다."""
        if self._archive_path is None:
            return
        try:
            self._archive_path.parent.mkdir(parents=True, exist_ok=True)
            with self._archive_path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(item, ensure_ascii=False) + "\n")
        except OSError as exc:
            print(f"  [사건 이력] 영구 기록 실패: {exc}")

    def history(self) -> list[dict]:
        """오늘(KST) 종료된 사건, 최근 종료 순."""
        today = self._clock().astimezone(KST).date()
        with self._lock:
            return [dict(h) for h in self._history
                    if datetime.fromisoformat(h["endedAt"]).astimezone(KST).date() == today]

    # ── 상태 저장·복구(hub 재시작에도 오늘 기록이 남게) ─────────────────────────

    def export_state(self) -> dict:
        with self._lock:
            return {"history": list(self._history), "numDay": self._num_day, "num": self._num,
                    "meta": dict(self._meta), "events": dict(self._events)}

    def import_state(self, state: dict) -> None:
        with self._lock:
            self._history = list(state.get("history") or [])
            self._num_day = state.get("numDay") or ""
            self._num = int(state.get("num") or 0)
            self._meta = dict(state.get("meta") or {})
            self._events = {k: list(v) for k, v in (state.get("events") or {}).items()}


def query_archive(path: Path, start: str, end: str, q: str = "", result: str = "all", limit: int = 200) -> dict:
    """영구 기록에서 종료일(KST, 양끝 포함)·검색어·결과로 걸러 최근 종료 순으로 돌려준다.
    stats는 limit과 무관하게 조건 전체 기준 — 대시보드 lib/case-archive.ts의 computeStats와 같은 식."""
    items: list[dict] = []
    if path.exists():
        for line in path.open(encoding="utf-8"):
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    q = q.strip().lower()
    hit = []
    for c in items:
        day = datetime.fromisoformat(c["endedAt"]).astimezone(KST).date().isoformat()
        if not (start <= day <= end) or (result != "all" and c.get("result") != result):
            continue
        if q and not any(q in str(c.get(k) or "").lower() for k in ("symptom", "ambulanceName", "hospital")):
            continue
        hit.append(c)
    hit.sort(key=lambda c: c["endedAt"], reverse=True)
    n = len(hit)
    requested = sum(c["requested"] for c in hit)
    dur = sum((datetime.fromisoformat(c["endedAt"]) - datetime.fromisoformat(c["startedAt"])).total_seconds() for c in hit)
    stats = {
        "total": n,
        "done": sum(1 for c in hit if c.get("result") == "done"),
        "cancel": sum(1 for c in hit if c.get("result") == "cancel"),
        "avgDurationSec": dur / n if n else 0,
        "avgRejected": sum(c["rejected"] for c in hit) / n if n else 0,
        "rejectRate": sum(c["rejected"] for c in hit) / requested if requested else 0,
        "zoneExpanded": sum(1 for c in hit if c.get("zone", 0) >= 2),
    }
    return {"cases": hit[:limit], "total": n, "stats": stats}


def _selftest() -> None:
    t = [datetime(2026, 10, 4, 10, 0, tzinfo=timezone.utc)]
    tracker = CaseTracker(clock=lambda: t[0])

    def advance(sec: int) -> None:
        t[0] = t[0] + timedelta(seconds=sec)

    tracker.start("c1", "SEL0160", "회현 구급 1", "high", "흉통", event_text="출동 · 신고: 흉통")
    base = {"caseId": "c1", "apid": "SEL0160", "ambulanceName": "회현 구급 1", "zoneActive": [1],
            "patientInfo": {"severityTag": "high", "chiefComplaint": "흉통(심장성)"},
            "hospitals": [{"hospitalId": "H1", "name": "갑병원", "status": "pending"},
                          {"hospitalId": "H2", "name": "을병원", "status": "pending"}]}
    advance(60); tracker.observe(base)
    advance(30); tracker.observe({**base, "hospitals": [{"hospitalId": "H1", "name": "갑병원", "status": "rejected", "rejectReason": "병상 없음"},
                                                        {"hospitalId": "H2", "name": "을병원", "status": "pending"}]})
    advance(30); tracker.observe({**base, "zoneActive": [1, 2], "hospitals": [
        {"hospitalId": "H1", "name": "갑병원", "status": "rejected"}, {"hospitalId": "H2", "name": "을병원", "status": "rejected"},
        {"hospitalId": "H3", "name": "병병원", "status": "pending"}]})
    advance(30); tracker.observe({**base, "zoneActive": [1, 2], "hospitals": [
        {"hospitalId": "H1", "name": "갑병원", "status": "rejected"}, {"hospitalId": "H2", "name": "을병원", "status": "rejected"},
        {"hospitalId": "H3", "name": "병병원", "status": "confirmed"}]})
    meta = tracker.meta("c1")
    assert meta["num"] == 1 and meta["symptom"] == "흉통", meta
    assert set(tracker.responded("c1")) == {"H1", "H2", "H3"}
    advance(300); item = tracker.close("c1", "arrival_accepted")
    kinds = [e["kind"] for e in item["events"]]
    assert kinds == ["p", "s", "r", "x", "t", "d"], kinds
    assert item["requested"] == 3 and item["rejected"] == 2 and item["zone"] == 2 and item["hospital"] == "병병원"
    assert item["result"] == "done" and tracker.history()[0]["caseId"] == "c1"
    assert tracker.meta("c1") is None
    tracker.start("c2")
    assert tracker.meta("c2")["num"] == 2
    import tempfile
    arch = Path(tempfile.mkdtemp()) / "a.jsonl"
    t2 = CaseTracker(clock=lambda: t[0], archive_path=arch)
    t2.start("c9", "SEL0001", "역삼 구급 1", "high", "흉통")
    t2.close("c9", "arrival_accepted")
    day = t[0].astimezone(KST).date().isoformat()
    r = query_archive(arch, day, day)
    assert r["total"] == 1 and r["stats"]["done"] == 1 and r["cases"][0]["caseId"] == "c9", r
    assert query_archive(arch, day, day, q="없는말")["total"] == 0
    assert query_archive(arch, "2000-01-01", "2000-01-02")["total"] == 0
    print("case_history 자체 검사 통과:", " → ".join(e["text"] for e in item["events"]))


if __name__ == "__main__":
    _selftest()
