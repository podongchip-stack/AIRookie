"""달빛어린이병원의 진료시간을 심평원 세부정보(getDtlInfo2.8)에서 받아 `poc/data/`에 캐시한다.

**왜 필요한가** — NMC 달빛어린이병원 목록(`fetch_moonlight.py`)은 이름·전화·주소·좌표만 주고 병원별 운영시간을
주지 않는다. 제도 기준(평일 밤 11~12시, 주말·공휴일 오후 6시까지)과 실제가 병원마다 달라서, 화면은 지금까지
"운영시간은 전화로 확인"만 말해 왔다. 심평원 의료기관별상세정보에는 병원이 등록한 요일별 진료시간이 있다.

**무엇을 주나 / 못 주나** (2026-10-20 달빛 144곳 실측)
  · 심평원과 좌표로 매칭되는 곳 135곳, 그중 진료시간이 있는 곳 약 75곳(대부분 병원급, 의원은 비어 있는 곳이 많다).
  · 병원이 스스로 등록한 값이다. 임시 휴진·변경은 반영되지 않고 갱신 시점도 알 수 없다.
  · 월~일 7일이 전부 같은 시간인 곳(13곳)은 임의로 채웠을 수 있어 `uniform: true`로 표시한다.
  · 공휴일은 시작·종료 필드가 없고 `noTrmtHoli` 자유 문장만 있다. 해석하지 않고 원문 그대로 둔다.
  · "지금 열려 있다"를 단정하는 근거로 쓰면 안 된다 — 화면은 "병원이 등록한 시간"으로만 말한다.

서비스키는 info 쪽 `.env`의 `HIRA_SERVICE_KEY`, 없으면 `EGEN_SERVICE_KEY`(data.go.kr은 계정당 키가 하나라 같은 값)를
읽기만 하고 출력하지 않는다.

운영 규칙(`sim/`·`spider/`와 같다): 다른 폴더의 기존 파일을 수정하지 않는다 — info의 심평원 호출부는 가져다 쓰기만 한다.

실행:
    cd poc && python fetch_moonlight_hours.py
산출물:
    poc/data/moonlight_hours.json   (키는 moonlight.json 항목의 "이름|전화")
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
INFO = os.path.join(ROOT, "info", "Hospital_inform", "info")
ENV_PATH = os.path.join(ROOT, "info", "Hospital_inform", ".env")
MOON = os.path.join(HERE, "data", "moonlight.json")
OUT = os.path.join(HERE, "data", "moonlight_hours.json")
KST = timezone(timedelta(hours=9))

#: 심평원 병원 좌표와 NMC 좌표가 이 거리 안이면 같은 기관으로 본다(실측 오차는 대부분 수십 m).
MATCH_KM = 0.3

DAYS = (("mon", "Mon"), ("tue", "Tue"), ("wed", "Wed"), ("thu", "Thu"), ("fri", "Fri"), ("sat", "Sat"), ("sun", "Sun"))
#: 원문 그대로 보존하는 자유 문장 칸(해석하지 않는다)
TEXT_FIELDS = ("rcvWeek", "rcvSat", "lunchWeek", "lunchSat", "noTrmtSun", "noTrmtHoli")


def read_key() -> str:
    """info `.env`에서 서비스키를 읽는다. python-dotenv에 의존하지 않고, 값은 출력하지 않는다."""
    env: dict[str, str] = {}
    try:
        with open(ENV_PATH, encoding="utf-8") as fp:
            for line in fp:
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    key = env.get("HIRA_SERVICE_KEY") or env.get("EGEN_SERVICE_KEY") or ""
    if not key:
        raise SystemExit(f"서비스키가 없다. {ENV_PATH} 에 HIRA_SERVICE_KEY 또는 EGEN_SERVICE_KEY 한 줄을 넣을 것.")
    return key


def km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(a))


def hhmm(raw: object) -> str | None:
    """심평원의 `0900`·`2400` 같은 4자리를 "09:00"·"24:00"으로. 비었거나 0이면 None(진료 안 함·미등록)."""
    s = str(raw or "").strip()
    if not s.isdigit() or int(s) == 0:
        return None
    s = s.zfill(4)
    return f"{s[:2]}:{s[2:]}"


def to_hours(detail: dict) -> dict | None:
    """세부정보 한 건 → 화면이 쓰는 최소 필드. 시간도 문장도 하나도 없으면 None."""
    week: dict[str, list[str]] = {}
    for short, long in DAYS:
        start, end = hhmm(detail.get(f"trmt{long}Start")), hhmm(detail.get(f"trmt{long}End"))
        if start and end:
            week[short] = [start, end]
    text = {k: str(detail[k]).strip() for k in TEXT_FIELDS if str(detail.get(k) or "").strip()}
    if not week and not text:
        return None
    out: dict = {}
    if week:
        out["week"] = week
        # 7일이 전부 같으면 병원이 임의로 채웠을 수 있다(실측 13곳) — 믿을 만한 요일 구분이 없다는 표시
        out["uniform"] = len(week) == 7 and len({tuple(v) for v in week.values()}) == 1
    out.update(text)
    if detail.get("emyNgtYn") in ("Y", "N"):
        out["emyNgt"] = detail["emyNgtYn"] == "Y"
    return out


def nearest(rows: list[dict], lat: float, lon: float) -> dict | None:
    best, best_d = None, MATCH_KM
    for r in rows:
        try:
            d = km(lat, lon, float(r["YPos"]), float(r["XPos"]))
        except (KeyError, TypeError, ValueError):
            continue
        if d <= best_d:
            best, best_d = r, d
    return best


def main() -> None:
    sys.path.insert(0, INFO)
    from hospital_score.hira import SVC_HOSP, OP_HOSP_LIST, HiraClient   # 읽기 전용으로 가져다 쓴다

    with open(MOON, encoding="utf-8") as fp:
        items = json.load(fp)["items"]

    client = HiraClient(service_key=read_key(), timeout=30.0)
    out: dict[str, dict] = {}
    unmatched, empty, failed = [], [], []
    for i, m in enumerate(items, 1):
        label = f'{m["n"]}|{m["t"]}'
        try:
            rows = client._call(SVC_HOSP, OP_HOSP_LIST, {"yadmNm": m["n"]})
            hit = nearest(rows, m["y"], m["x"])
            if not hit:
                unmatched.append(m["n"])
                continue
            rows = client.detail_op("detail", hit["ykiho"])
            hours = to_hours(rows[0]) if rows else None
        except Exception as exc:                      # 한 곳이 실패해도 멈추지 않는다
            failed.append(f'{m["n"]}({type(exc).__name__})')
            continue
        if not hours:
            empty.append(m["n"])
            continue
        out[label] = hours
        if i % 30 == 0:
            print(f"  {i}/{len(items)} …", flush=True)
        time.sleep(0.1)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fp:
        json.dump({
            "asOf": datetime.now(KST).strftime("%Y-%m-%d"),
            "source": "건강보험심사평가원 의료기관별상세정보서비스 getDtlInfo2.8 (병원이 등록한 값)",
            "note": "병원 자체 등록 값이라 임시 휴진·변경이 반영되지 않는다. uniform=true는 7일이 전부 같은 의심값",
            "items": out,
        }, fp, ensure_ascii=False, indent=1)

    uniform = sum(1 for h in out.values() if h.get("uniform"))
    print(f"달빛 {len(items)}곳 → 진료시간 확보 {len(out)}곳 (의심값 uniform {uniform}곳)")
    print(f"  심평원 매칭 실패 {len(unmatched)}곳 · 세부정보 비어 있음 {len(empty)}곳 · 호출 실패 {len(failed)}곳")
    if failed:
        print("  ⚠ 호출 실패:", ", ".join(failed[:10]))
    print(f"저장: {OUT}")


if __name__ == "__main__":
    main()
