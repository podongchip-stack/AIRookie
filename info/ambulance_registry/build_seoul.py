"""서울 119 구급차 레지스트리 만들기 — 소방청 공공데이터 두 CSV → 구급차 1대 = 1행 (2026-10-04).

입력(dashboard/에 둔 UTF-8 변환본):
  - NationalFireAgency.csv    소방청_119안전센터 현황 (시도본부·소방서·119안전센터명·주소·전화)
  - NationalFireAgencyAMB.csv 소방청_전국 소방서 및 119안전센터별 구급차 정보 (시도·소방서·안전센터·지역대·수량)

처리:
  1. 서울만, 119안전센터 이름으로 두 파일을 묶는다(소방서는 묶는 키로 쓰지 않음). 지역대 행은 보류(서울엔 없음).
  2. 센터 주소 → 좌표: 카카오 주소 검색, 실패하면 카카오 키워드 검색(센터명, 서울 안 결과만).
     둘 다 실패하면 좌표를 지어내지 않는다(상위 센터 좌표로 대신하지 않음) — result/unregistered_centers.csv로 따로 뺀다.
  3. 구급차 수량만큼 1대 = 1행으로 펼친다. apid = SEL0001부터(센터 이름순), 이름 = "<센터명> 구급 N".
     voice_port는 중앙 voice(6000) 하나를 쓰므로 모두 6000.

출력(result/):
  - seoul_ambulances.csv     Supabase ambulances 테이블에 넣을 행(기존 컬럼 + 보강 컬럼)
  - unregistered_centers.csv 좌표를 못 구해 등록하지 않은 센터와 이유
  - geocode_cache.json       카카오 검색 결과 캐시(다시 돌릴 때 재사용)

실행: python info/ambulance_registry/build_seoul.py   (카카오 키: KAKAO_REST_API_KEY 환경변수 → hub/.env 순)
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
CENTERS_CSV = ROOT / "dashboard" / "NationalFireAgency.csv"
AMB_CSV = ROOT / "dashboard" / "NationalFireAgencyAMB.csv"
RESULT = HERE / "result"
CACHE = RESULT / "geocode_cache.json"

APID_PREFIX = "SEL"
VOICE_PORT = 6000  # 중앙 voice
# 서울 대략 범위 — 검색 결과가 이 밖이면 잘못 찾은 것으로 본다
SEOUL_BOX = (37.41, 37.72, 126.76, 127.19)


def norm(name: str) -> str:
    """센터명 비교용 — 공백·'119'·'안전센터'를 지운다(예: '역삼 119 안전센터' → '역삼')."""
    return re.sub(r"\s|119|안전센터", "", name or "")


def kakao_key() -> str:
    key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    if not key:
        env = ROOT / "hub" / ".env"
        if env.is_file():
            for line in env.read_text(encoding="utf-8").splitlines():
                k, sep, v = line.partition("=")
                if sep and k.strip() == "KAKAO_REST_API_KEY":
                    key = v.strip().strip("'\"")
    if not key:
        sys.exit("❌ KAKAO_REST_API_KEY가 없습니다(환경변수 또는 hub/.env)")
    return key


def in_seoul(lat: float, lng: float) -> bool:
    return SEOUL_BOX[0] <= lat <= SEOUL_BOX[1] and SEOUL_BOX[2] <= lng <= SEOUL_BOX[3]


class Geocoder:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"KakaoAK {kakao_key()}"
        self.cache: dict = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.is_file() else {}

    def _get(self, kind: str, query: str) -> list[dict]:
        ck = f"{kind}:{query}"
        if ck not in self.cache:
            url = f"https://dapi.kakao.com/v2/local/search/{kind}.json"
            r = self.session.get(url, params={"query": query, "size": 5}, timeout=10)
            r.raise_for_status()
            self.cache[ck] = r.json().get("documents", [])
            time.sleep(0.05)
        return self.cache[ck]

    def address(self, addr: str):
        # "(개포동)" 같은 괄호 참고 동명은 빼고 찾는다
        q = re.sub(r"\s*\(.*?\)\s*", " ", addr).strip()
        for d in self._get("address", q):
            lat, lng = float(d["y"]), float(d["x"])
            if in_seoul(lat, lng):
                return lat, lng
        return None

    def keyword(self, center: str):
        target = norm(center)
        for d in self._get("keyword", f"서울 {center}"):
            lat, lng = float(d["y"]), float(d["x"])
            if in_seoul(lat, lng) and target and target in norm(d.get("place_name", "")):
                return lat, lng, d.get("road_address_name") or d.get("address_name") or ""
        return None

    def save(self) -> None:
        CACHE.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> None:
    RESULT.mkdir(parents=True, exist_ok=True)
    centers = {
        norm(r["119안전센터명"]): r
        for r in csv.DictReader(CENTERS_CSV.open(encoding="utf-8"))
        if r["시도본부"].startswith("서울")
    }
    amb_rows = [
        r for r in csv.DictReader(AMB_CSV.open(encoding="utf-8"))
        if r["시도"] == "서울" and not r["지역대"].strip()  # 지역대는 보류
    ]
    geo = Geocoder()
    registered, unregistered = [], []
    for r in sorted(amb_rows, key=lambda x: (x["안전센터"])):
        name, qty = r["안전센터"].strip(), int(r["수량"] or 0)
        info = centers.get(norm(name))
        addr, phone, lat_lng, source = (info or {}).get("주소", ""), (info or {}).get("전화번호", ""), None, ""
        if addr:
            lat_lng, source = geo.address(addr), "address"
        if lat_lng is None:
            hit = geo.keyword(name)
            if hit:
                lat_lng, source = hit[:2], "keyword"
                addr = addr or hit[2]
        if lat_lng is None:
            reason = "주소 검색·키워드 검색 모두 결과 없음" if info else "센터 현황 파일에 없음 + 키워드 검색 결과 없음"
            unregistered.append({"시도": "서울", "소방서": r["소방서"], "안전센터": name, "구급차_수량": qty, "주소": addr, "이유": reason})
            continue
        registered.append({"center": name, "fire_station": r["소방서"], "qty": qty, "addr": addr, "phone": phone,
                           "lat": lat_lng[0], "lng": lat_lng[1], "source": source})
    geo.save()

    rows, seq = [], 0
    for c in registered:
        for n in range(1, c["qty"] + 1):
            seq += 1
            rows.append({
                "apid": f"{APID_PREFIX}{seq:04d}",
                "name": f"{c['center']} 구급 {n}",
                "wgs84_lat": round(c["lat"], 6),
                "wgs84_lon": round(c["lng"], 6),
                "voice_port": VOICE_PORT,
                # ── 보강 컬럼(schema_extend.sql) — info→hub 전송에는 쓰지 않는다 ──
                "sido": "서울",
                "fire_station": c["fire_station"],
                "center": c["center"],
                "unit_no": n,
                "addr": c["addr"],
                "phone": c["phone"],
                "coord_source": c["source"],
            })
    with (RESULT / "seoul_ambulances.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with (RESULT / "unregistered_centers.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["시도", "소방서", "안전센터", "구급차_수량", "주소", "이유"])
        w.writeheader()
        w.writerows(unregistered)

    by_src = {s: sum(1 for c in registered if c["source"] == s) for s in ("address", "keyword")}
    print(f"서울 센터 {len(amb_rows)}곳 중 등록 {len(registered)}곳(주소 검색 {by_src['address']} · 키워드 검색 {by_src['keyword']}), "
          f"미등록 {len(unregistered)}곳")
    print(f"구급차 {len(rows)}대 → {RESULT / 'seoul_ambulances.csv'}")
    if unregistered:
        print(f"미등록 센터 {sum(u['구급차_수량'] for u in unregistered)}대 → {RESULT / 'unregistered_centers.csv'}")


if __name__ == "__main__":
    main()
