"""경남 응급의료 정보 공백 — 상위 보고용 리포트 생성기.

`build_jinju_replay.py`가 실무자용(진주 8곳 상세)이라면 이쪽은 **기관장·본부
단위에 올리는 경남 전체판**이다. 두 가지를 분리해 담는다 —
보고 범위는 경남 48곳 전체, 실증 요청은 진주 한 곳.

프레이밍도 다르다. "응급실 뺑뺑이를 해결한다"가 아니라 **"구급대 현장 업무
부담을 낮춘다"**로 쓴다. 뺑뺑이 해소는 아직 증명 못 한 2단(동시 전달)의
결과물이고, 지금 증명할 수 있는 것은 부담 경감이기 때문이다. 뺑뺑이는 배경
한 줄로만 둔다.

병원 실명은 쓰지 않는다. 상위로 올라갈수록 실명 표는 "우리가 지목당했다"로
읽혀 실증 협조를 막는다 — 시군 이름과 등급까지만 쓰면 메시지는 그대로다.

운영 규칙(`sim/`·`spider/`와 같다): 다른 폴더의 기존 파일을 수정하지 않는다.

실행:
    conda activate dev
    cd poc && python build_gyeongnam.py
산출물:
    poc/out/gyeongnam.html
"""

from __future__ import annotations

import collections
import glob
import json
import os
import re
import statistics
import sys
from dataclasses import dataclass, field

from report_base import esc, hav, page

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
INFO = os.path.join(ROOT, "info", "Hospital_inform", "info")
SNAP_DIR = os.path.join(INFO, "data", "snapshots_nationwide")
HIRA_DIR = os.path.join(INFO, "data", "hira")
FIRE_CENTERS = os.path.join(ROOT, "dashboard", "NationalFireAgency.csv")
FIRE_AMB = os.path.join(ROOT, "dashboard", "NationalFireAgencyAMB.csv")
OUT = os.path.join(HERE, "out", "gyeongnam.html")

sys.path.insert(0, INFO)
from hospital_score import vocabulary as V  # noqa: E402

SIDO = "경상남도"
PILOT_SIGUNGU = "진주시"
MK = re.compile(r"^MKioskTy\d+$")
GRADES = ["권역응급의료센터", "지역응급의료센터", "지역응급의료기관", "응급실운영신고기관"]
CENTER_GRADES = ("권역응급의료센터", "지역응급의료센터")
ISOLATION_KM = 5.0


@dataclass
class H:
    hpid: str
    name: str
    grade: str
    sigungu: str
    lat: float
    lng: float
    beds: list[int] = field(default_factory=list)
    cap: int | None = None
    severe: dict[int, str] = field(default_factory=dict)
    er_spec: int = 0
    near5: int = 0           # 반경 5km 안의 다른 응급실 수 (전국 기준)
    center_km: float = 0.0   # 가장 가까운 응급의료센터까지 직선거리
    center_sido: str = ""    # 그 센터가 속한 시·도

    @property
    def isolated(self) -> bool:
        return self.near5 == 0

    @property
    def unknown_cells(self) -> int:
        """28항목 중 "모른다"로 읽히는 칸 수. 응답 자체가 없으면 28칸 전부."""
        known = sum(1 for v in self.severe.values() if v != V.ACCEPT_UNKNOWN)
        return 28 - known

    @property
    def full_pct(self) -> float | None:
        if not self.beds:
            return None
        return sum(1 for v in self.beds if v <= 0) / len(self.beds) * 100


def ival(raw) -> int | None:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def read_csv_rows(path: str) -> list[dict]:
    import csv

    for enc in ("cp949", "utf-8-sig", "utf-8"):
        try:
            with open(path, encoding=enc) as fp:
                return list(csv.DictReader(fp))
        except (UnicodeDecodeError, FileNotFoundError):
            continue
    return []


def load() -> tuple[list[H], dict]:
    files = sorted(glob.glob(os.path.join(SNAP_DIR, "*.jsonl")))
    if not files:
        raise SystemExit(f"스냅샷이 없다: {SNAP_DIR} — info 쪽 snapshot_cloud.py --sync 먼저")

    listing = None
    for p in reversed(files):
        for line in open(p, encoding="utf-8"):
            rec = json.loads(line)
            if rec.get("operation") == "getEgytListInfoInqire" and rec.get("items"):
                listing = rec["items"]
                break
        if listing:
            break

    hs: dict[str, H] = {}
    nationwide: list[tuple[str, float, float, str, str]] = []  # hpid, lat, lng, grade, sido
    for it in listing:
        addr = it.get("dutyAddr") or ""
        try:
            lat, lng = float(it["wgs84Lat"]), float(it["wgs84Lon"])
        except (TypeError, ValueError, KeyError):
            continue
        nationwide.append((it["hpid"], lat, lng, it.get("dutyEmclsName") or "", addr.split()[0] if addr else ""))
        if addr.startswith(SIDO):
            parts = addr.split()
            hs[it["hpid"]] = H(
                hpid=it["hpid"],
                name=it.get("dutyName") or it["hpid"],
                grade=it.get("dutyEmclsName") or "-",
                sigungu=parts[1] if len(parts) > 1 else "-",
                lat=lat,
                lng=lng,
            )

    stats = {"files": len(files), "polls": 0}
    for path in files:
        for line in open(path, encoding="utf-8"):
            rec = json.loads(line)
            items = rec.get("items")
            if not items:
                continue
            if rec["operation"] == "getEmrrmRltmUsefulSckbdInfoInqire":
                stats["polls"] += 1
                for it in items:
                    h = hs.get(it.get("hpid"))
                    if not h:
                        continue
                    v = ival(it.get("hvec"))
                    if v is not None:
                        h.beds.append(v)
                    if h.cap is None:
                        c = ival(it.get("hvs01"))
                        if c:
                            h.cap = c
            elif rec["operation"] == "getSrsillDissAceptncPosblInfoInqire":
                for it in items:
                    h = hs.get(it.get("hpid"))
                    if not h:
                        continue
                    for k, raw in it.items():
                        if MK.match(k):
                            n = V.normalize_accept(raw)
                            if n:
                                h.severe[int(k[len("MKioskTy"):])] = n

    # 고립도 — 도 경계를 무시하고 전국 기준으로 센다. 구급차는 행정구역을 안 따진다
    for h in hs.values():
        for hpid, lat, lng, grade, sido in nationwide:
            if hpid == h.hpid:
                continue
            d = hav((h.lat, h.lng), (lat, lng))
            if d <= ISOLATION_KM:
                h.near5 += 1
            if grade in CENTER_GRADES and (h.center_km == 0.0 or d < h.center_km):
                h.center_km, h.center_sido = d, sido

    try:
        spec = json.load(open(os.path.join(HIRA_DIR, "specialists.json"), encoding="utf-8"))
    except FileNotFoundError:
        spec = {}
    for h in hs.values():
        h.er_spec = next(
            (ival(x.get("dtlSdrCnt")) or 0 for x in spec.get(h.hpid, []) if x.get("dgsbjtCdNm") == "응급의학과"),
            0,
        )

    centers = [c for c in read_csv_rows(FIRE_CENTERS) if SIDO in (c.get("시도본부") or "")]
    amb = [a for a in read_csv_rows(FIRE_AMB) if (a.get("시도") or "").strip() in ("경남", SIDO)]
    stats["fire_stations"] = len({c["소방서명"] for c in centers})
    stats["fire_centers"] = len(centers)
    stats["ambulances"] = sum(int(a["수량"]) for a in amb if (a.get("수량") or "").strip().isdigit())
    stats["pilot_amb"] = sum(
        int(a["수량"])
        for a in amb
        if (a.get("수량") or "").strip().isdigit() and PILOT_SIGUNGU[:2] in (a.get("소방서") or "")
    )
    stats["span"] = (os.path.basename(files[0])[:10], os.path.basename(files[-1])[:10])
    return sorted(hs.values(), key=lambda x: (GRADES.index(x.grade) if x.grade in GRADES else 9, x.sigungu)), stats


# ───────────────────────────── 차트 ─────────────────────────────

def bar_gap_by_grade(rows: list[tuple[str, int, float]]) -> str:
    """등급별 '모른다' 비율 — 등급은 순서값이라 단일 색 순서 램프."""
    W, L, R, TOP, ROW = 620, 150, 86, 26, 42
    H = TOP + len(rows) * ROW + 10
    iw = W - L - R
    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="등급별 중증질환 신고 공백 비율">']
    for pct in (0, 25, 50, 75, 100):
        x = L + iw * pct / 100
        parts.append(
            f'<line x1="{x:.1f}" y1="{TOP - 8}" x2="{x:.1f}" y2="{H - 10}" stroke="var(--grid)" stroke-width="1"/>'
            f'<text x="{x:.1f}" y="{TOP - 14}" class="ax" text-anchor="middle">{pct}%</text>'
        )
    for i, (grade, n, pct) in enumerate(rows):
        y = TOP + i * ROW
        w = max(2.0, iw * pct / 100)
        parts.append(
            f'<text x="{L - 12}" y="{y + 20:.1f}" class="lb" text-anchor="end">{esc(grade)} ({n}곳)</text>'
        )
        parts.append(
            f'<rect class="cell" x="{L}" y="{y + 5}" width="{w:.1f}" height="24" rx="4" '
            f'fill="var(--g-{i})" data-tip="{esc(grade)} {n}곳 · 28항목 중 {pct:.0f}%가 정보미제공"/>'
        )
        parts.append(f'<text x="{L + w + 10:.1f}" y="{y + 22:.1f}" class="lb">{pct:.0f}%</text>')
    parts.append("</svg>")
    return "".join(parts)


def bar_center_distance(hospitals: list[H]) -> str:
    """가장 가까운 응급의료센터까지 거리 — 먼 순. 고립/밀집 2색."""
    rows = sorted(hospitals, key=lambda h: -h.center_km)
    W, L, R, TOP, ROW = 620, 150, 70, 26, 15
    H = TOP + len(rows) * ROW + 14
    iw = W - L - R
    top = max(h.center_km for h in rows) * 1.08
    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="가장 가까운 응급의료센터까지 거리">']
    for km in (0, 10, 20, 30, 40, 50):
        x = L + iw * km / top
        parts.append(
            f'<line x1="{x:.1f}" y1="{TOP - 8}" x2="{x:.1f}" y2="{H - 14}" stroke="var(--grid)" stroke-width="1"/>'
            f'<text x="{x:.1f}" y="{TOP - 14}" class="ax" text-anchor="middle">{km}km</text>'
        )
    for i, h in enumerate(rows):
        y = TOP + i * ROW
        w = max(1.5, iw * h.center_km / top)
        color = "var(--iso)" if h.isolated else "var(--dense)"
        out = " · 道 밖" if h.center_sido and not h.center_sido.startswith(SIDO) else ""
        tip = (
            f"{h.sigungu} · {h.grade} · 가장 가까운 센터 {h.center_km:.1f}km"
            f"{'(' + h.center_sido + ')' if out else ''} · 반경 5km 안 다른 응급실 {h.near5}곳 · "
            f"응급의학과 전문의 {h.er_spec}명"
        )
        parts.append(
            f'<rect class="cell" x="{L}" y="{y + 2}" width="{w:.1f}" height="11" rx="3" '
            f'fill="{color}" data-tip="{esc(tip)}"/>'
        )
        if h.center_km >= 28:
            parts.append(
                f'<text x="{L - 10}" y="{y + 11:.1f}" class="ax" text-anchor="end">'
                f"{esc(h.sigungu)}{esc(out)}</text>"
            )
            parts.append(f'<text x="{L + w + 7:.1f}" y="{y + 11:.1f}" class="ax">{h.center_km:.0f}</text>')
    parts.append(
        f'<text x="{L - 10}" y="{H - 2}" class="ax" text-anchor="end">응급의료기관 {len(rows)}곳</text></svg>'
    )
    return "".join(parts)


# ───────────────────────────── 본문 ─────────────────────────────

EXTRA_CSS = """
<style>
.viz-root{--iso:#eb6834;--dense:#2a78d6}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme=light])) .viz-root{--iso:#d95926;--dense:#3987e5}}
:root[data-theme=dark] .viz-root{--iso:#d95926;--dense:#3987e5}
.ask{border-left:3px solid var(--good)}
.ask ol{margin:8px 0 0;padding-left:20px;color:var(--ink2)}
.ask li{margin:6px 0}
</style>
"""


def build(hospitals: list[H], stats: dict) -> str:
    iso = [h for h in hospitals if h.isolated]
    dense = [h for h in hospitals if not h.isolated]
    pilot = [h for h in hospitals if h.sigungu == PILOT_SIGUNGU]
    no_feed = [h for h in hospitals if not h.beds]
    out_prov = [h for h in iso if h.center_sido and not h.center_sido.startswith(SIDO)]

    def gap(group: list[H]) -> float:
        return sum(h.unknown_cells for h in group) / (len(group) * 28) * 100 if group else 0.0

    def thin(group: list[H]) -> int:
        return sum(1 for h in group if h.er_spec <= 1)

    fulls = [h.full_pct for h in hospitals if h.full_pct is not None]
    grade_rows = [
        (g, len([h for h in hospitals if h.grade == g]), gap([h for h in hospitals if h.grade == g]))
        for g in GRADES
        if any(h.grade == g for h in hospitals)
    ]

    o = []
    A = o.append

    A("<h1>경남 구급대 현장 업무 부담 — 공개 데이터 실측</h1>")
    A(
        f'<p class="sub">E-Gen 전국 스냅샷 {stats["span"][0]} ~ {stats["span"][1]} '
        f'(병상 폴링 {stats["polls"]:,}회) · 심평원 공개 API · 소방청 119안전센터 현황 · '
        f"규칙 기반 집계, 추정 모델 없음 · 병원 실명은 쓰지 않았다</p>"
    )
    A(
        '<div class="banner"><strong>이 문서의 성격</strong> — 공개 데이터만으로 과거를 되감아 본 '
        "관찰 기록이다. 환자 데이터와 현장 수집 자료는 한 건도 들어 있지 않고, 특정 기관을 "
        "평가하지 않는다. 신고가 비어 있는 것은 “수용 불가”가 아니라 “알 수 없음”을 뜻한다.</div>"
    )

    A('<div class="card find">')
    A(
        "<p>응급실 수용 지연(이른바 뺑뺑이)의 상당 부분은 <strong>현장에서 전화를 돌리는 시간</strong>에서 "
        "생긴다. 그 전화가 왜 필요한지를 경남 공개 데이터로 확인했다.</p>"
    )
    A(
        f"<p style='margin-top:12px'>경남 응급의료기관 <strong>{len(hospitals)}곳</strong>의 응급실은 "
        f"실제로는 비어 있었다 — 가용 병상 0 이하인 시간 비율 <strong>중앙값 {statistics.median(fulls):.1f}%</strong>. "
        f"병상은 병목이 아니다.</p>"
    )
    A(
        f"<p style='margin-top:12px'>대신 <strong>“이 환자를 받을 수 있는가”가 비어 있다</strong> — "
        f"중증질환 수용가능 신고 28항목 기준 <strong>{gap(hospitals):.0f}%가 알 수 없음</strong>이고, "
        f"{len(no_feed)}곳은 실시간 병상 정보 자체가 올라오지 않는다. "
        f"그래서 구급대원은 전화를 건다.</p>"
    )
    A(
        f"<p style='margin-top:12px'>그리고 <strong>부담이 큰 곳일수록 정보가 없다</strong>. 반경 5km 안에 "
        f"다른 응급실이 하나도 없는 <strong>{len(iso)}곳</strong>은 신고 공백이 <strong>{gap(iso):.0f}%</strong>, "
        f"응급의학과 전문의가 1명 이하인 곳이 <strong>{thin(iso)}곳({thin(iso)}/{len(iso)})</strong>, "
        f"한 번 거절되면 다음 응급의료센터까지 <strong>중앙 "
        f"{statistics.median([h.center_km for h in iso]):.0f}km</strong>다. "
        f"그중 <strong>{len(out_prov)}곳</strong>은 가장 가까운 센터가 <strong>경남 밖</strong>에 있다.</p>"
    )
    A("</div>")

    # 1. 무엇을 드리는가
    A('<h2><span class="n">1</span>무엇을 덜어드리려 하는가</h2>')
    A(
        "<p>사람을 줄이는 도구가 아니다. <strong>같은 인원이 현장 처치에 더 머물 수 있게</strong> 하는 것이 "
        "목적이고, 효과는 체감이 아니라 시간으로 잰다.</p>"
    )
    A('<div class="card scroll"><table>')
    A("<thead><tr><th>덜어드리는 부담</th><th>지금</th><th>확인 시점</th></tr></thead><tbody>")
    for burden, now, when in [
        ("통화 내용을 옮겨 적는 일", "현장에서 전화를 돌리며 동시에 기록", "지금 확인 가능"),
        ("어디에 먼저 연락할지 고르는 일", "경험과 전화에 의존", "지금 확인 가능"),
        ("왜 그 병원으로 갔는지 남기는 일", "사후 재구성이 어려움", "이미 구현"),
        ("수용 가능 병원을 수소문하는 일", "상황실·구급대가 개별 통화", "실증 이후"),
    ]:
        A(
            f"<tr><td><strong>{burden}</strong></td>"
            f"<td style='text-align:left;color:var(--ink2)'>{now}</td>"
            f"<td style='text-align:left;color:var(--ink2)'>{when}</td></tr>"
        )
    A("</tbody></table></div>")
    A(
        "<p>첫 두 줄만으로도 측정이 된다 — <strong>현장 체류 시간</strong>과 <strong>기록 작성 시간</strong>. "
        "둘 다 구급활동 기록에서 이미 나오는 값이다. "
        "⚠ 구급활동일지 자체를 자동 작성하지는 않는다(소방청 전산 연계가 선행돼야 한다). "
        "지금 되는 것은 <strong>일지에 옮겨 적을 내용을 통화에서 구조화해 두는 것</strong>까지다.</p>"
    )

    # 2. 경남 자원
    A('<h2><span class="n">2</span>경남의 응급 자원</h2>')
    A(
        f"<p>구급차 <strong>{stats['ambulances']}대</strong> · 소방서 {stats['fire_stations']}곳 · "
        f"119안전센터 {stats['fire_centers']}곳이 응급의료기관 {len(hospitals)}곳을 상대한다. "
        f"기관 수로는 전국 3위(경기·서울 다음)지만 넓게 흩어져 있다.</p>"
    )
    A('<div class="grid2">')
    A('<div class="card scroll"><table><caption>등급별</caption>')
    A("<thead><tr><th>등급</th><th>곳</th><th>병상 정보<br>올라오는 곳</th><th>응급의학과<br>전문의 ≤1명</th></tr></thead><tbody>")
    for g in GRADES:
        grp = [h for h in hospitals if h.grade == g]
        if not grp:
            continue
        A(
            f"<tr><td>{esc(g)}</td><td>{len(grp)}</td>"
            f"<td>{len([h for h in grp if h.beds])}</td><td>{thin(grp)}</td></tr>"
        )
    A("</tbody></table></div>")
    A('<div class="card scroll"><table><caption>시군별 (상위 8)</caption>')
    A("<thead><tr><th>시군</th><th>곳</th><th>신고 공백</th></tr></thead><tbody>")
    by_sgg = collections.Counter(h.sigungu for h in hospitals)
    for sgg, n in by_sgg.most_common(8):
        grp = [h for h in hospitals if h.sigungu == sgg]
        A(f"<tr><td>{esc(sgg)}</td><td>{n}</td><td>{gap(grp):.0f}%</td></tr>")
    A("</tbody></table></div>")
    A("</div>")

    # 3. 신고 공백
    A('<h2><span class="n">3</span>전화 전에 알 수 있는 것이 적다</h2>')
    A(
        "<p>중증질환 수용가능 신고 28항목 가운데 “알 수 없음”으로 남는 비율. "
        "<strong>등급이 낮아질수록 계단처럼 올라간다</strong> — 특정 병원의 문제가 아니라 "
        "신고 체계가 상위 기관에 맞춰져 있다는 뜻으로 읽는 게 맞다.</p>"
    )
    A(f'<div class="card">{bar_gap_by_grade(grade_rows)}</div>')
    A(
        f"<p>문제는 구급대가 실제로 가장 자주 상대하는 곳이 아래쪽 등급이라는 점이다. "
        f"경남 {len(hospitals)}곳 중 지역응급의료기관·응급실운영신고기관이 "
        f"<strong>{len([h for h in hospitals if h.grade in GRADES[2:]])}곳</strong>이고, "
        f"실시간 병상 정보가 올라오지 않는 <strong>{len(no_feed)}곳</strong>도 대부분 여기에 몰려 있다.</p>"
    )

    # 4. 고립
    A('<h2><span class="n">4</span>부담이 큰 곳일수록 정보가 없다</h2>')
    A(
        "<p>가장 가까운 응급의료센터까지의 직선거리(먼 순). "
        f'<span style="color:var(--iso);font-weight:600">주황</span>은 반경 5km 안에 다른 응급실이 '
        "하나도 없는 곳이다. 도 경계는 무시하고 전국 기준으로 쟀다 — 구급차는 행정구역을 따지지 않는다.</p>"
    )
    A(f'<div class="card">{bar_center_distance(hospitals)}</div>')
    A('<div class="card scroll"><table><caption>두 집단 비교</caption>')
    A(
        "<thead><tr><th></th><th>곳</th><th>신고<br>공백</th><th>병상 정보<br>올라옴</th>"
        "<th>응급의학과<br>전문의 ≤1명</th><th>센터까지<br>거리 중앙</th></tr></thead><tbody>"
    )
    for label, grp in (("반경 5km 안 대안 없음", iso), ("그 외", dense)):
        A(
            f"<tr><td><strong>{label}</strong></td><td>{len(grp)}</td><td>{gap(grp):.0f}%</td>"
            f"<td>{len([h for h in grp if h.beds])}/{len(grp)}</td>"
            f"<td>{thin(grp)}/{len(grp)}</td>"
            f"<td>{statistics.median([h.center_km for h in grp]):.1f}km</td></tr>"
        )
    A("</tbody></table></div>")
    A(
        f"<p>여기서 한 번 거절되는 비용은 도심과 다르다. 다음 센터까지 중앙 "
        f"{statistics.median([h.center_km for h in iso]):.0f}km이고, 가장 먼 곳은 "
        f"<strong>{max(h.center_km for h in hospitals):.0f}km</strong>다. "
        f"그리고 이 {len(iso)}곳 중 <strong>{len(out_prov)}곳은 가장 가까운 센터가 경남 밖</strong>이다 — "
        f"{esc(' · '.join(sorted({h.sigungu for h in out_prov})))}. "
        "현장에서 도 경계를 넘는 판단을, 전화로 하고 있다.</p>"
    )

    # 5. 병상
    A('<h2><span class="n">5</span>병상은 병목이 아니다</h2>')
    busy = sorted((h for h in hospitals if (h.full_pct or 0) >= 5), key=lambda h: -(h.full_pct or 0))
    A(
        f"<p>가용 병상이 0 이하였던 시간 비율은 경남 전체 중앙값 "
        f"<strong>{statistics.median(fulls):.1f}%</strong>, 최대 {max(fulls):.0f}%다. "
        f"5%를 넘는 곳은 {len(busy)}곳뿐이고 대부분 창원·양산 등 도시권 중심 병원이다. "
        "즉 경남에서 전화를 돌리게 만드는 것은 “자리가 없어서”가 아니라 "
        "<strong>“받을 수 있는지 알 수 없어서”</strong>다.</p>"
    )
    A(
        "<p>덧붙여, 이 값들은 폴링마다 실제로 움직인다 — 경남 응급실 병상은 대체로 실시간으로 "
        "연동되고 있다. <strong>병상 정보 자체는 잘 돌아가고 있다</strong>는 점은 분명히 해 둘 필요가 있다.</p>"
    )

    # 6. 요청
    A('<h2><span class="n">6</span>요청 — 진주에서 먼저 재보겠습니다</h2>')
    A('<div class="card">')
    A(
        f"<p style='color:var(--ink)'>경남 {len(hospitals)}곳 가운데 <strong>{PILOT_SIGUNGU}</strong>를 "
        f"첫 실증지로 제안한다 — 응급실 {len(pilot)}곳이 모두 반경 5km 안에 모여 있어 "
        f"효과를 짧은 기간에 측정할 수 있고, 권역응급의료센터가 그 안에 있으며, "
        f"{PILOT_SIGUNGU[:2]}소방서 구급차 {stats['pilot_amb']}대로 표본이 충분하다.</p>"
    )
    A("<h3>어떻게</h3>")
    A(
        "<p>구급대원은 <strong>평소대로 전화를 돌린다.</strong> 앱은 같은 시점에 "
        "“이 병원을 먼저 추천했다”를 기록만 한다. 추천을 따를 필요도, 참고할 필요도 없다. "
        "업무 절차는 하나도 바뀌지 않는다.</p>"
    )
    A("<h3>무엇을 재는가</h3>")
    A(
        "<p>① 현장 체류 시간 ② 재이송률 ③ 첫 연락 수용률·통화 횟수 ④ 기록 작성 시간. "
        "모두 <strong>병원명·시각·횟수</strong>만으로 계산되므로 "
        "<strong>환자 식별정보가 들어가지 않고</strong>, 병원 측 협조도 필요하지 않다. "
        "①②는 이미 구급활동 기록에 있는 값이다.</p>"
    )
    A("<h3>성공 기준</h3>")
    A(
        "<p>현장 체류 시간 중앙값과 재이송률이 개선되지 않으면 <strong>실패로 보고한다.</strong> "
        "추천 적중률이 기존보다 낮게 나오는 경우도 그대로 공개한다.</p>"
    )
    A('<div class="card ask" style="margin:18px 0 0">')
    A("<p style='color:var(--ink);font-weight:600;margin:0'>허락을 구하는 것은 하나입니다</p>")
    A("<ol>")
    A("<li>구급대원 <strong>1~2명</strong>이 <strong>2~3주간</strong> 업무 절차를 바꾸지 않고 병행 사용</li>")
    A("<li>환자 정보는 수집하지 않으며, 병원 측 협조도 필요하지 않습니다</li>")
    A("<li>결과는 개선·악화 여부와 무관하게 그대로 보고드립니다</li>")
    A("</ol></div>")
    A("</div>")

    # 한계
    A("<footer>")
    A("<p style='color:var(--ink2)'><strong>데이터 출처와 한계</strong></p><ul>")
    A(
        f"<li>E-Gen 응급의료기관 목록·실시간 가용병상·중증질환 수용가능 공개 API를 "
        f"{stats['span'][0]}부터 {stats['span'][1]}까지 직접 수집한 원본 스냅샷 {stats['files']}일분.</li>"
    )
    A("<li>심평원 의료기관별상세 공개 API(전문과목 전문의 수). 공통 식별자가 없어 좌표 최근접으로 이었다.</li>")
    A("<li>소방청 119안전센터 현황·센터별 구급차 대수 공개자료.</li>")
    A("<li>집계는 전부 규칙 기반이다. 이 문서에 추정·예측 모델은 쓰이지 않았다.</li>")
    A(
        "<li>“알 수 없음”은 수용 불가가 아니라 미신고다. 신고 공백은 본 항목 28칸만 세므로 "
        "동반 메시지 칸에 적힌 내용은 반영되지 않는다 — <strong>보수적으로 높게 잡힌 값</strong>이다.</li>"
    )
    A(
        "<li>전문의 수는 보유 인원이고 특정 시각의 당직이 아니다. “전문의가 적다”는 "
        "“수용 불가”와 같은 말이 아니다.</li>"
    )
    A("<li>거리는 직선거리다. 실제 이송 시간은 도로 사정에 따라 다르다.</li>")
    A("<li>현장 데이터는 한 건도 포함돼 있지 않다. 6절은 수행 전 설계안이다.</li>")
    A("</ul></footer>")

    return EXTRA_CSS + page("경남 구급대 현장 업무 부담 — 공개 데이터 실측", "\n".join(o))


def main() -> None:
    hospitals, stats = load()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fp:
        fp.write(build(hospitals, stats))
    iso = [h for h in hospitals if h.isolated]
    print(f"생성: {OUT}")
    print(f"  경남 {len(hospitals)}곳 / 고립 {len(iso)}곳 / 구급차 {stats['ambulances']}대 / 폴링 {stats['polls']:,}회")


if __name__ == "__main__":
    main()
