"""일반 소아병원(아동병원·소아청소년과 의원) 목록을 심평원 병원정보서비스(15001698)에서 받아 둔다.

**왜 따로 받나** — 응급의료기관 목록(E-Gen)에는 응급실이 아닌 아동병원·소아청소년과 의원이 없다.
달빛어린이병원(144곳)만 별도 구역으로 보여 주고 있어서, 그 밖의 소아 진료 기관은 화면에 아예 없었다.

**무엇을 주나 / 못 주나** — 이름·종별·주소·전화·좌표뿐이다. 실시간 병상도, 응급 수용 여부도, **운영 시간도
공개되지 않는다.** 그래서 화면에서는 응급실과 섞지 않고 "응급실이 아닌 곳 · 전화로 확인"으로 따로 둔다.

**거르는 방법(휴리스틱)** — 진료과목이 소아청소년과(코드 11)로 등록된 의원·병원 가운데 **이름에 소아·아동·
어린이·키즈·청소년이 들어간 곳**만 남긴다. 진료과목만 보면 내과·가정의학과 의원도 소아청소년과를
함께 등록해 두어 "소아 진료가 주인 곳"과 구분이 안 된다. 이름이 평범한데 소아가 주인 곳은 빠질 수 있다.

실행: `python fetch_peds_clinics.py` → `data/peds_clinics.json` (심평원 호출 몇 번 — 응답이 큰 쪽만 페이지가 넘어간다)
서비스키는 info 쪽 `.env`의 `HIRA_SERVICE_KEY`를 그대로 쓴다(이 파일은 키를 읽기만 하고 출력하지 않는다).

운영 규칙(`sim/`·`spider/`와 같다): 다른 폴더의 기존 파일을 수정하지 않는다 — info의 심평원 호출부는 가져다 쓰기만 한다.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
INFO = os.path.join(os.path.dirname(HERE), "info", "Hospital_inform", "info")
OUT = os.path.join(HERE, "data", "peds_clinics.json")
ENV_PATH = os.path.join(os.path.dirname(HERE), "info", "Hospital_inform", ".env")
KST = timezone(timedelta(hours=9))

#: 진료과목코드 11 = 소아청소년과 (병원정보서비스 요청 변수 dgsbjtCd)
DGSBJT_PEDS = "11"
#: 종별코드 21 병원(아동병원 포함) · 31 의원. 상급종합(01)·종합병원(11)은 응급의료기관 목록에서 이미 본다
CL_CODES = {"21": "병원", "31": "의원"}
PEDS_NAME = re.compile(r"소아|아동|어린이|키즈|청소년")


def to_item(r: dict, kind: str) -> dict | None:
    """심평원 원본 한 건 → 화면이 쓰는 최소 필드. 좌표가 없으면 버린다(거리를 못 잰다)."""
    try:
        x, y = float(r["XPos"]), float(r["YPos"])
    except (KeyError, TypeError, ValueError):
        return None
    name = (r.get("yadmNm") or "").strip()
    if not name or not PEDS_NAME.search(name):
        return None
    return {
        "n": name,
        "k": kind,
        "a": (r.get("addr") or "").strip(),
        "t": (r.get("telno") or "").strip(),
        "y": round(y, 5),
        "x": round(x, 5),
    }


def read_key() -> str:
    """info `.env`에서 서비스키를 읽는다 — python-dotenv 없이도 돌고, 값은 출력하지 않는다.
    HIRA_SERVICE_KEY가 없으면 EGEN_SERVICE_KEY(data.go.kr은 계정당 키가 하나라 같은 값)를 쓴다."""
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


def main() -> None:
    sys.path.insert(0, INFO)
    from hospital_score.hira import SVC_HOSP, OP_HOSP_LIST, HiraClient   # 읽기 전용으로 가져다 쓴다

    client = HiraClient(service_key=read_key())
    items: dict[str, dict] = {}
    for cl, kind in CL_CODES.items():
        # _call은 페이지를 끝까지 따라간다. dgsbjtCd는 info의 hospital_list()가 받지 않아 같은 호출부를 직접 쓴다
        rows = client._call(SVC_HOSP, OP_HOSP_LIST, {"dgsbjtCd": DGSBJT_PEDS, "clCd": cl})
        kept = 0
        for r in rows:
            it = to_item(r, kind)
            if it:
                items[f'{it["n"]}|{it["a"]}'] = it      # 같은 이름·주소는 한 곳
                kept += 1
        print(f"  {kind}({cl}): 소아청소년과 등록 {len(rows)}곳 → 이름 거름 {kept}곳")

    out = sorted(items.values(), key=lambda i: (i["k"], i["n"]))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fp:
        json.dump({"asOf": datetime.now(KST).strftime("%Y-%m-%d"), "items": out}, fp,
                  ensure_ascii=False, separators=(",", ":"))
    print(f"생성: {OUT} — {len(out)}곳 ({os.path.getsize(OUT)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
