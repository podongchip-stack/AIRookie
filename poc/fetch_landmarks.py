"""위치 검색용 랜드마크(지하철·기차역, 대학) 색인을 만들어 `poc/data/landmarks.json`에 캐시한다.

**왜 필요한가** — 보호자는 "강남역", "홍대", "서울대"처럼 말한다. 화면의 위치 검색은 입력한 글자를 밖으로 보내지
않으려고 외부 지오코더를 쓰지 않고(`place_search`), 병원 주소에서 뽑은 시군구·동·병원 이름만 찾는다. 그러면 역과 대학은
못 찾는다. 역·대학 좌표를 **한 번만** 공개 지도 데이터에서 받아 화면에 내장하면, 검색어는 여전히 밖으로 나가지 않는다.

**출처** — OpenStreetMap(Overpass API). ODbL 라이선스라 화면에 출처를 적는다("© OpenStreetMap contributors").
공식 통계가 아니라 지도 참여자가 입력한 값이라 빠지거나 틀린 곳이 있을 수 있다(대학은 캠퍼스 단위로 흩어져 있다).

**정제**(`build()`)
  · 역: 한글 이름만. 이름 끝에 "역"이 없으면 붙인다. 같은 이름이 1km 안에 여럿(환승·출구)이면 한 곳으로 합친다.
  · 대학: 학부·단과대·건물 이름은 거른다("공과대학", "○○관"). 같은 이름이 3km 안에 여럿이면 합친다. 흔한 줄임말은 `al`에 넣는다.
  · 시군구(`a`): 가장 가까운 병원(응급실·달빛·소아과)의 시군구를 붙인다 — 같은 이름이 여러 도시에 있어도 구분되게.

실행:
    cd poc && python fetch_landmarks.py            # Overpass를 한 번 호출한다
    LANDMARK_RAW=<저장해 둔 raw.json> python fetch_landmarks.py   # 다시 받지 않고 정제만
산출물: poc/data/landmarks.json

운영 규칙(`sim/`·`spider/`와 같다): 다른 폴더의 기존 파일을 수정하지 않는다. `out/data.json`은 읽기만 한다.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "landmarks.json")
DATA_JSON = os.path.join(HERE, "out", "data.json")
KST = timezone(timedelta(hours=9))

OVERPASS = "https://overpass-api.de/api/interpreter"
QUERY = """[out:json][timeout:180];
area["ISO3166-1"="KR"][admin_level=2]->.kr;
(
  node["railway"="station"](area.kr);
  node["railway"="halt"]["subway"="yes"](area.kr);
  nwr["amenity"="university"](area.kr);
  nwr["amenity"="college"](area.kr);
);
out center tags;"""

HANGUL = re.compile(r"[가-힣]")
#: 학부·단과대·건물 이름 — 검색 목적지로는 쓸모없고 대학 이름만 남기려고 거른다
FACULTY = re.compile(
    r"(공과|의과|인문|사회과학|자연과학|경영|예술|음악|미술|사범|법과|법학|약학|간호|치과|수의과|농과|농업생명과학|생활과학|"
    r"체육|건축|공학|의학|교육|신학|보건|디자인|자유전공|융합|글로벌|국제|정보|바이오|과학기술|IT)(대학|대학원)$")
BUILDING = re.compile(r"(관|동|홀|센터|도서관|기숙사|연구소|연구원|박물관|병원|체육관|학생회관|강의실|실습실|부속|부설)$")
#: 대학이 아니거나 대학원·부설 기관 — 평생교육원, 교회·사찰 부설 "대학", 산학협력단 등
NOT_UNIV = re.compile(r"(교회|통도사|사찰|평생|실버|전문대학원|법학|산학협력|대학원$|연구소|연구원)")
UNIV_OK = re.compile(r"(대학교|대학원대학교|대학원|대학|캠퍼스|칼리지|폴리텍)$|대학교[^\s]*\s*[가-힣]+캠퍼스$")
#: 흔한 줄임말 — 보호자가 실제로 이렇게 부른다. 경대·한대·동대·국대처럼 여러 대학이 같이 쓰는 줄임말은 뺐다. 이름 안에 이미 들어 있는 줄임말(서울대 ⊂ 서울대학교)은 따로 안 적어도 찾아진다
ALIASES = {
    "홍익대학교": ["홍대"], "연세대학교": ["연대"], "고려대학교": ["고대"], "이화여자대학교": ["이대"],
    "성균관대학교": ["성대"], "중앙대학교": ["중대"], "한국외국어대학교": ["외대"], "서울시립대학교": ["시립대"],
    "한국항공대학교": ["항공대"], "건국대학교": ["건대"], "숭실대학교": ["숭대"], "단국대학교": ["단대"],
}


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    p = math.pi / 180
    h = (math.sin((b[0] - a[0]) * p / 2) ** 2
         + math.cos(a[0] * p) * math.cos(b[0] * p) * math.sin((b[1] - a[1]) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(h))


def fetch_raw() -> dict:
    path = os.environ.get("LANDMARK_RAW")
    if path:
        with open(path, encoding="utf-8") as fp:
            return json.load(fp)
    req = urllib.request.Request(
        OVERPASS, data=urllib.parse.urlencode({"data": QUERY}).encode(),
        headers={"User-Agent": "goldenlink-peds-poc/1.0 (landmark index, one-off)"})
    with urllib.request.urlopen(req, timeout=200) as resp:
        return json.loads(resp.read())


def point(e: dict) -> tuple[float, float] | None:
    if "lat" in e and "lon" in e:
        return e["lat"], e["lon"]
    c = e.get("center")
    return (c["lat"], c["lon"]) if c else None


def cluster(items: list[dict], gap_km: float) -> list[dict]:
    """같은 이름이 gap_km 안에 여럿이면 한 곳(평균 좌표)으로 합친다. 멀리 떨어진 같은 이름은 따로 둔다."""
    groups: dict[str, list[list[dict]]] = {}
    for it in items:
        for g in groups.setdefault(it["n"], []):
            if km((g[0]["y"], g[0]["x"]), (it["y"], it["x"])) <= gap_km:
                g.append(it)
                break
        else:
            groups[it["n"]].append([it])
    out = []
    for gs in groups.values():
        for g in gs:
            out.append({**g[0], "y": sum(i["y"] for i in g) / len(g), "x": sum(i["x"] for i in g) / len(g)})
    return out


def anchors() -> list[tuple[float, float, str]]:
    """가장 가까운 병원의 시군구를 붙이려고, 이미 만들어 둔 out/data.json의 병원 좌표·주소를 읽기만 한다."""
    pts: list[tuple[float, float, str]] = []
    try:
        with open(DATA_JSON, encoding="utf-8") as fp:
            d = json.load(fp)
    except FileNotFoundError:
        return pts
    for h in d.get("rows", []):
        if h.get("a"):
            pts.append((h["y"], h["x"], h["a"]))
    for key in ("moon", "clinics"):
        for m in d.get(key, []):
            tok = (m.get("a") or "").split(" ")
            a = " ".join(tok[:2]) if len(tok) > 1 and tok[1].endswith(("시", "군", "구")) else (tok[0] if tok else "")
            if a:
                pts.append((m["y"], m["x"], a))
    return pts


def nearest_area(y: float, x: float, pts: list[tuple[float, float, str]]) -> str:
    best, bd = "", 1e9
    for py, px, a in pts:
        d = (py - y) ** 2 + ((px - x) * 0.8) ** 2          # 대략적인 거리면 된다(비교만)
        if d < bd:
            best, bd = a, d
    return best


def build(raw: dict) -> list[dict]:
    stations, univs = [], []
    for e in raw.get("elements", []):
        t, pt = e.get("tags", {}), point(e)
        name = (t.get("name:ko") or t.get("name") or "").strip()
        if not pt or not name or not HANGUL.search(name):
            continue
        if t.get("amenity") in ("university", "college"):
            if FACULTY.search(name) or BUILDING.search(name) or NOT_UNIV.search(name) or not UNIV_OK.search(name):
                continue
            univs.append({"n": name, "y": pt[0], "x": pt[1], "k": "u"})
        elif t.get("railway") in ("station", "halt"):
            name = re.sub(r"\s*\(.*?\)", "", name)
            if not name.endswith("역"):
                name += "역"
            if len(name) < 3:                          # "역" 한 글자 같은 잘못된 이름
                continue
            sub = t.get("station", "")
            stations.append({"n": name, "y": pt[0], "x": pt[1], "k": "s",
                             "s": "지하철역" if sub in ("subway", "light_rail", "monorail") or t.get("subway") == "yes" else "기차역"})
    items = cluster(stations, 1.0) + cluster(univs, 3.0)
    pts = anchors()
    for it in items:
        it["y"], it["x"] = round(it["y"], 5), round(it["x"], 5)
        if pts:
            it["a"] = nearest_area(it["y"], it["x"], pts)
        if it["k"] == "u":
            for full, al in ALIASES.items():
                if it["n"] == full or it["n"].startswith(full + " "):      # "연세대학교", "연세대학교 신촌캠퍼스"
                    it["al"] = al
                    break
        if it["k"] == "u":
            it["s"] = "대학"
    items.sort(key=lambda i: (i["k"], i["n"]))
    return items


def main() -> None:
    raw = fetch_raw()
    items = build(raw)
    if not items:
        raise SystemExit("한 곳도 못 만들었다 — Overpass 응답을 확인할 것")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fp:
        json.dump({
            "asOf": datetime.now(KST).strftime("%Y-%m-%d"),
            "source": "OpenStreetMap contributors (ODbL), Overpass API",
            "note": "역·대학 위치 색인(검색용). 지도 참여자가 입력한 값이라 빠지거나 틀린 곳이 있을 수 있다",
            "items": items,
        }, fp, ensure_ascii=False, separators=(",", ":"))
    n_s = sum(1 for i in items if i["k"] == "s")
    n_u = sum(1 for i in items if i["k"] == "u")
    print(f"역 {n_s}곳 · 대학 {n_u}곳 → {OUT} ({os.path.getsize(OUT)/1024:.0f} KB)")
    no_area = sum(1 for i in items if not i.get("a"))
    if no_area:
        print(f"  ⚠ 시군구를 못 붙인 곳 {no_area}곳 (out/data.json이 없거나 병원이 멀리 있음)")


if __name__ == "__main__":
    main()
