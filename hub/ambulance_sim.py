"""구급차 출동 시뮬레이션 — 시연용 가짜 위치 (2026-10-01).

구급차 대시보드의 [이동] 버튼을 누를 때만 구급차가 움직인다. 상시 배회는 카카오 API를 계속
부르고, 실제 출동 순서(출동 → 현장 도착 → 병원 연락 → 이송 → 복귀)와도 안 맞아서 버렸다.
설계 문서: documents/1001v1_0134_구급차 출동 시뮬레이션 작업 계획.md

    idle ──[이동]──> dispatching ──도착──> on_scene ──이송 승인──> transporting ──도착──> at_hospital
     ▲                  ▲                    │ [현장 종료]       ▲                            │ 병원이 도착 결과를 고를 때까지 대기
     │                  │                    │                   └─ 이송 승인 ── rerouting ◀─┤ 수용 불가 (그 자리에서 재선택 대기)
     └── 기지 도착 ── returning <────────────┴───────────────── 15초 ◀── 수용 ───────────────┘
                        │ [이동] (복귀 중 재출동)          rerouting에서 [현장 종료]도 가능 → returning

- 환자 발생 위치: 기지에서 자동차로 5~12분 걸리는 지점 30~50곳을 처음 한 번 카카오 다중 목적지
  ETA로 골라 파일로 저장한다(이후 호출 0회). 키가 없으면 반경 3.5km 직선 지점으로 대신한다.
- 이동: 구간마다 도로 경로를 1번 받아 그 선을 따라 보간한다. 실제 소요 시간 ÷ SPEEDUP으로 빨리
  감되, 남은 ETA는 실제 도로 기준 값으로 보여준다(빨리 가는 건 연출일 뿐).
- 이 모듈은 위치 계산만 한다. hub 엔진·소켓·로그는 모른다 — app.py가 이벤트를 받아 처리한다.
  모든 위치는 시뮬레이션이라 밖으로 나가는 메시지에 `simulated: true`를 붙인다(app.py).

자체 검사: python ambulance_sim.py
"""
from __future__ import annotations

import json
import math
import os
import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from geo import haversine_km
from schema import GpsPoint

PHASES = ("idle", "dispatching", "on_scene", "transporting", "at_hospital", "rerouting", "returning")

#: 서울 범위(대략의 사각형 — 경기 일부 포함). 무작위 지점은 이 안에서만 뽑는다.
SEOUL_BBOX = (37.43, 37.70, 126.76, 127.18)  # (위도 최소, 최대, 경도 최소, 최대)

POOL_SAMPLE = 90              # 한 번에 뽑아 ETA를 물어볼 지점 수 (카카오 30곳씩 → 3회)
POOL_RADIUS_KM = 5.0          # 도심 평균 시속 25~30km면 10분 ≈ 4~5km
POOL_MIN_SEC, POOL_MAX_SEC = 300, 720   # 5~12분만 남긴다(너무 가까우면 출동 장면이 없다)
POOL_MIN_SIZE, POOL_MAX_SIZE = 30, 50
FALLBACK_RADIUS_KM = 3.5      # 카카오 키가 없을 때 직선 기준 반경
FALLBACK_SPEED_KMH = 30.0     # 도로 경로가 없을 때 직선 이동 속도

SPEEDUP = float(os.environ.get("HUB_SIM_SPEEDUP", "5"))
HOSPITAL_DWELL_SEC = float(os.environ.get("HUB_SIM_HOSPITAL_DWELL_SEC", "15"))
POOL_DIR = Path(__file__).resolve().parent / "data" / "sim"


# ── 경로 보간 ────────────────────────────────────────────────────────────────


def _bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlng = math.radians(b[1] - a[1])
    x = math.sin(dlng) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlng)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


@dataclass
class Trip:
    """경로 하나를 따라가는 이동. `duration_sec`는 실제 도로 소요 시간이고, 화면 이동은 SPEEDUP배 빠르다."""

    path: list[tuple[float, float]]
    duration_sec: float
    started_at: float
    speedup: float = SPEEDUP
    _cum: list[float] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if len(self.path) < 2:
            self.path = [self.path[0], self.path[0]]
        self._cum = [0.0]
        for a, b in zip(self.path, self.path[1:]):
            self._cum.append(self._cum[-1] + haversine_km(a[0], a[1], b[0], b[1]))

    def progress(self, now: float) -> float:
        if self.duration_sec <= 0:
            return 1.0
        return min(1.0, max(0.0, (now - self.started_at) * self.speedup / self.duration_sec))

    def done(self, now: float) -> bool:
        return self.progress(now) >= 1.0

    def remaining_sec(self, now: float) -> int:
        """실제 도로 기준 남은 시간(초). 받아 둔 경로의 남은 비율로 계산 — 카카오를 다시 안 부른다."""
        return int(round(self.duration_sec * (1.0 - self.progress(now))))

    def position(self, now: float) -> tuple[float, float, float]:
        """(위도, 경도, 진행 방향°)."""
        total = self._cum[-1]
        if total <= 0:
            lat, lng = self.path[-1]
            return lat, lng, 0.0
        target = total * self.progress(now)
        i = 1
        while i < len(self._cum) - 1 and self._cum[i] < target:
            i += 1
        a, b = self.path[i - 1], self.path[i]
        seg = self._cum[i] - self._cum[i - 1]
        t = 0.0 if seg <= 0 else (target - self._cum[i - 1]) / seg
        return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, _bearing(a, b)


def plan_trip(router, origin: GpsPoint, dest: GpsPoint, now: float) -> Trip:
    """도로 경로로 Trip을 만든다. 키가 없거나 실패하면 직선 + 기본 속도."""
    route = router.route(origin, dest) if router is not None else None
    if route and route.get("path"):
        return Trip([tuple(p) for p in route["path"]], float(route["durationSec"]), now)
    km = haversine_km(origin.lat, origin.lng, dest.lat, dest.lng)
    return Trip([(origin.lat, origin.lng), (dest.lat, dest.lng)], km / FALLBACK_SPEED_KMH * 3600.0, now)


# ── 환자 발생 위치 후보 ──────────────────────────────────────────────────────


def _in_seoul(lat: float, lng: float) -> bool:
    return SEOUL_BBOX[0] <= lat <= SEOUL_BBOX[1] and SEOUL_BBOX[2] <= lng <= SEOUL_BBOX[3]


def _sample_around(base: GpsPoint, radius_km: float, n: int, rng: random.Random) -> list[GpsPoint]:
    points: list[GpsPoint] = []
    for _ in range(n * 20):
        if len(points) >= n:
            break
        r = radius_km * math.sqrt(rng.random())  # 원 안에 고르게
        theta = rng.random() * 2 * math.pi
        lat = base.lat + (r / 111.0) * math.cos(theta)
        lng = base.lng + (r / (111.0 * math.cos(math.radians(base.lat)))) * math.sin(theta)
        if _in_seoul(lat, lng):
            points.append(GpsPoint(lat=lat, lng=lng))
    return points


def build_incident_pool(base: GpsPoint, router, rng: random.Random) -> list[dict]:
    """기지에서 5~12분 걸리는 지점 30~50곳. [{lat, lng, etaSec(없으면 None)}]"""
    if router is None:
        return [
            {"lat": p.lat, "lng": p.lng, "etaSec": None}
            for p in _sample_around(base, FALLBACK_RADIUS_KM, POOL_MIN_SIZE, rng)
        ]
    pool: list[dict] = []
    for radius in (POOL_RADIUS_KM, POOL_RADIUS_KM * 1.5):
        points = _sample_around(base, radius, POOL_SAMPLE, rng)
        etas = router.etas(base, {str(i): p for i, p in enumerate(points)})
        pool += [
            {"lat": points[int(k)].lat, "lng": points[int(k)].lng, "etaSec": sec}
            for k, (sec, _m) in etas.items()
            if POOL_MIN_SEC <= sec <= POOL_MAX_SEC
        ]
        if len(pool) >= POOL_MIN_SIZE:
            break
    rng.shuffle(pool)
    if not pool:  # 카카오가 전부 실패했으면 직선으로라도 돈다
        return build_incident_pool(base, None, rng)
    return pool[:POOL_MAX_SIZE]


def load_or_build_pool(apid: str, base: GpsPoint, router, rng: random.Random, pool_dir: Path = POOL_DIR) -> list[dict]:
    """기지 좌표가 같으면 저장해 둔 목록을 쓴다(카카오 호출 0회). 기지가 바뀌면 다시 만든다."""
    path = pool_dir / f"incident_points_{apid}.json"
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved.get("base") == [round(base.lat, 5), round(base.lng, 5)] and saved.get("points"):
            return saved["points"]
    except (OSError, ValueError):
        pass
    points = build_incident_pool(base, router, rng)
    pool_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"base": [round(base.lat, 5), round(base.lng, 5)], "points": points}, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  [시뮬레이션] {apid} 환자 발생 위치 후보 {len(points)}곳 생성 → {path.name}")
    return points


# ── 구급차 상태 ──────────────────────────────────────────────────────────────


@dataclass
class Unit:
    apid: str
    base: GpsPoint
    phase: str = "idle"
    gps: Optional[GpsPoint] = None
    heading: float = 0.0
    case_id: Optional[str] = None
    trip: Optional[Trip] = None
    incident: Optional[GpsPoint] = None
    hospital_id: Optional[str] = None
    hospital_gps: Optional[GpsPoint] = None
    # 병원 도착 뒤 복귀 시각. 병원이 "수용"을 누르기 전엔 None — 결과가 나올 때까지 병원에서 기다린다.
    dwell_until: Optional[float] = None
    last_incident: Optional[tuple[float, float]] = None

    def snapshot(self, now: float) -> dict:
        """밖으로 내보낼 상태(경로 포함). app.py가 type·simulated를 붙인다."""
        return {
            "apid": self.apid,
            "caseId": self.case_id,
            "phase": self.phase,
            "gps": self.gps.model_dump() if self.gps else None,
            "heading": round(self.heading, 1),
            "etaSec": self.trip.remaining_sec(now) if self.trip is not None else None,
            "path": [list(p) for p in self.trip.path] if self.trip is not None else None,
            "base": self.base.model_dump(),
            "incident": self.incident.model_dump() if self.incident else None,
            "hospitalId": self.hospital_id,
        }


class DispatchSim:
    """구급차별 출동 상태 머신. 스레드 안전(내부 락). 시간은 clock()으로 주입해 테스트한다."""

    def __init__(self, router=None, rng: random.Random | None = None,
                 clock: Callable[[], float] = time.time, pool_dir: Path = POOL_DIR) -> None:
        self._router = router
        self._rng = rng or random.Random()
        self._clock = clock
        self._pool_dir = pool_dir
        self._units: dict[str, Unit] = {}
        self._lock = threading.Lock()

    def ensure_unit(self, apid: str, base: GpsPoint) -> None:
        """구급차 등록(또는 기지 좌표 갱신). 대기 중이면 새 기지로 옮긴다."""
        with self._lock:
            unit = self._units.get(apid)
            if unit is None:
                self._units[apid] = Unit(apid=apid, base=base, gps=base)
                return
            unit.base = base
            if unit.phase == "idle":
                unit.gps = base

    def gps_for(self, apid: str) -> Optional[GpsPoint]:
        with self._lock:
            unit = self._units.get(apid)
            return unit.gps if unit else None

    def phase_of(self, apid: str) -> Optional[str]:
        with self._lock:
            unit = self._units.get(apid)
            return unit.phase if unit else None

    def state(self, apid: str) -> Optional[dict]:
        with self._lock:
            unit = self._units.get(apid)
            return unit.snapshot(self._clock()) if unit else None

    def case_of(self, apid: str) -> Optional[str]:
        with self._lock:
            unit = self._units.get(apid)
            return unit.case_id if unit else None

    def dispatch(self, apid: str, case_id: str) -> tuple[bool, str]:
        """[이동]: 대기 또는 복귀 중일 때만. 그 순간 위치에서 현장으로 간다."""
        with self._lock:
            unit = self._units.get(apid)
            if unit is None:
                return False, "unknown_ambulance"
            if unit.phase not in ("idle", "returning"):
                return False, f"phase_{unit.phase}"
            origin = unit.gps or unit.base
            base = unit.base
        pool = load_or_build_pool(apid, base, self._router, self._rng, self._pool_dir)  # 락 밖(카카오 호출)
        with self._lock:
            unit = self._units[apid]
            candidates = [p for p in pool if (p["lat"], p["lng"]) != unit.last_incident] or pool
            if unit.phase == "returning":
                # 기지 기준 목록이라 지금 위치에선 멀 수 있다 — 지금 위치에서 가까운 절반 안에서 고른다.
                candidates.sort(key=lambda p: haversine_km(origin.lat, origin.lng, p["lat"], p["lng"]))
                candidates = candidates[: max(1, len(candidates) // 2)]
            chosen = self._rng.choice(candidates)
            unit.last_incident = (chosen["lat"], chosen["lng"])
            incident = GpsPoint(lat=chosen["lat"], lng=chosen["lng"])
        trip = plan_trip(self._router, origin, incident, self._clock())
        with self._lock:
            unit = self._units[apid]
            unit.phase, unit.case_id, unit.incident, unit.trip = "dispatching", case_id, incident, trip
            unit.hospital_id = unit.hospital_gps = None
        return True, "ok"

    def scene_end(self, apid: str, case_id: str) -> bool:
        """[현장 종료]: 현장(또는 도착 후 수용 불가로 재선택 대기 중)에서 이송 없이 끝낸다 → 바로 기지로."""
        with self._lock:
            unit = self._units.get(apid)
            if unit is None or unit.phase not in ("on_scene", "rerouting") or unit.case_id != case_id:
                return False
            origin, base = unit.gps or unit.base, unit.base
        trip = plan_trip(self._router, origin, base, self._clock())
        with self._lock:
            unit = self._units[apid]
            unit.phase, unit.trip, unit.case_id, unit.incident = "returning", trip, None, None
        return True

    def on_confirmed(self, apid: str, case_id: str, hospital_id: str, hospital_gps: GpsPoint) -> bool:
        """이송 확정(재선택 포함): 그 순간 위치에서 확정 병원으로 간다."""
        with self._lock:
            unit = self._units.get(apid)
            if unit is None or unit.case_id != case_id or unit.phase not in ("on_scene", "transporting", "rerouting"):
                return False
            if unit.phase == "transporting" and unit.hospital_id == hospital_id:
                return False
            origin = unit.gps or unit.base
        trip = plan_trip(self._router, origin, hospital_gps, self._clock())
        with self._lock:
            unit = self._units[apid]
            unit.phase, unit.trip, unit.hospital_id, unit.hospital_gps = "transporting", trip, hospital_id, hospital_gps
        return True

    def on_arrival_result(self, apid: str, case_id: str, accepted: bool) -> bool:
        """병원 도착 뒤 병원의 결과: 수용이면 HOSPITAL_DWELL_SEC 뒤 기지로, 수용 불가면 그 자리에서
        재선택 대기(rerouting) — 승인한 다른 병원으로 이송 승인하면 다시 출발한다."""
        with self._lock:
            unit = self._units.get(apid)
            if unit is None or unit.phase != "at_hospital" or unit.case_id != case_id:
                return False
            if accepted:
                unit.dwell_until = self._clock() + HOSPITAL_DWELL_SEC
            else:
                unit.phase, unit.hospital_id, unit.hospital_gps, unit.dwell_until = "rerouting", None, None, None
            return True

    def tick(self) -> tuple[list[dict], list[dict]]:
        """위치를 한 칸 옮긴다. (상태가 바뀐 구급차들의 snapshot, 움직이는 구급차들의 snapshot)."""
        now = self._clock()
        changed: list[Unit] = []
        to_plan_return: list[Unit] = []
        with self._lock:
            moving = []
            for unit in self._units.values():
                if unit.trip is not None and unit.phase in ("dispatching", "transporting", "returning"):
                    lat, lng, heading = unit.trip.position(now)
                    unit.gps, unit.heading = GpsPoint(lat=lat, lng=lng), heading
                    moving.append(unit)
                    if unit.trip.done(now):
                        if unit.phase == "dispatching":
                            unit.phase, unit.trip, unit.gps = "on_scene", None, unit.incident
                        elif unit.phase == "transporting":
                            unit.phase, unit.trip = "at_hospital", None
                            unit.gps, unit.dwell_until = unit.hospital_gps, None
                        else:
                            unit.phase, unit.trip, unit.gps, unit.case_id = "idle", None, unit.base, None
                            unit.hospital_id = unit.hospital_gps = None
                        changed.append(unit)
                elif unit.phase == "at_hospital" and unit.dwell_until is not None and now >= unit.dwell_until:
                    to_plan_return.append(unit)
        for unit in to_plan_return:  # 락 밖에서 경로 조회
            trip = plan_trip(self._router, unit.gps or unit.base, unit.base, now)
            with self._lock:
                unit.phase, unit.trip, unit.case_id, unit.incident = "returning", trip, None, None
                unit.dwell_until = None
                changed.append(unit)
        with self._lock:
            return [u.snapshot(now) for u in changed], [u.snapshot(now) for u in moving if u not in changed]


# ── 자체 검사 ────────────────────────────────────────────────────────────────


def _selftest() -> None:
    import tempfile

    class _Clock:
        t = 1000.0

        def __call__(self) -> float:
            return self.t

    clock = _Clock()
    base = GpsPoint(lat=37.5665, lng=126.9780)  # 서울시청
    rng = random.Random(7)

    pool = build_incident_pool(base, None, rng)
    assert len(pool) == POOL_MIN_SIZE and all(_in_seoul(p["lat"], p["lng"]) for p in pool)
    assert all(haversine_km(base.lat, base.lng, p["lat"], p["lng"]) <= FALLBACK_RADIUS_KM + 0.01 for p in pool)

    trip = Trip([(37.0, 127.0), (37.0, 127.1)], duration_sec=600, started_at=0, speedup=5)
    assert abs(trip.position(60)[1] - 127.05) < 1e-9, "10분 경로를 5배속이면 60초에 절반"
    assert trip.remaining_sec(60) == 300 and trip.done(120)
    assert abs(trip.position(60)[2] - 90) < 1, "동쪽으로 가면 진행 방향 90°"

    with tempfile.TemporaryDirectory() as d:
        sim = DispatchSim(None, rng, clock, Path(d))
        sim.ensure_unit("A1", base)
        assert sim.dispatch("A1", "c1") == (True, "ok") and sim.phase_of("A1") == "dispatching"
        assert sim.dispatch("A1", "c2")[0] is False, "출동 중에는 다시 출동할 수 없다"
        assert not sim.on_confirmed("A1", "c1", "H1", base), "현장 도착 전엔 이송 확정을 받지 않는다"
        clock.t += 3600
        changed, _ = sim.tick()
        assert [c["phase"] for c in changed] == ["on_scene"]
        assert sim.gps_for("A1").model_dump() == sim.state("A1")["incident"], "현장 도착하면 현장 좌표에 선다"
        hospital = GpsPoint(lat=37.58, lng=126.99)
        assert sim.on_confirmed("A1", "c1", "H1", hospital) and sim.phase_of("A1") == "transporting"
        assert sim.on_confirmed("A1", "c1", "H2", GpsPoint(lat=37.57, lng=127.0)), "재선택하면 방향을 튼다"
        clock.t += 3600
        sim.tick()
        assert sim.phase_of("A1") == "at_hospital"
        clock.t += 3600
        sim.tick()
        assert sim.phase_of("A1") == "at_hospital", "도착 결과가 나올 때까지 병원에서 기다린다"
        assert sim.on_arrival_result("A1", "c1", accepted=False) and sim.phase_of("A1") == "rerouting"
        assert sim.on_confirmed("A1", "c1", "H3", GpsPoint(lat=37.56, lng=127.01)), "재선택 대기에서 다른 병원으로"
        clock.t += 3600
        sim.tick()
        assert sim.on_arrival_result("A1", "c1", accepted=True)
        clock.t += HOSPITAL_DWELL_SEC - 1
        sim.tick()
        assert sim.phase_of("A1") == "at_hospital", "수용 뒤 15초는 병원에 머문다"
        clock.t += 2
        sim.tick()
        assert sim.phase_of("A1") == "returning" and sim.case_of("A1") is None
        assert sim.dispatch("A1", "c3")[0], "복귀 중 재출동 허용"
        clock.t += 3600
        sim.tick()
        assert sim.scene_end("A1", "c3") and sim.phase_of("A1") == "returning", "[현장 종료] → 바로 복귀"
        clock.t += 3600
        sim.tick()
        assert sim.phase_of("A1") == "idle" and sim.gps_for("A1") == base
        assert (Path(d) / "incident_points_A1.json").exists(), "환자 발생 위치 후보는 파일로 저장한다"
    print("ambulance_sim 자체 검사 통과")


if __name__ == "__main__":
    _selftest()
