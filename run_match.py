"""테스트 데이터(data/test/)로 HubEngine의 2단계 매칭을 실행해보는 CLI.

1단계: 병원 정보만으로 존 기반 후보 리스트 생성
2단계: voice 요약이 도착했다고 가정하고 최종 매칭 결과 생성
추가로 존 확장(거절 비율 기반)과, 진료과 정보가 없는 병원이 배제되지 않는지도
같이 확인한다.
"""
from __future__ import annotations

import time
from pathlib import Path

import delivery
from hub_engine import HubEngine
from schema import ApprovalAction, GpsPoint, HospitalInfo, VoiceCallSummaryMessage

BASE_DIR = Path(__file__).resolve().parent
TEST_DIR = BASE_DIR / "data" / "test"
HOSPITALS_DIR = TEST_DIR / "hospitals"
# feature/voice가 실제로 만드는 파일명 규칙(<stem>_call_summary.json)을 그대로 흉내낸
# 테스트 픽스처. delivery.py가 이 파일명에서 stem을 뽑아 결과 파일명을 짓는다.
VOICE_SUMMARY_PATH = TEST_DIR / "DrRomantic3v3_call_summary.json"

AMBULANCE_GPS = GpsPoint(lat=35.1800, lng=128.1080)


def load_hospitals(engine: HubEngine) -> None:
    for path in sorted(HOSPITALS_DIR.glob("*.json")):
        info = HospitalInfo.model_validate_json(path.read_text(encoding="utf-8"))
        engine.update_hospital_info(info)
        print(f"  [info] {info.hospitalId} {info.name} 등록 (진료과 {len(info.specialties)}개)")


def main() -> None:
    engine = HubEngine()

    print("=== 병원 정보 로드 (feature/info 시뮬레이션) ===")
    load_hospitals(engine)

    print("\n=== 1단계: GPS + 병원 정보만으로 존(zone=1) 기반 후보 리스트 ===")
    stage1 = engine.build_zone_candidates(AMBULANCE_GPS, max_zone=1)
    for c in stage1:
        print(f"  {c['hospitalId']} {c['name']} — {c['distanceKm']}km")
    print("  (voice 정보가 아직 없어 진료과 매칭은 수행하지 않음)")

    print("\n=== 2단계: voice 의료 정보 도착 → 재처리 ===")
    voice = VoiceCallSummaryMessage.model_validate_json(VOICE_SUMMARY_PATH.read_text(encoding="utf-8"))
    print(f"  예상 병명(mechanism): {voice.summary.mechanism}")
    print(f"  부상 상태(symptoms): {voice.summary.symptoms}")
    print(f"  중증도(severity_tag): {voice.summary.severity_tag}")

    t0 = time.perf_counter()
    result = engine.process_voice_summary(voice, AMBULANCE_GPS, max_zone=1)
    elapsed = time.perf_counter() - t0

    print(f"\n  매칭 소요 시간: {elapsed:.2f}초 (병원 {len(result.hospitals)}곳, 배치 임베딩 1회 호출)")
    for h in result.hospitals:
        dept = h.specialtyMatch.department or "(매칭 실패, 거리만으로 순위 유지)"
        print(
            f"  {h.hospitalId} {h.name} — 거리 {h.distanceKm}km, "
            f"진료과 매칭: {dept} (score={h.specialtyMatch.score}), status={h.status}"
        )

    assert any(h.hospitalId == "H002" and h.specialtyMatch.department is None for h in result.hospitals), (
        "진료과 정보가 없는 병원(H002)이 후보에서 빠지면 안 된다"
    )
    print("\n  [확인] 진료과 정보가 없는 H002도 후보 리스트에서 제외되지 않음 (거리 기준으로만 순위)")

    assert not any(h.hospitalId == "H003" for h in result.hospitals), (
        "zone=1 밖의 병원(H003)은 이 단계에서 후보에 들어오면 안 된다"
    )
    print("  [확인] zone=1 밖의 H003은 아직 후보에 포함되지 않음")

    # 로컬 저장 + (자리만 준비된) 통신을 함께 수행한다. 결과 파일명은 voice 요약
    # 파일명에서 stem을 그대로 이어받는다 (DrRomantic3v3_call_summary.json ->
    # DrRomantic3v3_hub_match_result.json) — 입력과 출력이 파일명만으로 짝지어져서
    # 여러 건이 동시에 처리돼도 서로 다른 파일로 섞이지 않는다.
    saved_path = delivery.deliver(result, VOICE_SUMMARY_PATH)
    print(f"\n  결과 저장: {saved_path}")

    print("\n=== 존 확장 시나리오: 거절 비율이 임계값을 넘으면 다음 존까지 확장 ===")
    max_zone = 1
    for reject_ratio in (0.2, 0.6):
        new_max_zone = engine.expand_if_needed(max_zone, reject_ratio)
        expanded = new_max_zone != max_zone
        print(f"  거절 비율 {reject_ratio:.0%} → 존 확장 {'O' if expanded else 'X'} (zone 1~{new_max_zone})")

    print("\n=== 존 확장 후 재매칭: zone=2까지 넓히면 H003도 후보에 포함되는지 확인 ===")
    result_zone2 = engine.process_voice_summary(voice, AMBULANCE_GPS, max_zone=2)
    included = {h.hospitalId for h in result_zone2.hospitals}
    print(f"  zone=2 활성 존: {result_zone2.zoneActive}, 후보 병원: {sorted(included)}")

    print("\n=== 승인 액션 시뮬레이션: dashboard가 1위 병원에 최종 승인을 보냈다고 가정 ===")
    # 지금은 feature/dashboard가 실제로 이 액션을 보내는 통신이 없으니, 여기서는
    # 같은 모양의 ApprovalAction을 직접 만들어 engine에 넣어본다 — 나중에 실제
    # 통신이 붙어도 HubEngine.apply_approval_action()을 그대로 부르면 되므로,
    # 이 테스트가 검증하는 로직 자체는 병합 후에도 안 바뀐다.
    top_hospital_id = result.hospitals[0].hospitalId
    action = ApprovalAction(
        action="final_approval",
        hospital_id=top_hospital_id,
        actor="paramedic",
        timestamp="2026-07-30T14:20:00Z",
    )
    bed_update = engine.apply_approval_action(action)
    assert bed_update is not None, "final_approval인데 병상 갱신이 안 나오면 안 된다"
    print(f"  {top_hospital_id} 확정 → 남은 병상 {bed_update.availableBedCount}개로 갱신")

    saved_bed_update_path = delivery.deliver_bed_update(bed_update)
    print(f"  병상 갱신 결과 저장: {saved_bed_update_path}")

    print("\n=== 재매칭: 같은 조건으로 다시 매칭하면 확정 상태·병상 수가 반영되는지 확인 ===")
    result_after_approval = engine.process_voice_summary(voice, AMBULANCE_GPS, max_zone=1)
    for h in result_after_approval.hospitals:
        print(f"  {h.hospitalId} {h.name} — availableBedCount={h.availableBedCount}, status={h.status}")

    confirmed = next(h for h in result_after_approval.hospitals if h.hospitalId == top_hospital_id)
    assert confirmed.status == "confirmed", "승인 액션을 반영했는데 status가 그대로면 안 된다"
    assert confirmed.availableBedCount == bed_update.availableBedCount, "병상 수가 갱신되지 않았다"
    print(f"\n  [확인] {top_hospital_id}의 status가 confirmed로, 병상 수가 감소분으로 반영됨")


if __name__ == "__main__":
    main()
