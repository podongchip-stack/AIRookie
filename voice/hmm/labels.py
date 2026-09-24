"""출력층 보기 목록. HANDMADE-MODEL src/handmade_model/labels.py에서 가져왔다.

모델의 출력층 크기는 여기 LabelSet.size에서 정해지므로, 보기를 하나라도 바꾸면
체크포인트(best.pt)와 호환되지 않는다 — 순서까지 학습 당시 그대로 둔다.

모델이 직접 고르는 보기(출력층)와, 규칙이 쓰는 어휘(대표 증상)를 나눠 둔다.
"""

from __future__ import annotations

from dataclasses import dataclass

#: 모델이 근거를 못 찾았을 때 고르는 보기. 조립기가 이 값을 만나면 해당 부분을 생략한다
#: (출력에 "미상" 같은 글자를 내보내지 않는다).
UNDECIDED = "판단 보류"


@dataclass(frozen=True)
class LabelSet:
    """단일 선택 출력층 하나의 보기 목록."""

    name: str
    options: tuple[str, ...]
    allow_undecided: bool = True

    @property
    def classes(self) -> tuple[str, ...]:
        """출력층의 실제 클래스 순서. 판단 보류는 항상 맨 뒤에 붙는다."""
        return self.options + ((UNDECIDED,) if self.allow_undecided else ())

    @property
    def size(self) -> int:
        return len(self.classes)


# --- mechanism 앞 칸: 원인 -------------------------------------------------

#: 원인 유형. 조립 규칙이 뒤 칸을 부위로 채울지 대표 증상으로 채울지 이걸로 가른다.
TRAUMA = "외상"
NON_TRAUMATIC_INJURY = "비외상성 손상"
DISEASE = "질병"

#: 구급활동일지 "교통사고" + "그 외 외상" 항목 그대로
TRAUMA_CAUSES: tuple[str, ...] = (
    "교통사고", "낙상", "추락", "그 밖의 둔상", "관통상", "기계", "농기계",
)

#: 구급활동일지 "비외상성 손상" 항목 + 기타 손상
NON_TRAUMATIC_INJURY_CAUSES: tuple[str, ...] = (
    "호흡위험", "화상", "연기흡입", "중독", "화학물질", "동물/곤충",
    "온열손상", "한랭손상", "성폭행", "상해", "기타 손상",
)

#: 계통 분류 12개. 대동맥질환은 통화에서 직접 의심·언급했을 때만 붙인다
DISEASE_CAUSES: tuple[str, ...] = (
    "심장질환", "뇌혈관질환", "대동맥질환", "소화기질환", "산과·부인과", "신장질환",
    "정신과적 응급", "호흡기질환", "신경계질환", "대사·내분비", "감염·발열", "기타 질병",
)

CAUSE_TYPE: dict[str, str] = {
    **{cause: TRAUMA for cause in TRAUMA_CAUSES},
    **{cause: NON_TRAUMATIC_INJURY for cause in NON_TRAUMATIC_INJURY_CAUSES},
    **{cause: DISEASE for cause in DISEASE_CAUSES},
}

CAUSE = LabelSet("cause", TRAUMA_CAUSES + NON_TRAUMATIC_INJURY_CAUSES + DISEASE_CAUSES)

# --- mechanism 뒤 칸 ---------------------------------------------------------

#: 외상·비외상성 손상일 때. 서로 다른 부위 2곳 이상이면 다발성
BODY_PART = LabelSet(
    "body_part",
    ("머리", "얼굴", "목", "가슴", "배", "등·허리", "골반", "팔", "다리", "다발성"),
)

#: 질병일 때의 대표 증상 보기. 출력층이 아니라 규칙(symptoms에서 도출)이 쓰는 어휘다.
#: 구급활동일지 "환자 증상"에서 외상 묶음·"그 밖의 ~"·"기타"를 뺀 것
REPRESENTATIVE_SYMPTOMS: tuple[str, ...] = (
    "두통", "흉통", "복통", "요통", "분만진통",
    "의식장애", "기도이물", "기침", "호흡곤란", "호흡정지", "두근거림", "가슴불편감", "심정지",
    "경련/발작", "실신", "오심", "구토", "설사", "변비", "배뇨장애", "객혈", "토혈", "혈변", "비출혈",
    "질출혈", "고열", "저체온증", "어지러움", "마비", "전신쇠약", "정신장애",
)

# --- severity_tag ------------------------------------------------------------

#: 필수 필드라 판단 보류가 없다
SEVERITY = LabelSet("severity", ("high", "medium", "low"), allow_undecided=False)

# --- patient -----------------------------------------------------------------

AGE_BAND = LabelSet(
    "age_band",
    ("10세 미만", "10대", "20대", "30대", "40대", "50대", "60대", "70대", "80대", "90대 이상"),
)

SEX = LabelSet("sex", ("남성", "여성"))

# --- treatment ---------------------------------------------------------------

#: 다중 선택 — 보기마다 "시행함" 여부를 따로 판정하므로 판단 보류가 없다.
#: 구급활동일지 응급처치 대항목. 서식의 "기타"는 출력에 넣어도 정보가 없어 뺐다.
TREATMENTS: tuple[str, ...] = (
    "기도확보", "산소투여", "CPR", "ECG", "AED", "순환보조",
    "약물투여", "고정", "상처처치", "분만", "보온",
)

# --- symptoms (토큰 단위) ------------------------------------------------------

#: 증상 구간 태그. 구간 표시와 있음/없음 판별을 태그 하나로 함께 푼다
SYMPTOM_TAGS: tuple[str, ...] = (
    "O",
    "B-증상있음", "I-증상있음",
    "B-증상없음", "I-증상없음",
)

#: 단일 선택 출력층 전체. 모델이 출력층을 만들 때 이 순서대로 쓴다
SINGLE_CHOICE_HEADS: tuple[LabelSet, ...] = (CAUSE, BODY_PART, SEVERITY, AGE_BAND, SEX)
