"""처치 범주 질문의 점수 -> 처치 범주 목록 (규칙). 원본 MF_BERT_treat_cat/treatments.py의 decode_categories다
(정답 만들기·채점 코드와, 내보내지 않는 처치 구절 디코딩은 뺐다).

모델은 환자마다 "k번째 환자의 처치 범주는?"을 묻고, 28개 범주(CATEGORIES)마다 있음 점수(로짓)를 낸다.
"""

from __future__ import annotations

#: 처치 범주 키. 모델 출력 28자리의 순서이고 catalog.json의 categories와 같다(MfBertExtractor가 대조한다)
CATEGORIES = ("oxygen", "suction", "foreign_body", "airway_basic", "airway_advanced", "ventilation",
              "cpr", "defib", "iv", "fluid", "bleeding",
              "med_aspirin", "med_nitro", "med_glucose", "med_epinephrine", "med_bronchodilator", "med_other",
              "spinal", "splint", "wound", "burn", "irrigation", "cold_pack", "cooling", "warming",
              "position", "delivery", "other")


def decode_categories(logits) -> list[str]:
    """질문 하나의 범주 점수 (28,) -> 있다고 고른 범주 목록(CATEGORIES 순서). 점수(로짓)가 0보다 크면(확률 0.5 초과) 있음이다."""
    return [c for c, z in zip(CATEGORIES, logits.tolist()) if z > 0]
