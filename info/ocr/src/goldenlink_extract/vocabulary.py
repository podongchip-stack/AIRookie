"""추출 대상 어휘 — 어떤 값만 인정할 것인가.

두 갈래로 되어 있다.

1. **복사해 온 어휘** (`CAPABILITY_CODES`, `BED_CODES`, `LABELS_KO`)
   출처: `Hospital_inform/info/schema.py`. 최종적으로 `feature/hub`가 대조하는
   표준 코드라 우리가 마음대로 만들 수 없다.

   ⚠️ **복사본이다.** 원본이 바뀌면 여기도 바꿔야 한다. 저장소 안에 같은 표가 두
   벌 있는 상태이므로, 어휘를 고칠 일이 생기면 반드시 양쪽을 함께 본다.
   `scripts/run_extract.py --check-vocabulary` 로 원본과 어긋났는지 확인할 수 있다.

   원본을 import 하지 않는 이유: `Hospital_inform/`은 E-Gen API를 다루는 별도
   수집 경로다. 이 모듈이 거기 의존하면 OCR 파이프라인만 돌리려는 사람도 그
   폴더 구조를 그대로 갖고 있어야 한다.

2. **여기서 정의한 어휘** (`DOCUMENT_TYPES`)
   서류에만 있고 공개 API에는 없는 것들이다. E-Gen에는 "이게 무슨 서류인지",
   "언제 기준 정보인지"라는 개념 자체가 없다 — 항상 실시간이니까.
"""

from __future__ import annotations

# ============================================================================
# 1. Hospital_inform/info/schema.py 에서 복사 — 임의 변경 금지
# ============================================================================

#: 병상 종류.
BED_CODES: frozenset[str] = frozenset(
    {
        "ER_ADULT",  # 응급실 일반병상(성인)
        "ER_PEDIATRIC",  # 소아 응급실 병상
        "ER_NEGATIVE",  # 음압 격리병상
        "ICU",  # 일반 중환자실
        "CCU",  # 심장 중환자실
        "OR",  # 가용 수술방
    }
)

#: 시술·장비 역량. 서류에서 뽑아 `capabilities`에 넣는다.
CAPABILITY_CODES: frozenset[str] = frozenset(
    {
        "PROC_PCI_EMERGENCY",  # 응급 관상동맥중재술(심근경색 재관류)
        "PROC_IV_THROMBOLYSIS",  # 정맥 혈전용해술(뇌경색 tPA)
        "PROC_EVT_THROMBECTOMY",  # 동맥내 혈전제거술
        "PROC_CRANIOTOMY",  # 개두술(뇌출혈 수술)
        "PROC_CESAREAN_EMERGENCY",  # 응급 제왕절개
        "EQP_CT_24H",  # CT 24시간 가동
        "EQP_ANGIO_SUITE",  # 혈관조영실(앤지오)
    }
)

#: 사람이 읽는 라벨. 프롬프트와 검증 출력에 쓴다.
LABELS_KO: dict[str, str] = {
    "ER_ADULT": "응급실 일반병상(성인)",
    "ER_PEDIATRIC": "소아 응급실 병상",
    "ER_NEGATIVE": "음압 격리병상",
    "ICU": "일반 중환자실",
    "CCU": "심장 중환자실",
    "OR": "가용 수술방",
    "PROC_PCI_EMERGENCY": "응급 관상동맥중재술",
    "PROC_IV_THROMBOLYSIS": "정맥 혈전용해술(tPA)",
    "PROC_EVT_THROMBECTOMY": "동맥내 혈전제거술",
    "PROC_CRANIOTOMY": "개두술",
    "PROC_CESAREAN_EMERGENCY": "응급 제왕절개",
    "EQP_CT_24H": "CT 24시간 가동",
    "EQP_ANGIO_SUITE": "혈관조영실",
}


# ============================================================================
# 2. 이 모듈에서 정의 — 서류에만 있는 개념
# ============================================================================

#: 서류 종류. 무엇이 적힌 서류인지 알면 어느 필드를 믿을지 판단할 수 있다.
#: 당직표에서 나온 당직 정보와 진단서에서 나온 당직 정보는 신뢰도가 다르다.
DOCUMENT_TYPES: frozenset[str] = frozenset(
    {
        "DUTY_ROSTER",  # 당직 편성표
        "DEPARTMENT_GUIDE",  # 진료과·의료진 안내
        "EQUIPMENT_STATUS",  # 장비·시설 현황
        "BED_STATUS",  # 병상 운영 현황
        "MEDICAL_CERTIFICATE",  # 진단서·소견서·진료의뢰서
        "OTHER",  # 위 어디에도 안 맞음
    }
)

DOCUMENT_TYPE_LABELS_KO: dict[str, str] = {
    "DUTY_ROSTER": "당직 편성표",
    "DEPARTMENT_GUIDE": "진료과·의료진 안내",
    "EQUIPMENT_STATUS": "장비·시설 현황",
    "BED_STATUS": "병상 운영 현황",
    "MEDICAL_CERTIFICATE": "진단서·소견서",
    "OTHER": "기타",
}


def label_ko(code: str) -> str:
    """코드의 한글 라벨. 없으면 코드를 그대로 돌려준다."""
    return LABELS_KO.get(code) or DOCUMENT_TYPE_LABELS_KO.get(code) or code


# ============================================================================
# 원본과 어긋났는지 확인
# ============================================================================

#: 원본 어휘가 있는 곳. 저장소 루트 기준 상대 경로다
UPSTREAM_SCHEMA = "Hospital_inform/info/schema.py"


def diff_with_upstream(upstream_path) -> list[str]:
    """복사해 온 어휘가 원본과 같은지 확인한다.

    원본 파일을 import 하지 않고 텍스트로 읽어 코드 이름만 뽑아 비교한다.
    import 하면 pydantic 의존성과 폴더 구조를 그대로 요구하게 되는데, 이 모듈을
    독립적으로 유지하려는 목적과 어긋난다.

    반환: 어긋난 항목 설명 목록. 비어 있으면 일치한다.
    원본 파일이 없으면 확인을 건너뛴다 (OCR만 쓰는 사람에게는 없는 게 정상이다).
    """
    import re
    from pathlib import Path

    path = Path(upstream_path)
    if not path.exists():
        return [f"원본을 찾을 수 없어 확인을 건너뛴다: {path}"]

    text = path.read_text(encoding="utf-8")
    problems: list[str] = []

    for name, ours in (("BED_CODES", BED_CODES), ("CAPABILITY_CODES", CAPABILITY_CODES)):
        block = re.search(rf"{name}[^{{]*\{{(.*?)\}}", text, re.DOTALL)
        if not block:
            problems.append(f"{name}: 원본에서 찾지 못했다")
            continue
        theirs = set(re.findall(r'"([A-Z0-9_]+)"', block.group(1)))
        if theirs != set(ours):
            missing = sorted(theirs - set(ours))
            extra = sorted(set(ours) - theirs)
            problems.append(
                f"{name}: 원본에만 있음 {missing} / 우리에게만 있음 {extra}"
            )

    return problems
