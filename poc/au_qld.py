"""호주 퀸즐랜드 응급실 어댑터 — 화면이 쓰는 행 형식으로 옮긴다.

한국(E-Gen)과 **같은 스키마를 억지로 쓰지 않는다.** 두 나라가 세는 것이 다르다.

    한국: 지금 빈 병상이 몇 개인가           (hvec)
    호주: 지금 몇 명이 기다리고 중앙 대기가 몇 분인가 (Waiting / MedianWait)

대기 인원을 병상 수 칸(`av`)에 넣으면 카드가 "응급실 12/67석"이라고 거짓말을 한다.
그래서 공통 키(이름·전화·좌표·주소·공지·정원)만 같이 쓰고, 나라에만 있는 값은
그 나라 키로 따로 내보낸다. 화면은 **있는 값만 그리고 없으면 안 그린다**(한국에서
신뢰도·공지를 그렇게 다뤄 온 방식 그대로).

출처: Queensland Health "Hospital Performance", data.qld.gov.au CKAN.
      공개 API · 키 없음 · CC BY 4.0 · 갱신주기 near-realtime(실측 15분 전 값).

⚠ 비공식 미러(publicdata.au)를 쓰지 않는 이유: 같은 시각에 대기 인원이 실제와
  달랐고(1명 vs 12명), **경증 대기(MedianWaitCat45)가 40곳 전부 비어 있었다.**
  소아에 가장 쓸모 있는 값이라 원본 CKAN을 직접 친다.

실행:
    PYTHONUTF8=1 python au_qld.py          # out/data.au.json 생성
    PYTHONUTF8=1 python au_qld.py --show   # 카드에 뭐가 적히는지 눈으로 확인
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

CKAN = "https://www.data.qld.gov.au/api/3/action"
PACKAGE = "hospital-performance"
#: 브리즈번은 일광절약시간이 없다 — 연중 UTC+10.
AEST = timezone(timedelta(hours=10))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "data.au.json")

#: 피드가 주는 기관 종류. MIIC(Minor Injury and Illness Clinic)는 응급실이 아니라
#: 경증 전용이라 섞지 않는다 — 한국에서 달빛어린이병원을 따로 묶은 것과 같은 이유.
KIND = {"Hospital": "Public hospital ED", "MIIC": "Minor injury clinic"}


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "peds-finder/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def resources() -> dict[str, str]:
    """자원 id를 이름으로 찾는다 — id를 박아 두면 퍼블리셔가 갈아 끼울 때 조용히 죽는다."""
    res = _get(f"{CKAN}/package_show?id={PACKAGE}")["result"]["resources"]
    return {r["name"]: r["id"] for r in res}


def rows_of(resource_id: str, limit: int = 1000) -> list[dict]:
    q = urllib.parse.urlencode({"resource_id": resource_id, "limit": limit})
    return _get(f"{CKAN}/datastore_search?{q}")["result"]["records"]


def iv(v):
    """'12' · 12 · '' · None · '-' 를 int 또는 None으로."""
    if v in (None, "", "-"):
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _area(addr: str) -> str:
    """'RODE ROAD, CHERMSIDE, QLD 4032' → 'Chermside QLD' (카드 둘째 줄용)."""
    parts = [p.strip() for p in (addr or "").split(",") if p.strip()]
    if len(parts) < 2:
        return "QLD"
    suburb = parts[-2].title()
    state = parts[-1].split()[0] if parts[-1].split() else "QLD"
    return f"{suburb} {state}"


def yn(v) -> bool:
    """퀸즐랜드 피드의 Y/N 칸. 미러는 0/1로 바꿔 놨지만 원본은 글자다."""
    return str(v).strip().upper() in ("Y", "YES", "TRUE", "1")


def _alerts(f: dict) -> list:
    """병원이 직접 띄운 공지. 한국 `ms`와 같은 자리 — [종류, 원문, '', 시작, 끝, 등급].

    등급은 한국 규칙 그대로 0 정보 / 1 조건 / 2 제한인데, 퀸즐랜드 피드에는 등급이
    없고 원문만 온다. **우리가 해석하지 않는다**는 원칙대로 전부 0(정보)으로 두고
    문장만 보여 준다 — 분과 제한인지 전면 차단인지 우리는 판별할 수 없다.
    """
    if not yn(f.get("CustomAlertActive")):
        return []
    msg = (f.get("CustomAlertMessage") or "").strip()
    # 피드가 HTML로 준다(<p></p>). 태그만 걷어내고 문장은 그대로 둔다.
    for tag in ("<p>", "</p>", "<br>", "<br/>", "<br />"):
        msg = msg.replace(tag, " ")
    msg = " ".join(msg.split())
    return [["er", msg, "", None, None, 0]] if msg else []


def assemble(facilities: list[dict], metrics: list[dict]) -> list[dict]:
    """두 피드를 기관 코드로 붙여 화면 행으로."""
    m = {r.get("FacilityCode"): r for r in metrics}
    rows = []
    for f in facilities:
        try:
            lat, lng = float(f["FacilityLatitude"]), float(f["FacilityLongitude"])
        except (TypeError, ValueError, KeyError):
            continue
        code = f.get("FacilityCode")
        w = m.get(code, {})
        addr = (f.get("Address") or "").strip()
        waiting, spaces = iv(w.get("Waiting")), iv(f.get("NumberOfTreatmentSpaces"))
        row = {
            # ── 한국과 같은 키 (화면이 이미 읽는 것들) ──
            "n": f.get("FacilityName") or code,
            "t": (f.get("ContactPhone") or "").strip(),
            "y": round(lat, 5),
            "x": round(lng, 5),
            "g": KIND.get(f.get("FacilityType"), f.get("FacilityType") or ""),
            "a": _area(addr),
            "ad": addr,
            "cp": spaces,                      # 치료 공간 수 = 정원 자리
            "ms": _alerts(f),
            # ── 호주에만 있는 값 ──
            "wq": waiting,                     # 지금 대기 인원
            "wm": iv(w.get("MedianWaitAllCat")),    # 중앙 대기(분, 전체)
            "w45": iv(w.get("MedianWaitCat45")),    # 중앙 대기(분, ATS 4·5 = 경증)
            "ds": w.get("DataStatus"),         # 퍼블리셔가 밝힌 데이터 상태
            "dl": iv(w.get("FacilityDataDelayHours")),   # 퍼블리셔가 밝힌 지연(시간)
            "h24": 1 if (f.get("OpenHours") or "").strip() == "24 hours" else 0,
            "hrs": (f.get("OpenHours") or "").strip(),
        }
        # 혼잡도는 한국과 **다른 뜻**이다. 한국 oc는 (정원−빈병상)÷정원이고,
        # 여기선 대기 인원÷치료 공간이다. 같은 칸에 넣되 설명 문구를 나라별로 바꾼다.
        row["oc"] = None if (waiting is None or not spaces) else min(100, round(waiting / spaces * 100))
        rows.append(row)
    rows.sort(key=lambda r: r["n"])
    return rows


def as_of(metrics: list[dict]) -> str:
    """피드가 밝힌 갱신 시각(현지시각). 없으면 지금."""
    stamps = [r.get("DataUpdatedTimestamp") for r in metrics if r.get("DataUpdatedTimestamp")]
    if stamps:
        return max(stamps).replace("T", " ")[:16]
    return datetime.now(AEST).strftime("%Y-%m-%d %H:%M")


def load() -> tuple[list[dict], dict]:
    res = resources()
    fac = rows_of(res["Facilities"])
    met = rows_of(res["Current Metrics"])
    rows = assemble(fac, met)
    meta = {
        "asOf": as_of(met),
        "tz": "AEST",
        "country": "AU",
        "region": "QLD",
        "source": "Queensland Health · data.qld.gov.au (CC BY 4.0)",
    }
    return rows, meta


def main() -> None:
    rows, meta = load()
    if "--show" in sys.argv:
        print(f"기준 {meta['asOf']} {meta['tz']} · {len(rows)}곳\n")
        have = [r for r in rows if r["wm"] is not None]
        have.sort(key=lambda r: (r["w45"] if r["w45"] is not None else r["wm"]))
        for r in have[:8]:
            bits = [f"대기 {r['wq']}명"]
            if r["w45"] is not None:
                bits.append(f"경증 중앙 {r['w45']}분")
            bits.append(f"전체 중앙 {r['wm']}분")
            if r["cp"]:
                bits.append(f"치료공간 {r['cp']}")
            print(f"  {r['n'][:36]:36} {' · '.join(bits)}")
            print(f"  {'':36} {r['g']} · {r['a']} · {r['hrs']}"
                  + (f" · 공지 {len(r['ms'])}건" if r["ms"] else ""))
        miss = len(rows) - len(have)
        if miss:
            print(f"\n  대기 정보 없는 곳 {miss}곳(문 닫았거나 미보고)")
        return

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fp:
        json.dump({"asOf": meta["asOf"], "meta": meta, "rows": rows, "moon": []},
                  fp, ensure_ascii=False, separators=(",", ":"))
    print(f"생성: {OUT}")
    print(f"  퀸즐랜드 {len(rows)}곳 · 기준 {meta['asOf']} {meta['tz']}")
    print(f"  대기 정보 있는 곳 {sum(1 for r in rows if r['wm'] is not None)}곳"
          f" · 경증(ATS4-5) 있는 곳 {sum(1 for r in rows if r['w45'] is not None)}곳"
          f" · 공지 {sum(1 for r in rows if r['ms'])}곳")


if __name__ == "__main__":
    main()
