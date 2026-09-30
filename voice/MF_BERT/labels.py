"""v2 출력층 보기 목록. 기준은 data_v2/README.md 3절, 공식 항목명은 data_v2/label_standards.md."""

from __future__ import annotations

from dataclasses import dataclass

UNDECIDED = "미언급"


@dataclass(frozen=True)
class LabelSet:
    name: str
    options: tuple[str, ...]
    allow_undecided: bool = True

    @property
    def classes(self) -> tuple[str, ...]:
        return self.options + ((UNDECIDED,) if self.allow_undecided else ())

    @property
    def size(self) -> int:
        return len(self.classes)

    def index(self, label: str) -> int:
        return self.classes.index(label)


# ---- Pre-KTAS 주증상 (label_standards.md 2.4~2.6, 성인 목록 + 소아 전용 항목) ----
MAJORS = (
    "A 물질오용", "B 정신건강", "C 신경계", "D 눈", "E 코", "F 귀", "G 입,목/얼굴", "H 호흡기계", "I 심혈관계",
    "J 소화기계", "K 임신/여성생식계", "L 비뇨기계/남성생식계", "M 근골격계", "N 몸통외상", "O 환경손상", "P 피부", "Q 일반",
)
MINORS_BY_MAJOR = {
    'A 물질오용': (
        '물질오용/중독',
        '과다복용',
        '물질금단',
    ),
    'B 정신건강': (
        '불안/위기상황',
        '환각/망상',
        '불면증',
        '폭력/살인행위',
        '우울증/자살/자해',
        '사회문제',
        '기괴한 행동',
        '환자의 안녕에 대한 고려(학대, 방임)',
        '소아의 파괴적 행동',
    ),
    'C 신경계': (
        '의식수준의 변화',
        '착란',
        '현훈',
        '두통',
        '발작',
        '보행장애/운동실조/강직',
        '사지약화/뇌졸중 증상',
        '두부손상',
        '떨림(Tremor)',
        '감각상실/이상감각',
        '기억상실',
        '축 늘어진 소아(Floppy child)',
    ),
    'D 눈': (
        '눈의 화학물질 노출',
        '눈의 이물질',
        '시력장애',
        '눈통증',
        '눈충혈·분비물',
        '눈부심',
        '복시',
        '안와주위 부종',
        '눈의 외상',
    ),
    'E 코': (
        '코피',
        '코막힘',
        '코의 이물질',
        '상기도감염 증상 호소',
        '코의 외상',
    ),
    'F 귀': (
        '이통(Earache)',
        '귀의 이물질',
        '청력손실',
        '이명',
        '귀의 삼출물',
        '귀의 손상',
    ),
    'G 입,목/얼굴': (
        '치아/구강 문제',
        '안면외상',
        '인후통',
        '목의 부종/통증',
        '목의 외상',
        '연하장애/연하곤란',
        '안면 통증(비외상성/비치아성)',
    ),
    'H 호흡기계': (
        '숨참',
        '호흡정지',
        '과다호흡증후군',
        '객혈',
        '기침/코막힘',
        '호흡기 이물질',
        '알레르기반응',
        '협착음',
        '영아의 무호흡 발작',
        '천명음(다른 증상 호소 없음)',
    ),
    'I 심혈관계': (
        '심정지(비외상성)',
        '심정지(외상성)',
        '흉통(심장성)',
        '흉통(비심장성)',
        '심계항진/불규칙한 심장박동',
        '고혈압',
        '전신쇠약',
        '실신/전실신',
        '전신부종',
        '다리 부기/부종',
        '맥박이 없거나 차가운 사지',
        '일측성의 홍조 띤 뜨거운 사지',
    ),
    'J 소화기계': (
        '복통',
        '식욕부진',
        '변비',
        '직장내 이물질',
        '샅고랑부위 통증/종괴',
        '구토/구역',
        '항문/직장/회음부 통증',
        '설사',
        '토혈',
        '혈변/흑색변',
        '황달',
        '딸꾹질',
        '복부종괴/팽만',
        '항문/직장/회음부 외상',
        '이물질 삼킴',
        '신생아 수유곤란',
        '신생아 황달',
    ),
    'K 임신/여성생식계': (
        '월경 문제',
        '질내 이물질',
        '질 분비물',
        '질통증/가려움',
        '질출혈',
        '음순부종',
        '20주 미만의 임신',
        '20주 이상의 임신',
        '성폭행',
        '생식기의 외상',
        '출산 후 문제(6주 이내)',
    ),
    'L 비뇨기계/남성생식계': (
        '옆구리 통증',
        '혈뇨',
        '생식기의 분비물/피부병변',
        '음경부종',
        '고환 통증/부종',
        '소변 배출장애',
        '요로감염 증상',
        '핍뇨증',
        '다뇨증',
        '생식기의 외상',
        '성폭행(남성)',
    ),
    'M 근골격계': (
        '목·등·허리 통증',
        '외상성 목·등·허리 손상',
        '절단',
        '상지 통증',
        '하지 통증',
        '상지 손상',
        '하지 손상',
        '관절 부종',
        '석고붕대 확인',
        '소아의 보행장애/보행 시 통증',
    ),
    'N 몸통외상': (
        '몸통을 포함한 다발성 외상',
        '단독 흉부외상-관통상',
        '단독 흉부외상-둔상',
        '단독 복부외상-관통상',
        '단독 복부외상-둔상',
    ),
    'O 환경손상': (
        '동상/한랭손상',
        '온열손상',
        '유해물질흡입',
        '전기손상',
        '화학물질 노출',
        '저체온증',
        '익수',
    ),
    'P 피부': (
        '물림(Bite)',
        '쏘임(Sting)',
        '찰과상',
        '열상/천공',
        '화상',
        '혈액이나 체액에 노출',
        '피부의 이물질',
        '상처확인',
        '스테이플/봉합사 제거',
        '발진',
        '유방의 발적/압통',
        '국소성 부종/발적',
        '혹·돌기·굳은살',
        '감염 가능성 확인',
        '청색증',
        '외상없이 저절로 멍듦',
        '소양증',
        '기타피부상태',
    ),
    'Q 일반': (
        '감염성 질환에 노출',
        '열',
        '고혈당',
        '저혈당',
        '전문진료를 위해서 의뢰된 환자',
        '드레싱교체',
        '영상검사/검사실 검사',
        '의료장비문제',
        '처방전/투약문의',
        '반지제거',
        '비정상 검사결과',
        '창백함/빈혈',
        '수술 후 합병증',
        '경증 및 비특이적 증상 호소',
        '영유아의 달랠 수 없는 울음',
        '소아의 선천적 문제',
        '방금 태어난 신생아',
    ),
}
#: 소분류 보기는 "대분류|소분류" (대분류마다 같은 이름이 있어서 — 예: 성폭행, 생식기의 외상)
MINORS = tuple(f"{major}|{minor}" for major in MAJORS for minor in MINORS_BY_MAJOR[major])

# ---- 구급활동일지 ----
INCIDENT_TYPES = (
    "질병", "교통사고", "낙상", "추락", "그 밖의 둔상", "관통상", "기계", "농기계", "호흡위험", "화상", "연기흡입", "중독",
    "화학물질", "동물/곤충", "온열손상", "한랭손상", "성폭행", "상해", "기타 손상",
)
INCIDENT_DETAILS = {
    "교통사고": ("운전자", "동승자", "보행자", "자전거", "오토바이", "개인형 이동장치", "그 밖의 탈 것", "미상"),
    "호흡위험": ("익수", "외력에 의한 압박", "이물질에 의한 기도막힘"),
    "화상": ("화염", "고온체", "전기", "물"),
}
DISEASES = (
    "심장질환", "뇌혈관질환", "대동맥질환", "소화기질환", "산과·부인과", "신장질환", "정신과적 응급", "호흡기질환", "신경계질환",
    "대사·내분비", "감염·발열", "기타 질병",
)
SYMPTOMS = (
    "두통", "흉통", "복통", "요통", "분만진통", "그 밖의 통증", "골절", "탈구", "삠", "열상", "찰과상", "타박상", "절단", "압궤손상",
    "화상", "의식장애", "기도이물", "기침", "호흡곤란", "호흡정지", "두근거림", "가슴불편감", "심정지", "경련/발작", "실신", "오심",
    "구토", "설사", "변비", "배뇨장애", "객혈", "토혈", "혈변", "비출혈", "질출혈", "그 밖의 출혈", "고열", "저체온증", "어지러움",
    "마비", "전신쇠약", "정신장애", "그 밖의 이물질", "기타",
)
SYMPTOM_STATUSES = ("확인", "부정")
TREATMENTS = ("기도확보", "산소투여", "CPR", "ECG", "AED", "순환보조", "약물투여", "고정", "상처처치", "분만", "보온")
TREATMENT_STATUSES = ("시행", "시도 실패", "거부")
TREATMENT_DETAILS = {
    "기도확보": ("도수조작", "기도유지기", "기관삽관", "성문외 기도유지기", "흡인기", "기도폐쇄처치"),
    "산소투여": ("비관", "안면마스크", "비재호흡마스크", "BVM", "산소소생기", "네뷸라이저", "기타"),
    "CPR": ("실시", "거부", "DNR", "유보"),
    "AED": ("Shock", "Monitoring"),
    "순환보조": ("정맥로 확보", "수액공급"),
    "고정": ("목뼈", "척추", "부목", "머리"),
    "상처처치": ("지혈", "상처 소독 처치"),
    "보온": ("온", "냉"),
}
# ---- 자체 정의 ----
REGIONS = ("머리", "얼굴", "목", "가슴", "배", "등·허리", "골반", "팔", "다리")
INJURY_TYPES = ("골절", "탈구", "삠", "열상", "찰과상", "타박상", "절단", "압궤손상", "화상")
SIDES = ("좌", "우", "양측")
AGE_BANDS = ("10세 미만", "10대", "20대", "30대", "40대", "50대", "60대", "70대", "80대", "90대 이상")

# ---- 문장 단위 단일 선택 출력층 ----
KTAS = LabelSet("ktas", ("1", "2", "3", "4", "5"), allow_undecided=False)
CC_MAJOR = LabelSet("cc_major", MAJORS)
CC_MINOR = LabelSet("cc_minor", MINORS)
PRIMARY_INCIDENT = LabelSet("primary_incident", INCIDENT_TYPES)
DISEASE = LabelSet("disease", DISEASES)
SEX = LabelSet("sex", ("남성", "여성"))
AVPU = LabelSet("avpu", ("A", "V", "P", "U"))
MED_STATUS = LabelSet("med_status", ("확인", "부정", "미언급"), allow_undecided=False)
SINGLE_CHOICE_HEADS = (KTAS, CC_MAJOR, CC_MINOR, PRIMARY_INCIDENT, DISEASE, SEX, AVPU, MED_STATUS)

# ---- 문장 단위 다중 선택 출력층 (보기마다 0/1) ----
MULTI_LABEL_HEADS = {
    "incidents": tuple(INCIDENT_TYPES),
    "incident_detail": tuple(f"{t}/{d}" for t, ds in INCIDENT_DETAILS.items() for d in ds),
    "treatment": tuple(f"{t}/{s}" for t in TREATMENTS for s in TREATMENT_STATUSES),
    "treatment_detail": tuple(f"{t}/{d}" for t, ds in TREATMENT_DETAILS.items() for d in ds),
    "symptoms": tuple(f"{n}/{s}" for n in SYMPTOMS for s in SYMPTOM_STATUSES),
    "injury": tuple(f"{r}/{t}" for r in REGIONS for t in INJURY_TYPES),
    "injury_side": tuple(f"{r}/{s}" for r in REGIONS for s in SIDES),
}

# ---- 토큰 단위 구간 태깅 (구간을 찾고 값은 규칙으로 읽는다) ----
SPAN_TYPES = ("VITALS", "AGE", "ONSET", "DX", "MED")
SPAN_TAGS = ("O",) + tuple(f"{p}-{t}" for t in SPAN_TYPES for p in ("B", "I"))

for _name, _values in [(h.name, h.options) for h in SINGLE_CHOICE_HEADS] + list(MULTI_LABEL_HEADS.items()) + [
    ("span_tags", SPAN_TAGS),
]:
    assert len(set(_values)) == len(_values), f"{_name}에 중복 보기"
