"""발표 슬라이드용 PNG 생성 — out/results.json을 읽어 1920×1080 정적 슬라이드를 만든다.

    python run.py            # 먼저 결과 생성
    python make_slides.py    # out/slide_summary.png, out/slide_hospitals.png

슬라이드는 JS 없는 순수 SVG(스크린샷 타이밍 문제 원천 차단)이고, 흰 배경 발표
덱 기준의 라이트 팔레트 고정이다. 색은 dataviz 검증을 통과한 카테고리 슬롯 1~3.
헤드리스 브라우저(Edge/Chrome)를 찾아 자동으로 PNG까지 뽑고, 없으면 명령을 안내한다.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

OUT = Path(__file__).resolve().parent / "out"

ARM_LABEL = {"nearest": "최근접 집중", "sequential": "순차 전화", "goldenlink": "골든링크"}
ARM_COLOR = {"nearest": "#2a78d6", "sequential": "#eb6834", "goldenlink": "#1baf7a"}
ARMS = ("nearest", "sequential", "goldenlink")
INK1, INK2, INK3 = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS, CRITICAL = "#e1e0d9", "#c3c2b7", "#d03b3b"

_PAGE = """<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><title>{title}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; }}
  body {{ width: 1920px; height: 1080px; background: #ffffff; overflow: hidden;
         font-family: system-ui, -apple-system, "Segoe UI", sans-serif; color: {ink1}; padding: 72px 88px; }}
  h1 {{ font-size: 44px; letter-spacing: -0.02em; }}
  .sub {{ font-size: 21px; color: {ink2}; margin-top: 10px; }}
  .note {{ font-size: 16px; color: {ink3}; margin-top: 6px; }}
</style></head><body>{body}</body></html>"""


def _tiles(arms: dict) -> str:
    cells = []
    for arm in ARMS:
        a = arms[arm]
        extra = (f'<span style="color:{CRITICAL};font-weight:700">쏠림 최대 {a["maxLoadRatio"]["mean"]}배 · 재이송 {a["transfersMean"]:.0f}건</span>'
                 if arm == "nearest" else
                 f'거절 전화 {a["rejectedCallsMean"]:.0f}통 · 쏠림 {a["maxLoadRatio"]["mean"]}배')
        cells.append(f"""
      <div style="flex:1;border:2px solid {GRID};border-radius:18px;padding:30px 34px">
        <div style="display:flex;align-items:center;gap:12px;font-size:26px;font-weight:700">
          <span style="width:18px;height:18px;border-radius:5px;background:{ARM_COLOR[arm]}"></span>{ARM_LABEL[arm]}</div>
        <div style="font-size:84px;font-weight:700;letter-spacing:-0.03em;margin-top:18px">{a["medianTransportMin"]["mean"]}<span style="font-size:30px;font-weight:400;color:{INK2}">분 · 수용까지 중앙값</span></div>
        <div style="font-size:22px;color:{INK2};margin-top:14px">p90 <b style="color:{INK1}">{a["p90TransportMin"]["mean"]}분</b> · {extra}</div>
      </div>""")
    return '<div style="display:flex;gap:28px;margin-top:40px">' + "".join(cells) + "</div>"


def _cdf_svg(arms: dict, width: int = 1744, height: int = 520) -> str:
    left, right, top, bottom = 84, 230, 24, 56
    series = {arm: arms[arm]["transportTimesSeed0"] for arm in ARMS}
    x_max = max(max(v) for v in series.values())
    x_max = -(-x_max // 10) * 10
    x = lambda v: left + (width - left - right) * v / x_max
    y = lambda q: top + (height - top - bottom) * (1 - q)
    parts = []
    for q in (0, 0.25, 0.5, 0.75, 1.0):
        parts.append(f'<line x1="{left}" y1="{y(q)}" x2="{width-right}" y2="{y(q)}" stroke="{GRID}" stroke-width="1.5"/>'
                     f'<text x="{left-14}" y="{y(q)+7}" text-anchor="end" font-size="21" fill="{INK3}">{int(q*100)}%</text>')
    step = 10 if x_max <= 60 else 20
    for v in range(0, int(x_max) + 1, step):
        parts.append(f'<text x="{x(v)}" y="{height-16}" text-anchor="middle" font-size="21" fill="{INK3}">{v}분</text>')
    parts.append(f'<line x1="{left}" y1="{y(0)}" x2="{width-right}" y2="{y(0)}" stroke="{AXIS}" stroke-width="1.5"/>')
    for arm in ARMS:
        times = series[arm]
        pts = " ".join(f"{x(t):.1f},{y((i+1)/len(times)):.1f}" for i, t in enumerate(times))
        parts.append(f'<polyline points="{x(0):.1f},{y(0):.1f} {pts}" fill="none" stroke="{ARM_COLOR[arm]}" stroke-width="4.5" stroke-linejoin="round"/>')
        last = min(times[-1], x_max)
        parts.append(f'<text x="{x(last)+12}" y="{y(1)+8}" font-size="24" font-weight="700" fill="{INK1}">{ARM_LABEL[arm]}</text>')
    return f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">{"".join(parts)}</svg>'


def _bars_svg(data: dict, width: int = 1744, height: int = 760) -> str:
    arms, hospitals = data["arms"], data["hospitals"]
    by_max: dict[str, float] = {}
    for arm in ARMS:
        for h in arms[arm]["hospitals"]:
            by_max[h["hpid"]] = max(by_max.get(h["hpid"], 0), h["arrivals"])
    top = [hpid for hpid, _ in sorted(by_max.items(), key=lambda kv: -kv[1])[:12]]
    import re
    names = {h["hpid"]: re.sub(r"^(학교법인|의료법인|사회복지법인)?[가-힣]*?(학원|재단)", "", h["name"])[:12]
             for h in hospitals}
    caps = {h["hpid"]: h["capacity"] for h in hospitals}
    x_max = max(max(by_max[h] for h in top), max(caps.values())) * 1.08
    lbl, gap = 310, 36
    col_w = (width - lbl) / 3 - gap
    row_h = (height - 60) / len(top)
    bar_h = min(row_h - 10, 34)
    parts = []
    for c, arm in enumerate(ARMS):
        ox = lbl + c * (col_w + gap)
        parts.append(f'<text x="{ox+col_w/2}" y="26" text-anchor="middle" font-size="26" font-weight="700" fill="{INK1}">{ARM_LABEL[arm]}</text>')
        rows = {h["hpid"]: h for h in arms[arm]["hospitals"]}
        for r, hpid in enumerate(top):
            h = rows.get(hpid)
            if h is None:
                continue
            yy = 52 + r * row_h
            w_arr = max(col_w * h["arrivals"] / x_max, 3 if h["arrivals"] > 0 else 0)
            w_cap = col_w * h["capacity"] / x_max
            over = h["arrivals"] > h["capacity"]
            w_ok = max(col_w * h["capacity"] / x_max - 2, 0) if over else w_arr
            parts.append(f'<rect x="{ox}" y="{yy}" width="{w_ok:.1f}" height="{bar_h}" rx="5" fill="{ARM_COLOR[arm]}"/>')
            if over:
                parts.append(f'<rect x="{ox+w_ok+3}" y="{yy}" width="{max(w_arr-w_ok-3, 2):.1f}" height="{bar_h}" rx="5" fill="{CRITICAL}"/>')
            parts.append(f'<line x1="{ox+w_cap:.1f}" y1="{yy-4}" x2="{ox+w_cap:.1f}" y2="{yy+bar_h+4}" stroke="{INK2}" stroke-width="3"/>')
    for r, hpid in enumerate(top):
        parts.append(f'<text x="{lbl-16}" y="{52 + r*row_h + bar_h/2 + 8}" text-anchor="end" font-size="22" fill="{INK2}">{names[hpid]}</text>')
    return f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">{"".join(parts)}</svg>'


def _scenario_line(s: dict) -> str:
    return (f'{s["scene"]["label"]} 반경 {s["radiusKm"]}km · E-Gen 스냅샷 {s["snapshotTs"][:16].replace("T", " ")} 실측 '
            f'(병원 {s["nHospitals"]}곳 · 가용 {s["totalBeds"]}병상) · 사상자 {s["patients"]}명 · 구급차 {s["ambulances"]}대 · 시드 {s["seeds"]}회 평균')


def _find_browser() -> list[str] | None:
    for p in (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ):
        if Path(p).exists():
            return [p]
    for name in ("msedge", "google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return [found]
    return None


def _screenshot(html: Path, png: Path) -> bool:
    browser = _find_browser()
    if browser is None:
        print(f"  헤드리스 브라우저를 못 찾음 — 수동 캡처: <브라우저> --headless --screenshot={png} --window-size=1920,1080 {html.as_uri()}")
        return False
    subprocess.run(
        browser + ["--headless", "--disable-gpu", f"--screenshot={png}", "--window-size=1920,1080",
                   "--default-background-color=FFFFFF", html.as_uri()],
        check=True, capture_output=True,
    )
    return True


def main() -> None:
    results_path = OUT / "results.json"
    if not results_path.exists():
        raise SystemExit("out/results.json이 없다 — 먼저 python run.py 실행")
    data = json.loads(results_path.read_text(encoding="utf-8"))
    scenario = _scenario_line(data["scenario"])

    summary_body = (
        "<h1>대량사고 분산 이송 — 같은 조건, 정보 전달 방식만 바꿨을 때</h1>"
        f'<p class="sub">{scenario}</p>'
        + _tiles(data["arms"])
        + f'<p class="sub" style="margin-top:34px;font-weight:700;color:{INK1}">환자가 몇 분 안에 수용되는가 (누적 %, 재이송·전화 시간 포함)</p>'
        + f'<div style="margin-top:6px">{_cdf_svg(data["arms"])}</div>'
        + '<p class="note">시뮬레이션 — 병원 위치·가용 병상은 실측(E-Gen), 시간 상수는 가정(민감도 검증: 상수를 흔들어도 순서 불변)</p>'
    )
    hospitals_body = (
        "<h1>쏠림은 어디서 생기나 — 병원별 도착 환자 vs 가용 병상</h1>"
        f'<p class="sub">{scenario}</p>'
        f'<p class="sub" style="margin-top:14px">막대 = 도착 환자 (시드 평균) · 세로선 = 가용 병상 · '
        f'<b style="color:{CRITICAL}">빨간 구간 = 병상을 넘겨 도착(재이송·과밀의 원인)</b></p>'
        + f'<div style="margin-top:26px">{_bars_svg(data)}</div>'
    )

    OUT.mkdir(exist_ok=True)
    made = []
    for stem, body, title in (
        ("slide_summary", summary_body, "대량사고 분산 이송 요약"),
        ("slide_hospitals", hospitals_body, "병원별 쏠림"),
    ):
        html_path = OUT / f"{stem}.html"
        html_path.write_text(
            _PAGE.format(title=title, body=body, ink1=INK1, ink2=INK2, ink3=INK3), encoding="utf-8"
        )
        png_path = OUT / f"{stem}.png"
        if _screenshot(html_path, png_path):
            made.append(png_path)
    for p in made:
        print(f"슬라이드 저장: {p}")


if __name__ == "__main__":
    main()
