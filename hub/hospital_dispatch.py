"""대시보드 전달 대상만 고르는 규칙. 내부 후보·거절 이력은 삭제하지 않는다.

spider 역량 모형은 임상 검증 전 시연 기준이다. 병원의 명시적 승인·이송 확정은
추정 역량보다 우선하며, 수용 가능을 보장하는 판정으로 사용하지 않는다.
"""
from __future__ import annotations

from typing import Any


def can_receive(match: Any) -> bool:
    get = match.get if isinstance(match, dict) else lambda key, default=None: getattr(match, key, default)
    if get("status") in ("approved", "confirmed"):
        return True  # 의료진의 명시적 수용 판단은 자동 모형보다 우선한다.
    suitability = get("ktasSuitability") or {}
    patient, hospital = suitability.get("patientKtas"), suitability.get("hospitalKtas")
    if patient is not None and hospital != patient:
        return False
    required, available = suitability.get("requiredCapacity"), suitability.get("effectiveCapacity")
    if required is not None and available is not None and available < required:
        return False
    return not get("spiderBlocked")


def dashboard_payload(payload: dict) -> dict:
    """폰·패드·웹·관제·재접속이 동일한 전달 목록을 보도록 변환한다(멱등)."""
    if (payload.get("dispatchPolicy") or {}).get("rule") == "spider_ktas_v1":
        return payload
    hospitals = payload.get("hospitals") or []
    targets = [h for h in hospitals if can_receive(h)]
    omitted = [{"hospitalId": h["hospitalId"], "reason": h.get("spiderBlocked") or "patient_hospital_ktas_mismatch"} for h in hospitals if not can_receive(h)]
    return {**payload, "hospitals": targets, "dispatchPolicy": {
        "source": "rule", "rule": "spider_ktas_v1", "clinicallyValidated": False,
        "ktasLevel": (payload.get("patientInfo") or {}).get("ktasLevel"),
        "consideredCount": len(hospitals), "targetCount": len(targets), "omitted": omitted,
    }}
