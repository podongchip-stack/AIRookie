"""병원 수용가능성 점수 — 규칙 기반, 근거를 남긴다.

무엇을 내보내나
--------------
병원마다 두 부분이다. 축이 다르면 쓰는 쪽도 달라야 한다.

    여건(conditions)   환자와 무관한 스칼라 — 병상 가동률·과밀·피드 신선도
    역량(capabilities) 환자에 따라 달라지는 15그룹 벡터

병원당 단일 점수는 만들지 않는다. 심근경색 환자와 화상 환자에게 같은 병원의
수용가능성이 다르기 때문이다.

왜 "최적값"을 찾지 않나
----------------------
최적화하려면 정답이 있어야 하는데, "이 병원이 이 환자를 실제로 받았는가"의 정답이
없다. 그건 시스템이 운영되며 거절 로그가 쌓여야 나온다(`rejection.py`).
쓸 수 있는 대용 정답은 전부 부족하다 — 병원의 `불가능` 신고는 전체의 1.2%인 데다
그건 우리 **입력**이지 정답이 아니고, 전문병원 지정은 5개 분야뿐이다.

없는 정답을 지어내는 대신 셋으로 간다.

1. **불변식** — 점수가 반드시 지켜야 할 순서를 못박는다(`INVARIANTS`, `--check`).
   가중치를 어떻게 잡든 이 순서만 안 깨지면 된다. 대부분의 파라미터 논쟁이 여기서 사라진다
2. **실패 비용의 비대칭** — 받을 수 있는 병원을 후보에서 빼는 것(골든타임 손실)이
   못 받는 병원을 올리는 것(전화 한 번 더)보다 훨씬 나쁘다. 애매하면 남긴다
3. **계층(tier)** — 근거 강도의 순서만 정한다. 근거 없이 `0.73` 같은 값을 두면
   임의값에 정밀함의 외양만 입히는 것이다

**절대값은 info가 정하지 않는다.** 거리와의 트레이드오프("2km 가깝지만 근거가 약한 병원
vs 5km 멀지만 확실한 병원")는 거리를 가진 hub가 결정한다. info는 순서와 근거만 준다.

점수와 신뢰도를 곱하지 않는 이유
------------------------------
섞으면 "확실히 낮음"과 "모르겠음"이 구분되지 않는다. 미상과 확인된 만실을 구분해온
기존 원칙과 같다. `score`와 `confidence`는 끝까지 별도 필드다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from . import dataset as D
from . import hira_files as HF
from . import vocabulary as V

CACHE_DIR = HF.CACHE_DIR
JOIN_PATH = CACHE_DIR / "egen_hira_join.json"
SPECIALISTS_PATH = CACHE_DIR / "specialists.json"

# --- 계층 -------------------------------------------------------------------
# 근거 강도의 순서다. 값 자체에 의미를 두지 않는다 — 순서만 쓴다.

TIER_DECLARED_NO = 1  # 병원이 직접 못 받는다고 함
TIER_UNKNOWN_BARE = 2  # 미상, 뒷받침할 근거 없음
TIER_UNKNOWN_SPECIALIST = 3  # 미상이지만 해당 진료과 전문의가 있음
TIER_UNKNOWN_DESIGNATED = 4  # 미상이지만 그 분야 전문병원으로 지정됨
TIER_DECLARED_YES = 5  # 병원이 가능하다고 신고
MAX_TIER = TIER_DECLARED_YES

TIER_LABEL = {
    TIER_DECLARED_NO: "declared_no",
    TIER_UNKNOWN_BARE: "unknown_bare",
    TIER_UNKNOWN_SPECIALIST: "unknown_specialist",
    TIER_UNKNOWN_DESIGNATED: "unknown_designated",
    TIER_DECLARED_YES: "declared_yes",
}

#: 하루 넘게 갱신이 없으면 "실시간"이라 부를 수 없다고 본다.
#: 근거: `hvidate` 갱신 경과 중앙값 5분, 443곳 중 88.7%가 10분 이내
STALE_THRESHOLD = timedelta(days=1)

#: 항목 -> 그 역량에 필요한 진료과.
#: ⚠️ 이 표는 우리가 세운 것이고 외부 근거로 검증되지 않았다. 게다가 심평원 진료과가
#: **대분류만**(`순환기내과` 없이 `내과`) 오기 때문에 특정성이 낮다 — 실제로 `불가능`이라
#: 신고한 칸의 91.2%도 해당 진료과 전문의를 갖고 있었다. 그래서 전문의 유무는 점수를
#: **올리는** 근거가 아니라 "역량 없음으로 단정하지 못하게 막는" 하한으로만 쓴다
#: (TIER_UNKNOWN_SPECIALIST가 TIER_UNKNOWN_BARE보다 한 칸만 위인 이유).
ITEM_TO_DEPARTMENTS: dict[int, tuple[str, ...]] = {
    1: ("내과",), 2: ("신경과",), 3: ("신경외과",), 4: ("신경외과",),
    5: ("심장혈관흉부외과",), 6: ("심장혈관흉부외과",),
    7: ("외과",), 8: ("외과",), 9: ("외과",),
    10: ("소아청소년과",), 11: ("내과",), 12: ("소아청소년과",),
    13: ("내과",), 14: ("소아청소년과",), 15: ("소아청소년과",),
    16: ("산부인과",), 17: ("산부인과",), 18: ("산부인과",),
    19: ("성형외과",), 20: ("정형외과", "성형외과"), 21: ("정형외과", "성형외과"),
    22: ("내과",), 23: ("내과",), 24: ("정신건강의학과",), 25: ("안과",),
    26: ("영상의학과",), 27: ("영상의학과",), 28: ("응급의학과",),
}


@dataclass
class Conditions:
    """환자와 무관한 여건. 병원당 하나."""

    availableBeds: int | None = None
    totalBeds: int | None = None
    bedOccupancy: float | None = None
    overcrowded: bool = False
    bedCountUnknown: bool = True
    feedAgeMinutes: int | None = None
    stale: bool = False
    missingFromFeed: bool = False


@dataclass
class GroupScore:
    """한 질환군에 대한 판단."""

    group: str
    tier: int
    score: float
    status: str  # available / unavailable / unknown
    confidence: str  # high / medium / low
    basis: list[str] = field(default_factory=list)
    items: dict[int, str] = field(default_factory=dict)  # 항목번호 -> 신고값


@dataclass
class HospitalScore:
    hpid: str
    name: str
    emcls: str | None
    conditions: Conditions
    capabilities: dict[str, GroupScore]
    #: 판정에 **실제로 쓰인** 근거의 기계가 읽는 형태. 원자료 전량이 아니다
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "hospitalId": self.hpid,
            "name": self.name,
            "emcls": self.emcls,
            "conditions": self.conditions.__dict__,
            "evidence": self.evidence,
            "capabilities": {
                group: {
                    "status": score.status,
                    "tier": TIER_LABEL[score.tier],
                    "score": score.score,
                    "confidence": score.confidence,
                    "basis": score.basis,
                    "items": score.items,
                }
                for group, score in self.capabilities.items()
            },
        }


# --- 외부 근거 로딩 ----------------------------------------------------------


def load_specialists() -> dict[str, dict[str, int]]:
    """hpid -> {진료과: 전문의 수}. 캐시가 없으면 빈 dict."""
    if not SPECIALISTS_PATH.exists():
        return {}
    raw = json.loads(SPECIALISTS_PATH.read_text(encoding="utf-8"))
    return {
        hpid: {
            str(row.get("dgsbjtCdNm", "")): int(row.get("dtlSdrCnt") or 0) for row in rows
        }
        for hpid, rows in raw.items()
    }


def load_designations() -> dict[str, set[str]]:
    """hpid -> {전문병원 지정분야}.

    전문병원 지정 현황에는 좌표도 요양기관기호도 없어 **기관명으로만** 붙는다.
    그래서 결과는 하한이다 — 표기 차이로 놓치는 곳이 있다.
    """
    rows = HF.load_specialty_hospitals()
    if not rows:
        return {}

    name_to_hpid: dict[str, str] = {}
    if JOIN_PATH.exists():
        for hpid, row in json.loads(JOIN_PATH.read_text(encoding="utf-8")).items():
            for key in ("egenName", "hiraName"):
                if row.get(key):
                    name_to_hpid.setdefault(HF.normalize_name(row[key]), hpid)

    designations: dict[str, set[str]] = {}
    for row in rows:
        hpid = name_to_hpid.get(HF.normalize_name(row.get("의료기관명")))
        if hpid:
            designations.setdefault(hpid, set()).add(row.get("지정분야", ""))
    return designations


# --- 점수 산출 ---------------------------------------------------------------


def _item_tier(
    declared: str | None,
    item_no: int,
    departments: dict[str, int],
    designated_fields: set[str],
) -> tuple[int, list[str]]:
    """항목 하나의 계층과 근거를 정한다."""
    if declared == V.ACCEPT_YES:
        return TIER_DECLARED_YES, ["병원 신고: 수용 가능"]
    if declared == V.ACCEPT_NO:
        return TIER_DECLARED_NO, ["병원 신고: 수용 불가"]

    # 여기부터 미상. 뺄지 말지가 아니라 **무엇을 근거로 남길지**의 문제다
    basis: list[str] = ["병원 신고 없음(정보미제공)"]

    for field_name, item_nos in HF.FIELD_TO_MKIOSK.items():
        if item_no in item_nos and field_name in designated_fields:
            basis.append(f"전문병원 지정: {field_name}")
            return TIER_UNKNOWN_DESIGNATED, basis

    for department in ITEM_TO_DEPARTMENTS.get(item_no, ()):
        count = departments.get(department, 0)
        if count > 0:
            basis.append(f"{department} 전문의 {count}명")
            return TIER_UNKNOWN_SPECIALIST, basis

    basis.append("뒷받침할 외부 근거 없음")
    return TIER_UNKNOWN_BARE, basis


def _confidence(tier: int, stale: bool) -> str:
    """신뢰도. 점수와 곱하지 않고 끝까지 따로 간다."""
    if tier in (TIER_DECLARED_YES, TIER_DECLARED_NO):
        base = "high"
    elif tier == TIER_UNKNOWN_DESIGNATED:
        base = "medium"
    else:
        base = "low"
    if stale and base == "high":
        return "medium"  # 값은 있으나 언제 적힌 건지 믿기 어렵다
    return base


def _status(tier: int) -> str:
    if tier == TIER_DECLARED_YES:
        return "available"
    if tier == TIER_DECLARED_NO:
        return "unavailable"
    return "unknown"


def build_conditions(row: dict | None, now: datetime) -> Conditions:
    if row is None:
        # 명부에는 있는데 응답에 등장하지 않는다. "병상 0"과 절대 같지 않다
        return Conditions(missingFromFeed=True)

    available = D.parse_bed_count(row.get("hvec"))
    total = D.parse_bed_count(row.get("hvs38"))
    updated = D.parse_hvidate(row.get("hvidate"))
    age = int((now - updated).total_seconds() // 60) if updated else None

    occupancy = None
    if available is not None and total and total > 0:
        occupancy = round(max(0.0, 1 - max(0, available) / total), 3)

    return Conditions(
        availableBeds=available,
        totalBeds=total,
        bedOccupancy=occupancy,
        overcrowded=available is not None and available < 0,
        bedCountUnknown=available is None,
        feedAgeMinutes=age,
        stale=bool(updated and (now - updated) > STALE_THRESHOLD),
    )


#: 판정에 쓰는 진료과만 근거로 싣는다. 26개 과 전부가 아니라 이 목록만이다 —
#: 근거는 "판단에 실제로 쓰인 것"이어야 검증이 되고, 전량을 실으면 hub가 심평원
#: 어휘를 알아야 해석할 수 있게 된다
JUDGEMENT_DEPARTMENTS: tuple[str, ...] = tuple(
    sorted({dept for depts in ITEM_TO_DEPARTMENTS.values() for dept in depts})
)

#: E-Gen 가용병상 응답에 같이 오는 장비 가용 여부
EQUIPMENT_FIELDS = {"hvctayn": "CT", "hvangioayn": "ANGIO"}


def build_evidence(
    hpid: str,
    row: dict | None,
    departments: dict[str, int],
    designated: set[str],
) -> dict:
    """판정 근거를 기계가 읽는 형태로 모은다.

    `basis`가 사람이 읽는 문장이라면 이쪽은 대조용 값이다. hub나 dashboard가
    "이 점수가 왜 나왔나"를 확인할 수 있으면서도, 심평원 도메인 지식(진료과 코드
    체계·ykiho·전문병원 분야명)을 알 필요는 없게 하는 것이 목적이다.
    원자료를 통째로 넘기면 그 지식이 hub에 복제되고, 심평원 스키마가 바뀔 때
    hub까지 깨진다 — 오늘 겪은 2.7→2.8 같은 일이 그렇다.
    """
    evidence: dict = {}
    if designated:
        evidence["designatedFields"] = sorted(designated)

    used = {
        dept: count
        for dept, count in departments.items()
        if dept in JUDGEMENT_DEPARTMENTS and count > 0
    }
    if used:
        evidence["specialists"] = dict(sorted(used.items()))

    if row:
        if row.get("hvidate"):
            evidence["hvidate"] = str(row["hvidate"]).strip()
        equipment = {
            label: (row.get(field_name) or "").strip().upper()
            for field_name, label in EQUIPMENT_FIELDS.items()
            if (row.get(field_name) or "").strip()
        }
        if equipment:
            evidence["equipment"] = equipment
    return evidence


def score_hospital(
    hospital: D.Hospital,
    frame: D.Frame,
    now: datetime,
    specialists: dict[str, dict[str, int]],
    designations: dict[str, set[str]],
) -> HospitalScore:
    conditions = build_conditions(frame.beds.get(hospital.hpid), now)
    declared = frame.accept.get(hospital.hpid, {})
    departments = specialists.get(hospital.hpid, {})
    designated = designations.get(hospital.hpid, set())

    capabilities: dict[str, GroupScore] = {}
    for group in V.GROUPS:
        best_tier, best_basis, items = None, [], {}
        for item in V.items_in_group(group):
            value = declared.get(item.no)
            items[item.no] = value or V.ACCEPT_UNKNOWN
            tier, basis = _item_tier(value, item.no, departments, designated)
            # 그룹 안에서는 가장 높은 근거를 택한다. 실패 비용이 비대칭이라
            # (후보에서 빼는 쪽이 훨씬 비싸다) 보수적으로 낮추지 않는다
            if best_tier is None or tier > best_tier:
                best_tier, best_basis = tier, basis
        if best_tier is None:
            continue
        if conditions.stale:
            best_basis = [*best_basis, f"마지막 입력 {conditions.feedAgeMinutes // 1440}일 전"]
        if hospital.emcls:
            best_basis = [*best_basis, f"등급: {hospital.emcls}"]

        capabilities[group] = GroupScore(
            group=group,
            tier=best_tier,
            score=round(best_tier / MAX_TIER, 3),
            status=_status(best_tier),
            confidence=_confidence(best_tier, conditions.stale),
            basis=best_basis,
            items=items,
        )

    return HospitalScore(
        hpid=hospital.hpid,
        name=hospital.name,
        emcls=hospital.emcls,
        conditions=conditions,
        capabilities=capabilities,
        evidence=build_evidence(
            hospital.hpid, frame.beds.get(hospital.hpid), departments, designated
        ),
    )


def build_payload(hospital_info: dict, score: HospitalScore, assessed_at: str) -> dict:
    """기존 `HospitalInfo`에 판정을 얹은 **하나의** 전송 객체를 만든다.

    병원 하나는 객체 하나여야 한다. 병원 정보와 판정을 따로 보내면 hub가 다시
    `hospitalId`로 조인해야 하고, 둘 중 하나만 도착한 상태가 생긴다.

    기존 필드는 건드리지 않는다 — hub가 이미 쓰고 있으므로 **superset**이 되게 한다.
    hub 입장에서는 `assessment` 키 하나가 늘어난 것뿐이다.

    ⚠️ 키 이름 주의: 기존 `HospitalInfo.capabilities`는 표준 역량 코드 7종의
    `list[str]`이고, 판정의 15그룹은 `assessment.groups`다. 같은 이름을 쓰면
    반드시 헷갈리므로 네임스페이스를 분리했다.

    이 함수는 `hospital_info`를 인자로 받는다 — `hospital_score/`가 `schema.py`나
    `mapper.py`를 import 하지 않기 위해서다(폴더째 버릴 수 있어야 한다는 원칙).
    쓰는 쪽에서 기존 파이프라인이 만든 dict를 그대로 넘기면 된다.
    """
    return {
        **hospital_info,
        "assessment": {
            "assessedAt": assessed_at,
            "source": "rule",
            "conditions": score.conditions.__dict__,
            "evidence": score.evidence,
            "groups": {
                group: {
                    "status": capability.status,
                    "tier": TIER_LABEL[capability.tier],
                    "score": capability.score,
                    "confidence": capability.confidence,
                    "basis": capability.basis,
                    "items": capability.items,
                }
                for group, capability in score.capabilities.items()
            },
        },
    }


def score_all(day: str | None = None) -> list[HospitalScore]:
    paths = D.snapshot_files(day=day)
    hospitals = D.load_hospitals(paths)
    frames = D.load_frames(paths)
    if not frames:
        return []
    frame = frames[-1]
    now = frame.ts.replace(tzinfo=None)
    specialists = load_specialists()
    designations = load_designations()
    return [
        score_hospital(hospital, frame, now, specialists, designations)
        for hospital in hospitals.values()
    ]


# --- 불변식 ------------------------------------------------------------------
# 정답이 없으므로 "반드시 지켜야 할 성질"을 대신 검사한다. 라벨 없이도 검증되고,
# 가중치를 어떻게 바꾸든 이게 깨지면 실패다.

INVARIANTS = [
    ("불가능 신고 < 근거 없는 미상", TIER_DECLARED_NO < TIER_UNKNOWN_BARE),
    ("근거 없는 미상 < 전문의 있는 미상", TIER_UNKNOWN_BARE < TIER_UNKNOWN_SPECIALIST),
    ("전문의 있는 미상 < 전문병원 지정 미상", TIER_UNKNOWN_SPECIALIST < TIER_UNKNOWN_DESIGNATED),
    ("전문병원 지정 미상 < 가능 신고", TIER_UNKNOWN_DESIGNATED < TIER_DECLARED_YES),
]


def check_invariants(scores: list[HospitalScore]) -> list[str]:
    """위반 목록을 돌려준다. 비어 있으면 통과."""
    failures = [f"계층 순서 위반: {label}" for label, ok in INVARIANTS if not ok]

    for hospital in scores:
        for group, capability in hospital.capabilities.items():
            where = f"{hospital.name}/{group}"
            # 미상이 "불가능"과 같은 취급을 받으면 안 된다 — 미상을 이유로 이송을
            # 막으면 뺑뺑이가 오히려 늘어난다
            if capability.status == "unknown" and capability.tier <= TIER_DECLARED_NO:
                failures.append(f"{where}: 미상이 불가능 이하로 평가됨")
            # 점수는 계층에서만 나온다 (다른 요인이 섞이면 순서가 깨진다)
            if abs(capability.score - capability.tier / MAX_TIER) > 1e-9:
                failures.append(f"{where}: score가 tier와 어긋남")
            # 근거는 반드시 남는다. "왜 이 병원인가"에 답할 수 없으면 실패다
            if not capability.basis:
                failures.append(f"{where}: 근거가 비어 있음")
            # 신뢰도가 점수에 섞여 들어가면 안 된다
            if capability.confidence not in ("high", "medium", "low"):
                failures.append(f"{where}: 신뢰도 값이 이상함")
    return failures


def validate_designations(scores: list[HospitalScore]) -> str:
    """전문병원 지정을 홀드아웃 정답으로 쓴 부분 검증.

    "화상 환자 시나리오에서 화상 전문병원이 후보 상위에 오는가"를 본다. 표본이
    작지만(분야당 1~6곳) 방향은 확실히 검증된다.
    """
    designations = load_designations()
    if not designations:
        return "전문병원 지정 캐시가 없다 (hira_files --fetch)"

    by_hpid = {hospital.hpid: hospital for hospital in scores}
    lines = ["전문병원 지정 홀드아웃 검증", ""]
    lines.append(f"  {'분야':<12}{'지정·매칭':>9}{'신고만 볼 때':>13}{'새 점수':>10}")

    for field_name, item_nos in HF.FIELD_TO_MKIOSK.items():
        groups = {V.BY_NO[no].group for no in item_nos if V.BY_NO[no].group}
        targets = [
            hpid for hpid, fields in designations.items() if field_name in fields
        ]
        if not targets:
            continue
        old_visible = new_visible = 0
        for hpid in targets:
            hospital = by_hpid.get(hpid)
            if not hospital:
                continue
            for group in groups:
                capability = hospital.capabilities.get(group)
                if not capability:
                    continue
                if capability.status == "available":
                    old_visible += 1  # 기존 방식: 신고가 '가능'이어야만 보인다
                if capability.tier >= TIER_UNKNOWN_DESIGNATED:
                    new_visible += 1  # 새 방식: 외부 근거로도 후보에 오른다
                break
        lines.append(
            f"  {field_name:<12}{len(targets):>9}{old_visible:>13}{new_visible:>10}"
        )

    lines.append("")
    lines.append("  '신고만 볼 때'는 기존 파이프라인이 후보로 올릴 수 있는 수,")
    lines.append("  '새 점수'는 외부 근거를 반영했을 때의 수다.")
    return "\n".join(lines)


def _demo_hospital_infos(day: str | None) -> dict[str, dict]:
    """데모용 — 기존 파이프라인이 만드는 `HospitalInfo`를 스냅샷에서 재현한다.

    `mapper`를 여기서만 **지연 import** 한다. 라이브러리 본문은 여전히
    `hospital_score/` 밖을 import 하지 않는다 — 이 함수는 "합친 전송 객체가
    실제로 어떻게 생겼는지" 팀에 보여주기 위한 CLI 전용이다.
    """
    from egen.mapper import map_all  # noqa: PLC0415 — 데모 전용 지연 import

    latest: dict[str, list] = {}
    for record in D.iter_records(D.snapshot_files(day=day)):
        latest[record["operation"]] = record["items"]  # 마지막 관측이 이긴다
    if not {D.OP_BEDS, D.OP_LIST, D.OP_ACCEPT} <= latest.keys():
        return {}

    hospitals, _ = map_all(latest[D.OP_BEDS], latest[D.OP_LIST], latest[D.OP_ACCEPT])
    return {h.hospitalId: json.loads(h.to_hub_json()) for h in hospitals}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="병원 수용가능성 점수")
    parser.add_argument("--day", default=None, help="특정 날짜 스냅샷만")
    parser.add_argument(
        "--payload", default=None, help="병원 이름 일부 — hub로 보낼 합친 객체를 찍는다"
    )
    parser.add_argument("--check", action="store_true", help="불변식 검사")
    parser.add_argument("--validate", action="store_true", help="전문병원 홀드아웃 검증")
    parser.add_argument("--sample", default=None, help="병원 이름 일부로 하나 출력")
    parser.add_argument("--out", default=None, help="전체를 JSON 파일로 저장")
    args = parser.parse_args()

    all_scores = score_all(day=args.day)
    print(f"점수 산출: 병원 {len(all_scores)}곳 × {len(V.GROUPS)}그룹")

    if args.check:
        problems = check_invariants(all_scores)
        print(f"\n불변식 {len(INVARIANTS)}개 + 산출물 검사")
        if problems:
            print(f"  위반 {len(problems)}건")
            for problem in problems[:10]:
                print(f"    {problem}")
        else:
            print("  통과")

    if args.validate:
        print()
        print(validate_designations(all_scores))

    if args.sample:
        found = [h for h in all_scores if args.sample in h.name]
        for hospital in found[:1]:
            print()
            print(json.dumps(hospital.to_dict(), ensure_ascii=False, indent=1))

    if args.payload:
        infos = _demo_hospital_infos(args.day)
        if not infos:
            raise SystemExit("스냅샷에서 HospitalInfo를 만들지 못했다")
        assessed_at = datetime.now().astimezone().isoformat(timespec="seconds")
        found = [h for h in all_scores if args.payload in h.name and h.hpid in infos]
        if not found:
            raise SystemExit(f"'{args.payload}'에 해당하는 병원을 찾지 못했다")

        merged = build_payload(infos[found[0].hpid], found[0], assessed_at)
        print()
        print(json.dumps(merged, ensure_ascii=False, indent=1))

        total = sum(
            len(json.dumps(build_payload(infos[h.hpid], h, assessed_at), ensure_ascii=False).encode())
            for h in all_scores
            if h.hpid in infos
        )
        covered = sum(1 for h in all_scores if h.hpid in infos)
        print(f"\n전체 {covered}곳 합친 전송 크기: {total / 1024:.0f} KB "
              f"(병원당 {total / max(1, covered):.0f} B)")

    if args.out:
        Path(args.out).write_text(
            json.dumps([h.to_dict() for h in all_scores], ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        print(f"\n저장: {args.out}")
