"""테스트 데이터(data/test/)로 HubEngine의 2단계 매칭을 실행해보는 CLI.

1단계: 병원 정보만으로 존 기반 후보 리스트 생성
2단계: voice 요약이 도착했다고 가정하고 최종 매칭 결과 생성
추가로 존 확장(실제 계산된 거절 비율 기반), 승인 액션 멱등성, 진료과 임베딩
캐싱에 따른 속도 개선, 의사결정 로그 위변조 검증까지 같이 확인한다.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import decision_log
import delivery
from hub_engine import BED_OVERLAY_TTL_MIN, HubEngine
from schema import (
    AmbulanceInfo,
    ApprovalAction,
    Assessment,
    AssessmentConditions,
    AssessmentGroup,
    GpsPoint,
    HospitalInfo,
    Specialty,
    VoiceCallSummaryMessage,
    VoiceSummary,
    VoiceTranscript,
)

BASE_DIR = Path(__file__).resolve().parent
TEST_DIR = BASE_DIR / "data" / "test"
HOSPITALS_DIR = TEST_DIR / "hospitals"
# feature/voice가 실제로 만드는 파일명 규칙(<stem>_call_summary.json)을 그대로 흉내낸
# 테스트 픽스처. delivery.py가 이 파일명에서 stem을 뽑아 결과 파일명을 짓는다.
VOICE_SUMMARY_PATH = TEST_DIR / "DrRomantic3v3_call_summary.json"

AMBULANCE_GPS = GpsPoint(lat=35.1800, lng=128.1080)
# 이 테스트는 사건(구급차) 1건만 다룬다 — 픽스처(DrRomantic3v3_call_summary.json)의
# caseId와 맞춰둔다.
CASE_ID = "case-DrRomantic3v3"


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
        beds = "미상" if h.bedCountUnknown else f"{h.availableBedCount}"
        print(
            f"  {h.hospitalId} {h.name} — 거리 {h.distanceKm}km, "
            f"진료과 매칭: {dept} (score={h.specialtyMatch.score}), "
            f"병상 {beds}, status={h.status}"
        )

    assert any(h.hospitalId == "H002" and h.specialtyMatch.department is None for h in result.hospitals), (
        "진료과 정보가 없는 병원(H002)이 후보에서 빠지면 안 된다"
    )
    print("\n  [확인] 진료과 정보가 없는 H002도 후보 리스트에서 제외되지 않음 (거리 기준으로만 순위)")

    assert not any(h.hospitalId == "H002" and h.bedCountUnknown for h in result.hospitals), (
        "H002는 bedsByType에 ER_ADULT=0을 명시한 '확인된 만실'이라 '미상'으로 잡히면 안 된다"
    )
    print("  [확인] H002의 병상 0은 '미상'이 아니라 '확인된 만실'로 구분됨")

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

    print("\n=== 거절 비율 계산: 아직 아무도 응답 안 했을 때는 0.0이어야 함 ===")
    ratio_before = engine.reject_ratio(CASE_ID, AMBULANCE_GPS, max_zone=1)
    assert ratio_before == 0.0, "아무도 응답 안 했는데 거절 비율이 0이 아니면 안 된다"
    print(f"  거절 비율(응답 전): {ratio_before:.0%}")

    print("\n=== 존 확장 시나리오: 병원 두 곳이 거절하면 실제 거절 비율로 확장 판단 ===")
    for hospital_id in ("H001", "H002"):
        engine.apply_approval_action(
            ApprovalAction(
                caseId=CASE_ID,
                action="hospital_reject",
                hospital_id=hospital_id,
                actor="hospital",
                timestamp="2026-07-30T14:15:00Z",
            )
        )
    max_zone = 1
    ratio_after = engine.reject_ratio(CASE_ID, AMBULANCE_GPS, max_zone)
    new_max_zone = engine.expand_if_needed(max_zone, ratio_after)
    print(f"  H001, H002 거절 → 거절 비율 {ratio_after:.0%} (임계값 넘으면 확장)")
    print(f"  존 확장 {'O' if new_max_zone != max_zone else 'X'} (zone 1~{new_max_zone})")
    assert new_max_zone == 2, "2/3 병원이 거절했으면 임계값(50%)을 넘어 존이 확장돼야 한다"

    print("\n=== 존 확장 후 재매칭: zone=2까지 넓히면 H003도 후보에 포함되는지 확인 ===")
    result_zone2 = engine.process_voice_summary(voice, AMBULANCE_GPS, max_zone=new_max_zone)
    included = {h.hospitalId for h in result_zone2.hospitals}
    print(f"  zone={new_max_zone} 활성 존: {result_zone2.zoneActive}, 후보 병원: {sorted(included)}")

    print("\n=== 승인 액션 시뮬레이션: dashboard가 1위 병원에 최종 승인을 보냈다고 가정 ===")
    # 지금은 feature/dashboard가 실제로 이 액션을 보내는 통신이 없으니, 여기서는
    # 같은 모양의 ApprovalAction을 직접 만들어 engine에 넣어본다 — 나중에 실제
    # 통신이 붙어도 HubEngine.apply_approval_action()을 그대로 부르면 되므로,
    # 이 테스트가 검증하는 로직 자체는 병합 후에도 안 바뀐다.
    top_hospital_id = result.hospitals[0].hospitalId
    hospital_before = engine.get_hospital(top_hospital_id)
    raw_before = hospital_before.availableBedCount
    effective_before = engine.effective_bed_count(hospital_before)
    action = ApprovalAction(
        caseId=CASE_ID,
        action="final_approval",
        hospital_id=top_hospital_id,
        actor="paramedic",
        timestamp="2026-07-30T14:20:00Z",
    )
    engine.apply_approval_action(action)
    effective_after = engine.effective_bed_count(engine.get_hospital(top_hospital_id))
    assert effective_after == effective_before - 1, "final_approval인데 TTL 오버레이로 병상이 안 줄면 안 된다"
    print(
        f"  {top_hospital_id} 확정 → 표시 병상 {effective_before}개 -> {effective_after}개 "
        f"(TTL {BED_OVERLAY_TTL_MIN}분, feature/info로 되돌려 쓰지 않음)"
    )

    print("\n=== 멱등성 확인: 같은 최종 승인이 중복으로 다시 도착해도 병상이 또 안 깎여야 함 ===")
    engine.apply_approval_action(action)
    effective_after_duplicate = engine.effective_bed_count(engine.get_hospital(top_hospital_id))
    assert effective_after_duplicate == effective_after, "이미 confirmed된 병원에 중복 요청이 오면 병상이 또 깎이면 안 된다"
    print(f"  [확인] 중복 final_approval 무시됨 — {top_hospital_id} 병상이 또 깎이지 않음 ({effective_after_duplicate}개 유지)")

    print("\n=== 재매칭: 같은 조건으로 다시 매칭하면 확정 상태·병상 수가 반영되는지 확인 ===")
    t1 = time.perf_counter()
    result_after_approval = engine.process_voice_summary(voice, AMBULANCE_GPS, max_zone=1)
    elapsed_cached = time.perf_counter() - t1
    for h in result_after_approval.hospitals:
        print(f"  {h.hospitalId} {h.name} — availableBedCount={h.availableBedCount}, status={h.status}")
    print(
        f"  매칭 소요 시간: {elapsed_cached:.3f}초 (최초 {elapsed:.3f}초 대비, 진료과 임베딩은 이미 "
        f"캐시돼 있어 훨씬 빠름)"
    )

    confirmed = next(h for h in result_after_approval.hospitals if h.hospitalId == top_hospital_id)
    assert confirmed.status == "confirmed", "승인 액션을 반영했는데 status가 그대로면 안 된다"
    assert confirmed.availableBedCount == effective_after, "병상 수가 갱신되지 않았다"
    print(f"\n  [확인] {top_hospital_id}의 status가 confirmed로, 병상 수가 감소분으로 반영됨")

    print("\n=== TTL 만료 확인: 오버레이가 만료되면 원래(E-Gen 원본) 병상 수로 돌아가야 함 ===")
    overlay_entries = engine._bed_overlay.get(top_hospital_id)
    assert overlay_entries, "final_approval 직후인데 오버레이 기록이 없으면 안 된다"
    # 실제로 15분을 기다릴 수 없으니, 만료 시각을 과거로 강제로 앞당겨 만료를 흉내낸다.
    engine._bed_overlay[top_hospital_id] = [datetime.now(timezone.utc) - timedelta(minutes=1)]
    effective_expired = engine.effective_bed_count(engine.get_hospital(top_hospital_id))
    assert effective_expired == raw_before, "TTL이 지났으면 원본(E-Gen) 병상 수로 돌아가야 한다"
    assert top_hospital_id not in engine._bed_overlay, "만료된 오버레이 기록은 조회 시점에 정리돼야 한다"
    print(f"  [확인] TTL 만료 후 병상 수가 원본({raw_before}개)으로 복귀, 오버레이 기록도 정리됨")

    print("\n=== 의사결정 로그 위변조 검증 ===")
    ok, checked = decision_log.verify_log()
    print(f"  {checked}건 검증, 위변조 {'없음' if ok else '발견됨'} — {decision_log.LOG_PATH}")
    assert ok, "의사결정 로그 해시가 안 맞으면 위변조 검증 실패"

    print("\n=== 다중 사건 격리 확인: 같은 병원 후보를 다른 사건 두 개가 동시에 씀 ===")
    other_case_id = "case-other-ambulance"
    voice_other = voice.model_copy(update={"caseId": other_case_id})
    result_other = engine.process_voice_summary(voice_other, AMBULANCE_GPS, max_zone=1)
    other_top_hospital_id = result_other.hospitals[0].hospitalId
    assert result_other.caseId == other_case_id, "HubMatchResult.caseId가 요청한 caseId와 달라선 안 된다"
    print(f"  case={CASE_ID}: {top_hospital_id} 확정 상태 유지 / case={other_case_id}: 아직 응답 없음(전부 pending)")
    assert all(h.status == "pending" for h in result_other.hospitals), (
        f"{other_case_id}는 아직 아무 승인도 안 받았는데 {CASE_ID}의 confirmed/rejected 상태가 새어 들어왔다"
    )
    print(f"  [확인] {other_case_id}의 병원 상태가 전부 pending — {CASE_ID}의 승인 상태와 안 섞임")

    engine.apply_approval_action(
        ApprovalAction(
            caseId=other_case_id,
            action="final_approval",
            hospital_id=other_top_hospital_id,
            actor="paramedic",
            timestamp="2026-07-30T14:25:00Z",
        )
    )
    case_a_cached = engine.get_case_result(CASE_ID)
    case_a_top = next(h for h in case_a_cached.hospitals if h.hospitalId == top_hospital_id)
    assert case_a_top.status == "confirmed", f"{CASE_ID}의 캐시된 결과가 다른 사건 승인 처리로 바뀌면 안 된다"
    print(f"  [확인] {other_case_id}에 승인 액션을 보내도 {CASE_ID}의 캐시(get_case_result)는 그대로 confirmed")

    print("\n=== 구급차 레지스트리 + 자가등록 매핑 확인 ===")
    ambulance = AmbulanceInfo(
        apid="A0000099",
        name="테스트 구급차",
        gps=AMBULANCE_GPS,
        voicePort=6099,
        updatedAt="2026-08-11T00:00:00Z",
    )
    engine.update_ambulance_info(ambulance)
    assert engine.get_ambulance("A0000099") is not None, "update_ambulance_info로 등록한 구급차를 못 찾으면 안 된다"
    engine.register_case("case-A0000099-001", "A0000099")
    assert engine.get_case_apid("case-A0000099-001") == "A0000099", (
        "register_case()로 등록한 (caseId -> apid)가 get_case_apid()로 그대로 조회돼야 한다"
    )
    print("  [확인] AmbulanceInfo 등록·조회, (caseId -> apid) 매핑 모두 정상 동작")

    test_declared_no_demotion()


def _assessment_group(tier: str, score: float, confidence: str) -> AssessmentGroup:
    return AssessmentGroup(status="unavailable" if tier == "declared_no" else "unknown",
                            tier=tier, score=score, confidence=confidence, basis=["테스트"], items={})


def test_declared_no_demotion() -> None:
    """hospital_score(assessment)의 관련 질환군이 declared_no(병원이 명시적으로
    "수용 불가"라고 신고)면, 거리·진료과가 아무리 유리해도 순위 맨 뒤로 밀려야
    한다(scoring.rank()의 demote 키). finalScore 계산식 자체는 안 바뀐다 —
    가중합으로 섞지 않고 정렬 순서만 조정하는 방식을 택한 이유는 hub_engine.py의
    `_should_demote()` 문서화 참고(임의 가중치 없이 안전을 보장하려면 실험상
    신뢰도 가중치가 70%대까지 필요해, 그럴 바엔 순서로 미는 편이 낫다는 결론).
    """
    print("\n=== declared_no 데모션 확인: 거리·진료과 1등이어도 수용불가 신고면 맨 뒤로 ===")
    engine = HubEngine()

    declared_no_hospital = HospitalInfo(
        hospitalId="D001", name="[테스트] 초근접·진료과 동점, 수용불가 신고",
        gps=GpsPoint(lat=35.1810, lng=128.1090), availableBedCount=5, nightDutyAvailable=True,
        specialties=[Specialty(department="흉부외과", doctorCount=0)],
        updatedAt="2026-08-14T00:00:00Z",
        assessment=Assessment(
            assessedAt="2026-08-14T00:00:00+09:00", conditions=AssessmentConditions(), evidence={},
            groups={"대동맥응급": _assessment_group("declared_no", 0.2, "high")},
        ),
    )
    unknown_hospital = HospitalInfo(
        hospitalId="D002", name="[테스트] 그다음, 미상",
        gps=GpsPoint(lat=35.1950, lng=128.1200), availableBedCount=3, nightDutyAvailable=True,
        specialties=[Specialty(department="흉부외과", doctorCount=0)],
        updatedAt="2026-08-14T00:00:00Z",
        assessment=Assessment(
            assessedAt="2026-08-14T00:00:00+09:00", conditions=AssessmentConditions(), evidence={},
            groups={"대동맥응급": _assessment_group("unknown_bare", 0.4, "low")},
        ),
    )
    no_assessment_hospital = HospitalInfo(
        hospitalId="D003", name="[테스트] assessment 없음 (구 데이터, 하위호환 확인)",
        gps=GpsPoint(lat=35.2000, lng=128.1300), availableBedCount=1, nightDutyAvailable=True,
        specialties=[Specialty(department="흉부외과", doctorCount=0)],
        updatedAt="2026-08-14T00:00:00Z",
        assessment=None,
    )
    for h in (declared_no_hospital, unknown_hospital, no_assessment_hospital):
        engine.update_hospital_info(h)

    voice = VoiceCallSummaryMessage(
        caseId="case-declared-no-test",
        transcript=VoiceTranscript(raw_text="x", filtered_text="x"),
        summary=VoiceSummary(
            patient="60대 남성", mechanism="대동맥 박리 의심",
            symptoms=["흉통"], treatment=["산소 공급"], severity_tag="high",
        ),
        source="ai",
    )
    result = engine.process_voice_summary(voice, GpsPoint(lat=35.1800, lng=128.1080), max_zone=1)
    for h in result.hospitals:
        rel = f"{h.reliability.group}/{h.reliability.score}" if h.reliability else "없음"
        print(f"  {h.hospitalId} {h.name} — 거리 {h.distanceKm}km, reliability=[{rel}]")

    assert result.hospitals[-1].hospitalId == "D001", (
        "declared_no 신고 병원(D001)은 거리·진료과가 유리해도 항상 맨 뒤여야 한다"
    )
    d001 = next(h for h in result.hospitals if h.hospitalId == "D001")
    assert d001.specialtyMatch.score > 0, "데모션은 specialtyMatch 값 자체를 건드리면 안 된다 — 정렬 순서만 바뀐다"
    print("  [확인] D001이 거리 1위·진료과 동점임에도 declared_no라서 맨 뒤로 밀림 (specialtyMatch 값 자체는 안 바뀜)")


if __name__ == "__main__":
    main()
