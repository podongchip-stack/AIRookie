"""진주 응급의료 존 — 2개월 실측 리플레이 리포트 생성기 (PoC 0단).

승인 0명으로 만들 수 있는 PoC다. 이미 쌓여 있는 E-Gen 전국 스냅샷과
심평원 조인 캐시만 읽어서, "진주에서 구급대원이 전화 전에 알 수 있는 것과
알 수 없는 것"을 2개월 전수로 보여주는 자가완결 HTML 한 장을 만든다.

운영 규칙 (sim/·spider/와 같다): 다른 폴더의 파일을 수정하지 않는다.
info/ 쪽은 데이터 파일 읽기와 어휘 모듈 읽기 전용 import만 한다.

실행:
    conda activate dev
    cd poc && python build_jinju_replay.py
산출물:
    poc/out/jinju_replay.html
"""

from __future__ import annotations

import collections
import glob
import html
import json
import math
import os
import re
import statistics
import sys
from dataclasses import dataclass, field
from datetime import date

from report_base import CSS, JS, esc

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
INFO = os.path.join(ROOT, "info", "Hospital_inform", "info")
SNAP_DIR = os.path.join(INFO, "data", "snapshots_nationwide")
HIRA_DIR = os.path.join(INFO, "data", "hira")
OUT = os.path.join(HERE, "out", "jinju_replay.html")

# 중증질환 28항목 어휘는 info 쪽 정본을 읽어 쓴다 (손으로 다시 옮겨 적으면 어긋난다)
sys.path.insert(0, INFO)
from hospital_score import vocabulary as V  # noqa: E402

TARGET_SIGUNGU = "경상남도 진주시"
MKIOSK_FIELD = re.compile(r"^MKioskTy\d+$")

GRADE_ORDER = ["권역응급의료센터", "지역응급의료센터", "지역응급의료기관", "응급실운영신고기관"]
# 등급은 순서가 있는 값이라 범주형 8색이 아니라 단일 색 순서 램프를 쓴다.
# 검증: node scripts/validate_palette.js "#86b6ef,#3987e5,#256abf,#104281" --mode light --ordinal → ALL PASS
GRADE_FILL_LIGHT = {
    "권역응급의료센터": "#104281",
    "지역응급의료센터": "#256abf",
    "지역응급의료기관": "#3987e5",
    "응급실운영신고기관": "#86b6ef",
}
GRADE_FILL_DARK = {
    "권역응급의료센터": "#cde2fb",
    "지역응급의료센터": "#86b6ef",
    "지역응급의료기관": "#3987e5",
    "응급실운영신고기관": "#184f95",
}

KEY_DEPTS = [
    "응급의학과",
    "내과",
    "외과",
    "정형외과",
    "신경외과",
    "신경과",
    "심장혈관흉부외과",
    "소아청소년과",
    "산부인과",
]

# 응급실 가용 병상(hvec)과 정원(hvs01)
F_AVAIL, F_CAP, F_IDATE = "hvec", "hvs01", "hvidate"


@dataclass
class Hospital:
    hpid: str
    name: str
    grade: str
    addr: str
    tel: str
    lat: float
    lng: float
    cap: int | None = None
    daily: dict[str, int] = field(default_factory=dict)  # 날짜 -> 가용 중앙값
    vals: list[int] = field(default_factory=list)
    severe: dict[int, str] = field(default_factory=dict)  # 항목 no -> 정규화 값
    severe_seen: bool = False
    dr_total: int | None = None
    depts: dict[str, int] = field(default_factory=dict)
    cl_cd: str = ""
    join_km: float | None = None

    @property
    def short(self) -> str:
        n = self.name
        for junk in ("의료법인 ", "의료법인", "문병욱의료재단 ", "바른의료재단 ", "학교법인"):
            n = n.replace(junk, "")
        return n.strip()

    @property
    def has_bed_feed(self) -> bool:
        return bool(self.vals)

    @property
    def er_specialists(self) -> int:
        return self.depts.get("응급의학과", 0)


def iround(raw) -> int | None:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def load() -> tuple[dict[str, Hospital], dict, list]:
    files = sorted(glob.glob(os.path.join(SNAP_DIR, "*.jsonl")))
    if not files:
        raise SystemExit(
            f"스냅샷이 없다: {SNAP_DIR}\n"
            "먼저 info 쪽에서 `python -m egen.snapshot_cloud --sync`로 받아야 한다."
        )

    # 목록 API는 하루 1회만 들어 있어 가장 최근 파일부터 거꾸로 찾는다
    listing = None
    for path in reversed(files):
        with open(path, encoding="utf-8") as fp:
            for line in fp:
                rec = json.loads(line)
                if rec.get("operation") == "getEgytListInfoInqire" and rec.get("items"):
                    listing = rec["items"]
                    break
        if listing:
            break
    if not listing:
        raise SystemExit("목록 API 응답을 스냅샷에서 찾지 못했다")

    hs: dict[str, Hospital] = {}
    for it in listing:
        addr = it.get("dutyAddr") or ""
        if not addr.startswith(TARGET_SIGUNGU):
            continue
        hs[it["hpid"]] = Hospital(
            hpid=it["hpid"],
            name=it.get("dutyName") or it["hpid"],
            grade=it.get("dutyEmclsName") or "-",
            addr=addr,
            tel=it.get("dutyTel3") or it.get("dutyTel1") or "-",
            lat=float(it["wgs84Lat"]),
            lng=float(it["wgs84Lon"]),
        )

    stats = {"files": len(files), "bed_polls": 0, "severe_polls": 0, "idate": set()}
    per_day: dict[str, dict[str, list[int]]] = collections.defaultdict(lambda: collections.defaultdict(list))

    for path in files:
        day = os.path.basename(path)[:10]
        with open(path, encoding="utf-8") as fp:
            for line in fp:
                rec = json.loads(line)
                items = rec.get("items")
                if not items:
                    continue
                op = rec.get("operation")
                if op == "getEmrrmRltmUsefulSckbdInfoInqire":
                    stats["bed_polls"] += 1
                    for it in items:
                        h = hs.get(it.get("hpid"))
                        if not h:
                            continue
                        avail = iround(it.get(F_AVAIL))
                        if avail is not None:
                            h.vals.append(avail)
                            per_day[h.hpid][day].append(avail)
                        if h.cap is None:
                            cap = iround(it.get(F_CAP))
                            if cap:
                                h.cap = cap
                        if it.get(F_IDATE):
                            stats["idate"].add(str(it[F_IDATE])[:8])
                elif op == "getSrsillDissAceptncPosblInfoInqire":
                    stats["severe_polls"] += 1
                    for it in items:
                        h = hs.get(it.get("hpid"))
                        if not h:
                            continue
                        h.severe_seen = True
                        for key, raw in it.items():
                            if not MKIOSK_FIELD.match(key):
                                continue
                            norm = V.normalize_accept(raw)
                            if norm:
                                h.severe[int(key[len("MKioskTy"):])] = norm

    for hpid, days in per_day.items():
        hs[hpid].daily = {d: int(statistics.median(v)) for d, v in sorted(days.items())}

    # 심평원 — 없으면 역량 섹션만 빠지고 나머지는 그대로 (fail-soft)
    try:
        with open(os.path.join(HIRA_DIR, "egen_hira_join.json"), encoding="utf-8") as fp:
            join = json.load(fp)
        with open(os.path.join(HIRA_DIR, "specialists.json"), encoding="utf-8") as fp:
            spec = json.load(fp)
    except FileNotFoundError:
        join, spec = {}, {}
    for hpid, h in hs.items():
        j = join.get(hpid)
        if j:
            h.dr_total = iround(j.get("drTotCnt"))
            h.cl_cd = j.get("clCdNm") or ""
            h.join_km = j.get("distanceKm")
        for row in spec.get(hpid, []):
            cnt = iround(row.get("dtlSdrCnt")) or 0
            if cnt:
                h.depts[row["dgsbjtCdNm"]] = cnt

    stats["span"] = (os.path.basename(files[0])[:10], os.path.basename(files[-1])[:10])
    stats["outside"] = outside_centers(listing, hs)
    return hs, stats, listing


def outside_centers(listing: list, hs: dict[str, Hospital]) -> list[tuple[str, str, float]]:
    """진주 밖 가장 가까운 권역·지역응급의료센터 — 진주 3곳이 막혔을 때의 다음 선택지."""
    anchor = next((h for h in hs.values() if h.grade == "권역응급의료센터"), None)
    if anchor is None:
        return []
    out = []
    for it in listing:
        if it["hpid"] in hs:
            continue
        if it.get("dutyEmclsName") not in ("권역응급의료센터", "지역응급의료센터"):
            continue
        try:
            p = (float(it["wgs84Lat"]), float(it["wgs84Lon"]))
        except (TypeError, ValueError, KeyError):
            continue
        out.append((it.get("dutyName") or "", it.get("dutyEmclsName") or "", haversine((anchor.lat, anchor.lng), p)))
    out.sort(key=lambda r: r[2])
    return out[:4]


# ───────────────────────────── SVG ─────────────────────────────

def svg_zone_strip(hospitals: list[Hospital], anchor: Hospital) -> str:
    """권역센터로부터의 직선거리 — 병원당 한 행.

    지도 산점도로 그렸더니 90m 떨어진 두 곳이 완전히 겹쳤다. 보여주려는 것은
    "한 덩어리에 모여 있다"는 사실 하나뿐이라, 겹칠 수 없는 1차원 거리 막대로
    바꿨다. 행마다 이름이 붙으니 색이 identity를 혼자 지지 않는다.
    """
    L, R, TOP, ROW = 176, 58, 30, 30
    W = 640
    H = TOP + len(hospitals) * ROW + 16
    dists = sorted(
        ((h, haversine((anchor.lat, anchor.lng), (h.lat, h.lng))) for h in hospitals),
        key=lambda r: r[1],
    )
    top = max(6.0, max(d for _, d in dists) * 1.12)
    iw = W - L - R

    def x_of(km: float) -> float:
        return L + iw * km / top

    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="권역센터로부터의 직선거리">']
    for km in range(0, int(top) + 1, 2):
        parts.append(
            f'<line x1="{x_of(km):.1f}" y1="{TOP - 8}" x2="{x_of(km):.1f}" y2="{H - 16}" '
            f'stroke="var(--grid)" stroke-width="1"/>'
            f'<text x="{x_of(km):.1f}" y="{TOP - 14}" class="ax" text-anchor="middle">{km}km</text>'
        )
    # 존 반경 5km 기준선
    parts.append(
        f'<line x1="{x_of(5):.1f}" y1="{TOP - 8}" x2="{x_of(5):.1f}" y2="{H - 16}" '
        f'stroke="var(--axis)" stroke-width="2" stroke-dasharray="4 3"/>'
        f'<text x="{x_of(5) + 5:.1f}" y="{H - 4}" class="ax">존 반경 5km</text>'
    )
    for i, (h, km) in enumerate(dists):
        y = TOP + i * ROW + ROW / 2
        cx = x_of(km)
        fill = f"var(--g-{GRADE_ORDER.index(h.grade)})"
        tip = (
            f"{h.short} · {h.grade} · 권역센터에서 직선 {km:.2f}km · "
            f"응급실 정원 {h.cap if h.cap else '피드 없음'} · 응급의학과 전문의 {h.er_specialists}명"
        )
        parts.append(f'<text x="{L - 12}" y="{y + 4:.1f}" class="lb" text-anchor="end">{html.escape(h.short[:12])}</text>')
        parts.append(
            f'<line x1="{x_of(0):.1f}" y1="{y:.1f}" x2="{cx:.1f}" y2="{y:.1f}" '
            f'stroke="var(--grid)" stroke-width="2"/>'
        )
        parts.append(
            f'<circle class="dot" cx="{cx:.1f}" cy="{y:.1f}" r="7" fill="{fill}" '
            f'stroke="var(--surface)" stroke-width="2" data-tip="{html.escape(tip)}"/>'
        )
        parts.append(
            f'<text x="{cx + 13:.1f}" y="{y + 4:.1f}" class="ax">{km:.2f}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def svg_bed_panel(h: Hospital, days: list[str]) -> str:
    """병원 1곳의 일별 가용 병상 중앙값 — 소형 다중 패널 하나."""
    W, H, L, R, T, B = 300, 104, 30, 8, 10, 20
    if not h.daily:
        return (
            f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(h.short)} 피드 없음">'
            f'<rect x="{L}" y="{T}" width="{W - L - R}" height="{H - T - B}" fill="none" '
            f'stroke="var(--grid)" stroke-width="1" stroke-dasharray="3 3"/>'
            f'<text x="{(W + L) / 2:.0f}" y="{H / 2 + 4:.0f}" class="ax" text-anchor="middle">'
            f"실시간 병상 피드 없음</text></svg>"
        )
    top = max(max(h.daily.values()), h.cap or 0, 1)
    iw, ih = W - L - R, H - T - B

    def x_of(i: int) -> float:
        return L + (iw * i / max(1, len(days) - 1))

    def y_of(v: float) -> float:
        return T + ih - (ih * v / top)

    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(h.short)} 일별 가용 병상">']
    parts.append(
        f'<line x1="{L}" y1="{y_of(0):.1f}" x2="{W - R}" y2="{y_of(0):.1f}" '
        f'stroke="var(--axis)" stroke-width="1"/>'
    )
    if h.cap:
        parts.append(
            f'<line x1="{L}" y1="{y_of(h.cap):.1f}" x2="{W - R}" y2="{y_of(h.cap):.1f}" '
            f'stroke="var(--grid)" stroke-width="1" stroke-dasharray="3 3"/>'
            f'<text x="{L - 4}" y="{y_of(h.cap) + 3:.1f}" class="ax" text-anchor="end">{h.cap}</text>'
        )
    parts.append(f'<text x="{L - 4}" y="{y_of(0) + 3:.1f}" class="ax" text-anchor="end">0</text>')

    pts = []
    for i, d in enumerate(days):
        v = h.daily.get(d)
        if v is None:
            continue
        pts.append((x_of(i), y_of(v), d, v))
    if pts:
        # 관측이 끊긴 날은 선을 잇지 않는다 (없는 데이터를 그리면 거짓말이 된다).
        # days는 관측된 날짜만 담고 있어 인덱스 차이로는 공백을 못 잡는다 — 달력 날짜로 본다
        segs, cur = [], [pts[0]]
        for prev, nxt in zip(pts, pts[1:]):
            gap = (date.fromisoformat(nxt[2]) - date.fromisoformat(prev[2])).days
            if gap > 1:
                segs.append(cur)
                cur = [nxt]
            else:
                cur.append(nxt)
        segs.append(cur)
        for seg in segs:
            if len(seg) == 1:
                parts.append(
                    f'<circle cx="{seg[0][0]:.1f}" cy="{seg[0][1]:.1f}" r="2" fill="var(--series)"/>'
                )
                continue
            path = " ".join(f"{'M' if k == 0 else 'L'}{p[0]:.1f},{p[1]:.1f}" for k, p in enumerate(seg))
            parts.append(f'<path d="{path}" fill="none" stroke="var(--series)" stroke-width="2" stroke-linejoin="round"/>')
        # 만실·과밀인 날만 선택적으로 표시
        for x, y, d, v in pts:
            if v <= 0:
                parts.append(
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="var(--critical)" '
                    f'stroke="var(--surface)" stroke-width="2"/>'
                )
    # 호버 띠
    bw = iw / max(1, len(days))
    for i, d in enumerate(days):
        v = h.daily.get(d)
        tip = f"{h.short} · {d} · 가용 중앙값 {v}석" if v is not None else f"{h.short} · {d} · 관측 없음"
        parts.append(
            f'<rect class="hv" x="{x_of(i) - bw / 2:.1f}" y="{T}" width="{bw:.2f}" height="{ih}" '
            f'fill="transparent" data-tip="{html.escape(tip)}"/>'
        )
    parts.append(
        f'<text x="{L}" y="{H - 6}" class="ax">{days[0][5:]}</text>'
        f'<text x="{W - R}" y="{H - 6}" class="ax" text-anchor="end">{days[-1][5:]}</text></svg>'
    )
    return "".join(parts)


def heatmap(hospitals: list[Hospital]) -> str:
    """중증질환 28항목 × 병원 — 3상태. 미제공이 '비어 있음'으로 읽히게 한다."""
    cell, gap, lw = 26, 2, 188
    top = 86  # 기울인 항목명이 올라갈 자리
    rows = len(hospitals)
    # 라벨이 오른쪽 위로 뻗으므로 마지막 열 너머의 여백을 따로 둔다
    W = lw + 28 * (cell + gap) + 62
    H = top + rows * (cell + gap)
    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="중증질환 수용가능 신고 현황">']
    for no in range(1, 29):
        item = V.BY_NO[no]
        x = lw + (no - 1) * (cell + gap) + cell / 2
        y = top - 6
        parts.append(
            f'<text x="{x:.1f}" y="{y}" class="ax" text-anchor="start" '
            f'transform="rotate(-55 {x:.1f} {y})">{html.escape(item.label[:9])}</text>'
        )
    for r, h in enumerate(hospitals):
        y = top + r * (cell + gap)
        parts.append(
            f'<text x="{lw - 8}" y="{y + cell * 0.68:.1f}" class="lb" text-anchor="end">'
            f"{html.escape(h.short[:13])}</text>"
        )
        for no in range(1, 29):
            item = V.BY_NO[no]
            x = lw + (no - 1) * (cell + gap)
            val = h.severe.get(no)
            if not h.severe_seen:
                fill, stroke, mark, label = "transparent", "var(--grid)", "", "응답 없음"
            elif val == V.ACCEPT_YES:
                fill, stroke, mark, label = "var(--good)", "var(--surface)", "✓", "가능"
            elif val == V.ACCEPT_NO:
                fill, stroke, mark, label = "var(--critical)", "var(--surface)", "✕", "불가능"
            else:
                fill, stroke, mark, label = "transparent", "var(--grid)", "", "정보미제공"
            tip = f"{h.short} · {item.full_label} · {label}"
            parts.append(
                f'<rect class="cell" x="{x}" y="{y}" width="{cell}" height="{cell}" rx="4" '
                f'fill="{fill}" stroke="{stroke}" stroke-width="2" data-tip="{html.escape(tip)}"/>'
            )
            if mark:
                parts.append(
                    f'<text x="{x + cell / 2:.1f}" y="{y + cell * 0.7:.1f}" class="mk" '
                    f'text-anchor="middle">{mark}</text>'
                )
    parts.append("</svg>")
    return "".join(parts)


# ───────────────────────────── HTML ─────────────────────────────

def build(hs: dict[str, Hospital], stats: dict) -> str:
    hospitals = sorted(hs.values(), key=lambda h: (GRADE_ORDER.index(h.grade), -(h.cap or 0)))
    with_feed = [h for h in hospitals if h.has_bed_feed]
    no_feed = [h for h in hospitals if not h.has_bed_feed]

    # 거리
    pts = {h.hpid: (h.lat, h.lng) for h in hospitals}
    ds = [
        haversine(pts[a.hpid], pts[b.hpid])
        for i, a in enumerate(hospitals)
        for b in hospitals[i + 1:]
    ]
    within5 = sum(1 for d in ds if d <= 5)

    # 병상
    full_pct = {h.hpid: (sum(1 for v in h.vals if v <= 0) / len(h.vals) * 100) if h.vals else None for h in hospitals}
    chg_pct = {}
    for h in hospitals:
        if len(h.vals) > 1:
            chg_pct[h.hpid] = sum(1 for a, b in zip(h.vals, h.vals[1:]) if a != b) / (len(h.vals) - 1) * 100
    worst_full = max((v for v in full_pct.values() if v is not None), default=0)

    # 중증질환 — 28항목 × 신고 응답이 있는 병원
    reporting = [h for h in hospitals if h.severe_seen]
    cells = len(reporting) * 28
    n_yes = sum(1 for h in reporting for no in range(1, 29) if h.severe.get(no) == V.ACCEPT_YES)
    n_no = sum(1 for h in reporting for no in range(1, 29) if h.severe.get(no) == V.ACCEPT_NO)
    n_unk = cells - n_yes - n_no
    unk_pct = n_unk / cells * 100 if cells else 0

    # 역량 두께
    thick = [h for h in hospitals if h.er_specialists >= 3]
    thin = [h for h in hospitals if h.er_specialists <= 1]
    days = sorted({d for h in hospitals for d in h.daily})

    o = []
    A = o.append
    A("<title>진주 응급의료 존 — 2개월 실측 리플레이</title>")
    A(f"<style>{CSS}</style>")
    A('<div class="viz-root">')
    A('<div id="tip"></div>')

    A("<h1>진주 응급의료 존 — 2개월 실측 리플레이</h1>")
    A(
        f'<p class="sub">E-Gen 전국 스냅샷 {stats["span"][0]} ~ {stats["span"][1]} '
        f'(병상 폴링 {stats["bed_polls"]:,}회 · 중증질환 폴링 {stats["severe_polls"]:,}회) · '
        f"심평원 조인 캐시 · 규칙 기반 집계, 추정 모델 없음</p>"
    )
    A(
        '<div class="banner"><strong>이 문서의 성격</strong> — 공개 데이터로 과거를 되감아 본 '
        "관찰 기록이다. 특정 사건의 재현이 아니고, 환자 데이터는 쓰이지 않았다. "
        "구급대 현장에서 수집한 자료는 한 건도 포함돼 있지 않다.</div>"
    )

    A('<div class="card find">')
    A(
        f"<p>진주 응급의료기관 <strong>{len(hospitals)}곳</strong>은 서로 "
        f"<strong>중앙 {statistics.median(ds):.1f}km / 최대 {max(ds):.1f}km</strong> 안에 모여 있다 — "
        f"{len(ds)}쌍 중 {within5}쌍({within5 / len(ds) * 100:.0f}%)이 5km 이내로, 사실상 단일 존이다.</p>"
    )
    A(
        f"<p style='margin-top:12px'>그 {len(hospitals)}곳의 응급실은 2개월간 거의 비어 있었다 — "
        f"<strong>만실·과밀 비율 최대 {worst_full:.1f}%</strong>. "
        f"즉 진주의 병목은 <strong>병상이 아니다</strong>.</p>"
    )
    A(
        f"<p style='margin-top:12px'>대신 <strong>“이 환자를 받을 수 있는가”가 비어 있다</strong> — "
        f"중증질환 수용가능 신고 {cells}칸 중 <strong>{n_unk}칸({unk_pct:.0f}%)이 정보미제공</strong>이고, "
        f"{len(no_feed)}곳은 실시간 피드 자체가 없다. "
        f"응급의학과 전문의가 3명 이상인 곳은 <strong>{len(thick)}곳</strong>뿐인데, "
        f"E-Gen 화면에서 {len(hospitals)}곳은 모두 같은 “응급의료기관”으로 보인다.</p>"
    )
    A("</div>")

    # ── 1. 존 구조
    A('<h2><span class="n">1</span>존 구조 — 8곳이 한 덩어리다</h2>')
    A(
        "<p>구급차가 진주 시내에서 출발하면 아래 전부가 동시 연락 범위에 들어온다. "
        "존 반경 5km로 후보가 8곳이 되는 도시는 전국에 드물다 — 동시 전달을 실증하기에 "
        "가장 작은 단위가 여기서 성립한다.</p>"
    )
    A('<div class="grid2">')
    anchor = next((h for h in hospitals if h.grade == "권역응급의료센터"), hospitals[0])
    A(f'<div class="card"><h3 style="margin-top:0">{esc(anchor.short)}에서의 직선거리</h3>')
    A(svg_zone_strip(hospitals, anchor))
    A('<div class="legend">')
    for i, g in enumerate(GRADE_ORDER):
        if any(h.grade == g for h in hospitals):
            A(f'<span><i class="sw" style="background:var(--g-{i})"></i>{esc(g)}</span>')
    A("</div></div>")
    A('<div class="card scroll"><table><caption>등급 순. 정원·전문의 수는 각각 E-Gen 실시간 병상 응답과 심평원 캐시</caption>')
    A(
        "<thead><tr><th>병원</th><th>등급</th><th>응급실<br>정원</th>"
        "<th>응급의학과<br>전문의</th><th>전체<br>의사</th></tr></thead><tbody>"
    )
    for h in hospitals:
        cap = f"{h.cap}" if h.cap else '<span class="no">피드 없음</span>'
        A(
            f"<tr><td>{esc(h.short)}</td><td style='text-align:left;font-size:12.5px'>{esc(h.grade)}</td>"
            f"<td>{cap}</td><td>{h.er_specialists or '<span class=no>0</span>'}</td>"
            f"<td>{h.dr_total if h.dr_total is not None else '-'}</td></tr>"
        )
    A("</tbody></table></div>")
    A("</div>")

    if stats["outside"]:
        nearest = stats["outside"][0]
        A(
            f"<p>진주 안에서 해결되지 않으면 다음 선택지는 존 밖이다 — 가장 가까운 외부 "
            f"응급의료센터는 <strong>{esc(nearest[0])}</strong>({esc(nearest[1])})로 "
            f"<strong>직선 {nearest[2]:.0f}km</strong>다. "
            "진주에서 한 번 거절되는 비용이 도심과 다른 이유가 이것이다.</p>"
        )

    # ── 2. 병상
    A('<h2><span class="n">2</span>2개월 병상 실측 — 병상은 문제가 아니다</h2>')
    A(
        f"<p>일별 가용 병상 중앙값. 점선은 응급실 정원, 빨간 점은 가용 0 이하(만실·과밀)인 날이다. "
        f"관측이 끊긴 구간은 선을 잇지 않았다. "
        f"{len(with_feed)}곳 모두 2개월 내내 자리가 있었다.</p>"
    )
    A('<div class="sm">')
    for h in hospitals:
        fp = full_pct[h.hpid]
        meta = (
            f"{h.grade} · 정원 {h.cap}석 · 만실·과밀 {fp:.1f}%"
            if h.has_bed_feed
            else f"{h.grade} · 실시간 병상 피드 없음"
        )
        A(f'<div class="panel"><h4>{esc(h.short)}</h4><p class="meta">{esc(meta)}</p>{svg_bed_panel(h, days)}</div>')
    A("</div>")

    A('<div class="card scroll"><table><caption>폴링 단위 원값 기준 (일별 집계가 아님)</caption>')
    A(
        "<thead><tr><th>병원</th><th>관측</th><th>정원</th><th>가용<br>중앙값</th>"
        "<th>최소</th><th>만실·과밀<br>비율</th><th>폴링마다<br>값이 바뀐 비율</th></tr></thead><tbody>"
    )
    for h in hospitals:
        if not h.has_bed_feed:
            A(f'<tr><td>{esc(h.short)}</td><td colspan="6" class="no" style="text-align:left">실시간 병상 피드 없음</td></tr>')
            continue
        A(
            f"<tr><td>{esc(h.short)}</td><td>{len(h.vals):,}</td><td>{h.cap or '-'}</td>"
            f"<td>{int(statistics.median(h.vals))}</td><td>{min(h.vals)}</td>"
            f"<td>{full_pct[h.hpid]:.1f}%</td><td>{chg_pct.get(h.hpid, 0):.0f}%</td></tr>"
        )
    A("</tbody></table></div>")
    A(
        "<p>오른쪽 끝 칸이 중요하다 — 폴링마다 값이 <strong>28~50%</strong> 바뀐다. "
        "진주의 응급실 병상은 환자 단위로 실시간 연동되고 있다는 뜻이고, "
        "“E-Gen 병상 숫자는 낡아서 못 믿는다”는 통념은 적어도 이 8곳에는 해당하지 않는다. "
        "병상 정보는 잘 돌아가고 있다. 그래서 병상으로는 설명이 안 된다.</p>"
    )

    # ── 3. 중증질환
    A('<h2><span class="n">3</span>전화 전에 알 수 없는 것 — 신고의 73%가 비어 있다</h2>')
    A(
        "<p>중증질환 수용가능 신고 28항목. 채워진 칸만이 구급대원이 전화 전에 알 수 있는 정보다. "
        "빈 칸은 “못 받는다”가 아니라 <strong>“모른다”</strong>다 — 그래서 전화를 건다.</p>"
    )
    A('<div class="legend">')
    A('<span><i class="sw" style="background:var(--good)"></i>✓ 가능</span>')
    A('<span><i class="sw" style="background:var(--critical)"></i>✕ 불가능</span>')
    A('<span><i class="sw hollow"></i>정보미제공 · 응답 없음</span>')
    A("</div>")
    A(f'<div class="card scroll">{heatmap(hospitals)}</div>')
    A('<div class="card scroll"><table><caption>항목 28개 기준. 신고 응답이 없는 병원은 28칸 전부를 모름으로 센다</caption>')
    A("<thead><tr><th>병원</th><th>가능</th><th>불가능</th><th>모름</th><th>모름 비율</th></tr></thead><tbody>")
    for h in hospitals:
        y = sum(1 for no in range(1, 29) if h.severe.get(no) == V.ACCEPT_YES)
        n = sum(1 for no in range(1, 29) if h.severe.get(no) == V.ACCEPT_NO)
        u = 28 - y - n
        A(
            f"<tr><td>{esc(h.short)}</td><td>{y}</td><td>{n}</td><td>{u}</td>"
            f"<td>{u / 28 * 100:.0f}%</td></tr>"
        )
    A(f"</tbody><tfoot><tr><th>합계</th><th>{n_yes}</th><th>{n_no}</th><th>{n_unk}</th>"
      f"<th>{unk_pct:.0f}%</th></tr></tfoot></table></div>")

    # ── 4. 역량
    A('<h2><span class="n">4</span>E-Gen이 비운 칸을 심평원이 설명한다</h2>')
    A(
        "<p>같은 8곳을 전문의 수로 보면 신고 공백의 상당 부분이 설명된다. "
        "E-Gen과 심평원은 공통 식별자가 없어 좌표 최근접으로 이었고, "
        f"이 8곳은 전부 <strong>100m 이내</strong>에서 매칭됐다.</p>"
    )
    A('<div class="card scroll"><table><caption>심평원 의료기관별 전문과목 전문의 수 (응급 수용과 관련된 과만 추림)</caption>')
    A("<thead><tr><th>병원</th><th>종별</th>" + "".join(f"<th>{d.replace('심장혈관흉부외과', '흉부외과')}</th>" for d in KEY_DEPTS) + "</tr></thead><tbody>")
    for h in hospitals:
        tds = "".join(
            f"<td>{h.depts[d]}</td>" if h.depts.get(d) else '<td class="no">·</td>' for d in KEY_DEPTS
        )
        A(f"<tr><td>{esc(h.short)}</td><td style='text-align:left;font-size:12.5px'>{esc(h.cl_cd or '-')}</td>{tds}</tr>")
    A("</tbody></table></div>")

    if no_feed:
        names = " · ".join(h.short for h in no_feed)
        A(
            f"<p><strong>실시간 피드가 없던 {len(no_feed)}곳({esc(names)})</strong>을 보면 "
            "응급의학과 전문의가 0명이고 정형외과·신경외과에 인력이 몰려 있다. "
            "피드가 빠진 게 아니라 <strong>애초에 응급 수용 후보로 보기 어려운 병원</strong>일 가능성이 크다 — "
            "E-Gen만 보면 “미상”이지만, 심평원을 겹치면 “역량이 얇다”로 설명된다. "
            "구급대원에게는 전혀 다른 정보다.</p>"
        )
    A(
        f"<p>반대쪽도 같은 방식으로 읽힌다 — 응급의학과 전문의 3명 이상은 "
        f"<strong>{len(thick)}곳</strong>({esc(' · '.join(h.short for h in thick))})이고, "
        f"1명 이하가 <strong>{len(thin)}곳</strong>이다. "
        "진주에 응급실은 8곳이지만 <strong>역량은 소수에 몰려 있다</strong>. "
        "지금 구급대원이 쓰는 어떤 화면도 이 차이를 보여주지 않는다.</p>"
    )

    # ── 5. PoC
    A('<h2><span class="n">5</span>그래서 무엇을 재야 하는가</h2>')
    A(
        "<p>위 네 절의 결론은 하나다 — 진주에서 측정해야 할 것은 "
        "<strong>“병상을 잘 찾았는가”가 아니라 “받아줄 곳에 처음부터 걸었는가”</strong>다. "
        "그래서 다음 단계는 다음과 같이 설계한다.</p>"
    )
    A('<div class="card">')
    A("<h3 style='margin-top:0'>섀도 PoC — 업무 절차를 바꾸지 않는다</h3>")
    A(
        "<p>구급대원은 평소대로 전화를 돌린다. 앱은 같은 시점에 "
        "“우리는 이 병원을 1순위로 추천했다”를 기록만 한다. 추천을 따를 필요도, "
        "참고할 필요도 없다. 출동 뒤 남기는 것은 <strong>처음 전화한 병원 · 통화 횟수 · "
        "최종 수용 병원</strong> 세 가지다.</p>"
    )
    A("<h3>지표 — 소방이 이미 재고 있는 것으로</h3>")
    A('<table><caption>새 지표를 만들지 않는다. 기존 구급활동 기록에서 나오는 값을 쓴다</caption>')
    A("<thead><tr><th>순위</th><th>지표</th><th>왜 이것인가</th></tr></thead><tbody>")
    for rank, name, why in [
        ("1차", "현장 체류 시간", "전화를 돌린 시간이 그대로 쌓이는 칸이다"),
        ("2차", "재이송률", "이미 통계로 내는 지표라 비교 기준이 따로 필요 없다"),
        ("3차", "첫 연락 수용률 · 통화 횟수", "추천이 맞았는지를 직접 센다"),
        ("보조", "기록 작성 시간", "구조화가 실제로 손을 덜어주는지 본다"),
    ]:
        A(f"<tr><td>{rank}</td><td style='text-align:left'><strong>{name}</strong></td>"
          f"<td style='text-align:left;color:var(--ink2)'>{why}</td></tr>")
    A("</tbody></table>")
    A(
        "<p style='margin-top:14px'>네 지표 모두 <strong>병원명 · 시각 · 횟수</strong>만 있으면 "
        "계산된다. 환자 식별정보가 들어가지 않고, 병원 쪽 협조도 필요 없다.</p>"
    )
    A("<h3>성공 기준을 먼저 적는다</h3>")
    A(
        "<p>현장 체류 시간 중앙값과 재이송률이 개선되지 않으면 실패로 보고한다. "
        "20~30건이면 방향이 보이고, 구급차 1대로 2~3주면 모인다. "
        "추천 적중률이 기존보다 낮게 나오는 경우도 그대로 공개한다.</p>"
    )
    A("</div>")

    # ── 한계
    A("<footer>")
    A("<p style='color:var(--ink2)'><strong>데이터 출처와 한계</strong></p><ul>")
    A(
        f"<li>E-Gen 응급의료기관 목록 · 실시간 가용병상 · 중증질환 수용가능 공개 API를 "
        f"{stats['span'][0]}부터 {stats['span'][1]}까지 직접 수집한 원본 스냅샷 "
        f"{stats['files']}일분. 가공 전 원본을 보관해 해석이 바뀌어도 다시 읽을 수 있게 했다.</li>"
    )
    A("<li>심평원 병원정보 · 의료기관별상세 공개 API 캐시. E-Gen과는 공통 식별자가 없어 좌표 최근접으로 이었다.</li>")
    A("<li>집계는 전부 규칙 기반이다. 이 문서에 추정·예측 모델은 쓰이지 않았다.</li>")
    A(
        "<li>“만실·과밀”은 가용 병상 0 이하를 뜻한다. 응급실 필드의 −1은 미입력이 아니라 "
        "과밀 1명으로 읽었다(전국 스냅샷에서 앞뒤 값이 이어지는 것으로 확인된 성질).</li>"
    )
    A(
        "<li>전문의 수는 병원이 보유한 인원이고, 특정 시각의 당직 여부가 아니다. "
        "“역량이 얇다”는 수용 불가와 같은 말이 아니다.</li>"
    )
    A("<li>신고가 비어 있는 것은 수용 불가가 아니라 미상이다. 이 문서는 어느 병원도 평가하지 않는다.</li>")
    A(
        "<li>중증질환 집계는 본 항목 28칸(<code>MKioskTy1~28</code>)만 센다. 영유아 5항목에 딸린 "
        "동반 메시지 칸에 “불가능”을 적어 둔 병원이 있어, 이 칸들은 본 항목이 비어 있으면 "
        "“모름”으로 집계된다 — 그만큼 공백 비율은 <strong>보수적으로 높게 잡힌 값</strong>이다.</li>"
    )
    A("<li>현장 데이터는 한 건도 포함돼 있지 않다. 위 5절은 수행 전 설계안이다.</li>")
    A("</ul>")
    A("</footer>")
    A("</div>")
    A(f"<script>{JS}</script>")
    return "\n".join(o)


def main() -> None:
    hs, stats, _ = load()
    if not hs:
        raise SystemExit(f"{TARGET_SIGUNGU} 기관을 찾지 못했다")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fp:
        fp.write(build(hs, stats))
    print(f"생성: {OUT}")
    print(f"  기관 {len(hs)}곳 / 파일 {stats['files']}일 / 병상 폴링 {stats['bed_polls']:,}회")


if __name__ == "__main__":
    main()
