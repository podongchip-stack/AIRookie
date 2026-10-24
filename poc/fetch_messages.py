"""E-Gen 병원 공지(응급실·중증질환 메시지)를 한 번 받아 `poc/data/`에 캐시한다.

병원이 E-Gen에 직접 걸어 두는 "지금 이런 환자는 못 받는다" 공지다. 보호자에게는
**헛전화를 가장 직접 줄여 주는 재료**라 따로 받아 둔다.

API 호출은 **전국 1회**다(파라미터를 비우면 전국이 한 번에 온다 — 추가 활용신청
불필요). 서비스키는 `info/Hospital_inform/.env`의 `EGEN_SERVICE_KEY`를 쓰고,
이 저장소에는 키를 적지 않는다.

캐시를 커밋해 두는 이유: 키가 없는 팀원 장비에서도 화면을 그대로 만들 수 있게
하기 위함이다(공개 데이터라 보관에 문제가 없다). 다만 공지는 시작·종료 시각이
있어 시간이 지나면 끝나므로, 화면은 **열람 시각 기준으로 다시 걸러서** 보여준다.

실행:
    conda activate dev
    cd poc && python fetch_messages.py
산출물:
    poc/data/acceptance_messages.json
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
INFO = os.path.join(ROOT, "info", "Hospital_inform", "info")
OUT = os.path.join(HERE, "data", "acceptance_messages.json")

sys.path.insert(0, INFO)
from egen.client import HttpEgenClient  # noqa: E402

KST = timezone(timedelta(hours=9))


def main() -> None:
    client = HttpEgenClient()
    rows = client.get_er_messages()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    payload = {
        "fetchedAt": datetime.now(KST).isoformat(timespec="seconds"),
        "operation": "getEmrrmSrsillDissMsgInqire",
        "count": len(rows),
        "items": rows,
    }
    with open(OUT, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=1)
    hospitals = {r.get("hpid") for r in rows if r.get("hpid")}
    print(f"저장: {OUT}")
    print(f"  공지 {len(rows)}건 · 병원 {len(hospitals)}곳 · 수집 {payload['fetchedAt']}")
    if rows:
        keys = sorted(rows[0].keys())
        print(f"  필드: {keys}")


if __name__ == "__main__":
    main()
