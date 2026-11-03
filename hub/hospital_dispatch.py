"""대시보드 전달 대상만 고르는 규칙. 내부 후보·거절 이력은 삭제하지 않는다.

spider 역량 모형은 임상 검증 전 시연 기준이다. 병원의 명시적 승인·이송 확정은
추정 역량보다 우선하며, 수용 가능을 보장하는 판정으로 사용하지 않는다.
"""
from __future__ import annotations

from typing import Any


def can_receive(match: Any) -> bool:
    """전달 대상(보고서 기준, 2026-11-04): 확인된 사실로 처치할 수 없는 병원(ktasSuitability.confirmedBlock — 혈관조영·CT
    미운영 신고, 알려진 등급 미달)만 뺀다. 줄이 없어도 정보가 없거나 역량이 추정상 모자란 병원은 보내고, 정렬이 맨 뒤 띠에
    둔다. 등급이 높은 병원도 받는다 — 대표 KTAS(hospitalKtas)는 표시용이다(정확 일치 필터는 권역센터가 KTAS 2 환자를
    못 받게 해서 뺐다). 수용·확정한 병원은 늘 받는다."""
    get = match.get if isinstance(match, dict) else lambda key, default=None: getattr(match, key, default)
    if get("status") in ("approved", "confirmed"):
        return True
    suitability = get("ktasSuitability")
    if suitability:
        return not suitability.get("confirmedBlock")
    return not get("spiderBlocked")  # 판정 근거가 없는 예전 결과


def dashboard_payload(payload: dict) -> dict:
    """폰·패드·웹·관제·재접속이 동일한 전달 목록을 보도록 변환한다(멱등)."""
    if (payload.get("dispatchPolicy") or {}).get("rule") == "spider_ktas_v1":
        return payload
    hospitals = payload.get("hospitals") or []
    targets = [h for h in hospitals if can_receive(h)]
    omitted = [{"hospitalId": h["hospitalId"], "reason": (h.get("ktasSuitability") or {}).get("confirmedBlock") or h.get("spiderBlocked")} for h in hospitals if not can_receive(h)]
    return {**payload, "hospitals": targets, "dispatchPolicy": {
        "source": "rule", "rule": "spider_ktas_v1", "clinicallyValidated": False,
        "ktasLevel": (payload.get("patientInfo") or {}).get("ktasLevel"),
        "consideredCount": len(hospitals), "targetCount": len(targets), "omitted": omitted,
    }}
