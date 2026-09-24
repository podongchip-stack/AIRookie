"""병원 거절 로그 — 어휘·기록·집계.

왜 이유를 나눠 받아야 하나
--------------------------
이유 없이 거절 횟수만 세면 성격이 전혀 다른 것들이 한 덩어리가 된다.

    A병원 거절 3회 → 점수 하락
      실제로는: 화상 병동이 아예 없음        ← 영구적
                그날 당직이 정형외과였음      ← 그날만
                마침 수술방이 다 차 있었음    ← 그 순간만

뒤의 둘을 앞의 것처럼 다루면 **일시적 사정 때문에 그 병원을 영구히 후보에서
밀어내게 된다.** 뺑뺑이를 줄이려다 선택지를 좁히는 결과라 목적과 정반대다.

그래서 이유마다 **갱신 대상이 다르다**. 그게 아래 4개 축의 기준이다.

    구조적  → 역량 벡터를 수정한다 (그리고 E-Gen 신고가 틀렸다는 증거가 된다)
    주기적  → 시간대·요일 패턴으로 남긴다. 상수 점수에 반영하면 안 된다
    순간적  → 그때의 여건일 뿐 병원 속성이 아니다
    환자    → 병원 속성이 아니라 환자-병원 조합의 문제다

받는 쪽 원칙 — 관대하게 받는다
------------------------------
지금 dashboard의 "수용 불가" 버튼은 이유를 묻지 않는다. 그 UI가 바뀔 때까지
기다리면 그동안의 로그가 0건이 되고, 로그는 나중에 소급해서 만들 수 없다.

그래서 **이유가 없어도 받는다**(`UNSPECIFIED`로 기록). 필드 이름도 여러 표기를
받아준다. 모르는 필드는 버리지 않고 `extra`에 보존한다 — 나중에 스키마가 바뀌어도
그 사이 로그가 죽지 않게 하려는 것이다. 스냅샷에 가공 전 원본을 남기는 것과 같은 이유다.

집계
----
    python -m hospital_score.rejection --summary
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

#: 로그 저장 위치. data/ 아래라 .gitignore에 걸려 커밋되지 않는다
LOG_DIR = Path(__file__).resolve().parent.parent / "data" / "rejections"

#: 거절 이유가 영향을 주는 축
AXIS_STRUCTURAL = "structural"  # 영구 — 역량 벡터를 고쳐야 한다
AXIS_PERIODIC = "periodic"  # 반복되나 조건부 — 시간대 패턴
AXIS_MOMENTARY = "momentary"  # 그때뿐 — 여건
AXIS_PATIENT = "patient"  # 환자-병원 조합
AXIS_UNKNOWN = "unknown"  # 이유 미기재 · 미등록 코드

#: 이유 코드 -> (축, 설명). dashboard의 거절 사유 선택지가 이 어휘를 따르면 된다
REASON_AXIS: dict[str, tuple[str, str]] = {
    "NO_WARD": (AXIS_STRUCTURAL, "해당 병동·시설 없음"),
    "NO_DEPARTMENT": (AXIS_STRUCTURAL, "그 진료과 자체가 없음"),
    "NO_EQUIPMENT": (AXIS_STRUCTURAL, "필요 장비 없음"),
    "ON_CALL_MISMATCH": (AXIS_PERIODIC, "당직자 전공 불일치"),
    "NIGHT_UNAVAILABLE": (AXIS_PERIODIC, "야간 미운영"),
    "BEDS_FULL": (AXIS_MOMENTARY, "병상 만실"),
    "OR_OCCUPIED": (AXIS_MOMENTARY, "수술방·시술실 사용 중"),
    "STAFF_BUSY": (AXIS_MOMENTARY, "의료진이 다른 환자 대응 중"),
    "SEVERITY_EXCEEDED": (AXIS_PATIENT, "중증도 초과"),
    "AGE_LIMIT": (AXIS_PATIENT, "연령·체중 제한"),
    "NO_RESPONSE": (AXIS_UNKNOWN, "응답 없음"),
    "UNSPECIFIED": (AXIS_UNKNOWN, "이유 미기재"),
    "OTHER": (AXIS_UNKNOWN, "그 외"),
}

#: 우리가 아는 필드의 여러 표기. hub·dashboard가 어느 쪽으로 보내도 받는다
ALIASES: dict[str, tuple[str, ...]] = {
    "hospitalId": ("hospitalId", "hospital_id", "hpid"),
    "caseId": ("caseId", "case_id"),
    "timestamp": ("timestamp", "ts", "time"),
    "diseaseGroup": ("diseaseGroup", "disease_group", "group"),
    "severity": ("severity", "severity_tag"),
    "reasonCode": ("reasonCode", "reason_code", "reason"),
    "reasonNote": ("reasonNote", "reason_note", "note"),
    "declaredAtRequest": ("declaredAtRequest", "declared"),
    "responseSec": ("responseSec", "response_sec"),
}


@dataclass
class RejectionRecord:
    """거절 한 건. 필수는 `hospitalId` 하나뿐이다."""

    hospitalId: str
    timestamp: str
    reasonCode: str
    axis: str
    caseId: str | None = None
    diseaseGroup: str | None = None
    severity: str | None = None
    reasonNote: str | None = None
    #: 물어볼 당시 E-Gen 신고가 뭐였나. "가능이라 했는데 거절"을 세려면 필요하다
    declaredAtRequest: str | None = None
    responseSec: float | None = None
    #: 우리가 모르는 필드. 버리지 않고 보존한다
    extra: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False)


def _pick(payload: dict, key: str):
    for alias in ALIASES[key]:
        if alias in payload and payload[alias] not in (None, ""):
            return payload[alias]
    return None


def normalize(payload: dict) -> RejectionRecord:
    """hub가 보낸 것을 기록 가능한 형태로 만든다.

    이유가 없거나 모르는 코드여도 예외를 내지 않는다 — 받아서 남기는 것이 우선이고,
    분류는 나중에 다시 할 수 있다. 반대로 거부하면 그 로그는 영영 사라진다.
    """
    hospital_id = _pick(payload, "hospitalId")
    if not hospital_id:
        raise ValueError("hospitalId(또는 hospital_id/hpid)가 없다")

    raw_reason = _pick(payload, "reasonCode")
    reason = str(raw_reason).strip().upper() if raw_reason else "UNSPECIFIED"
    axis = REASON_AXIS.get(reason, (AXIS_UNKNOWN, ""))[0]

    known = {alias for aliases in ALIASES.values() for alias in aliases}
    extra = {k: v for k, v in payload.items() if k not in known}

    timestamp = _pick(payload, "timestamp") or datetime.now(timezone.utc).isoformat()
    response_sec = _pick(payload, "responseSec")

    return RejectionRecord(
        hospitalId=str(hospital_id),
        timestamp=str(timestamp),
        reasonCode=reason,
        axis=axis,
        caseId=_pick(payload, "caseId"),
        diseaseGroup=_pick(payload, "diseaseGroup"),
        severity=_pick(payload, "severity"),
        reasonNote=_pick(payload, "reasonNote"),
        declaredAtRequest=_pick(payload, "declaredAtRequest"),
        responseSec=float(response_sec) if response_sec is not None else None,
        extra=extra,
    )


def append(record: RejectionRecord) -> Path:
    """날짜별 JSONL에 덧붙인다. 스냅샷과 같은 append-only 방식."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    day = record.timestamp[:10] if len(record.timestamp) >= 10 else "unknown"
    path = LOG_DIR / f"{day}.jsonl"
    with path.open("a", encoding="utf-8") as fp:
        fp.write(record.to_json() + "\n")
    return path


def load_all() -> list[dict]:
    if not LOG_DIR.exists():
        return []
    records = []
    for path in sorted(LOG_DIR.glob("*.jsonl")):
        for line in path.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def summarize(records: list[dict]) -> str:
    """축별로 나눠 보여준다. 축이 다르면 점수에 반영하는 방식도 달라야 한다."""
    if not records:
        return (
            "거절 로그가 아직 없다.\n"
            "  dashboard의 '수용 불가' 버튼이 이유를 묻도록 바뀌고, hub가 그 값을\n"
            "  POST /hub/rejection 으로 넘겨주면 여기에 쌓인다.\n"
            "  이유가 없어도 UNSPECIFIED로 기록되므로, hub는 지금 형태 그대로 보내도 된다."
        )

    lines = [f"거절 로그 {len(records):,}건"]
    by_axis = Counter(r.get("axis", AXIS_UNKNOWN) for r in records)
    by_reason = Counter(r.get("reasonCode", "UNSPECIFIED") for r in records)

    axis_label = {
        AXIS_STRUCTURAL: "구조적 (역량 벡터를 고쳐야 함)",
        AXIS_PERIODIC: "주기적 (시간대 패턴으로만)",
        AXIS_MOMENTARY: "순간적 (여건일 뿐)",
        AXIS_PATIENT: "환자 요인 (병원 속성 아님)",
        AXIS_UNKNOWN: "미분류",
    }
    lines.append("")
    for axis, count in by_axis.most_common():
        lines.append(f"  {axis_label.get(axis, axis):<32}{count:>6}건")
        for reason, n in by_reason.most_common():
            if REASON_AXIS.get(reason, (AXIS_UNKNOWN, ""))[0] == axis:
                desc = REASON_AXIS.get(reason, ("", "미등록 코드"))[1]
                lines.append(f"      {reason:<20}{n:>5}  {desc}")

    # 구조적 거절이 반복되는 병원 = 신고가 틀렸을 가능성이 높은 곳
    structural = defaultdict(Counter)
    for record in records:
        if record.get("axis") == AXIS_STRUCTURAL:
            structural[record["hospitalId"]][record.get("diseaseGroup") or "?"] += 1
    if structural:
        lines.append("")
        lines.append("  구조적 거절이 반복되는 병원 (신고 오류 후보):")
        for hospital_id, groups in sorted(
            structural.items(), key=lambda kv: -sum(kv[1].values())
        )[:10]:
            detail = ", ".join(f"{g} {n}회" for g, n in groups.most_common(3))
            lines.append(f"      {hospital_id:<12}{detail}")

    # 신고는 가능이었는데 거절당한 건 — 신고 정확도의 직접 측정
    declared_yes = [r for r in records if r.get("declaredAtRequest") == "Y"]
    if declared_yes:
        lines.append("")
        lines.append(
            f"  '가능' 신고였는데 거절: {len(declared_yes)}건 "
            f"({len(declared_yes) / len(records):.1%}) — 신고 정확도의 직접 지표"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="거절 로그 집계")
    parser.add_argument("--summary", action="store_true", help="축별 집계 출력")
    parser.add_argument("--vocab", action="store_true", help="이유 코드 어휘 출력")
    args = parser.parse_args()

    if args.vocab:
        print(f"{'코드':<20}{'축':<12}설명")
        for code, (axis, desc) in REASON_AXIS.items():
            print(f"{code:<20}{axis:<12}{desc}")
    else:
        print(summarize(load_all()))
