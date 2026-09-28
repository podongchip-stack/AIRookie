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

import bed_reliability
import decision_log
import delivery
from hub_engine import (
    _ASSESSMENT_GROUPS,
    BED_OVERLAY_TTL_MIN,
    CASE_RETENTION_MIN,
    SEVERE_EXPIRY_RULE_SEC,
    HubEngine,
)
from schema import (
    AmbulanceInfo,
    ApprovalAction,
    Assessment,
    AssessmentConditions,
    AssessmentGroup,
    BedReliabilityInput,
    GpsPoint,
    HospitalInfo,
    SevereDeclarations,
    SevereGroupDeclaration,
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
    test_case_eviction()
    test_bed_reliability()
    test_severe_freshness()
    test_bed_full_and_rejected_ranking()
    test_travel_time_ranking()
    test_gps_fallback_and_message_type()
    test_refresh_case()
    test_state_roundtrip()
    test_decision_log_chain()


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


def test_case_eviction() -> None:
    """이송이 확정된 지 CASE_RETENTION_MIN이 지난 사건은 인메모리 캐시에서
    걷어내지만(무한 누적 방지), 진행 중이거나 아직 확정 전인 사건은 그대로
    남겨 다중 사건 격리·따라잡기(_send_catchup)를 깨지 않는다.
    """
    print("\n=== 사건 캐시 정리 확인: 오래 전 확정된 사건만 비우고 진행 중 사건은 남긴다 ===")
    engine = HubEngine()

    hospital = HospitalInfo(
        hospitalId="E001", name="[테스트] 캐시 정리용 병원",
        gps=GpsPoint(lat=35.1810, lng=128.1090), availableBedCount=5, nightDutyAvailable=True,
        specialties=[Specialty(department="응급의학과", doctorCount=1)],
        updatedAt="2026-09-10T00:00:00Z",
    )
    engine.update_hospital_info(hospital)

    def _voice(case_id: str) -> VoiceCallSummaryMessage:
        return VoiceCallSummaryMessage(
            caseId=case_id,
            transcript=VoiceTranscript(raw_text="x", filtered_text="x"),
            summary=VoiceSummary(
                patient="50대 남성", mechanism="복통", symptoms=["복통"],
                treatment=["산소 공급"], severity_tag="medium",
            ),
            source="ai",
        )

    gps = GpsPoint(lat=35.1800, lng=128.1080)
    old_case, live_case = "case-evict-old", "case-evict-live"

    # 1) 오래된 사건: 매칭 → 확정 → 확정 시각을 CASE_RETENTION_MIN+5분 과거로 강제
    engine.process_voice_summary(_voice(old_case), gps, max_zone=1)
    engine.apply_approval_action(ApprovalAction(
        caseId=old_case, action="final_approval", hospital_id="E001",
        actor="paramedic", timestamp="2026-09-10T00:00:00Z",
    ))
    assert old_case in engine._case_confirmed_at, "final_approval인데 확정 시각이 기록되지 않았다"
    engine._case_confirmed_at[old_case] = datetime.now(timezone.utc) - timedelta(minutes=CASE_RETENTION_MIN + 5)

    # 2) 진행 중 사건: 매칭만 (확정 안 함)
    engine.process_voice_summary(_voice(live_case), gps, max_zone=1)

    # 3) 아무 사건이나 새로 처리되면 진입 시점에 정리가 돈다
    engine.process_voice_summary(_voice("case-evict-trigger"), gps, max_zone=1)

    assert engine.get_case_result(old_case) is None, "확정된 지 오래된 사건의 매칭 결과 캐시가 안 지워졌다"
    assert old_case not in engine._case_voice, "오래된 사건의 voice 요약 캐시가 안 지워졌다"
    assert any(k[0] == old_case for k in engine._approval_status), (
        "승인 상태는 멱등성 가드용이라 정리하면 안 된다 — 중복 final_approval 시 병상이 두 번 깎인다"
    )
    assert engine.get_case_result(live_case) is not None, "아직 확정 전인 진행 중 사건이 잘못 지워졌다"
    print(f"  [확인] {CASE_RETENTION_MIN}분 지난 확정 사건({old_case})의 큰 캐시는 제거, 승인 상태(멱등성)는 유지, 진행 중 사건({live_case})은 유지")

    # 오래된 사건에 중복 final_approval이 와도 병상이 또 깎이면 안 된다 (멱등성 유지 확인)
    engine.apply_approval_action(ApprovalAction(
        caseId=old_case, action="final_approval", hospital_id="E001",
        actor="paramedic", timestamp="2026-09-10T02:00:00Z",
    ))
    overlay_count = len(engine._bed_overlay.get("E001", []))
    assert overlay_count == 1, (
        f"오래된 확정 사건에 중복 final_approval이 왔는데 병상 오버레이가 {overlay_count}개다 (1개여야 함)"
    )
    print("  [확인] 캐시 정리 후에도 중복 final_approval은 멱등 — 병상이 두 번 안 깎임")


def test_bed_reliability() -> None:
    """feature/info가 bedReliability(infosurv 병상 정보 신뢰도 예측)를 실어
    보내면, hub가 매칭 시점의 authority(지금 유효 확률)·rArrive(도착 시점
    유효 확률)로 환산해 HospitalMatch에 싣는지 확인한다. finalScore·순위에는
    관여하지 않고(설명용), 이 필드 없이 오는 구 데이터는 None으로 통과한다.
    """
    print("\n=== bedReliability 환산 확인: 병상 숫자의 유효 확률이 매칭 결과에 실리는지 ===")
    engine = HubEngine()
    now = datetime.now(timezone.utc)

    fresh_born = now.isoformat(timespec="seconds")
    old_born = (now - timedelta(minutes=30)).isoformat(timespec="seconds")
    with_fresh = HospitalInfo(
        hospitalId="B001", name="[테스트] 방금 갱신된 병상 값",
        gps=GpsPoint(lat=35.1810, lng=128.1090), availableBedCount=5, nightDutyAvailable=True,
        specialties=[Specialty(department="흉부외과", doctorCount=1)],
        updatedAt="2026-09-24T00:00:00Z",
        bedReliability=BedReliabilityInput(
            predictedSurvivalSec=2400.0, bornAt=fresh_born,
            authorityAtSend=1.0, ttlSec=2400.0, modelTag="aft_egen_theta3_ext0923",
        ),
        # 확장 필드(수술실) — bedReliability와 같은 환산이 byType으로도 나가는지 확인용
        bedReliabilityByType={
            "hvoc": BedReliabilityInput(
                predictedSurvivalSec=9600.0, bornAt=fresh_born,
                authorityAtSend=1.0, ttlSec=9600.0, modelTag="aft_egen_hvoc_theta3",
            )
        },
    )
    with_old = HospitalInfo(
        hospitalId="B002", name="[테스트] 30분 묵은 병상 값",
        gps=GpsPoint(lat=35.1950, lng=128.1200), availableBedCount=3, nightDutyAvailable=True,
        specialties=[Specialty(department="흉부외과", doctorCount=1)],
        updatedAt="2026-09-24T00:00:00Z",
        bedReliability=BedReliabilityInput(
            predictedSurvivalSec=2400.0, bornAt=old_born,
            authorityAtSend=0.7, ttlSec=0.0, modelTag="aft_egen_theta3_ext0923",
        ),
    )
    without = HospitalInfo(
        hospitalId="B003", name="[테스트] bedReliability 없음 (구 데이터, 하위호환 확인)",
        gps=GpsPoint(lat=35.2000, lng=128.1300), availableBedCount=1, nightDutyAvailable=True,
        specialties=[Specialty(department="흉부외과", doctorCount=1)],
        updatedAt="2026-09-24T00:00:00Z",
    )
    for h in (with_fresh, with_old, without):
        engine.update_hospital_info(h)

    voice = VoiceCallSummaryMessage(
        caseId="case-bed-reliability-test",
        transcript=VoiceTranscript(raw_text="x", filtered_text="x"),
        summary=VoiceSummary(
            patient="50대 남성", mechanism="교통사고 흉부 충격",
            symptoms=["호흡 곤란"], treatment=["산소 공급"], severity_tag="high",
        ),
        source="ai",
    )
    result = engine.process_voice_summary(voice, GpsPoint(lat=35.1800, lng=128.1080), max_zone=1)
    matches = {h.hospitalId: h for h in result.hospitals}
    for h in result.hospitals:
        br = h.bedReliability
        desc = (
            f"authority={br.authority} rArrive={br.rArrive} ttl={br.ttlSec}s ({br.source})"
            if br else "없음"
        )
        print(f"  {h.hospitalId} {h.name} — 병상신뢰도 [{desc}]")

    b1, b2 = matches["B001"].bedReliability, matches["B002"].bedReliability
    assert b1 is not None and b2 is not None, "bedReliability를 보낸 병원은 환산 결과가 실려야 한다"
    assert matches["B003"].bedReliability is None, "bedReliability 없이 온 구 데이터는 None으로 통과해야 한다"
    assert 0.0 <= b1.rArrive <= b1.authority <= 1.0, "도착 시점 확률(rArrive)은 지금 확률(authority)보다 클 수 없다"
    assert b1.authority > b2.authority, "방금 갱신된 값(B001)이 30분 묵은 값(B002)보다 authority가 높아야 한다"
    assert b2.ttlSec == 0.0 or b2.authority >= bed_reliability.AUTHORITY_TTL_THRESHOLD, (
        "authority가 임계(0.8) 아래인데 ttl이 남아 있으면 안 된다"
    )
    # 도착 시점(horizon)은 순위에 쓴 이동 시간과 같아야 한다(2026-09-28). 카카오 키가 없는
    # 테스트라 기본 추정(직선 1.5분/km = 예전 40km/h 가정과 같은 값)이 쓰인다.
    expected_horizon = matches["B001"].travelMin * 60.0
    assert abs(b1.horizonSec - expected_horizon) < 6.0, "horizonSec은 순위에 쓴 이동 시간(travelMin)과 같아야 한다"
    assert matches["B001"].travelBasis == "estimate", "카카오 키가 없으면 이동 시간은 추정치여야 한다"
    by_type = matches["B001"].bedReliabilityByType
    assert by_type is not None and "hvoc" in by_type, "확장 필드(byType) 환산이 실려야 한다"
    assert 0.0 <= by_type["hvoc"].rArrive <= by_type["hvoc"].authority <= 1.0
    assert by_type["hvoc"].modelTag == "aft_egen_hvoc_theta3"
    assert matches["B002"].bedReliabilityByType is None, "byType 없이 온 병원은 None으로 통과해야 한다"
    order_without_demote = [h.hospitalId for h in result.hospitals]
    print(f"  [확인] 신선한 값 authority({b1.authority}) > 묵은 값 authority({b2.authority}), "
          f"rArrive ≤ authority, 구 데이터는 None 통과 (순위 불변: {order_without_demote})")


def test_severe_freshness() -> None:
    """feature/info가 severeDeclarations(중증질환 신고의 관측 기준 탄생 시각)를
    보내면, hub가 매칭된 질환군의 신고 나이와 9시간 만료 규칙 잔여를 계산해
    HospitalMatch.severeFreshness로 싣는지 확인한다. 매칭되는 질환군이 임베딩
    결과에 따라 달라지므로 15개 그룹 전부에 신고를 넣어 결정성을 확보한다.
    """
    print("\n=== severeFreshness 환산 확인: 중증신고가 언제 적 것인지가 매칭 결과에 실리는지 ===")
    engine = HubEngine()
    now = datetime.now(timezone.utc)

    def declarations(born: datetime, age_is_min: bool = False) -> SevereDeclarations:
        return SevereDeclarations(
            groups={
                g: SevereGroupDeclaration(
                    value="Y", bornAt=born.isoformat(timespec="seconds"), ageIsMin=age_is_min
                )
                for g in _ASSESSMENT_GROUPS
            }
        )

    fresh = HospitalInfo(
        hospitalId="S001", name="[테스트] 2시간 전 신고",
        gps=GpsPoint(lat=35.1810, lng=128.1090), availableBedCount=5, nightDutyAvailable=True,
        specialties=[Specialty(department="흉부외과", doctorCount=1)],
        updatedAt="2026-09-28T00:00:00Z",
        severeDeclarations=declarations(now - timedelta(hours=2)),
    )
    expired = HospitalInfo(
        hospitalId="S002", name="[테스트] 10시간 전 신고(규칙상 만료 경과, 갱신 유지 중)",
        gps=GpsPoint(lat=35.1950, lng=128.1200), availableBedCount=3, nightDutyAvailable=True,
        specialties=[Specialty(department="흉부외과", doctorCount=1)],
        updatedAt="2026-09-28T00:00:00Z",
        severeDeclarations=declarations(now - timedelta(hours=10), age_is_min=True),
    )
    without = HospitalInfo(
        hospitalId="S003", name="[테스트] severeDeclarations 없음 (구 데이터)",
        gps=GpsPoint(lat=35.2000, lng=128.1300), availableBedCount=1, nightDutyAvailable=True,
        specialties=[Specialty(department="흉부외과", doctorCount=1)],
        updatedAt="2026-09-28T00:00:00Z",
    )
    for h in (fresh, expired, without):
        engine.update_hospital_info(h)

    voice = VoiceCallSummaryMessage(
        caseId="case-severe-freshness-test",
        transcript=VoiceTranscript(raw_text="x", filtered_text="x"),
        summary=VoiceSummary(
            patient="60대 남성", mechanism="급성 심근경색 의심",
            symptoms=["흉통"], treatment=["산소 공급"], severity_tag="high",
        ),
        source="ai",
    )
    result = engine.process_voice_summary(voice, GpsPoint(lat=35.1800, lng=128.1080), max_zone=1)
    matches = {h.hospitalId: h for h in result.hospitals}
    for h in result.hospitals:
        sf = h.severeFreshness
        desc = (
            f"[{sf.group}] {sf.value} — {sf.ageSec / 3600:.1f}h 전{'(최소)' if sf.ageIsMin else ''}, "
            f"규칙 잔여 {sf.ruleRemainingSec / 3600:.1f}h ({sf.source})"
            if sf else "없음"
        )
        print(f"  {h.hospitalId} {h.name} — 신고 신선도 [{desc}]")

    s1, s2 = matches["S001"].severeFreshness, matches["S002"].severeFreshness
    assert s1 is not None and s2 is not None, "신고를 보낸 병원은 신선도가 실려야 한다"
    assert matches["S003"].severeFreshness is None, "severeDeclarations 없이 온 구 데이터는 None으로 통과해야 한다"
    assert abs(s1.ageSec - 2 * 3600) < 60, "신고 나이가 bornAt에서 계산돼야 한다"
    assert abs(s1.ageSec + s1.ruleRemainingSec - SEVERE_EXPIRY_RULE_SEC) < 60, (
        "잔여 = 9h 규칙 − 나이여야 한다"
    )
    assert s2.ruleRemainingSec == 0.0 and s2.ageIsMin, (
        "만료 규칙 경과분은 잔여 0 + 좌측검열 플래그가 유지돼야 한다"
    )
    print("  [확인] 신고 나이·9h 규칙 잔여 계산, 좌측검열 플래그, 구 데이터 None 통과 전부 정상")


# ── 2026-09-28 hub 정비 검증 ──────────────────────────────────────────────────

_TEST_GPS = GpsPoint(lat=35.1800, lng=128.1080)
_shared_engine: HubEngine | None = None


def _engine() -> HubEngine:
    """임베딩 모델을 매 테스트마다 다시 올리지 않게 matcher만 공유한 새 엔진."""
    global _shared_engine
    if _shared_engine is None:
        _shared_engine = HubEngine()
        return _shared_engine
    return HubEngine(specialty_matcher=_shared_engine._matcher)


def _hospital(hid: str, name: str, lat: float, lng: float, beds: int, *, beds_by_type=None,
              updated_at: str | None = None, bed_rel: BedReliabilityInput | None = None) -> HospitalInfo:
    return HospitalInfo(
        hospitalId=hid, name=name, gps=GpsPoint(lat=lat, lng=lng), availableBedCount=beds,
        nightDutyAvailable=True, specialties=[Specialty(department="흉부외과", doctorCount=1)],
        updatedAt=updated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        bedsByType=beds_by_type, bedReliability=bed_rel,
    )


def _voice(case_id: str, raw_text: str = "x") -> VoiceCallSummaryMessage:
    return VoiceCallSummaryMessage(
        caseId=case_id,
        transcript=VoiceTranscript(raw_text=raw_text, filtered_text=raw_text),
        summary=VoiceSummary(
            patient="50대 남성", mechanism="교통사고 흉부 충격",
            symptoms=["호흡 곤란"], treatment=["산소 공급"], severity_tag="high",
        ),
        source="ai",
    )


def _action(case_id: str, action: str, hospital_id: str) -> ApprovalAction:
    return ApprovalAction(
        caseId=case_id, action=action, hospital_id=hospital_id,
        actor="paramedic" if action == "final_approval" else "hospital",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def test_bed_full_and_rejected_ranking() -> None:
    """확인된 만실은 뒤로, 미상·오래된 값은 그대로, 거절한 병원은 맨 뒤, 승인한 병원은 만실이어도
    안 내린다. 승인 액션 뒤 캐시도 재정렬돼야 한다."""
    print("\n=== 만실·거절 순위 확인: 확인된 만실은 뒤로, 미상·오래된 값은 유지, 거절은 맨 뒤 ===")
    engine = _engine()
    three_days_ago = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(timespec="seconds")
    for h in (
        _hospital("F001", "[테스트] 가장 가까움, 확인된 만실", 35.1805, 128.1085, 0, beds_by_type={"ER_ADULT": 0}),
        _hospital("F002", "[테스트] 만실이지만 3일 묵은 값", 35.1850, 128.1120, 0, beds_by_type={"ER_ADULT": 0},
                  updated_at=three_days_ago),
        _hospital("F003", "[테스트] 병상 미상", 35.1900, 128.1160, 0),
        _hospital("F004", "[테스트] 가장 멂, 병상 있음", 35.1950, 128.1200, 3, beds_by_type={"ER_ADULT": 3}),
    ):
        engine.update_hospital_info(h)

    case_id = "case-bed-full-test"
    result = engine.process_voice_summary(_voice(case_id), _TEST_GPS, max_zone=1)
    order = [h.hospitalId for h in result.hospitals]
    by_id = {h.hospitalId: h for h in result.hospitals}
    print(f"  순위: {order} / F001 내림 이유 {by_id['F001'].demoteReasons}, F002 오래된 값 {by_id['F002'].bedDataStale}")
    assert order == ["F002", "F003", "F004", "F001"], "확인된 만실(F001)만 뒤로 가고 나머지는 거리 순이어야 한다"
    assert by_id["F001"].demoteReasons == ["beds_full"]
    assert by_id["F002"].bedDataStale and not by_id["F002"].demoteReasons, "오래된 값의 0은 만실로 믿으면 안 된다"
    assert by_id["F003"].bedCountUnknown and not by_id["F003"].demoteReasons, "미상은 순위를 막으면 안 된다"

    engine.apply_approval_action(_action(case_id, "hospital_approve", "F001"))
    engine.apply_approval_action(_action(case_id, "hospital_reject", "F002"))
    patched = engine.get_case_result(case_id)
    order = [h.hospitalId for h in patched.hospitals]
    print(f"  F001 승인·F002 거절 후 캐시 순위: {order}")
    assert order[0] == "F001", "병원이 승인했으면 병상 0이어도 내리지 않는다(명시적 응답 우선)"
    assert order[-1] == "F002" and patched.hospitals[-1].demoteReasons == ["rejected"], "거절한 병원은 맨 뒤"
    print("  [확인] 확인된 만실만 뒤로, 승인 응답은 만실 판정보다 우선, 거절은 캐시에서도 즉시 맨 뒤로 재정렬")


class _FakeRouter:
    """routing.KakaoRouting 대역. hospitalId -> (초, 미터)만 돌려준다."""

    def __init__(self, etas: dict[str, tuple[int, int]]) -> None:
        self._etas = etas

    def etas(self, origin, destinations):  # noqa: ANN001
        return {hid: v for hid, v in self._etas.items() if hid in destinations}


def test_travel_time_ranking() -> None:
    """순위가 직선거리가 아니라 이동 시간(ETA 우선)으로 매겨지고, ETA 없는 먼 병원은 같은
    사건의 ETA로 보정한 분/km로 추정하며, 20km 밖에서도 거리 차이가 살아 있어야 한다."""
    print("\n=== 이동 시간 순위 확인: ETA 우선, 없는 병원은 보정 추정, 20km 밖도 구분 ===")
    from scoring import TRAVEL_HALF_LIFE_MIN, travel_score

    assert travel_score(25 * 1.5) > travel_score(40 * 1.5) > 0.0, "20km 밖 병원끼리도 가까운 쪽 점수가 높아야 한다"
    assert abs(travel_score(TRAVEL_HALF_LIFE_MIN) - 0.5) < 1e-9

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    engine = HubEngine(
        specialty_matcher=_engine()._matcher,
        router=_FakeRouter({"R001": (20 * 60, 5000), "R002": (8 * 60, 4000)}),
    )
    for h in (
        _hospital("R001", "[테스트] 직선 가깝지만 강 건너 (ETA 20분)", 35.1980, 128.1080, 3, beds_by_type={"ER_ADULT": 3}),
        _hospital("R002", "[테스트] 직선 조금 멀지만 길 좋음 (ETA 8분)", 35.1800, 128.1520, 3, beds_by_type={"ER_ADULT": 3},
                  bed_rel=BedReliabilityInput(predictedSurvivalSec=2400.0, bornAt=now_iso, authorityAtSend=1.0,
                                              ttlSec=2400.0, modelTag="test")),
        _hospital("R003", "[테스트] 반경 밖, ETA 없음", 35.1800, 128.2400, 3, beds_by_type={"ER_ADULT": 3}),
    ):
        engine.update_hospital_info(h)

    result = engine.process_voice_summary(_voice("case-travel-test"), _TEST_GPS, max_zone=3)
    by_id = {h.hospitalId: h for h in result.hospitals}
    for h in result.hospitals:
        print(f"  {h.hospitalId} 직선 {h.distanceKm}km → 이동 {h.travelMin}분({h.travelBasis}), 점수 {h.finalScore}")
    assert [h.hospitalId for h in result.hospitals][:2] == ["R002", "R001"], "직선거리가 아니라 ETA로 앞서야 한다"
    assert by_id["R001"].travelBasis == by_id["R002"].travelBasis == "eta"
    assert by_id["R003"].travelBasis == "estimate" and by_id["R003"].etaMin is None
    ratios = sorted([20 / by_id["R001"].distanceKm, 8 / by_id["R002"].distanceKm])
    expected = by_id["R003"].distanceKm * (sum(ratios) / 2)
    assert abs(by_id["R003"].travelMin - expected) < 0.5, "ETA 없는 병원은 같은 사건 ETA 비율 중앙값으로 추정해야 한다"
    assert abs(by_id["R002"].bedReliability.horizonSec - 8 * 60) < 1.0, "rArrive의 도착 시점은 ETA여야 한다"
    print("  [확인] ETA 기준 순위, ETA 없는 병원은 보정 추정, 병상 신뢰도 도착 시점 = ETA")


def test_gps_fallback_and_message_type() -> None:
    print("\n=== 위치 대체 표시·메시지 구분자 확인 ===")
    engine = _engine()
    engine.update_hospital_info(_hospital("G001", "[테스트] 병원", 35.1810, 128.1090, 2, beds_by_type={"ER_ADULT": 2}))
    result = engine.process_voice_summary(_voice("case-gps-fallback"), _TEST_GPS, max_zone=1, gps_fallback=True)
    dumped = result.model_dump()
    assert dumped["type"] == "match_result", "HubMatchResult에 type 구분자가 실려야 한다"
    assert dumped["ambulanceGpsFallback"] is True, "기본 좌표로 대체한 사실이 결과에 실려야 한다"
    normal = engine.process_voice_summary(_voice("case-gps-normal"), _TEST_GPS, max_zone=1)
    assert normal.ambulanceGpsFallback is False
    print("  [확인] type=match_result, 대체 좌표 사건만 ambulanceGpsFallback=True")


def test_refresh_case() -> None:
    """진행 중 사건 재계산: 바뀐 게 없으면 None, 병상이 바뀌면 새 결과 + 의사결정 로그."""
    print("\n=== 주기적 재계산 확인: 변화 없으면 조용히, 병상이 바뀌면 다시 보냄 ===")
    engine = _engine()
    engine.update_hospital_info(_hospital("P001", "[테스트] 병원", 35.1810, 128.1090, 4, beds_by_type={"ER_ADULT": 4}))
    case_id = "case-refresh-test"
    engine.process_voice_summary(_voice(case_id), _TEST_GPS, max_zone=1)
    assert engine.get_active_case_ids() == [case_id]
    assert engine.refresh_case(case_id, _TEST_GPS) is None, "아무것도 안 바뀌었으면 다시 보낼 필요 없다"

    engine.update_hospital_info(_hospital("P001", "[테스트] 병원", 35.1810, 128.1090, 1, beds_by_type={"ER_ADULT": 1}))
    updated = engine.refresh_case(case_id, _TEST_GPS)
    assert updated is not None and updated.hospitals[0].availableBedCount == 1, "병상이 바뀌면 새 결과를 돌려줘야 한다"
    with decision_log.LOG_PATH.open(encoding="utf-8") as f:
        last = [line for line in f if line.strip()][-1]
    assert '"eventType": "hub_match_refreshed"' in last, "순위·병상이 바뀐 재계산은 의사결정 로그에 남아야 한다"
    print("  [확인] 변화 없음 → None, 병상 4→1 → 재전송 대상 + hub_match_refreshed 로그")


def test_state_roundtrip() -> None:
    """디스크 저장·복구: 병원·승인 상태·병상 오버레이·사건이 살아나고, 통화 원문은 저장 안 됨."""
    print("\n=== 상태 저장·복구 확인: 재시작해도 병원·승인·병상 차감이 남고 통화 원문은 안 남음 ===")
    import json

    engine = _engine()
    engine.update_hospital_info(_hospital("S001", "[테스트] 병원", 35.1810, 128.1090, 5, beds_by_type={"ER_ADULT": 5}))
    engine.update_ambulance_info(AmbulanceInfo(apid="A9", name="구급 9호차", gps=_TEST_GPS, voicePort=5002,
                                               updatedAt="2026-09-28T00:00:00Z"))
    case_id = "case-state-test"
    secret = "환자 홍길동 010-0000-0000 통화 원문"
    engine.register_case(case_id, "A9")
    engine.process_voice_summary(_voice(case_id, raw_text=secret), _TEST_GPS, max_zone=1)
    engine.apply_approval_action(_action(case_id, "final_approval", "S001"))
    assert engine.take_dirty() is True and engine.take_dirty() is False, "변경 표시는 한 번 읽으면 지워져야 한다"

    serialized = json.dumps(engine.export_state(), ensure_ascii=False)
    assert secret not in serialized, "통화 원문이 상태 파일에 들어가면 안 된다"

    restored = HubEngine(specialty_matcher=engine._matcher)
    counts = restored.import_state(json.loads(serialized))
    print(f"  복구: {counts}")
    assert counts == {"hospitals": 1, "ambulances": 1, "cases": 1}
    info = restored.get_hospital("S001")
    assert restored.effective_bed_count(info) == 4, "병상 차감(오버레이)이 복구돼야 한다"
    result = restored.get_case_result(case_id)
    assert result is not None and result.hospitals[0].status == "confirmed"
    assert restored.get_case_apid(case_id) == "A9" and restored.get_ambulance("A9").name == "구급 9호차"
    restored.apply_approval_action(_action(case_id, "final_approval", "S001"))
    assert restored.effective_bed_count(info) == 4, "복구 뒤에도 중복 최종 승인은 멱등이어야 한다"
    print("  [확인] 병원·구급차·사건·확정 상태·병상 차감 복구, 복구 뒤 멱등성 유지, 통화 원문 미저장")


def test_decision_log_chain() -> None:
    """해시 체인: 중간 줄 삭제·내용 수정 후 hash 재계산을 잡아내고, 체인 이전 기록은 통과."""
    print("\n=== 의사결정 로그 해시 체인 확인 ===")
    import json
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "log.jsonl"
        # 체인 이전(prevHash 없는) 기록 2줄 → 그 뒤로 체인 기록 3줄
        legacy = []
        for i in range(2):
            ts, payload = f"2026-01-0{i + 1}T00:00:00Z", {"n": i}
            legacy.append({"timestamp": ts, "eventType": "legacy", "payload": payload,
                           "hash": decision_log._hash_entry(ts, "legacy", payload)})
        path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in legacy), encoding="utf-8")
        for i in range(3):
            decision_log.log_decision("chained", {"n": i}, log_path=path)
        assert decision_log.verify_log(path) == (True, 5), "체인 이전 기록 + 체인 기록이 함께 통과해야 한다"

        lines = path.read_text(encoding="utf-8").splitlines()

        path.write_text("\n".join(lines[:3] + lines[4:]) + "\n", encoding="utf-8")
        assert decision_log.verify_log(path)[0] is False, "중간 줄 삭제를 잡아야 한다"

        forged = json.loads(lines[3])
        forged["payload"] = {"n": 999}
        forged["hash"] = decision_log._hash_entry(forged["timestamp"], forged["eventType"], forged["payload"],
                                                  forged["prevHash"])
        path.write_text("\n".join(lines[:3] + [json.dumps(forged, ensure_ascii=False)] + lines[4:]) + "\n",
                        encoding="utf-8")
        assert decision_log.verify_log(path)[0] is False, "내용 수정 후 hash를 다시 계산해도 다음 줄에서 잡아야 한다"

        path.write_text("\n".join(lines[:3] + [lines[0]] + lines[3:]) + "\n", encoding="utf-8")
        assert decision_log.verify_log(path)[0] is False, "체인 시작 뒤 끼워 넣은 체인 밖 줄을 잡아야 한다"
    print("  [확인] 체인 이전 기록 통과, 중간 삭제·수정 후 재해시·끼워 넣기 모두 탐지")


if __name__ == "__main__":
    main()
