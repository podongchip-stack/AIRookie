"""E-Gen 목록정보에서 전국 병원 좌표를 1회 받아 캐시한다 (sim/data/egen_coords.json).

    python fetch_coords.py      # E-Gen API 전국 1회 호출 (서비스키는 info/.env의 것)

왜 필요한가 — 기존 좌표 캐시(info/.../data/output/)는 서울 55곳뿐이라, 일산(고양) 등
서울 밖 시나리오를 돌리려면 전국 좌표가 필요하다. 결과는 커밋해서 다른 장비에서는
API 호출 없이 재사용한다(좌표는 사실상 불변).

feature/sim의 "기존 파일 수정 금지" 규칙 안에서, info의 E-Gen 클라이언트를
**읽기 전용으로 import**만 한다(복사하면 오류 봉투 처리 등이 갈라진다).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parent
INFO_DIR = SIM_DIR.parent / "info" / "Hospital_inform" / "info"
sys.path.insert(0, str(INFO_DIR))

from egen.client import HttpEgenClient  # noqa: E402

OUT_PATH = SIM_DIR / "data" / "egen_coords.json"


def main() -> None:
    client = HttpEgenClient()
    rows = client.get_list_info("", "")  # 지역 인자를 비우면 전국
    coords: dict[str, dict] = {}
    skipped = 0
    for row in rows:
        lat, lng = row.get("wgs84Lat"), row.get("wgs84Lon")
        if not lat or not lng:
            skipped += 1
            continue
        try:
            coords[row["hpid"]] = {
                "name": row.get("dutyName", ""),
                "lat": float(lat),
                "lng": float(lng),
            }
        except ValueError:
            skipped += 1
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(coords, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(coords)}곳 좌표 저장 (좌표 없음 {skipped}곳 제외) → {OUT_PATH}")


if __name__ == "__main__":
    main()
