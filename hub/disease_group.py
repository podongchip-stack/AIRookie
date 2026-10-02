"""예상 병명 → info-v2 중증질환군(E-Gen MKioskTy 15그룹) 하나, 없으면 None (2026-10-02, 규칙 기반).

예전엔 진료과와 같은 임베딩으로 15개 중 가장 가까운 것을 골랐는데, 기준선이 없어 어떤 환자든 하나를
골랐고 그 값도 엉뚱했다(실측: 다리 골절·심근경색·뇌출혈·"미상"이 전부 담낭담관질환으로, 유사도 0.47~0.93이라
기준선으로도 못 거름). 질환군은 dashboard 신뢰도 칩과 `declared_no` 순위 내림에 쓰이므로, 틀린 질환군은
상관없는 신고로 병원을 뒤로 미는 오류가 된다. 그래서 E-Gen 항목명 그대로의 키워드로만 고르고,
해당이 없으면(골절·타박상·발열 등 중증질환군 밖) None — 칩도 내림도 없다.

위에서부터 처음 맞는 것. 뇌출혈을 재관류(뇌경색)보다, 대동맥을 흉통보다 먼저 본다.
자체 검사: python disease_group.py
"""
from __future__ import annotations

import re

RULES: list[tuple[str, str]] = [
    ("대동맥응급", r"대동맥"),
    ("뇌출혈수술", r"뇌출혈|거미막하|지주막하|두개내\s*출혈|경막[하외]\s*(출혈|혈종)"),
    ("재관류중재술", r"심근\s*경색|급성\s*관상|STEMI|흉통\(심장성\)|경색|뇌졸중"),
    ("중증화상", r"화상"),
    ("사지접합", r"절단"),
    ("담낭담관질환", r"담낭|담관|담도|담석"),
    ("장중첩/폐색", r"장중첩|장\s*폐색"),
    ("응급내시경", r"토혈|혈변|흑색변|위장관\s*출혈|이물"),
    ("복부응급수술", r"충수|맹장|복막염|천공|급성\s*복증"),
    ("저체중출생아", r"미숙아|저체중|조산아"),
    ("산부인과응급", r"임신|분만|산과|부인과|질\s*출혈|태반|자궁"),
    ("응급투석", r"투석|고칼륨|신부전"),
    ("정신과적응급", r"정신과|자해|자살|환각"),
    ("안과적수술", r"안구|안과|망막|눈\s*(열상|손상)"),
    ("영상의학혈관중재", r"객혈|색전|동맥류"),
]
_COMPILED = [(group, re.compile(pattern)) for group, pattern in RULES]


def match_group(expected_diagnosis: str | None, vocabulary: list[str]) -> str | None:
    """vocabulary(이번 후보 병원들의 assessment에 실제로 있는 질환군)에 있는 것만 돌려준다."""
    text = expected_diagnosis or ""
    for group, pattern in _COMPILED:
        if group in vocabulary and pattern.search(text):
            return group
    return None


if __name__ == "__main__":
    groups = [g for g, _ in RULES]
    cases = {
        "교통사고(보행자) · 하지 손상 · 오른쪽 다리 골절 의심 · 우 다리 골절": None,
        "심장질환 · 흉통(심장성) · 경색 의심": "재관류중재술",
        "뇌혈관질환 · 편측마비 · 뇌출혈 의심": "뇌출혈수술",
        "대동맥질환 · 찢어지는 흉통 · 대동맥 박리 의심": "대동맥응급",
        "화상(화염) · 전신 화상": "중증화상",
        "기계(절단) · 손가락 절단": "사지접합",
        "소화기질환 · 토혈 · 위장관 출혈": "응급내시경",
        "산과·부인과 · 질출혈 · 임신 32주": "산부인과응급",
        "정신과적 응급 · 자해": "정신과적응급",
        "교통사고(운전자) · 가슴 타박상": None,
        "감염·발열 · 고열": None,
        "미상": None,
    }
    for text, want in cases.items():
        got = match_group(text, groups)
        assert got == want, (text, got, want)
    assert match_group("전신 화상", ["재관류중재술"]) is None, "후보 병원 어휘에 없으면 고르지 않는다"
    print("disease_group 자체 검사 통과")
