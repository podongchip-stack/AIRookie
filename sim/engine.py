"""대량사고 이송 시뮬레이션 엔진 — 이벤트 기반, 표준 라이브러리만 사용.

세 팔(arm)은 같은 세계(병원·병상·구급차·환자)에서 **정보 전달 방식만** 다르다:

- nearest    : 병상 정보 없이 전원 최근접 응급실로. 만실은 도착해서야 알고 재이송.
- sequential : 가까운 순으로 전화(통화당 t_call 분). 자리 있는 곳에 예약 후 출발.
- goldenlink : 존 후보 전체 동시 요청(t_broadcast 분). 가용 병원 중 최단 이동 병원
               배정 + 예약 — hub가 자기 배정을 전부 보므로(TTL 오버레이에 해당)
               구급차끼리 같은 병상을 두 번 세지 않는다.

sequential/goldenlink는 예약이 성립해 도착 거절이 없다(병원이 자기 수용+예약
상태를 알고 승인한다는 가정). nearest만 도착 후 만실을 알게 되어 재이송이 생긴다.

시간 단위는 분. random은 환자 중증도 배치와 적재 시간의 미세 잡음에만 쓴다.
"""
from __future__ import annotations

import heapq
import random
from dataclasses import dataclass, field

from data_load import Hospital

ARMS = ("nearest", "sequential", "goldenlink")

SEVERITIES = ("immediate", "urgent", "delayed")


@dataclass
class SimParams:
    n_patients: int = 120
    n_ambulances: int = 30
    speed_kmh: float = 40.0        # 심야 서울 평균
    road_factor: float = 1.3       # 직선거리 -> 도로거리 보정
    t_load_min: float = 3.0        # 현장 적재
    t_handover_min: float = 8.0    # 병원 인계(정상 수용)
    t_transfer_min: float = 5.0    # 재이송 결정·재적재(만실 도착 시 추가)
    t_call_min: float = 2.5        # 전화 1통 (sequential)
    t_broadcast_min: float = 1.0   # 동시 요청 1회 (goldenlink)
    severity_mix: tuple[float, float, float] = (0.3, 0.4, 0.3)  # immediate/urgent/delayed
    # v2 자리: 신고가 처음부터 틀렸을 확률(infosurv로 대체 예정). v1은 0.
    info_error_rate: float = 0.0


@dataclass
class HospitalState:
    hospital: Hospital
    admitted: int = 0
    reserved: int = 0
    arrivals: int = 0              # 이 병원 앞에 도착한 환자 수(재이송 출발 포함 전 기준)
    overload_arrivals: int = 0     # 만실인데 도착한 환자 수 (nearest의 재이송 원인)
    timeline: list[tuple[float, int, int]] = field(default_factory=list)  # (t, arrivals, admitted)

    @property
    def free_for_promise(self) -> int:
        return self.hospital.capacity - self.admitted - self.reserved

    @property
    def free_actual(self) -> int:
        return self.hospital.capacity - self.admitted

    def record(self, t: float) -> None:
        self.timeline.append((round(t, 2), self.arrivals, self.admitted))


@dataclass
class PatientResult:
    index: int
    severity: str
    t_pickup: float        # 현장에서 구급차에 실린 시각
    t_admitted: float      # 최종 수용 병원 도착(인계 시작) 시각
    hospital: str          # 최종 수용 병원 hpid
    calls: int             # 쓴 전화 수 (sequential)
    hops: int              # 재이송 횟수 (nearest)


@dataclass
class Trip:
    """구급차 이동 구간 하나 — 재생 화면의 점 애니메이션용.

    kind: out(현장→병원) / transfer(병원→병원 재이송) / return(병원→현장 복귀)
    """
    amb: int
    t0: float
    t1: float
    from_hpid: str | None   # None = 사고 현장
    to_hpid: str | None
    kind: str


@dataclass
class RunResult:
    arm: str
    seed: int
    patients: list[PatientResult]
    hospitals: list[HospitalState]
    finished_at: float
    trips: list[Trip] = field(default_factory=list)


def travel_min(a_lat: float, a_lng: float, h: Hospital, p: SimParams, from_scene_distance: float | None = None) -> float:
    from data_load import haversine_km
    distance = from_scene_distance if from_scene_distance is not None else haversine_km(a_lat, a_lng, h.lat, h.lng)
    return distance * p.road_factor / p.speed_kmh * 60.0


def _assign_severities(n: int, mix: tuple[float, float, float], rng: random.Random) -> list[str]:
    counts = [round(n * mix[0]), round(n * mix[1])]
    counts.append(n - sum(counts))
    severities = (["immediate"] * counts[0]) + (["urgent"] * counts[1]) + (["delayed"] * counts[2])
    rng.shuffle(severities)
    # 이송 순서는 중증 우선 (현장 triage) — 같은 등급 안에서는 무작위 순서 유지
    order = {"immediate": 0, "urgent": 1, "delayed": 2}
    severities.sort(key=lambda s: order[s])
    return severities


def simulate(arm: str, hospitals: list[Hospital], params: SimParams, seed: int) -> RunResult:
    if arm not in ARMS:
        raise ValueError(f"모르는 arm: {arm}")
    rng = random.Random(seed)
    states = [HospitalState(h) for h in hospitals]
    by_travel_from_scene = sorted(
        range(len(states)), key=lambda i: travel_min(0, 0, states[i].hospital, params, states[i].hospital.distance_km)
    )
    severities = _assign_severities(params.n_patients, params.severity_mix, rng)
    patients: list[PatientResult] = []
    trips: list[Trip] = []
    next_patient = 0

    # 이벤트 큐: (시각, 일련번호, 구급차 번호) — 구급차가 현장에서 다음 환자를 실을 수 있는 시각
    queue: list[tuple[float, int, int]] = []
    counter = 0
    for amb in range(params.n_ambulances):
        heapq.heappush(queue, (0.0, counter, amb))
        counter += 1

    # nearest·sequential 전용 — 구급차별 "직접 겪은 만실" 기억(목격 또는 전화 거절).
    # 구급차끼리 공유는 없다는 게 두 팔의 정의지만, 같은 구급차가 같은 만실 병원에
    # 계속 가거나 계속 전화하는 것은 비현실적이라 개인 경험만큼은 반영한다 —
    # 베이스라인을 불리하게 과장하지 않기 위한 보정 (비교는 보수적으로).
    known_full: list[set[int]] = [set() for _ in range(params.n_ambulances)]

    def choose(t: float, amb: int) -> tuple[int | None, float, int]:
        """팔별 병원 선택. 반환: (병원 index 또는 None, 결정에 쓴 분, 전화 수)."""
        if arm == "nearest":
            for i in by_travel_from_scene:
                if i not in known_full[amb]:
                    return i, 0.0, 0
            return by_travel_from_scene[0], 0.0, 0
        if arm == "sequential":
            calls = 0
            for i in by_travel_from_scene:
                if i in known_full[amb]:
                    continue  # 이번 사고에서 이미 거절당한 병원 — 다시 걸지 않는다
                calls += 1
                if states[i].free_for_promise > 0:
                    return i, calls * params.t_call_min, calls
                known_full[amb].add(i)
            return None, calls * params.t_call_min, calls
        # goldenlink: 동시 요청 — 가용(수용+예약 반영) 병원 중 최단 이동
        candidates = [i for i in by_travel_from_scene if states[i].free_for_promise > 0]
        if not candidates:
            return None, params.t_broadcast_min, 0
        return candidates[0], params.t_broadcast_min, 0

    while queue:
        t, _, amb = heapq.heappop(queue)
        if next_patient >= params.n_patients:
            continue  # 남은 환자가 없으면 이 구급차는 종료
        severity = severities[next_patient]
        patient_index = next_patient
        next_patient += 1

        t_pickup = t
        t = t + params.t_load_min
        target, decision_min, calls = choose(t, amb)
        t += decision_min
        if target is None:
            # 반경 안 전 병원 만실 — 가장 여유가 덜 나쁜 곳(최근접)으로 보내고 과밀로 기록.
            # 기본 파라미터(N <= 총병상)에서는 거의 발생하지 않는다 — README 한계 참고.
            target = by_travel_from_scene[0]
        else:
            if arm in ("sequential", "goldenlink"):
                states[target].reserved += 1

        hops = 0
        current = target
        t_arrive = t + travel_min(0, 0, states[current].hospital, params, states[current].hospital.distance_km)
        trips.append(Trip(amb, round(t, 2), round(t_arrive, 2), None, states[current].hospital.hpid, "out"))
        while True:
            state = states[current]
            state.arrivals += 1
            if arm == "nearest" and state.free_actual <= 0:
                # 만실 도착 — 재이송: 이 병원에서 가장 가까운, 실제 자리가 있는 병원으로
                state.overload_arrivals += 1
                state.record(t_arrive)
                known_full[amb].add(current)
                hops += 1
                options = sorted(
                    (i for i in range(len(states)) if states[i].free_actual > 0 and i != current),
                    key=lambda i: travel_min(state.hospital.lat, state.hospital.lng, states[i].hospital, params),
                )
                if not options:
                    # 반경 안 어디에도 자리가 없음 — 그 자리에서 수용(과밀 수용)으로 처리
                    state.admitted += 1
                    state.record(t_arrive)
                    break
                nxt = options[0]
                t_depart = t_arrive + params.t_transfer_min
                t_arrive = t_depart + travel_min(
                    state.hospital.lat, state.hospital.lng, states[nxt].hospital, params
                )
                trips.append(Trip(amb, round(t_depart, 2), round(t_arrive, 2),
                                  state.hospital.hpid, states[nxt].hospital.hpid, "transfer"))
                current = nxt
                continue
            # 수용
            if arm in ("sequential", "goldenlink") and hops == 0:
                state.reserved -= 1
            state.admitted += 1
            state.record(t_arrive)
            break

        patients.append(PatientResult(
            index=patient_index, severity=severity, t_pickup=round(t_pickup, 2),
            t_admitted=round(t_arrive, 2), hospital=states[current].hospital.hpid,
            calls=calls, hops=hops,
        ))

        # 인계 후 현장 복귀
        t_depart = t_arrive + params.t_handover_min
        t_free = t_depart + travel_min(
            0, 0, states[current].hospital, params, states[current].hospital.distance_km
        )
        if next_patient < params.n_patients:  # 남은 환자가 있을 때만 복귀 구간을 그린다
            trips.append(Trip(amb, round(t_depart, 2), round(t_free, 2),
                              states[current].hospital.hpid, None, "return"))
        counter += 1
        heapq.heappush(queue, (t_free, counter, amb))

    finished = max((p.t_admitted for p in patients), default=0.0)
    return RunResult(arm=arm, seed=seed, patients=patients, hospitals=states,
                     finished_at=round(finished, 2), trips=trips)


# ── 요약 지표 ────────────────────────────────────────────────────────────────


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo), 2)


def summarize(run: RunResult) -> dict:
    durations = [p.t_admitted - p.t_pickup for p in run.patients]
    admit_times = [p.t_admitted for p in run.patients]
    loads = [
        (s.hospital.hpid, s.hospital.name, s.hospital.capacity, s.arrivals, s.admitted, s.overload_arrivals)
        for s in run.hospitals
    ]
    with_capacity = [s for s in run.hospitals if s.hospital.capacity > 0]
    max_load = max((s.arrivals / s.hospital.capacity for s in with_capacity), default=0.0)
    return {
        "arm": run.arm,
        "seed": run.seed,
        "medianTransportMin": percentile(durations, 0.5),
        "p90TransportMin": percentile(durations, 0.9),
        "medianAdmitAtMin": percentile(admit_times, 0.5),
        "finishedAtMin": run.finished_at,
        "maxLoadRatio": round(max_load, 2),
        "transfers": sum(p.hops for p in run.patients),
        "rejectedCalls": sum(max(p.calls - 1, 0) for p in run.patients),
        "hospitals": loads,
    }
