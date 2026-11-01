"""거미줄 분배 모델(spider)의 매칭 규칙을 hub로 옮긴 것(2026-10-15). 숫자만 계산하는 순수 규칙 기반 모듈
(source: "rule"). 원본은 spider/map.html의 JS 엔진(KTAS_Z·COND·zEff·candidates·solve의 충돌 규칙)과
spider/voice_to_patient.py(질환군 규칙)이고, 값은 map.html 화면의 기본값이다 — 한쪽을 고치면 다른 쪽도 맞출 것.

    병원      = (위치, 유효 역량 z)   z = 등급(1~4) + 전문의 두께 + 야간 감점        (부하는 z에 안 넣는다)
    환자      = 필요 역량           KTAS 1→4, 2→3, 3→2, 4·5→1
    줄 길이   = 도로 분 − μ × 올라가는 이득(한 단계까지 전액, 그 위 1/4)          (유효 역량 ≥ 필요)
             = 도로 분 + ν × 모자란 양                                       (유효 역량 < 필요, 0.75 넘게 모자라면 줄 없음)
             + 부하(분)  — 이송 중 10×n/(n+가용) + 포화 최대 5분 (hub scoring과 같은 식)
    μ        = KTAS 1·2 30분/레벨, 3은 5분, 4·5는 −λ(5분, 센터 회피). 이송 중 중증(K1·2)이 10명이면 0까지 감쇠
    ν        = 30 / 15 / 5분
    벽(질환군) = 심근경색 → 혈관조영 운영, 뇌졸중 → CT 운영 + 등급 2 이상, 중증외상 → 등급 3 이상
    τ 창      = 도착 시각이 τ(10분) 안에 겹치는 다른 사건. **표시만 한다 — 순위에 넣지 않는다**(2026-10-22)

숫자는 전부 spider 쪽 표기 그대로 "전문의 검토 전 초안"이다. 진료과 임베딩 점수는 이 모델에 없어 순위에 쓰지 않는다
(설명용으로만 남는다). 줄이 없는 병원(벽·모자람)도 계산·감사용 후보에는 남긴다. 실제 대시보드 전달에서는
hospital_dispatch.py가 이를 거른다(2026-11-01). 임상 검증 전 시연 기준이라는 점은 같다.

⚠ **τ 창 충돌·양보를 순위에서 뺐다(2026-10-22).** 예전엔 같은 창에 우선하는 사건의 줄이 한도(2)만큼 차 있으면
그 병원을 건너뛰고(점수 띠를 한 단계 내림) 밀린 사건이 다음 병원으로 줄을 옮겼다(spider의 "양보"). 근거 둘이
같은 방향이라 뺐다 — ① `spider/replay_probe.py` 실측: 창 항을 켜면 서울 밀집에서 도착 거절이 **46→51**(lag 0)·
**56→65**(lag 15)로 늘고 시간 이득은 없다(전국은 창이 겹치지 않아 효과 0). 공개 GPU 트레이스에서도 혼잡 항 단독
+11~19%, 우선순위 양보·노화는 +9~141%였다. ② 임상 자문(2026-10): *"중등도를 받기로 한 상태에서 심정지가 추가로
오면 혼란이 있더라도 두 환자를 모두 수용하고 대응하려 노력하는 경우가 많다"* — 창이 찼다는 이유로 hub가 미리
건너뛰면 병원이 판단할 기회 자체가 없어진다. 지금은 `spiderWindow`로 **사실만 싣고 수용 판단은 병원이 한다.**
근거·수치는 `poc/CLINICAL_CONVERGENCE.md` §3. spider 연구 엔진(`spider/engine/`·`spider/map.html`)은 창 항을
연구 대상으로 **그대로 둔다** — 그쪽 README의 "①~⑤를 합친 판단"도 "창 혼잡·양보는 (hub에) 넣지 않는다"다.
"""
from __future__ import annotations

import math
import os
import re
from datetime import datetime, timedelta, timezone

KTAS_Z = {1: 4, 2: 3, 3: 2, 4: 1, 5: 1}
NU = {1: 30.0, 2: 30.0, 3: 15.0, 4: 5.0, 5: 5.0}
GAP_FLOOR = -0.75
MU2, MU3, LAM = 30.0, 5.0, 5.0
TAU_MIN = 10.0
WINDOW_CAP = 2
SEVERITY_K = {"high": 2, "medium": 3, "low": 4}
LEVEL_G = {"권역응급의료센터": 4, "지역응급의료센터": 3, "지역응급의료기관": 2, "응급실운영신고기관": 1}
COND_LABEL = {"general": "일반", "stemi": "심근경색", "stroke": "뇌졸중", "trauma": "중증외상"}
KST = timezone(timedelta(hours=9))

# spider/voice_to_patient.py와 같은 질환군 키워드. 뇌졸중 → 심근경색 → 중증외상(외상 기전 + KTAS 1·2) → 일반
STROKE = re.compile(r"뇌졸중|뇌\s*경색|뇌출혈|편마비|구음\s*장애|거미막하|지주막하|두개내\s*출혈|경막[하외]\s*(출혈|혈종)")
STEMI = re.compile(r"심근\s*경색|급성\s*관상|STEMI|흉통\(심장성\)|경색")


def patient_of(ktas_level: int | None, severity_tag: str | None, expected_text: str, trauma: bool | None) -> tuple[int, str]:
    """(KTAS, 질환군). KTAS가 없으면(예전 6필드 voice) 중증도로 대표값."""
    k = ktas_level if ktas_level in (1, 2, 3, 4, 5) else SEVERITY_K.get(severity_tag or "", 3)
    text = expected_text or ""
    if STROKE.search(text):
        return k, "stroke"
    if STEMI.search(text):
        return k, "stemi"
    if trauma and k <= 2:
        return k, "trauma"
    return k, "general"


def local_hour(now: datetime) -> float:
    """야간 감점(22~06시)에 쓰는 지금 시각(한국 시간). HUB_SPIDER_HOUR를 주면 그 시각으로 고정한다 — 검사가 돌리는 시각에 따라
    결과가 바뀌지 않게(검사는 map.html 기본값 14시로 고정), 또는 시연에서 낮·밤 순위를 일부러 보여 줄 때."""
    fixed = os.environ.get("HUB_SPIDER_HOUR")
    if fixed:
        return float(fixed) % 24
    t = now.astimezone(KST)
    return t.hour + t.minute / 60.0


def _equipment(info, key: str, capability: str) -> str | None:
    """E-Gen 장비 운영(Y/N/N1) → 'Y'/'N'. 운영값이 없으면 역량 코드로, 그것도 없으면 None(모름)."""
    value = (getattr(info, "equipmentOperating", None) or {}).get(key)
    if value:
        return "Y" if value == "Y" else "N"
    caps = getattr(info, "capabilities", None) or []
    return "Y" if capability in caps else None


def hospital_z(info, hour: float) -> tuple[int, float, str]:
    """(등급 g, 유효 역량 z, 설명). 전문의 두께는 응급의학과 전문의 수(심평원)."""
    g = LEVEL_G.get(info.emergencyLevel or "", 1)
    em = next((s.doctorCount for s in info.specialties if s.department == "응급의학과"), 0) or 0
    thick = -0.4 if em <= 1 else -0.2 if em <= 3 else 0.2 if em >= 8 else 0.0
    night = hour >= 22 or hour < 6
    nt = (-0.6 if (g <= 2 and em <= 2) else -0.25 if em <= 3 else -0.1) if night else 0.0
    parts = f"등급{g} 전문의{em}명 {'+' if thick >= 0 else ''}{thick:.1f}" + (f" 야간{nt:.1f}" if night else "")
    return g, g + thick + nt, parts


def wall_ok(info, g: int, cond: str) -> bool:
    if cond == "stemi":
        return _equipment(info, "ANGIO", "EQP_ANGIO_SUITE") == "Y"
    if cond == "stroke":
        return _equipment(info, "CT", "EQP_CT_24H") == "Y" and g >= 2
    if cond == "trauma":
        return g >= 3
    return True


def line(k: int, cond: str, info, travel_min: float, load_min: float, inflight_severe: int, hour: float) -> dict:
    """한 병원에 거는 줄. {len, gap, gain_min, parts, blocked} — 줄이 없으면 len=None, blocked=이유."""
    need = KTAS_Z[k]
    mu0 = MU2 if k <= 2 else MU3 if k == 3 else -LAM
    mu = mu0 * max(0.0, 1 - inflight_severe / 10.0) if k <= 3 else mu0
    g, z, parts = hospital_z(info, hour)
    if not wall_ok(info, g, cond):
        return {"len": None, "gap": z - need, "gain_min": 0.0, "parts": parts, "blocked": f"{COND_LABEL[cond]} 벽"}
    gap = z - need
    if gap < GAP_FLOOR:
        return {"len": None, "gap": gap, "gain_min": 0.0, "parts": parts, "blocked": f"역량 모자람 {gap:+.2f}"}
    if gap >= 0:
        gain = mu * (min(gap, 1.0) + 0.25 * max(0.0, gap - 1.0))
    else:
        gain = -NU[k] * (-gap)
    return {"len": travel_min - gain + load_min, "gap": gap, "gain_min": gain, "parts": parts, "blocked": None}


def ktas_suitability(k: int, cond: str, info, hour: float) -> dict:
    """병원별 KTAS 전달 근거. 기존 spider의 벽·허용 역량 차이를 그대로 쓴다.

    supportedKtas는 이 질환군·시각에 대한 모형상의 값이며 실제 수용 보장이 아니다.
    """
    g, z, _ = hospital_z(info, hour)
    supported = [level for level, need in KTAS_Z.items() if wall_ok(info, g, cond) and z - need >= GAP_FLOOR]
    return {"source": "rule", "rule": "spider_ktas_v1", "clinicallyValidated": False,
            "patientKtas": k, "condition": cond, "requiredCapacity": KTAS_Z[k],
            "effectiveCapacity": round(z, 2), "minimumGap": GAP_FLOOR,
            "supportedKtas": supported, "eligible": k in supported}


def gain_reasons(sp: dict, k: int) -> list[str]:
    """줄 길이의 이득·비용을 사람이 읽는 문구로 — 위급할수록 상급 병원으로(μ), 경증은 센터 보존(−λ), 역량 모자람(ν)."""
    gain, gap = sp["gain_min"], sp["gap"]
    if sp["len"] is None or abs(gain) < 0.05:
        return []
    if gap < 0:
        return [f"역량 {-gap:.2f} 모자람 +{-gain:.1f}분"]
    if gain < 0:
        return [f"경증 · 센터 보존(λ) +{-gain:.1f}분"]
    return [f"KTAS {k} · 역량 {gap:+.2f} 이득 −{gain:.1f}분"]


def score(line_len: float | None, travel_min: float, load_min: float = 0.0) -> float:
    """정렬용 점수(클수록 앞) — hub 정렬(scoring.rank_key: 확정 → 승인 → 나머지 → 내림 → 거절)의 finalScore 칸에 넣는다.
    줄이 짧을수록 높다. 띠를 둘로 나눠 '줄 있음 > 줄 없음'이 항상 지켜지게 한다. 줄 없는 병원끼리는
    spider의 '초과로 붙이기'처럼 도로 분 + 부하로 가른다(부하가 쌓인 병원이 계속 앞에 남지 않게).

    τ 창은 여기에 들어오지 않는다(2026-10-22, 위 모듈 설명 ⚠) — 창이 찬 병원도 줄 길이 그대로 겨룬다."""
    if line_len is None:
        return round(0.5 / (1 + math.exp((travel_min + load_min) / 15.0)), 6)
    s = 1 / (1 + math.exp(line_len / 15.0))   # 0~1, 줄이 짧을수록 1에 가깝다(음수 줄 길이도 그대로 순서가 선다)
    return round(0.5 + 0.5 * s, 6)


def outranks(a: tuple, b: tuple) -> bool:
    """τ 창 표시에서 a가 b보다 먼저 자리를 가졌다고 볼지 — (KTAS, 도착 시각, 사건 id) 순. KTAS 낮은 숫자, 같으면
    먼저 닿는 쪽. 순위에는 쓰지 않는다(창은 표시용) — 어느 사건을 `spiderWindow`에 적을지만 정한다."""
    return a < b
