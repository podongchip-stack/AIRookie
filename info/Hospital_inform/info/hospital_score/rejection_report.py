"""거절 로그 확장 리포트 — 결정 시점 스냅샷·무응답 축까지 읽는 집계 CLI.

    python -m hospital_score.rejection_report                 # 전체
    python -m hospital_score.rejection_report --exclude-demo  # 실 로그만
    python -m hospital_score.rejection_report --only-demo     # 데모만

기존 `rejection.summarize()`(4축 집계·신고 오류 후보·Y 신고 거절률)에 더해,
hub가 2026-09-28~29에 페이로드에 확충한 필드들을 읽는다 — 수신구가 모르는
필드를 `extra`에 보존해 둔 덕에(관대 수신 원칙) 스키마 변경 없이 여기서
꺼내 쓰면 된다:

- **정보 무효의 독립 관측 후보**: 시스템이 병상 유효 확률을 높게(≥0.8) 봤는데
  BEDS_FULL로 거절된 건 — infosurv G2 라벨의 원형이자 "E-Gen 값이 틀렸다"의
  E-Gen 밖 증거
- **무응답 3분해**: 도달했는데 무응답(응답성 지표) / 미도달(보급 지표) /
  미결 종료 사건(요청 유효성 모호 — 통계에서 분리). 무응답은 수용성 판정에
  쓰지 않는다는 소비 지침(CLAUDE.md)의 집계 구현
- 데모 필터: `demo_rejections.py`가 심은 `demo: true` 마커로 데모/실 로그 분리
"""
from __future__ import annotations

import argparse
import html as html_escape
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import rejection as R

#: 정보 무효 관측 후보로 볼 결정 시점 authority 하한
AUTHORITY_HIGH = 0.8


def _get(record: dict, key: str):
    """최상위 또는 extra(관대 수신으로 보존된 미등록 필드)에서 값을 찾는다."""
    if key in record and record[key] is not None:
        return record[key]
    return (record.get("extra") or {}).get(key)


def _is_demo(record: dict) -> bool:
    return bool(_get(record, "demo"))


def extended_report(records: list[dict]) -> str:
    lines: list[str] = []

    # ── 정보 무효의 독립 관측 후보 ──────────────────────────────────────
    invalidated = [
        r for r in records
        if r.get("reasonCode") == "BEDS_FULL"
        and isinstance(_get(r, "bedAuthorityAtRequest"), (int, float))
        and _get(r, "bedAuthorityAtRequest") >= AUTHORITY_HIGH
    ]
    lines.append("")
    lines.append(f"  정보 무효의 독립 관측 후보 (authority ≥ {AUTHORITY_HIGH:.0%}인데 만실 거절): "
                 f"{len(invalidated)}건")
    for r in invalidated[:8]:
        beds = _get(r, "availableBedCountAtRequest")
        lines.append(
            f"      {r['hospitalId']:<12}표시 병상 {beds}석 · "
            f"authority {_get(r, 'bedAuthorityAtRequest'):.0%} → BEDS_FULL "
            f"({r.get('diseaseGroup') or '?'})"
        )
    if invalidated:
        lines.append("      → E-Gen 밖에서 얻은 '값이 틀렸다'의 관측 — infosurv G2 라벨 재료")

    # ── 무응답 3분해 ────────────────────────────────────────────────────
    no_response = [r for r in records if r.get("reasonCode") == "NO_RESPONSE"]
    if no_response:
        finalized = [r for r in no_response if _get(r, "caseFinalized") is not False]
        unresolved = [r for r in no_response if _get(r, "caseFinalized") is False]
        reached = [r for r in finalized if _get(r, "reachedAtBroadcast") is True]
        unreached = [r for r in finalized if _get(r, "reachedAtBroadcast") is False]
        unknown = len(finalized) - len(reached) - len(unreached)
        lines.append("")
        lines.append(f"  무응답(NO_RESPONSE) {len(no_response)}건 — 거절과 다른 축, 수용성 판정에서 제외:")
        lines.append(f"      도달했는데 무응답 (응답성 지표)   {len(reached):>4}건"
                     + ("  ← 반복되면 전화 확인 우선 대상" if reached else ""))
        lines.append(f"      미도달 — 대시보드 미접속 (보급 지표) {len(unreached):>4}건  ← 병원 탓 아님")
        if unknown:
            lines.append(f"      도달 여부 미기록 (구버전 로그)     {unknown:>4}건")
        lines.append(f"      미결 종료 사건 (유효성 모호, 분리)   {len(unresolved):>4}건")

    # ── 병원×질환군: '가능' 신고였는데 거절 상위 ─────────────────────────
    declared_yes = Counter(
        (r["hospitalId"], r.get("diseaseGroup") or "?")
        for r in records
        if r.get("declaredAtRequest") == "Y" and r.get("reasonCode") != "NO_RESPONSE"
    )
    if declared_yes:
        lines.append("")
        lines.append("  '가능(Y)' 신고였는데 거절 — 병원×질환군 상위:")
        for (hospital_id, group), n in declared_yes.most_common(8):
            lines.append(f"      {hospital_id:<12}{group:<14}{n}회")

    return "\n".join(lines)


# ── HTML 출력 ────────────────────────────────────────────────────────────────
# 자기완결 단일 파일(외부 자원 0)로 뽑는다 — 회의·심사 자료로 링크/파일 하나만
# 건네면 되게. 팔레트·마크 규격은 검증된 참조 dataviz 팔레트를 그대로 쓴다
# (단일 계열 blue slot-1 + 잉크/표면 역할, 라이트·다크 모두 명시).

AXIS_LABEL = {
    R.AXIS_STRUCTURAL: ("구조적", "역량 벡터를 고쳐야 함 — E-Gen 신고 오류의 증거"),
    R.AXIS_PERIODIC: ("주기적", "시간대·당직 패턴 — 상수 점수 반영 금지"),
    R.AXIS_MOMENTARY: ("순간적", "그때의 여건일 뿐 — 병원 속성 아님"),
    R.AXIS_PATIENT: ("환자 요인", "환자-병원 조합의 문제"),
    R.AXIS_UNKNOWN: ("미분류·무응답", "이유 미기재 또는 무응답(별도 축)"),
}

_HTML_CSS = """
:root { color-scheme: light;
  --surface:#fcfcfb; --plane:#f9f9f7; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --hairline:#e1e0d9; --border:rgba(11,11,11,0.10); --bar:#2a78d6;
  --warn:#fab219; --good:#006300; --critical:#d03b3b; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  color-scheme: dark;
  --surface:#1a1a19; --plane:#0d0d0d; --ink:#ffffff; --ink2:#c3c2b7; --muted:#898781;
  --hairline:#2c2c2a; --border:rgba(255,255,255,0.10); --bar:#3987e5;
  --warn:#fab219; --good:#0ca30c; --critical:#d03b3b; } }
:root[data-theme="dark"] {
  color-scheme: dark;
  --surface:#1a1a19; --plane:#0d0d0d; --ink:#ffffff; --ink2:#c3c2b7; --muted:#898781;
  --hairline:#2c2c2a; --border:rgba(255,255,255,0.10); --bar:#3987e5;
  --warn:#fab219; --good:#0ca30c; --critical:#d03b3b; }
* { box-sizing:border-box; margin:0; }
body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  background:var(--plane); color:var(--ink); padding:28px; line-height:1.5; }
main { max-width: 880px; margin: 0 auto; display:flex; flex-direction:column; gap:16px; }
h1 { font-size:1.15rem; }
h2 { font-size:0.95rem; margin-bottom:10px; }
.sub { color:var(--ink2); font-size:0.8rem; }
section, .tile { background:var(--surface); border:1px solid var(--border);
  border-radius:10px; padding:16px 18px; }
.tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:10px; }
.tile .lbl { color:var(--ink2); font-size:0.75rem; }
.tile .val { font-size:1.7rem; font-weight:650; margin-top:2px; }
.tile .note { color:var(--muted); font-size:0.72rem; margin-top:2px; }
.banner { display:flex; gap:8px; align-items:flex-start; border-left:3px solid var(--warn);
  background:var(--surface); border-radius:8px; padding:10px 14px; font-size:0.8rem; color:var(--ink2); }
.chart { display:flex; flex-direction:column; gap:6px; }
.row { display:grid; grid-template-columns: 130px 1fr 52px; gap:10px; align-items:center; }
.row .lbl { font-size:0.8rem; color:var(--ink2); text-align:right; }
.row .track { min-width:0; }
.row .fill { height:18px; background:var(--bar); border-radius:0 4px 4px 0; min-width:2px; }
.row .val { font-size:0.8rem; font-weight:600; font-variant-numeric:tabular-nums; }
.axisnote { color:var(--muted); font-size:0.72rem; margin-top:8px; }
table { width:100%; border-collapse:collapse; font-size:0.8rem; }
th { text-align:left; color:var(--muted); font-weight:500; padding:4px 8px;
  border-bottom:1px solid var(--hairline); }
td { padding:5px 8px; border-bottom:1px solid var(--hairline);
  font-variant-numeric:tabular-nums; }
td:last-child, th:last-child { text-align:right; }
.g2 { color:var(--critical); font-weight:600; }
.wrap { overflow-x:auto; }
footer { color:var(--muted); font-size:0.72rem; }
code { font-size:0.72rem; background:var(--plane); border:1px solid var(--hairline);
  border-radius:4px; padding:1px 5px; }
"""


def _esc(value) -> str:
    return html_escape.escape(str(value))


def _bar_rows(items: list[tuple[str, str, int]], total_max: int) -> str:
    rows = []
    for label, tooltip, count in items:
        width = max(round(count / total_max * 100), 2) if total_max else 2
        rows.append(
            f'<div class="row"><span class="lbl">{_esc(label)}</span>'
            f'<div class="track"><div class="fill" style="width:{width}%" '
            f'title="{_esc(tooltip)}"></div></div>'
            f'<span class="val">{count}건</span></div>'
        )
    return "\n".join(rows)


def build_html(records: list[dict], demo_count: int, filter_label: str) -> str:
    by_axis = Counter(r.get("axis", R.AXIS_UNKNOWN) for r in records)
    by_reason = Counter(r.get("reasonCode", "UNSPECIFIED") for r in records)
    no_response = [r for r in records if r.get("reasonCode") == "NO_RESPONSE"]
    rejected = [r for r in records if r.get("reasonCode") != "NO_RESPONSE"]
    declared_yes = [r for r in rejected if r.get("declaredAtRequest") == "Y"]
    invalidated = [
        r for r in records
        if r.get("reasonCode") == "BEDS_FULL"
        and isinstance(_get(r, "bedAuthorityAtRequest"), (int, float))
        and _get(r, "bedAuthorityAtRequest") >= AUTHORITY_HIGH
    ]
    dates = sorted(r.get("timestamp", "")[:10] for r in records if r.get("timestamp"))
    period = f"{dates[0]} ~ {dates[-1]}" if dates else "—"

    # 축별 분포 (단일 계열 막대 — 계열이 하나라 범례 불필요, 값은 직접 라벨)
    axis_items = [
        (AXIS_LABEL[axis][0], AXIS_LABEL[axis][1], count)
        for axis, count in by_axis.most_common()
        if axis in AXIS_LABEL
    ]
    axis_max = max((c for _, _, c in axis_items), default=0)

    # 무응답 3분해
    finalized = [r for r in no_response if _get(r, "caseFinalized") is not False]
    unresolved = [r for r in no_response if _get(r, "caseFinalized") is False]
    reached = sum(1 for r in finalized if _get(r, "reachedAtBroadcast") is True)
    unreached = sum(1 for r in finalized if _get(r, "reachedAtBroadcast") is False)
    unknown_reach = len(finalized) - reached - unreached
    nr_items = [
        ("도달 후 무응답", "응답성 지표 — 반복되면 전화 확인 우선 대상", reached),
        ("미도달(미접속)", "보급 지표 — 병원 탓 아님", unreached),
        ("미결 종료 사건", "요청 유효성 모호 — 통계에서 분리", len(unresolved)),
    ]
    if unknown_reach:
        nr_items.insert(2, ("도달 여부 미기록", "구버전 로그", unknown_reach))
    nr_max = max((c for _, _, c in nr_items), default=0)

    reason_rows = "\n".join(
        f"<tr><td>{_esc(AXIS_LABEL.get(R.REASON_AXIS.get(code, (R.AXIS_UNKNOWN,))[0], ('?',))[0])}</td>"
        f"<td>{_esc(code)}</td>"
        f"<td>{_esc(R.REASON_AXIS.get(code, ('', '미등록 코드'))[1])}</td>"
        f"<td>{count}</td></tr>"
        for code, count in by_reason.most_common()
    )

    invalid_rows = "\n".join(
        f"<tr><td>{_esc(r['hospitalId'])}</td><td>{_esc(r.get('diseaseGroup') or '?')}</td>"
        f"<td>{_esc(_get(r, 'availableBedCountAtRequest'))}석</td>"
        f"<td class=\"g2\">{_get(r, 'bedAuthorityAtRequest'):.0%}</td>"
        f"<td>{_esc((r.get('timestamp') or '')[:16].replace('T', ' '))}</td></tr>"
        for r in invalidated[:10]
    )

    structural = Counter(
        (r["hospitalId"], r.get("diseaseGroup") or "?")
        for r in records if r.get("axis") == R.AXIS_STRUCTURAL
    )
    structural_rows = "\n".join(
        f"<tr><td>{_esc(h)}</td><td>{_esc(g)}</td><td>{n}</td></tr>"
        for (h, g), n in structural.most_common(10)
    )

    yes_counter = Counter(
        (r["hospitalId"], r.get("diseaseGroup") or "?") for r in declared_yes
    )
    yes_rows = "\n".join(
        f"<tr><td>{_esc(h)}</td><td>{_esc(g)}</td><td>{n}</td></tr>"
        for (h, g), n in yes_counter.most_common(10)
    )

    yes_rate = f"{len(declared_yes) / len(rejected):.0%}" if rejected else "—"
    generated = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")

    demo_banner = (
        f'<div class="banner"><span aria-hidden="true">⚠</span><span>'
        f"<b>데모 데이터 {demo_count}건이 포함된 리포트입니다.</b> 거절 로그는 실서비스가"
        f" 돌아야 쌓이는 운영 데이터라, 이 화면은 통계 주장이 아니라 <b>배선의 시연</b>입니다"
        f" — 실 로그가 쌓이면 <code>--exclude-demo</code>로 완전히 분리됩니다.</span></div>"
        if demo_count else ""
    )

    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>거절 로그 리포트 — GoldenLink</title>
<style>{_HTML_CSS}</style></head>
<body><main>
<header>
  <h1>거절 로그 리포트 — GoldenLink 운영 관제</h1>
  <p class="sub">기간 {_esc(period)} · 생성 {generated} · 대상 {_esc(filter_label)} ·
  출처: hub → <code>POST /hub/rejection</code> (결정 시점 스냅샷 포함)</p>
</header>
{demo_banner}
<div class="tiles">
  <div class="tile"><div class="lbl">총 기록</div><div class="val">{len(records)}건</div>
    <div class="note">거절 {len(rejected)} · 무응답 {len(no_response)}</div></div>
  <div class="tile"><div class="lbl">'가능' 신고였는데 거절</div><div class="val">{yes_rate}</div>
    <div class="note">{len(declared_yes)}건 — 신고 정확도의 직접 지표</div></div>
  <div class="tile"><div class="lbl">정보 무효의 독립 관측</div><div class="val">{len(invalidated)}건</div>
    <div class="note">authority ≥ {AUTHORITY_HIGH:.0%}인데 만실 거절 — G2 라벨 재료</div></div>
  <div class="tile"><div class="lbl">신고 오류 후보 병원</div><div class="val">{len({h for (h, _g) in structural})}곳</div>
    <div class="note">구조적 거절 발생 병원</div></div>
</div>

<section>
  <h2>거절 사유의 4축 분포</h2>
  <div class="chart">{_bar_rows(axis_items, axis_max)}</div>
  <p class="axisnote">축이 다르면 갱신 대상이 다르다 — 구조적은 역량 벡터 수정, 주기적은 시간대
  패턴, 순간적은 그때의 여건, 환자 요인은 병원 속성이 아님. 하나로 뭉치면 일시적 사정으로
  병원을 영구히 후보에서 밀어내게 된다.</p>
</section>

<section>
  <h2>사유별 상세</h2>
  <div class="wrap"><table>
    <thead><tr><th>축</th><th>코드</th><th>설명</th><th>건수</th></tr></thead>
    <tbody>{reason_rows}</tbody>
  </table></div>
</section>

{f'''<section>
  <h2>정보 무효의 독립 관측 후보 <span class="sub">— 시스템이 유효하다고 봤는데 만실 거절</span></h2>
  <div class="wrap"><table>
    <thead><tr><th>병원</th><th>질환군</th><th>표시 병상</th><th>당시 authority</th><th>시각</th></tr></thead>
    <tbody>{invalid_rows}</tbody>
  </table></div>
  <p class="axisnote">E-Gen 밖에서 얻은 "값이 틀렸다"의 관측 — infosurv G2 라벨(독립 관측
  기반 재학습)의 재료가 된다.</p>
</section>''' if invalidated else ''}

{f'''<section>
  <h2>무응답(NO_RESPONSE) 분해 <span class="sub">— 거절과 다른 축, 수용성 판정에서 제외</span></h2>
  <div class="chart">{_bar_rows(nr_items, nr_max)}</div>
</section>''' if no_response else ''}

{f'''<section>
  <h2>구조적 거절 반복 병원 <span class="sub">— E-Gen 신고 오류 후보</span></h2>
  <div class="wrap"><table>
    <thead><tr><th>병원</th><th>질환군</th><th>횟수</th></tr></thead>
    <tbody>{structural_rows}</tbody>
  </table></div>
</section>''' if structural else ''}

{f'''<section>
  <h2>'가능(Y)' 신고였는데 거절 — 병원×질환군</h2>
  <div class="wrap"><table>
    <thead><tr><th>병원</th><th>질환군</th><th>횟수</th></tr></thead>
    <tbody>{yes_rows}</tbody>
  </table></div>
</section>''' if yes_counter else ''}

<footer>재현: <code>python -m hospital_score.demo_rejections</code> →
<code>python -m hospital_score.rejection_report --html</code> · 소비 지침: 무응답은
수용성 판정(G2·assessment 검증)에 쓰지 않는다 — 미도달=보급 지표, 무시=응답성 지표(전화
확인 우선 대상), 미결 종료는 분리(CLAUDE.md 거절 로그 절).</footer>
</main></body></html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--exclude-demo", action="store_true", help="데모 마커 제외 (실 로그만)")
    group.add_argument("--only-demo", action="store_true", help="데모 마커만")
    parser.add_argument("--html", nargs="?", const="", default=None, metavar="PATH",
                        help="자기완결 HTML 리포트도 생성 (기본: data/rejections/report.html)")
    args = parser.parse_args()

    records = R.load_all()
    demo_count = sum(1 for r in records if _is_demo(r))
    filter_label = "전체"
    if args.exclude_demo:
        records = [r for r in records if not _is_demo(r)]
        demo_count = 0
        filter_label = "실 로그만 (데모 제외)"
    elif args.only_demo:
        records = [r for r in records if _is_demo(r)]
        filter_label = "데모 데이터만"

    print(R.summarize(records))
    if records:
        print(extended_report(records))
    if demo_count and not args.only_demo and not args.exclude_demo:
        print(f"\n  ⚠ 데모 데이터 {demo_count}건 포함 — 실 통계는 --exclude-demo로 볼 것")

    if args.html is not None:
        out = Path(args.html) if args.html else R.LOG_DIR / "report.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            build_html(records, demo_count if not args.exclude_demo else 0, filter_label),
            encoding="utf-8",
        )
        print(f"\nHTML 리포트: {out}")


if __name__ == "__main__":
    main()
