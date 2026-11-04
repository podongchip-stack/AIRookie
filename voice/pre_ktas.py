"""MF_BERT 환자 출력(13필드) -> Pre-KTAS 추정 단계 (규칙 기반, AI 아님).

모델은 KTAS를 예측하지 않는다. 대신 모델이 뽑은 주증상·의식·활력징후를 공개된 객관 기준에 넣어 단계를 계산한다.
각 기준에서 나온 단계 중 가장 위급한(숫자가 작은) 값이 최종 단계다 — Pre-KTAS·OTAS가 쓰는 방식과 같다.

    1. 주증상별 최소 단계   OTAS 보충표 2 (Kim 외, Yonsei Med J 2022;63(3):272, PMC8860940)
    2. 산소포화도·혈역학·의식(AVPU)·SIRS   OTAS 표 1 (같은 논문)
    3. GCS 3-8 -> 1, 9-13 -> 2   Pre-KTAS 시범사업 앱 화면 (강창신 외, 대한응급의학회지 2024;35(1):6)
    4. 외상 주증상 + 수축기혈압 90 미만 -> 1   Pre-KTAS 첫인상 평가 "Major trauma (SBP<90mmHg)" (같은 논문)
    5. 혈당   Ontario Prehospital CTAS Field Reference Guide v1.0 표 8 (Pre-KTAS의 바탕인 Pre-CTAS)

한계 — 결과는 실제보다 덜 위급하게 나올 수 있는 추정값이다.
    - 통증 점수·사고 기전·출혈성 질환·경련 진행 여부·절단 범위·화상 면적·분만 징후는 모델이 뽑지 않아 반영 못 한다.
    - 성인(OTAS는 18세 이상) 기준이다. 소아 나이별 활력징후 기준·65세 이상 가산(S-OTAS)은 아직 넣지 않았다.
    - 소방청 공식 Pre-KTAS 수치표는 공개돼 있지 않아 병원 KTAS를 객관화한 OTAS를 쓴다(공식 판정이 아니다).
    - 정답(KTAS) 데이터로 검증하지 않았다.
자체 검사: python pre_ktas.py   (모델 예측 대조: python pre_ktas.py <eval_predictions.jsonl>)
"""
from __future__ import annotations

import json
import sys
from collections import Counter

#: 주증상(cc_minor) -> OTAS 최소 단계. 괄호 안은 OTAS 보충표 2의 영문 주증상명.
#: 표에 대응하는 항목이 없는 것(소아·신생아 전용 등)은 넣지 않는다 — 그 환자는 주증상 기준 없이 나머지 기준으로만 판정된다.
COMPLAINT_MIN_LEVEL: dict[str, int] = {
    # A 물질오용
    "물질오용/중독": 4,  # Substance misuse/intoxication
    "과다복용": 4,  # Overdose ingestion
    "물질금단": 4,  # Substance withdrawal
    # B 정신건강
    "불안/위기상황": 4,  # Anxiety/situational crisis
    "환각/망상": 4,  # Hallucination/delusion
    "불면증": 4,  # Insomnia
    "폭력/살인행위": 3,  # Violent/homicidal behavior
    "우울증/자살/자해": 3,  # Depression/suicidal/deliberate self-harm
    "사회문제": 4,  # Social problem
    "기괴한 행동": 4,  # Bizarre behavior
    "환자의 안녕에 대한 고려(학대, 방임)": 4,  # Concern for patient's welfare
    # C 신경계
    "의식수준의 변화": 3,  # Altered level of consciousness
    "착란": 4,  # Confusion
    "현훈": 3,  # Vertigo
    "두통": 4,  # Headache
    "발작": 3,  # Seizure
    "보행장애/운동실조/강직": 4,  # Gait disturbance/ataxia
    "사지약화/뇌졸중 증상": 2,  # Extremity weakness/symptoms of CVA
    "두부손상": 4,  # Head injury
    "떨림(Tremor)": 4,  # Tremor
    "감각상실/이상감각": 4,  # Sensory loss/paresthesia
    # D 눈
    "눈의 화학물질 노출": 2,  # Chemical exposure (eye)
    "눈의 이물질": 5,  # Foreign body - eye
    "시력장애": 4,  # Visual disturbance
    "눈통증": 4,  # Eye pain
    "눈충혈·분비물": 5,  # Redeye/discharge
    "눈부심": 4,  # Photophobia
    "복시": 4,  # Diplopia
    "안와주위 부종": 5,  # Periorbital swelling
    "눈의 외상": 4,  # Eye trauma
    # E 코
    "코피": 5,  # Epistaxis
    "코막힘": 5,  # Nasal congestion/hay fever
    "코의 이물질": 5,  # Foreign body - nose
    "상기도감염 증상 호소": 5,  # Upper respiratory tract infection complaints
    "코의 외상": 5,  # Nasal trauma
    # F 귀
    "이통(Earache)": 5,  # Earache
    "귀의 이물질": 5,  # Foreign body - ear
    "청력손실": 5,  # Loss of hearing
    "이명": 4,  # Tinnitus
    "귀의 삼출물": 4,  # Discharge, ear
    "귀의 손상": 5,  # Ear injury
    # G 입,목/얼굴
    "치아/구강 문제": 5,  # Dental/gum problem
    "안면외상": 5,  # Facial trauma
    "인후통": 5,  # Sore throat
    "목의 부종/통증": 4,  # Neck swelling/pain
    "목의 외상": 4,  # Neck trauma
    "연하장애/연하곤란": 3,  # Difficulty swallowing/dysphagia
    "안면 통증(비외상성/비치아성)": 5,  # Facial pain
    # H 호흡기계
    "숨참": 4,  # Shortness of breath
    "호흡정지": 1,  # Respiratory arrest
    "과다호흡증후군": 4,  # Hyperventilation
    "객혈": 4,  # Hemoptysis
    "기침/코막힘": 5,  # Cough/congestion
    "호흡기 이물질": 4,  # Respiratory foreign body
    "알레르기반응": 5,  # Allergic reaction
    # I 심혈관계
    "심정지(비외상성)": 1,  # Cardiac arrest (non-traumatic)
    "심정지(외상성)": 1,  # Cardiac arrest (traumatic)
    "흉통(심장성)": 2,  # Chest pain (with cardiac feature)
    "흉통(비심장성)": 4,  # Chest pain (non-cardiac features)
    "심계항진/불규칙한 심장박동": 4,  # Palpitations/irregular heartbeat
    "고혈압": 4,  # Hypertension
    "전신쇠약": 4,  # General weakness
    "실신/전실신": 4,  # Syncope/pre-syncope
    "전신부종": 4,  # Edema-generalized
    "다리 부기/부종": 5,  # Bilateral leg swelling/edema
    "맥박이 없거나 차가운 사지": 2,  # Cool pulseless limb
    "일측성의 홍조 띤 뜨거운 사지": 4,  # Unilateral reddened hot limb
    # J 소화기계
    "복통": 4,  # Abdominal pain
    "식욕부진": 4,  # Anorexia
    "변비": 4,  # Constipation
    "직장내 이물질": 5,  # Foreign body in rectum
    "샅고랑부위 통증/종괴": 4,  # Groin pain/mass
    "구토/구역": 4,  # Nausea/vomiting
    "항문/직장/회음부 통증": 4,  # Rectal/perineal pain
    "설사": 4,  # Diarrhea
    "토혈": 3,  # Vomiting blood (hematemesis)
    "혈변/흑색변": 3,  # Blood in stool/melena
    "황달": 4,  # Jaundice
    "딸꾹질": 4,  # Hiccoughs
    "복부종괴/팽만": 4,  # Abdominal distension/mass
    "항문/직장/회음부 외상": 5,  # Anal/rectal trauma
    "이물질 삼킴": 4,  # Oral/esophageal Foreign body
    # K 임신/여성생식계
    "월경 문제": 4,  # Menstrual problem
    "질내 이물질": 5,  # Foreign body - vagina
    "질 분비물": 5,  # Vaginal discharge
    "질통증/가려움": 5,  # Vaginal pain/itch
    "질출혈": 3,  # Vaginal bleeding
    "20주 미만의 임신": 4,  # Pregnancy issue <20weeks
    "20주 이상의 임신": 3,  # Pregnancy issue >20 weeks
    "성폭행": 4,  # Sexual assault
    "생식기의 외상": 4,  # Genital trauma
    # L 비뇨기계/남성생식계
    "옆구리 통증": 4,  # Flank pain
    "혈뇨": 5,  # Hematuria
    "생식기의 분비물/피부병변": 5,  # Genital discharge/lesion
    "음경부종": 5,  # Penile swelling
    "고환 통증/부종": 4,  # Scrotal pain and/or swelling
    "소변 배출장애": 4,  # Urinary retention
    "요로감염 증상": 5,  # Urinary tract infection complaints
    "핍뇨증": 4,  # Oliguria
    "다뇨증": 4,  # Polyuria
    "성폭행(남성)": 4,  # Sexual assault
    # M 근골격계
    "목·등·허리 통증": 4,  # Back pain
    "외상성 목·등·허리 손상": 4,  # Traumatic back/spine injury
    "절단": 4,  # Amputation
    "상지 통증": 5,  # Upper extremity pain
    "하지 통증": 5,  # Lower extremity pain
    "상지 손상": 5,  # Upper extremity injury
    "하지 손상": 5,  # Lower extremity injury
    "관절 부종": 5,  # Joint swelling
    "석고붕대 확인": 5,  # Cast check
    # N 몸통외상
    "몸통을 포함한 다발성 외상": 4,  # Major trauma (blunt) — 관통상(3)인지 모르므로 둔상 값
    "단독 흉부외상-관통상": 2,  # Isolated chest trauma (penetrating)
    "단독 흉부외상-둔상": 4,  # Isolated chest trauma (blunt)
    "단독 복부외상-관통상": 2,  # Isolated abdomen trauma (penetrating)
    "단독 복부외상-둔상": 4,  # Isolated abdominal trauma (blunt)
    # O 환경손상
    "동상/한랭손상": 5,  # Cold injury/frostbite
    "유해물질흡입": 4,  # Noxious inhalation
    "전기손상": 3,  # Electrical injury
    "화학물질 노출": 2,  # Chemical exposure
    "저체온증": 4,  # Hypothermia
    "익수": 3,  # Near drowning
    # P 피부
    "물림(Bite)": 5,  # Bite
    "쏘임(Sting)": 5,  # Sting
    "찰과상": 5,  # Abrasion
    "열상/천공": 5,  # Laceration/puncture
    "화상": 5,  # Burn
    "혈액이나 체액에 노출": 3,  # Blood and body fluid exposure
    "피부의 이물질": 5,  # Foreign body - skin
    "상처확인": 5,  # Wound check
    "스테이플/봉합사 제거": 5,  # Removal staples/stitches
    "발진": 5,  # Rash
    "유방의 발적/압통": 5,  # Redness/tenderness, breast
    "국소성 부종/발적": 5,  # Localized swelling/redness
    "혹·돌기·굳은살": 5,  # Lumps, bumps, calluses
    "감염 가능성 확인": 5,  # Rule out infestation
    "청색증": 3,  # Cyanosis
    "외상없이 저절로 멍듦": 3,  # Spontaneous bruising
    "소양증": 5,  # Pruritus
    "기타피부상태": 5,  # Other skin conditions
    # Q 일반
    "감염성 질환에 노출": 5,  # Exposure to communicable disease
    "열": 4,  # Fever
    "고혈당": 3,  # Hyperglycemia
    "저혈당": 3,  # Hypoglycemia
    "전문진료를 위해서 의뢰된 환자": 5,  # Direct referral for consultation
    "드레싱교체": 5,  # Dressing change
    "영상검사/검사실 검사": 5,  # Imaging tests
    "의료장비문제": 4,  # Medical device problem
    "처방전/투약문의": 5,  # Prescription/medication request
    "반지제거": 5,  # Ring removal
    "비정상 검사결과": 5,  # Abnormal lab values
    "창백함/빈혈": 4,  # Pallor/anemia
    "수술 후 합병증": 4,  # Postoperative complications
    "경증 및 비특이적 증상 호소": 5,  # Minor complaints
}

#: 첫인상 평가 "중증외상 + 수축기혈압 90 미만"의 외상 주증상. 외상성 심정지는 주증상만으로 이미 1단계라 뺀다.
TRAUMA_COMPLAINTS = frozenset({
    "두부손상", "눈의 외상", "코의 외상", "귀의 손상", "안면외상", "목의 외상", "항문/직장/회음부 외상",
    "생식기의 외상", "외상성 목·등·허리 손상", "절단", "상지 손상", "하지 손상", "열상/천공",
    "몸통을 포함한 다발성 외상", "단독 흉부외상-관통상", "단독 흉부외상-둔상", "단독 복부외상-관통상", "단독 복부외상-둔상",
})

#: 혈당 기준의 "증상 있음"을 대신하는 출력. 원문 증상 중 모델 출력에 대응하는 것만 쓴다.
#: 저혈당: 착란·경련·행동 변화(의식 저하 포함) / 고혈당: 호흡곤란·쇠약·다뇨
LOW_GLUCOSE_SYMPTOMS = frozenset({"착란", "발작", "의식수준의 변화", "기괴한 행동"})
HIGH_GLUCOSE_SYMPTOMS = frozenset({"숨참", "전신쇠약", "다뇨증"})
GLUCOSE_LOW_MG_DL = 54  # 3 mmol/L
GLUCOSE_HIGH_MG_DL = 324  # 18 mmol/L


def _num(value) -> float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def assess(patient: dict) -> dict:
    """환자 1명(모델 출력 dict) -> {"level": 1~5 | None, "basis": [{"rule", "level", "text"}], "source": "rule"}.

    basis에는 걸린 기준을 모두 남긴다(최종 단계를 정한 것만이 아니라). 어느 기준에도 걸리지 않으면 level은 None —
    없는 단계를 지어내지 않는다."""
    basis: list[dict] = []

    def hit(rule: str, level: int, text: str) -> None:
        basis.append({"rule": rule, "level": level, "text": text})

    cc_minor = patient.get("cc_minor")
    avpu = patient.get("avpu")
    sbp, hr, rr = _num(patient.get("sbp")), _num(patient.get("hr")), _num(patient.get("rr"))
    spo2, temp, gcs, glucose = (_num(patient.get(k)) for k in ("spo2", "temp", "gcs", "glucose"))

    if cc_minor in COMPLAINT_MIN_LEVEL:
        hit("complaint", COMPLAINT_MIN_LEVEL[cc_minor], f"주증상 {cc_minor}")

    if spo2 is not None:
        if spo2 < 90:
            hit("spo2", 1, f"산소포화도 {spo2:g}% (90 미만)")
        elif spo2 < 92:
            hit("spo2", 2, f"산소포화도 {spo2:g}% (90 이상 92 미만)")
        elif spo2 < 94:
            hit("spo2", 3, f"산소포화도 {spo2:g}% (92 이상 94 미만)")

    # 혈역학: OTAS는 수축기혈압이 있어야 판정한다. 맥박이 없으면 80~100 구간은 맥박과 무관하게 3단계 이상이라 3으로 본다
    if sbp is not None:
        hr_abnormal = hr is not None and (hr > 100 or hr < 60)
        if sbp < 80:
            hit("hemodynamic", 1, f"수축기혈압 {sbp:g} (80 미만)")
        elif sbp < 100 and hr_abnormal:
            hit("hemodynamic", 2, f"수축기혈압 {sbp:g} (80 이상 100 미만) + 맥박 {hr:g}")
        elif sbp < 100:
            hit("hemodynamic", 3, f"수축기혈압 {sbp:g} (80 이상 100 미만)")
        elif hr_abnormal:
            hit("hemodynamic", 3, f"수축기혈압 {sbp:g} + 맥박 {hr:g} (100 초과 또는 60 미만)")
        if sbp < 90 and cc_minor in TRAUMA_COMPLAINTS:
            hit("trauma_hypotension", 1, f"외상({cc_minor}) + 수축기혈압 {sbp:g} (90 미만)")

    if avpu == "U":
        hit("avpu", 1, "의식 U(무반응)")
    elif avpu in ("V", "P"):
        hit("avpu", 2, f"의식 {avpu}")

    if gcs is not None:
        if 3 <= gcs <= 8:
            hit("gcs", 1, f"GCS {gcs:g} (3-8)")
        elif 9 <= gcs <= 13:
            hit("gcs", 2, f"GCS {gcs:g} (9-13)")

    # SIRS: OTAS의 체온 기준은 셋 다 체온 이상을 전제로 한다
    if temp is not None and (temp < 36 or temp > 38):
        others = [s for s, on in ((f"맥박 {hr:g}" if hr is not None else "", hr is not None and hr > 90),
                                  (f"호흡수 {rr:g}" if rr is not None else "", rr is not None and rr > 20)) if on]
        if len(others) == 2:
            hit("sirs", 2, f"SIRS 3개 — 체온 {temp:g}, {', '.join(others)}")
        elif others:
            hit("sirs", 3, f"체온 {temp:g} + {others[0]}")
        else:
            hit("sirs", 4, f"체온 {temp:g} (36 미만 또는 38 초과)")

    if glucose is not None:
        altered = avpu in ("V", "P", "U") or (gcs is not None and gcs <= 13)
        if glucose < GLUCOSE_LOW_MG_DL:
            if altered or cc_minor in LOW_GLUCOSE_SYMPTOMS:
                hit("glucose", 2, f"혈당 {glucose:g} (54 미만) + 의식·행동 변화")
            else:
                hit("glucose", 3, f"혈당 {glucose:g} (54 미만)")
        elif glucose >= GLUCOSE_HIGH_MG_DL and cc_minor in HIGH_GLUCOSE_SYMPTOMS:
            hit("glucose", 2, f"혈당 {glucose:g} (324 이상) + {cc_minor}")

    level = min((b["level"] for b in basis), default=None)
    return {"level": level, "basis": basis, "source": "rule"}


def annotate(summary: dict) -> dict:
    """MF_BERT 출력 {"patient_count", "patients"} -> 환자마다 "pre_ktas"를 덧붙인 새 dict (모델 출력 값은 그대로)."""
    return {**summary, "patients": [{**patient, "pre_ktas": assess(patient)} for patient in summary["patients"]]}


def _self_test() -> None:
    def level(**patient) -> int | None:
        return assess(patient)["level"]

    assert level(cc_minor="심정지(비외상성)") == 1
    assert level(cc_minor="코피") == 5
    assert level(cc_minor="코피", spo2=91) == 2
    assert level(cc_minor="복통", sbp=75, hr=120) == 1
    assert level(cc_minor="복통", sbp=95, hr=110) == 2
    assert level(cc_minor="복통", sbp=95) == 3
    assert level(cc_minor="코피", sbp=130, hr=120) == 3
    assert level(cc_minor="하지 손상", sbp=85) == 1  # 외상 + 수축기혈압 90 미만
    assert level(cc_minor="복통", sbp=85) == 3  # 외상 아님
    assert level(cc_minor="코피", avpu="P") == 2
    assert level(cc_minor="코피", avpu="기타", gcs=7) == 1
    assert level(cc_minor="코피", temp=38.6, hr=110, rr=24) == 2
    assert level(cc_minor="코피", temp=38.6, hr=110) == 3
    assert level(cc_minor="코피", temp=38.6) == 4
    assert level(cc_minor="코피", glucose=40) == 3
    assert level(cc_minor="착란", glucose=40) == 2
    assert level(cc_minor="숨참", glucose=400) == 2
    assert level(cc_minor="코피", glucose=400) == 5  # 증상 없는 고혈당은 원문 표에 단계가 없다
    assert level(cc_minor="판단 보류") is None
    assert level(cc_minor="판단 보류", spo2=99, sbp=120, hr=80) is None  # 걸린 기준이 없으면 단계도 없다
    print("자체 검사 통과")


def _report(path: str) -> None:
    """MF_BERT eval_predictions.jsonl(pred·gold 환자 출력)로 단계 분포와, 모델 오차가 단계를 얼마나 바꾸는지 본다."""
    pairs = Counter()
    pred_dist, gold_dist = Counter(), Counter()
    for line in open(path, encoding="utf-8"):
        row = json.loads(line)
        for pred, gold in zip(row["pred"]["patients"], row["gold"]["patients"]):
            p, g = assess(pred)["level"], assess(gold)["level"]
            pred_dist[p] += 1
            gold_dist[g] += 1
            pairs[(g, p)] += 1
    total = sum(pairs.values())
    same = sum(n for (g, p), n in pairs.items() if g == p)
    under = sum(n for (g, p), n in pairs.items() if g is not None and p is not None and p > g)
    keys = sorted(set(gold_dist) | set(pred_dist), key=lambda k: (k is None, k or 0))
    print(f"환자 {total}명 (환자 슬롯이 정답과 짝지어진 것만)")
    print("단계   정답 출력으로   모델 출력으로")
    for k in keys:
        print(f"{str(k):>4}   {gold_dist[k]:>12}   {pred_dist[k]:>12}")
    print(f"정답 출력과 같은 단계 {same / total:.1%}, 모델 출력이 덜 위급하게 낸 경우 {under / total:.1%}")


if __name__ == "__main__":
    _self_test()
    if len(sys.argv) > 1:
        _report(sys.argv[1])
