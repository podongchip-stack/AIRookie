"""상황실 배정 에이전트 — 1단계: 충돌 감지(규칙 기반, 2026-11-04).

평상시엔 구급대원이 hub의 1순위 수용 병원을 보고 바로 이송 승인한다. 여러 사건이 같은 병원을 1순위로 두고 그 병원 여력이
모자라면 각자 승인하는 순간 한 병원에 몰리므로, 그 사건들을 "관제 판단 대기"로 묶어 상황실이 정하게 한다.

충돌 = 이송 확정 전인 사건 2건 이상의 1순위 수용 병원이 같고, 그 병원 여력(응급실 가용 − 이송 중, hub 표시값)이 사건 수보다
적을 때. 병상이 미상이거나 1일 넘은 값이면 여력을 모르므로 2건 이상이면 충돌로 본다 — 넉넉하다고 보면 몰림을 놓친다.
보고서의 "10분 안 2명 초과" 창 규칙 대신 이 기준을 쓴다(창은 실측에서 거절을 늘려 hub 순위에서 뺐다 — spider_rule.py ⚠).

생성형이 아니라 규칙이다(source "rule"). 엔진·소켓을 모르는 순수 함수만 두고 배선은 app.py가 한다.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

RULE = "top_accepted_overlap_v1"


def _get(obj: Any, key: str, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def top_accepted(result: Any) -> str | None:
    """사건의 1순위 수용 병원. hub 정렬(확정 → 수용 → 나머지)을 그대로 믿고 수용 병원 중 맨 앞을 고른다.
    이송이 확정된 사건은 이미 정해졌으므로 None."""
    hospitals = _get(result, "hospitals") or []
    if any(_get(h, "status") == "confirmed" for h in hospitals):
        return None
    for h in hospitals:
        if _get(h, "status") == "approved" and not _get(h, "excluded") and not _get(h, "notSelected"):
            return _get(h, "hospitalId")
    return None


def _ktas(result: Any) -> int:
    level = _get(_get(result, "patientInfo") or {}, "ktasLevel")
    return level if isinstance(level, int) else 9


def detect_conflicts(results: Iterable[Any], capacity_of: Callable[[str], int | None]) -> list[dict]:
    """충돌 묶음 목록. capacity_of(hospitalId)는 여력(가용 − 이송 중), 모르면 None.
    사건은 위급한 순(KTAS 낮은 숫자, 같으면 들어온 순)으로 적는다 — 배분 안을 만들 때 그 순서로 자리를 준다."""
    by_hospital: dict[str, list[tuple[int, int, str]]] = {}
    for index, result in enumerate(results):
        hospital_id = top_accepted(result)
        if hospital_id is not None:
            by_hospital.setdefault(hospital_id, []).append((_ktas(result), index, _get(result, "caseId")))
    groups = []
    for hospital_id, cases in by_hospital.items():
        if len(cases) < 2:
            continue
        capacity = capacity_of(hospital_id)
        if capacity is not None and capacity >= len(cases):
            continue
        groups.append({
            "hospitalId": hospital_id,
            "caseIds": [case_id for _, _, case_id in sorted(cases)],
            "capacity": capacity,
            "capacityKnown": capacity is not None,
            "source": "rule",
            "rule": RULE,
        })
    return sorted(groups, key=lambda g: g["hospitalId"])


def pending_cases(groups: Iterable[dict]) -> dict[str, str]:
    """caseId → 충돌 병원. 구급대 화면의 "관제 판단 대기" 대상."""
    return {case_id: g["hospitalId"] for g in groups for case_id in g["caseIds"]}


# ── 2단계: 배분 안 + 근거(2026-11-04) ─────────────────────────────────────────
# 묶인 사건을 위급한 순(KTAS)으로 놓고, 사건마다 수용 병원 중 줄 길이(분)가 가장 짧은 곳에 자리를 준다. 자리를 줄 때마다
# 그 병원 여력을 하나 줄이고 부하(분)를 더해, 여력이 바닥난 병원은 다음 사건에게 넘어가지 않는다(다른 수용 병원이
# 있을 때) — 보고서 "가장 위급한 환자에게 먼저, 나머지는 다음 후보"를 여력 기준으로 한 것. 확정은 관제가 한다.

#: 같은 배분 안에서 앞 사건에 자리를 줄 때마다 그 병원 줄에 더하는 분 — hub 부하 페널티 상한(10분)과 같은 단위의 초안값
PLAN_LOAD_STEP_MIN = 10.0
#: 사건마다 근거에 싣는 후보 수(수용 병원 전부 + 판단 대기 상위 몇 곳)
EVIDENCE_PENDING = 3
#: 근거에 보이는 장비(E-Gen 운영 Y/N/N1) — 질환군 벽(심근경색 혈관조영·뇌졸중 CT)과 배후역량 대표
EVIDENCE_EQUIPMENT = ("CT", "ANGIO", "MRI", "ECMO")


def _line_key(h: dict) -> float:
    """정렬 기준 분. 줄이 없는 병원은 줄 있는 병원 뒤(이동 시간 + 1000)."""
    if h.get("spiderLen") is not None:
        return h["spiderLen"]
    return 1000.0 + (h.get("travelMin") or 0.0)


def hospital_evidence(match: dict, info: dict | None, required_department: str | None) -> dict:
    """한 병원의 추천 근거 — 필요한 것과 가진 것(장비·전문의·등급·병상)과 줄 길이 분해. 모두 규칙·공공데이터 값."""
    info = info or {}
    specialties = {s.get("department"): s.get("doctorCount") for s in info.get("specialties") or []}
    operating = info.get("equipmentOperating") or {}
    travel = match.get("travelMin")
    load = ((match.get("loadPenaltyMin") or 0.0) + (match.get("occupancyPenaltyMin") or 0.0)
            + (match.get("refusalPenaltyMin") or 0.0))
    line = match.get("spiderLen")
    suitability = match.get("ktasSuitability") or {}
    return {
        "hospitalId": match.get("hospitalId"),
        "name": match.get("name"),
        "status": match.get("status"),
        "rejectReason": match.get("rejectReason"),
        "emergencyLevel": match.get("emergencyLevel"),
        "travelMin": travel,
        "lineMin": line,
        # 줄 길이 = 이동 − 역량 이득 + 부하 → 이득 = 이동 + 부하 − 줄 길이(음수면 경증 센터 보존·역량 모자람 비용)
        "gainMin": round(travel + load - line, 1) if line is not None and travel is not None else None,
        "loadMin": round(load, 1),
        "lineBlocked": match.get("spiderBlocked"),
        # 다른 사건에서 받은 수용 곤란의 되먹임 설명(순간적 30분 +분 / 구조적 같은 질환군 뒤로)
        "refusalReasons": match.get("refusalReasons") or [],
        "confirmedBlock": suitability.get("confirmedBlock"),
        "availableBedCount": match.get("availableBedCount"),
        "bedCountUnknown": match.get("bedCountUnknown"),
        "erBedCapacity": match.get("erBedCapacity"),
        "inFlightCount": match.get("inFlightCount") or 0,
        # 병상 값 위험 등급(AI 정보 생존 모델 → 등급) · 최종 확인 시각 — 수용 확률이 아니라 숫자가 도착까지 유지될지
        "bedRisk": (match.get("bedReliability") or {}).get("riskLevel"),
        "bedCheckedAt": (match.get("bedReliability") or {}).get("checkedAt"),
        "equipment": {key: operating.get(key) for key in EVIDENCE_EQUIPMENT},
        "emDoctors": specialties.get("응급의학과"),
        "requiredDepartment": required_department,
        "deptDoctors": specialties.get(required_department) if required_department else None,
        "effectiveCapacity": suitability.get("effectiveCapacity"),
        "requiredCapacity": suitability.get("requiredCapacity"),
    }


def _receivable(h: dict) -> bool:
    return h.get("status") == "approved" and not h.get("excluded") and not h.get("notSelected")


def _designatable(h: dict) -> bool:
    """수용 회신 전이지만 상황실이 지정할 수 있는 병원(2026-11-04) — 판단 대기이고, 확인된 사실로 처치 불가가 아니며,
    첫 전송 보류(최근 차단 공지)·제외가 아닌 곳. 줄이 있는 병원만(추정상 모자란 병원을 상황실이 고르게 제안하진 않는다)."""
    return (h.get("status") == "pending" and not h.get("excluded") and not h.get("dispatchHold")
            and not (h.get("ktasSuitability") or {}).get("confirmedBlock") and h.get("spiderLen") is not None)


def build_proposal(group: dict, results: dict[str, dict], infos: dict[str, dict],
                   capacity_of: Callable[[str], int | None]) -> dict:
    """충돌 묶음 하나의 배분 안. results는 caseId → 매칭 결과(dump), infos는 hospitalId → 병원 정보(dump)."""
    remaining: dict[str, int | None] = {}
    used: dict[str, int] = {}
    cases = []
    for case_id in group["caseIds"]:  # 이미 위급한 순
        result = results.get(case_id) or {}
        patient = result.get("patientInfo") or {}
        hospitals = result.get("hospitals") or []
        accepted = [h for h in hospitals if _receivable(h)]
        for h in accepted:
            remaining.setdefault(h["hospitalId"], capacity_of(h["hospitalId"]))
        ranked = sorted(accepted, key=lambda h: _line_key(h) + PLAN_LOAD_STEP_MIN * used.get(h["hospitalId"], 0))
        with_room = [h for h in ranked if remaining[h["hospitalId"]] is None or remaining[h["hospitalId"]] > 0]
        pick = (with_room or ranked or [None])[0]
        over = pick is not None and not with_room
        designate = False
        if pick is None:  # 수용한 병원이 없다 — 상황실 지정 후보(판단 대기 중 줄 최단)를 제안한다
            options = sorted((h for h in hospitals if _designatable(h)),
                             key=lambda h: _line_key(h) + PLAN_LOAD_STEP_MIN * used.get(h["hospitalId"], 0))
            if options:
                pick, designate = options[0], True
                remaining.setdefault(pick["hospitalId"], capacity_of(pick["hospitalId"]))
        if pick is not None:
            hid = pick["hospitalId"]
            used[hid] = used.get(hid, 0) + 1
            if remaining[hid] is not None:
                remaining[hid] -= 1
        top = accepted[0] if accepted else None
        if pick is None:
            reason = "수용한 병원도 지정할 병원도 없습니다 — 수용 확인 요청이나 범위 확장이 필요합니다"
        elif designate:
            reason = (f"수용 회신이 없습니다 — 판단 대기 중 줄 길이 최단 {pick.get('name')}을(를) 상황실 지정으로 제안"
                      " (지정하면 병원에 지정 통보)")
        elif over:
            reason = f"수용 병원이 모두 여력 소진 — 가장 짧은 {pick.get('name')}(여력 초과)"
        elif top is not None and pick["hospitalId"] != top["hospitalId"]:
            # 줄 길이 차이엔 역량 이득이 섞여 "몇 분 더 걸린다"로 읽히면 틀린다 — 실제 이동 시간 차이만 보인다
            travel_diff = (pick.get("travelMin") or 0.0) - (top.get("travelMin") or 0.0)
            reason = (f"{top.get('name')} 여력은 더 위급한 환자에게 — 다음 수용 병원 {pick.get('name')}"
                      f"(이동 {'+' if travel_diff >= 0 else '−'}{abs(travel_diff):.0f}분)")
        else:
            reason = f"Pre-KTAS {patient.get('ktasLevel') or '-'} · 수용 병원 중 줄 길이 최단"
        pending = [h for h in hospitals if h.get("status") == "pending"][:EVIDENCE_PENDING]
        required = patient.get("requiredDepartment")
        cases.append({
            "caseId": case_id,
            "ambulanceName": result.get("ambulanceName"),
            "ktasLevel": patient.get("ktasLevel"),
            "expectedDiagnosis": patient.get("expectedDiagnosis"),
            "chiefComplaint": patient.get("chiefComplaint"),
            "requiredDepartment": required,
            "proposedHospitalId": pick["hospitalId"] if pick else None,
            "overCapacity": over,
            "designation": designate,
            "reason": reason,
            "candidates": [hospital_evidence(h, infos.get(h["hospitalId"]), required) for h in ranked + pending],
        })
    return {"hospitalId": group["hospitalId"], "cases": cases, "source": "rule", "rule": RULE,
            "clinicallyValidated": False}
