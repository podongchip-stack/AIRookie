"""근거 대조 — LLM이 지어낸 값을 걸러낸다. [규칙 기반]

이 파일에는 AI가 없다. LLM이 "근거"라며 내놓은 원문 조각이 **실제로 OCR 원문에
있는지** 문자열로 대조할 뿐이다.

왜 필요한가
-----------
JSON Schema로 디코딩을 제약하면 *형식*은 반드시 맞다. 하지만 형식이 맞는 거짓말은
얼마든지 만들어진다. `{"department": "흉부외과", "doctorCount": 3}`은 스키마를
완벽히 만족하지만 서류에 그런 말이 없을 수 있다.

`goldenlink_ocr.validator`가 confidence를 안 믿는 것과 같은 이유다 —
`ocr/README.md`에 모델이 토큰을 무한 반복하는 동안에도 confidence가 0.99로 나온
사례가 기록돼 있다. 모델이 스스로 보고하는 지표 말고 **바깥에서 검사할 수 있는
사실**이 필요하고, 여기서 그 사실은 "이 문자열이 원문에 있는가"다.

`ocr/README.md`가 적어둔 실패 사례 — 워터마크 문서에서 라벨(`성명`)은 읽고 값은
비우는 경우 — 가 특히 위험하다. 그 빈칸을 LLM이 그럴듯하게 메우기 때문이다.
지어낸 값에는 원문 근거가 없으므로 이 대조에 걸린다.

검사는 세 겹이고 뒤로 갈수록 엄격하다.

1. `is_grounded()`            근거 문장 자체를 지어낸 경우
2. `value_appears_in()`       근거는 진짜인데 값만 다른 경우
3. `capability_supported_by()` 근거도 진짜고 값도 어휘에 있지만 둘이 무관한 경우
"""

from __future__ import annotations

import re
import unicodedata

#: 대조 전에 지우는 문자들. OCR 결과는 띄어쓰기와 문장부호가 흔들려서 그대로
#: 비교하면 사람 눈에는 같은데 기계는 다르다고 판정한다
_NOISE = re.compile(r"[\s​　·:：,，.。/()\[\]{}\-–—_|~'\"“”‘’]+")


def normalize(text: str) -> str:
    """대조용으로 문자열을 납작하게 만든다.

    - NFKC 정규화: 전각 숫자·괄호가 반각과 같아진다. OCR이 전각으로 읽는 일이 잦다
    - 공백·문장부호 제거: 띄어쓰기 오차를 흡수한다
    - 소문자화: 영문 약어 표기 흔들림(CT/ct)을 흡수한다

    의미를 바꾸는 정규화는 하지 않는다. 숫자와 한글은 그대로 남긴다 —
    `3명`과 `8명`이 같아져 버리면 대조가 아무 의미가 없다.
    """
    return _NOISE.sub("", unicodedata.normalize("NFKC", text)).lower()


def is_grounded(evidence: str, source_text: str, min_chars: int = 4) -> tuple[bool, str | None]:
    """근거가 원문에 실제로 있는지 판정한다.

    반환: (통과 여부, 실패 이유). 통과면 이유는 None이다.

    짧은 근거를 통과시키지 않는 이유: "3"이나 "명"은 어느 문서에나 있어서 대조를
    통과하지만 아무것도 증명하지 못한다. 근거로 못 쓸 만큼 짧으면 근거가 없는
    것으로 본다.
    """
    normalized_evidence = normalize(evidence)
    if not normalized_evidence:
        return False, "근거가 비어 있다"
    if len(normalized_evidence) < min_chars:
        return False, f"근거가 너무 짧아 대조 의미가 없다: {evidence!r}"
    if normalized_evidence not in normalize(source_text):
        return False, f"원문에 없는 근거다 (지어낸 것으로 판단): {evidence!r}"
    return True, None


def value_appears_in(value: str, evidence: str) -> bool:
    """추출된 값 자체가 근거 안에 들어 있는지 확인한다.

    근거는 원문에서 가져왔는데 값은 딴 데서 온 경우를 잡는다. 원문의
    "흉부외과 당직 3명"을 근거로 제시하면서 `doctorCount: 5`를 내놓는 식이다.
    근거 대조만으로는 이걸 못 잡는다 — 근거 문자열 자체는 원문에 있으니까.

    숫자에 특히 중요하다. 진료과명은 원문 표기와 조금 달라도(`순환기 내과` /
    `순환기내과`) 정규화가 흡수하지만, 숫자는 흡수할 여지가 없어야 한다.
    """
    return normalize(value) in normalize(evidence)


#: 역량 코드별로, 근거에 최소한 하나는 나와야 하는 원문 표현.
#:
#: 왜 필요한가 — 근거 대조만으로는 "원문에 있는 아무 문장"을 근거랍시고 붙이는 것을
#: 못 막는다. `"흉부외과 2명"`은 원문에 실재하므로 대조를 통과하지만 개두술과는
#: 아무 상관이 없다. 역량 코드는 영문이라 원문에 그대로 나올 리 없어
#: `value_appears_in()`도 못 쓴다. 그래서 코드별로 "이 말이 나와야 인정한다"를
#: 따로 정해둔다.
#:
#: 역량은 나중에 hub의 하드필터가 대조하는 값이다. 잘못 올라간 코드 하나가
#: "그 시술이 안 되는 병원"을 후보 1위로 만든다. 다른 필드보다 엄격할 이유가 있다.
#:
#: `vocabulary.CAPABILITY_CODES`와 1:1로 맞춰야 한다. 코드를 추가하고 여기를
#: 빠뜨리면 그 코드는 근거를 못 찾아 전부 걸러진다 (조용히 통과하는 것보다 낫다).
CAPABILITY_EVIDENCE_TERMS: dict[str, tuple[str, ...]] = {
    "PROC_PCI_EMERGENCY": ("관상동맥", "중재술", "PCI", "스텐트", "재관류", "심혈관조영"),
    "PROC_IV_THROMBOLYSIS": ("혈전용해", "tPA", "티피에이", "혈전용해제"),
    "PROC_EVT_THROMBECTOMY": ("혈전제거", "동맥내", "기계적혈전", "EVT"),
    "PROC_CRANIOTOMY": ("개두", "두개골", "뇌수술", "뇌출혈수술", "감압술"),
    "PROC_CESAREAN_EMERGENCY": ("제왕절개", "C-sec", "응급분만"),
    # 24시간 여부까지는 문자열로 못 가린다. 그건 프롬프트가 지시하고 사람이 검토한다.
    # 여기서 막으려는 것은 "CT 얘기가 아예 없는데 CT 역량을 넣는" 경우다
    "EQP_CT_24H": ("CT", "전산화단층"),
    "EQP_ANGIO_SUITE": ("혈관조영", "앤지오", "angio"),
}


def capability_supported_by(code: str, evidence: str) -> bool:
    """근거가 그 역량 코드를 실제로 뒷받침하는지 확인한다.

    어휘에 없는 코드는 뒷받침할 표현을 모르므로 False다. 모르면 통과시키지 않는
    쪽이 맞다 — 잘못 올라간 역량은 갈 수 없는 병원을 후보로 만든다.
    """
    terms = CAPABILITY_EVIDENCE_TERMS.get(code)
    if not terms:
        return False
    normalized_evidence = normalize(evidence)
    return any(normalize(term) in normalized_evidence for term in terms)


def locate_region(evidence: str, regions: list[dict]) -> int | None:
    """근거가 OCR의 몇 번째 영역에서 나왔는지 찾는다.

    사후 추적용이다. 값이 이상할 때 원본 이미지의 어느 부분을 다시 보면 되는지
    바로 짚을 수 있다. 못 찾으면 None이며 그 자체는 실패가 아니다 — 영역 경계에
    걸친 문장은 결합된 전체 텍스트에만 온전히 존재한다.
    """
    normalized_evidence = normalize(evidence)
    if not normalized_evidence:
        return None
    for index, region in enumerate(regions):
        if normalized_evidence in normalize(region.get("text", "")):
            return index
    return None
