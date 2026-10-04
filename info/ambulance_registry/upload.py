"""서울 구급차 레지스트리를 Supabase ambulances 테이블에 넣기 (2026-10-04).

result/seoul_ambulances.csv(build_seoul.py 결과)를 apid 기준으로 덮어쓰고(upsert), 이 목록에 없는 기존 행(예전
시연용 A0000001~3 등)은 지운다 — 새 데이터와 같은 과정으로 전부 교체한다.

  python info/ambulance_registry/upload.py           확인만(무엇을 넣고 지울지 출력, 쓰지 않음)
  python info/ambulance_registry/upload.py --apply   실제로 쓴다

필요한 값(info/ambulance_registry/.env, git에 올리지 않음):
  AMBULANCE_SUPABASE_URL          구급차용 Supabase 프로젝트 주소
  AMBULANCE_SUPABASE_SERVICE_KEY  쓰기 권한 키(service_role) — 읽기용 키로는 쓰기·지우기가 막힌다

보강 컬럼(sido·fire_station·center·unit_no·addr·phone·coord_source)이 테이블에 없으면 먼저 schema_extend.sql을
Supabase SQL 편집기에서 실행한다. info → hub 전송(send_to_hub.py)은 기존 컬럼만 읽으므로 형식이 바뀌지 않는다.
"""
from __future__ import annotations

import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")
TABLE = "ambulances"
SOURCE = HERE / "result" / "seoul_ambulances.csv"
INT_COLS = {"voice_port", "unit_no"}
FLOAT_COLS = {"wgs84_lat", "wgs84_lon"}


def load_rows() -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for r in csv.DictReader(SOURCE.open(encoding="utf-8")):
        row = {k: (int(v) if k in INT_COLS else float(v) if k in FLOAT_COLS else v) for k, v in r.items()}
        row["updated_at"] = now
        row["source"] = "rule"  # 기존 행과 같은 값(규칙 기반 데이터 표시)
        rows.append(row)
    return rows


def main() -> None:
    apply = "--apply" in sys.argv
    url, key = os.environ.get("AMBULANCE_SUPABASE_URL"), os.environ.get("AMBULANCE_SUPABASE_SERVICE_KEY")
    if not url or not key:
        sys.exit(f"❌ {HERE / '.env'}에 AMBULANCE_SUPABASE_URL·AMBULANCE_SUPABASE_SERVICE_KEY를 넣어 주세요")
    rows = load_rows()
    new_ids = {r["apid"] for r in rows}
    client = create_client(url, key)
    existing = [r["apid"] for r in client.table(TABLE).select("apid").execute().data]
    to_delete = sorted(set(existing) - new_ids)
    print(f"지금 테이블 {len(existing)}행 → 넣거나 덮어쓸 행 {len(rows)} · 지울 행 {len(to_delete)} {to_delete[:10]}")
    if not apply:
        print("확인만 했습니다. 실제로 쓰려면 --apply")
        return
    try:
        client.table(TABLE).upsert(rows, on_conflict="apid").execute()
    except Exception as e:  # noqa: BLE001
        sys.exit(f"❌ 넣기 실패: {e}\n   보강 컬럼이 없다는 오류면 schema_extend.sql을 먼저 실행하세요")
    if to_delete:
        client.table(TABLE).delete().in_("apid", to_delete).execute()
    after = client.table(TABLE).select("apid", count="exact").execute()
    print(f"✅ 완료 — 테이블 {after.count}행")


if __name__ == "__main__":
    main()
