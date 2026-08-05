"""E-Gen 데이터를 읽어 `HospitalInfo` JSON 파일을 만드는 실행 진입점.

    conda activate dev
    python info/build_hospitals.py

병원 1곳당 파일 1개를 `info/data/output/`에 쓴다. feature/hub의 `run_match.py`가
`data/test/hospitals/*.json`을 그대로 파싱하므로, 여기서 나온 파일을 그 폴더에
복사하면 바로 연동 검증을 할 수 있다.

지금은 fixture(가상 데이터)를 읽는다. 서비스키가 승인되면 `--http` 옵션으로
실제 API를 쓰도록 `HttpEgenClient`를 채우면 되고, 이 파일과 매퍼는 바뀌지 않는다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from egen.client import FixtureEgenClient, SupabaseEgenClient  # noqa: E402
from egen.mapper import map_all  # noqa: E402

OUTPUT_DIR = BASE_DIR / "data" / "output"


def main() -> int:
    parser = argparse.ArgumentParser(description="E-Gen 데이터를 HospitalInfo JSON으로 변환한다")
    parser.add_argument("--region", default="jinju", help="fixture 지역 이름 (기본: jinju, --supabase와 무관)")
    parser.add_argument(
        "--supabase",
        action="store_true",
        help="fixture 대신 Supabase 대체 DB를 읽는다 (SUPABASE_URL, SUPABASE_KEY 환경변수 필요)",
    )
    parser.add_argument("--out", type=Path, default=OUTPUT_DIR, help="출력 폴더")
    args = parser.parse_args()

    client = SupabaseEgenClient() if args.supabase else FixtureEgenClient(region=args.region)
    hospitals, report = map_all(
        client.get_realtime_beds(),
        client.get_list_info(),
        client.get_severe_illness(),
    )

    print("=== 변환 결과 ===")
    print(report.summary())

    args.out.mkdir(parents=True, exist_ok=True)
    for info in hospitals:
        path = args.out / f"{info.hospitalId}.json"
        path.write_text(info.to_hub_json() + "\n", encoding="utf-8")
        beds = info.bedsByType or {}
        print(
            f"  {info.hospitalId} {info.name}"
            f" — 병상 {info.availableBedCount}"
            f", 소아 {beds.get('ER_PEDIATRIC', '미상')}"
            f", 역량 {len(info.capabilities)}개 -> {path.name}"
        )

    print(f"\n{len(hospitals)}개 파일을 {args.out}에 썼다.")
    if not hospitals:
        print("변환된 병원이 없다. fixture와 매퍼를 확인할 것.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
