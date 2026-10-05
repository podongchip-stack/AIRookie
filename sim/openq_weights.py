"""열린 질문 ②: "finalScore 가중치 0.6/0.4의 근거는?"

    python openq_weights.py     # 서울 실측 55개 병원 + 대표 환자 6종 × 출발지 3곳

정직한 답의 구조: (1) 초기값은 휴리스틱이다. (2) 대신 가중치가 뒤집을 수 있는 범위에
상한을 걸었다(가산 8분·부하 페널티 10분 불변식). (3) 그리고 가중치를 흔들어도 순위가
안정적임을 실측 데이터로 보인다 — 이 스크립트가 (3)이다.

방법: 실제 hub 엔진(임베딩 포함)을 서울 실측 병원 55곳(E-Gen 좌표·진료과 캐시)으로
돌려 시나리오별 각 병원의 (진료과 점수, 유효 이동시간)을 얻은 뒤, w_진료과를
0.30~0.80으로 흔들며 상위 1위·상위 3위 구성이 기준(0.6)과 달라지는지 센다.
hub 코드는 읽기 전용 import만 한다(feature/sim 규칙).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parent
HUB_DIR = SIM_DIR.parent / "hub"
INFO_OUTPUT = SIM_DIR.parent / "info" / "Hospital_inform" / "info" / "data" / "output"
sys.path.insert(0, str(HUB_DIR))

from hub_engine import HubEngine  # noqa: E402
from schema import GpsPoint, HospitalInfo, VoiceCallSummaryMessage, VoiceSummary, VoiceTranscript  # noqa: E402
from scoring import travel_score  # noqa: E402

#: 출발지 — 서울 안 세 곳 (현장이 달라지면 거리 구조가 달라져 민감도도 달라질 수 있어 분산)
ORIGINS = {
    "이태원": GpsPoint(lat=37.53465, lng=126.99418),
    "시청": GpsPoint(lat=37.5663, lng=126.9779),
    "동대문": GpsPoint(lat=37.5713, lng=127.0095),
}

#: 대표 환자 — 예상 병명(임베딩 입력)과 중증도. v1 스키마(mechanism) 그대로.
PATIENTS = [
    ("급성 심근경색 의심, 흉통", "high"),
    ("교통사고 다발성 외상, 의식 저하", "high"),
    ("뇌출혈 의심, 편마비", "high"),
    ("급성 복통, 복막염 의심", "medium"),
    ("호흡곤란, 폐렴 의심", "medium"),
    ("발목 골절", "low"),
]

WEIGHTS = [round(0.30 + 0.05 * i, 2) for i in range(11)]  # 0.30 ~ 0.80
BASELINE = 0.6


def load_engine() -> HubEngine:
    engine = HubEngine()
    count = 0
    for path in sorted(INFO_OUTPUT.glob("*.json")):
        info = HospitalInfo.model_validate_json(path.read_text(encoding="utf-8"))
        engine.update_hospital_info(info)
        count += 1
    print(f"서울 실측 병원 {count}곳 적재 (E-Gen 좌표·진료과 캐시)")
    return engine


def rank_at(rows: list[tuple[str, float, float]], w: float) -> list[str]:
    """rows = (hospitalId, 진료과 점수, 유효 이동분). w 가중치로 병원 ID 순위."""
    scored = sorted(rows, key=lambda r: (-(w * r[1] + (1 - w) * travel_score(r[2])), r[0]))
    return [r[0] for r in scored]


def main() -> None:
    engine = load_engine()
    scenario_rows: list[tuple[str, list[tuple[str, float, float]]]] = []
    for origin_name, gps in ORIGINS.items():
        zone = engine.resolve_start_zone(gps)
        for i, (mechanism, severity) in enumerate(PATIENTS):
            voice = VoiceCallSummaryMessage(
                caseId=f"openq-{origin_name}-{i}",
                transcript=VoiceTranscript(raw_text=mechanism, filtered_text=mechanism),
                summary=VoiceSummary(patient="성인", mechanism=mechanism, symptoms=[],
                                     treatment=[], severity_tag=severity),
                source="ai",
            )
            result = engine.process_voice_summary(voice, gps, max_zone=zone)
            rows = [
                (h.hospitalId, h.specialtyMatch.score,
                 max(h.travelMin - h.travelBonusMin + h.loadPenaltyMin, 0.0))
                for h in result.hospitals
                if not h.demoteReasons and h.travelMin is not None
            ]
            if len(rows) >= 3:
                scenario_rows.append((f"{origin_name}·{mechanism[:12]}({severity})", rows))

    print(f"시나리오 {len(scenario_rows)}개 (출발지 {len(ORIGINS)} × 환자 {len(PATIENTS)}, 후보 3곳 미만 제외)\n")
    header = "가중치(진료과)".ljust(14) + "1위 유지".rjust(8) + "상위3 집합 유지".rjust(14) + "상위3 순서 유지".rjust(14)
    print(header)
    stable_range_top1: list[float] = []
    for w in WEIGHTS:
        top1 = top3set = top3seq = 0
        for _, rows in scenario_rows:
            base = rank_at(rows, BASELINE)
            cur = rank_at(rows, w)
            top1 += base[0] == cur[0]
            top3set += set(base[:3]) == set(cur[:3])
            top3seq += base[:3] == cur[:3]
        n = len(scenario_rows)
        if top1 == n:
            stable_range_top1.append(w)
        mark = " ← 기준" if w == BASELINE else ""
        print(f"{w:<16.2f}{top1:>4}/{n:<4}{top3set:>8}/{n:<6}{top3seq:>8}/{n:<6}{mark}")

    if stable_range_top1:
        print(f"\n1위가 전 시나리오에서 바뀌지 않는 가중치 범위: "
              f"{min(stable_range_top1):.2f} ~ {max(stable_range_top1):.2f} (기준 0.6)")
    print("해석: 이 범위가 넓을수록 '0.6이냐 0.55냐'는 결과를 바꾸지 않는 선택이라는 뜻이다.")
    print("가중치와 무관하게 상한 불변식(가산 8분·부하 페널티 10분)이 역전 가능 범위를 따로 묶는다.")


if __name__ == "__main__":
    main()
