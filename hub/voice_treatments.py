"""2026-10-29 voice 처치판 → 기존 단일 환자 계약. 범주명 변환은 규칙 기반.

서로 다른 환자의 처치를 섞지 않도록 다중 환자 입력은 명시적으로 거절한다.
"""
TREATMENTS = dict(zip(
    ('oxygen suction foreign_body airway_basic airway_advanced ventilation cpr defib iv fluid bleeding '
     'med_aspirin med_nitro med_glucose med_epinephrine med_bronchodilator med_other spinal splint wound burn '
     'irrigation cold_pack cooling warming position delivery other').split(),
    ['산소투여', '기도 흡인', '기도 이물 제거', '기본 기도확보', '전문 기도확보', '인공호흡', 'CPR', 'AED',
     '정맥로 확보', '수액공급', '지혈', '아스피린 투여', '니트로글리세린 투여', '포도당 투여', '에피네프린 투여',
     '기관지확장제 투여', '기타 약물투여', '척추 고정', '부목 고정', '상처처치', '화상 처치', '세척', '냉찜질',
     '냉각', '보온', '체위 조절', '분만 처치', '기타 처치']))


def normalize(summary):
    patients = summary.get('patients') or []
    if len(patients) != 1 or summary.get('patient_count') != 1:
        raise ValueError('현재 사건은 환자 1명만 지원합니다. 환자별 사건으로 구분해 전송해 주세요.')
    p = patients[0]
    def known(value):
        return value if value not in (None, '', '판단 보류', '미상') else None
    complaint = known(p.get('cc_minor')) or known(p.get('cc_major'))
    level = (p.get('pre_ktas') or {}).get('level')
    return dict(
        patient=' '.join(str(v) for v in [known(p.get('age_group')), known(p.get('gender'))] if v) or '미상',
        mechanism=complaint or '미상', chief_complaint=complaint,
        symptoms=[complaint] if complaint else [],
        treatment=list(dict.fromkeys(TREATMENTS.get(c, f'기타 처치({c})') for c in p.get('treat_categories') or [])),
        severity_tag={1:'high', 2:'high', 3:'medium', 4:'low', 5:'low'}.get(level, 'medium'),
        ktas_level=level, required_department=None,
        consciousness={'A':'명료(A)', 'V':'음성 반응(V)', 'P':'통증 반응(P)', 'U':'무반응(U)'}.get(p.get('avpu')),
        vitals=[dict(sequence=1, **{k:p.get(k) for k in ('sbp','dbp','hr','rr','spo2','glucose')}, bt=p.get('temp'))],
    )
