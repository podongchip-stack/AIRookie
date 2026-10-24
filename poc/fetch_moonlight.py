"""달빛어린이병원 전국 목록을 받아 `poc/data/`에 캐시한다.

달빛어린이병원은 **응급실이 아니라 야간·휴일 소아 외래**다. 경증 아이를 응급실로
보내지 않기 위해 만들어진 제도이고, 우리 화면이 "응급실로 가세요"만 말하면
그 제도를 정면으로 거스르게 된다(hub의 "경증은 센터를 아껴라"와 같은 원칙).

출처: 국립중앙의료원 응급의료포털 `nmc.or.kr/nmc/babyList`.
  · data.go.kr에 전국 단위 OpenAPI가 없다(울산 남구 파일데이터만 있다).
  · 이 페이지는 `?region=<시도명>`으로 지역을 나눠 서버에서 그려 주고,
    **카드 안에 좌표가 들어 있다**(`openMapModal('이름', 위도, 경도, '전화')`).
    그래서 지오코딩이 따로 필요 없다.
  · 지역마다 **페이지가 나뉜다**(`&currentPage=N`, 한 쪽 12곳). 쪽수는 페이지가
    심는 `setPaging('pagination','현재','쪽당','블록','전체')`의 전체 건수로 안다.
  · 한 번 받아 캐시해 두고 다시 치지 않는다.

⚠ 2026-10-16 수집 기준 **144곳**이다. 페이지 머리글은 "148곳"이라고 적고 있지만
지역 탭을 모두 더하면 144곳이고, **광주광역시·전라남도 탭은 0건**으로 나온다
(그 두 지역은 '전남광주통합특별시'로 통합됐는데 이 페이지에는 통합 탭이 없다).
없는 곳을 지어내지 않고 받은 그대로 둔다.

⚠ 운영시간은 병원별로 공개되지 않는다. 제도 기준(평일 밤 11~12시, 주말·공휴일
오후 6시까지, 만 18세 이하)만 알 수 있고 병원마다 다를 수 있어 화면에서
"전화로 확인"을 함께 안내한다. 임시 휴진·운영 중단도 이 목록엔 안 나온다.

실행:
    conda activate dev
    cd poc && python fetch_moonlight.py
산출물:
    poc/data/moonlight.json
"""

from __future__ import annotations

import json
import os
import re
import time
import http.client
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "moonlight.json")
BASE = "https://www.nmc.or.kr/nmc/babyList"
KST = timezone(timedelta(hours=9))

REGIONS = [
    "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시",
    "울산광역시", "세종특별자치시", "경기도", "강원특별자치도", "충청북도", "충청남도",
    "전북특별자치도", "전라남도", "경상북도", "경상남도", "제주특별자치도",
]

CARD = re.compile(r'find_card_cell_type02">(.*?)find_card_cell_bottom_type02">(.*?)</div>\s*</div>\s*</div>',
                  re.S)
NAME = re.compile(r'find_card_cell_top_type02">\s*<div>([^<]+)</div>')
TD = re.compile(r'class="td_type02[^"]*">\s*([^<]+?)\s*</div>', re.S)
MAP = re.compile(r"openMapModal\('([^']*)',\s*([-\d.]+),\s*([-\d.]+),\s*'([^']*)'")
#: setPaging('pagination', 현재쪽, 쪽당, 블록, 전체건수)
PAGING = re.compile(r"setPaging\(\s*'pagination'\s*,\s*'(\d+)'\s*,\s*'(\d+)'\s*,\s*'(\d+)'\s*,\s*'(\d+)'")


def fetch(region: str, page: int = 1, tries: int = 3) -> str:
    """한 쪽을 받는다. 공공 사이트라 간헐적으로 연결이 끊겨(IncompleteRead) 재시도한다."""
    url = f"{BASE}?region={urllib.parse.quote(region)}&currentPage={page}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (poc/moonlight)"})
    last = None
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except http.client.IncompleteRead as exc:
            # 0건인 지역에서 서버가 본문을 일찍 끊는다. 받은 만큼이 온전한 HTML이라 살려 쓴다
            if exc.partial:
                return exc.partial.decode("utf-8", errors="replace")
            last = exc
            time.sleep(1.5 * (attempt + 1))
        except Exception as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise last


def parse(html: str, region: str) -> list[dict]:
    rows = []
    for head, bottom in CARD.findall(html):
        m = MAP.search(bottom)
        n = NAME.search(head)
        if not m or not n:
            continue
        tds = [t.strip() for t in TD.findall(head)]
        rows.append({
            "n": n.group(1).strip(),
            "kind": tds[0] if tds else "",
            "t": m.group(4).strip(),
            "a": tds[2] if len(tds) > 2 else "",
            "y": round(float(m.group(2)), 5),
            "x": round(float(m.group(3)), 5),
            "sido": region,
        })
    return rows


def main() -> None:
    allrows, seen, missed = [], set(), []
    for region in REGIONS:
        page, total, got = 1, None, 0
        while True:
            try:
                html = fetch(region, page)
            except Exception as exc:
                missed.append(f"{region} {page}쪽({type(exc).__name__})")
                break
            if total is None:
                m = PAGING.search(html)
                total = int(m.group(4)) if m else 0
                per = int(m.group(2)) if m else 12
            rows = parse(html, region)
            if not rows:
                break
            new = [r for r in rows if (r["n"], r["t"]) not in seen]
            seen.update((r["n"], r["t"]) for r in new)
            allrows += new
            got += len(rows)
            if total and got >= total:
                break
            page += 1
            time.sleep(0.4)      # 공공 사이트라 느슨하게 친다
        print(f"  {region}: {got}곳" + (f" (표기 {total}곳)" if total and got != total else ""))
        time.sleep(0.4)
    if missed:
        print("  ⚠ 못 받은 쪽:", ", ".join(missed))

    if not allrows:
        raise SystemExit("한 곳도 못 받았다 — 페이지 구조가 바뀌었을 수 있다")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fp:
        json.dump({
            "fetchedAt": datetime.now(KST).isoformat(timespec="seconds"),
            "source": BASE,
            "note": "달빛어린이병원 — 야간·휴일 소아 외래. 응급실이 아니다. 운영시간은 병원별 비공개",
            "count": len(allrows),
            "items": allrows,
        }, fp, ensure_ascii=False, indent=1)
    print(f"\n저장: {OUT}  총 {len(allrows)}곳")


if __name__ == "__main__":
    main()
