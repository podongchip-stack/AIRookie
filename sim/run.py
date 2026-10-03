"""대량사고 시뮬레이션 실행기 — 세 팔 × 시드 반복, 결과 JSON + 자가완결 HTML 리포트.

    python run.py                          # 기본 장면: itaewon (환자 120, 구급차 30, 시드 20)
    python run.py --scene ilsan            # 2019 일산 여성병원 화재 조건 + 실측 분포 참조선
    python run.py --patients 150 --seeds 30
    python run.py --sweep                  # 상수 민감도(전화 시간·환자 수) 표만 출력

출력: out/results_<장면>.json, out/mci_report_<장면>.html (브라우저로 열면 됨 — 외부 의존 없음)
"""
from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import replace
from pathlib import Path

from data_load import SCENES, build_world
from engine import ARMS, SimParams, percentile, simulate, summarize

OUT_DIR = Path(__file__).resolve().parent / "out"


def run_all(params: SimParams, scene: dict, snapshot_date: str, target_hhmm: str,
            radius_km: float, seeds: int) -> dict:
    snapshot_ts, hospitals = build_world(snapshot_date, target_hhmm, radius_km,
                                         scene_lat=scene["lat"], scene_lng=scene["lng"])
    arms: dict[str, dict] = {}
    for arm in ARMS:
        runs = [summarize(simulate(arm, hospitals, params, seed)) for seed in range(seeds)]
        medians = [r["medianTransportMin"] for r in runs]
        p90s = [r["p90TransportMin"] for r in runs]
        max_loads = [r["maxLoadRatio"] for r in runs]
        finished = [r["finishedAtMin"] for r in runs]
        # 병원별 도착 수는 시드 평균으로 집계 (차트용)
        n_hosp = len(runs[0]["hospitals"])
        hospital_rows = []
        for i in range(n_hosp):
            hpid, name, capacity, *_ = runs[0]["hospitals"][i]
            hospital_rows.append({
                "hpid": hpid, "name": name, "capacity": capacity,
                "arrivals": round(statistics.mean(r["hospitals"][i][3] for r in runs), 1),
                "admitted": round(statistics.mean(r["hospitals"][i][4] for r in runs), 1),
                "overload": round(statistics.mean(r["hospitals"][i][5] for r in runs), 1),
            })
        arms[arm] = {
            "medianTransportMin": {"mean": round(statistics.mean(medians), 1), "min": min(medians), "max": max(medians)},
            "p90TransportMin": {"mean": round(statistics.mean(p90s), 1), "min": min(p90s), "max": max(p90s)},
            "maxLoadRatio": {"mean": round(statistics.mean(max_loads), 2), "min": min(max_loads), "max": max(max_loads)},
            "finishedAtMin": {"mean": round(statistics.mean(finished), 1), "min": min(finished), "max": max(finished)},
            "transfersMean": round(statistics.mean(r["transfers"] for r in runs), 1),
            "rejectedCallsMean": round(statistics.mean(r["rejectedCalls"] for r in runs), 1),
            "hospitals": hospital_rows,
            # 대표 시드(0)의 환자별 이송 시간 — CDF 차트용
            "transportTimesSeed0": sorted(
                round(p["t_admitted"] - p["t_pickup"], 1) if isinstance(p, dict) else 0.0
                for p in []
            ),
        }
    # CDF용 환자별 시간은 요약이 아니라 원시 run에서 다시 뽑는다 (대표 시드 0)
    for arm in ARMS:
        run0 = simulate(arm, hospitals, params, seed=0)
        arms[arm]["transportTimesSeed0"] = sorted(round(p.t_admitted - p.t_pickup, 1) for p in run0.patients)
        arms[arm]["timelineSeed0"] = [
            {"hpid": s.hospital.hpid, "events": s.timeline} for s in run0.hospitals
        ]
        # 구급차 이동 구간 — 재생 화면의 점 애니메이션용. hpid=None은 사고 현장.
        arms[arm]["tripsSeed0"] = [
            {"amb": tr.amb, "t0": tr.t0, "t1": tr.t1, "from": tr.from_hpid, "to": tr.to_hpid, "kind": tr.kind}
            for tr in run0.trips
        ]
    reference = None
    if scene.get("reference") and Path(scene["reference"]).exists():
        reference = json.loads(Path(scene["reference"]).read_text(encoding="utf-8"))
    return {
        "reference": reference,
        "scenario": {
            "scene": {"lat": scene["lat"], "lng": scene["lng"], "label": scene["label"]},
            "snapshotTs": snapshot_ts,
            "radiusKm": radius_km,
            "nHospitals": len(hospitals),
            "totalBeds": sum(h.capacity for h in hospitals),
            "patients": params.n_patients,
            "ambulances": params.n_ambulances,
            "seeds": seeds,
            "params": {
                "tCallMin": params.t_call_min, "tBroadcastMin": params.t_broadcast_min,
                "tLoadMin": params.t_load_min, "tHandoverMin": params.t_handover_min,
                "tTransferMin": params.t_transfer_min, "speedKmh": params.speed_kmh,
                "roadFactor": params.road_factor, "severityMix": list(params.severity_mix),
            },
        },
        "hospitals": [
            {"hpid": h.hpid, "name": h.name, "lat": h.lat, "lng": h.lng,
             "capacity": h.capacity, "distanceKm": h.distance_km}
            for h in hospitals
        ],
        "arms": arms,
    }


def sweep(base: SimParams, scene: dict, snapshot_date: str, target_hhmm: str,
          radius_km: float, seeds: int) -> None:
    """상수 민감도 — 결론(순서)이 가정에 얼마나 민감한지 표로 보여준다."""
    print(f"{'변주':<28}{'nearest 중앙':>13}{'sequential 중앙':>16}{'goldenlink 중앙':>16}{'쏠림(nearest)':>14}")
    variants: list[tuple[str, SimParams]] = [("기본", base)]
    for t_call in (1.5, 4.0):
        variants.append((f"전화 {t_call}분/통", replace(base, t_call_min=t_call)))
    for n in (60, 180):
        variants.append((f"환자 {n}명", replace(base, n_patients=n)))
    for m in (15, 50):
        variants.append((f"구급차 {m}대", replace(base, n_ambulances=m)))
    snapshot_ts, hospitals = build_world(snapshot_date, target_hhmm, radius_km,
                                         scene_lat=scene["lat"], scene_lng=scene["lng"])
    for label, params in variants:
        rows = {}
        for arm in ARMS:
            runs = [summarize(simulate(arm, hospitals, params, seed)) for seed in range(seeds)]
            rows[arm] = (
                statistics.mean(r["medianTransportMin"] for r in runs),
                statistics.mean(r["maxLoadRatio"] for r in runs),
            )
        print(f"{label:<28}{rows['nearest'][0]:>11.1f}분{rows['sequential'][0]:>14.1f}분"
              f"{rows['goldenlink'][0]:>14.1f}분{rows['nearest'][1]:>13.1f}x")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", choices=sorted(SCENES), default="itaewon",
                        help="장면 — 좌표·스냅샷 시각·사상자 구성 기본값이 장면을 따른다")
    parser.add_argument("--patients", type=int, default=None)
    parser.add_argument("--ambulances", type=int, default=30)
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--snapshot-date", default=None)
    parser.add_argument("--time", default=None, help="스냅샷 목표 시각 HH:MM (기본: 장면의 사건 발생 시각)")
    parser.add_argument("--radius", type=float, default=None)
    parser.add_argument("--sweep", action="store_true", help="상수 민감도 표만 출력")
    args = parser.parse_args()

    scene = SCENES[args.scene]
    patients = args.patients if args.patients is not None else scene["patients"]
    snapshot_date = args.snapshot_date or scene["snapshot_date"]
    target_hhmm = args.time or scene["time"]
    radius = args.radius if args.radius is not None else scene["radius_km"]
    params = SimParams(n_patients=patients, n_ambulances=args.ambulances,
                       severity_mix=scene["severity_mix"])
    if args.sweep:
        sweep(params, scene, snapshot_date, target_hhmm, radius, seeds=max(args.seeds // 2, 5))
        return

    results = run_all(params, scene, snapshot_date, target_hhmm, radius, args.seeds)
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / f"results_{args.scene}.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"[{scene['label']}]")
    print(f"스냅샷 {results['scenario']['snapshotTs']} — 병원 {results['scenario']['nHospitals']}곳, "
          f"가용 {results['scenario']['totalBeds']}병상, 환자 {patients}명, 시드 {args.seeds}개")
    print(f"{'arm':<12}{'이송 중앙값':>12}{'p90':>8}{'쏠림 최대':>10}{'재이송':>8}{'거절 전화':>10}{'종료':>8}")
    for arm in ARMS:
        a = results["arms"][arm]
        print(f"{arm:<12}{a['medianTransportMin']['mean']:>10.1f}분{a['p90TransportMin']['mean']:>7.1f}분"
              f"{a['maxLoadRatio']['mean']:>9.1f}x{a['transfersMean']:>8.1f}{a['rejectedCallsMean']:>10.1f}"
              f"{a['finishedAtMin']['mean']:>7.1f}분")

    from html_report import render
    html_path = OUT_DIR / f"mci_report_{args.scene}.html"
    html_path.write_text(render(results), encoding="utf-8")
    print(f"\n리포트: {html_path}")


if __name__ == "__main__":
    main()
