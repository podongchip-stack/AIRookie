"""거미줄 분배 모델의 식 — 필요 역량, 유효 역량, 줄 길이, 질환군 벽. 상태 없는 순수 규칙(source: "rule").

map.html(JS 엔진)의 `KTAS_Z`·`COND`·`zEff`·`candidates`를 그대로 옮겼다(README "모델" 절). 숫자는 전부 전문의 검토 전
초안이고, 화면 슬라이더(τ·한도·회전·μ·λ·시작 시각·유효 역량·부하 항)가 `Params`로 들어온다. 한쪽을 고치면 parity_check.py로
JS와 다시 대조한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from .roads import straight_min

KTAS_Z = {1: 4, 2: 3, 3: 2, 4: 1, 5: 1}   # 필요 역량: KTAS 1→4, 2→3, 3→2, 4·5→1
GAP_FLOOR = -0.75                          # 유효 역량이 이보다 더 모자라면 줄이 안 걸린다
NU = {1: 30.0, 2: 30.0, 3: 15.0, 4: 5.0, 5: 5.0}   # 모자람의 비용(분/레벨) — 위급할수록 큼


def fx(x: float, digits: int) -> str:
    """JS Number.prototype.toFixed와 같은 반올림(정확한 십진 전개에서 반올림, 동률은 큰 쪽). 기록 문구 대조용."""
    q = Decimal(1).scaleb(-digits)
    return str(Decimal(x).quantize(q, rounding=ROUND_HALF_UP))


@dataclass
class Params:
    """화면 슬라이더 값. 기본값은 map.html 초기값과 같다."""
    tau: float = 10.0        # 도착 시각이 이 안에 겹치면 같은 창(분)
    cap: int = 2             # 한 창 안에 받는 환자 수
    dwell: float = 30.0      # 도착 후 병상을 비우기까지(분)
    mu2: float = 30.0        # KTAS 1·2가 한 단계 위로 가려고 더 갈 분
    mu3: float = 5.0         # KTAS 3
    lam: float = 5.0         # 경증(KTAS 4·5)이 센터로 갈 때 물리는 분
    start_hour: float = 14.0 # 시작 시각(시) — 야간 22~06은 얇은 병원 역량이 내려간다
    dyn: bool = True         # 유효 역량(전문의 두께·야간) + 부하 항 사용
    wload: bool = True       # 부하 항을 줄 길이에 분으로

    @classmethod
    def from_dict(cls, d: dict | None) -> "Params":
        d = d or {}
        p = cls()
        for k in ("tau", "dwell", "mu2", "mu3", "lam", "start_hour"):
            if d.get(k) is not None:
                setattr(p, k, float(d[k]))
        if d.get("cap") is not None:
            p.cap = int(d["cap"])
        for k in ("dyn", "wload"):
            if d.get(k) is not None:
                setattr(p, k, bool(d[k]))
        return p


# 질환군 딱딱한 벽: 이 장비·등급이 없으면 줄 자체가 안 걸린다(초안, 전문의 검토 전)
COND = {
    "general": {"label": "일반", "wall": lambda h: True},
    "stemi": {"label": "심근경색", "wall": lambda h: h.get("angio") == "Y"},
    "stroke": {"label": "뇌졸중", "wall": lambda h: h.get("ct") == "Y" and h["g"] >= 2},
    "trauma": {"label": "중증외상", "wall": lambda h: h["g"] >= 3},
}


def cond_label(cond: str | None) -> str:
    return COND.get(cond or "general", COND["general"])["label"]


def is_full(h: dict) -> bool:
    """확인된 만실 — 병상 데이터가 있고 응급실 가용이 0 이하. 미상(None)은 만실로 보지 않는다."""
    return bool(h.get("hasBeds")) and h.get("hvec") is not None and h["hvec"] <= 0


class Ctx:
    """해소 루프가 후보 계산에 넘기는 '지금 장부' — 창 안 인원·이송 중 건수를 병원별로 세는 함수들."""

    def __init__(self, cap: int, inflight_severe: int, inflight, win_count):
        self.cap = cap
        self.inflight_severe = inflight_severe
        self.inflight = inflight        # hpid -> 이송 중(아직 도착 전) 건수
        self.win_count = win_count      # hpid -> 지금 시각 ±τ 창 안 건수


def z_eff(h: dict, t_now: float, ctx: Ctx, prm: Params) -> dict:
    """병원 유효 역량 z와 부하(분). 설명용 분해 문구를 같이 돌려준다.

    부하(포화·이송 중)는 z에 넣지 않는다 — z는 μ에 곱해지는데 μ가 경증에서 음수라 붐비는 병원이 경증에게 더 짧아졌다
    (2026-10-12 재생에서 확인). 부하는 분으로 따로 돌려주고 줄 길이에 더한다: hub와 같은 식 —
    이송 중 페널티 10 × 이송 중/(이송 중+가용), 포화 페널티 최대 5분.
    """
    if not prm.dyn:
        return {"z": float(h["g"]), "parts": "", "load": 0.0, "load_parts": ""}
    em = h.get("em") if h.get("em") is not None else 0
    thick = -0.4 if em <= 1 else -0.2 if em <= 3 else 0.2 if em >= 8 else 0.0
    hour = (prm.start_hour + t_now / 60.0) % 24
    night = hour >= 22 or hour < 6
    nt = (-0.6 if (h["g"] <= 2 and em <= 2) else -0.25 if em <= 3 else -0.1) if night else 0.0
    occ = max(0.0, min(1.0, 1 - h["hvec"] / h["er_cap"])) if (h.get("er_cap") and h.get("hvec") is not None) else 0.5
    infl = ctx.inflight(h["hpid"]) if prm.wload else 0
    free = max(0, h["hvec"] if h.get("hvec") is not None else ctx.cap)
    lp = 10.0 * infl / max(1, infl + free)
    op = 5.0 * occ if prm.wload else 0.0
    parts = f"등급{h['g']} 전문의{em}명 {'+' if thick >= 0 else ''}{fx(thick, 1)}{(' 야간' + fx(nt, 1)) if night else ''}"
    load_parts = f"{(' 포화+' + fx(op, 1) + '분') if op else ''}{(' 이송중' + str(infl) + '건+' + fx(lp, 1) + '분') if infl else ''}"
    return {"z": h["g"] + thick + nt, "parts": parts, "load": lp + op, "load_parts": load_parts}


def candidates(row: dict, frm: dict, p: dict, t_now: float, ctx: Ctx, prm: Params, live: list[dict]) -> list[dict]:
    """환자 p가 지금 위치 frm에서 걸 수 있는 줄들을 짧은 순으로. 원소: h·road·gap·mu·len·parts.

    줄 길이 = 도로 분 − μ × 올라가는 이득(한 단계까지 전액, 그 위 1/4)        (유효 역량 ≥ 필요 역량)
            = 도로 분 + ν × 모자란 양                                       (유효 역량 < 필요 역량, 0.75 넘게 모자라면 줄 없음)
            + 부하(분)
    μ: 위급할수록 한 단계 위로 더 멀리 간다. 이송 중 중증(K1·2)이 많을수록 μ를 깎아 센터를 아낀다(10명이면 0).
    """
    k = p["k"]
    need = KTAS_Z[k]
    mu0 = prm.mu2 if k <= 2 else prm.mu3 if k == 3 else -prm.lam
    mu = mu0 * max(0.0, 1 - ctx.inflight_severe / 10.0) if k <= 3 else mu0
    wall = COND.get(p.get("cond") or "general", COND["general"])["wall"]
    nu = NU[k]
    # 환자별 제외 병원(p["exclude"]) — 실시간 모드에서 hub가 이 사건에 수용 불가(병상 0·불가·제외)로 본 병원(2026-10-15).
    # 초과로 붙일 때도 이 후보 목록을 쓰므로 거기서도 빠진다. 가상 시나리오엔 없다(map.html과 같은 규칙)
    exclude = set(p.get("exclude") or ())
    out = []
    for h in live:
        if is_full(h) or not wall(h) or h["hpid"] in exclude:
            continue
        road = row.get(h["hpid"])
        if road is None:
            road = straight_min(frm["lat"], frm["lng"], h["lat"], h["lng"])
        ze = z_eff(h, t_now, ctx, prm)
        gap = ze["z"] - need
        if gap < GAP_FLOOR:
            continue
        if gap >= 0:
            length = road - mu * (min(gap, 1.0) + 0.25 * max(0.0, gap - 1.0))
        else:
            length = road + nu * (-gap)
        length += ze["load"]
        out.append({"h": h, "road": road, "gap": gap, "mu": mu, "len": length, "parts": ze["parts"] + ze["load_parts"]})
    out.sort(key=lambda c: c["len"])  # 안정 정렬 — 동률이면 병원 목록 순서(z 내림차순) 그대로, JS와 같다
    return out
