"""E-Gen 데이터를 읽어 `HospitalInfo` JSON 파일을 만드는 실행 진입점.

    conda activate dev
    python info/build_hospitals.py

병원 1곳당 파일 1개를 `info/data/output/`에 쓴다. feature/hub의 `run_match.py`가
`data/test/hospitals/*.json`을 그대로 파싱하므로, 여기서 나온 파일을 그 폴더에
복사하면 바로 연동 검증을 할 수 있다.

데이터 출처는 셋 중 하나를 고른다. 기본은 fixture(가상 데이터)이고, `--http`가
실제 E-Gen API다.

    python info/build_hospitals.py                      # fixture
    python info/build_hospitals.py --supabase           # Supabase 대체 DB
    python info/build_hospitals.py --http               # 실제 API (서울 전체)
    python info/build_hospitals.py --http --stage2 강남구  # 실제 API (시군구 한정)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from egen.client import FixtureEgenClient, HttpEgenClient, SupabaseEgenClient  # noqa: E402
from egen.mapper import map_all  # noqa: E402

OUTPUT_DIR = BASE_DIR / "data" / "output"


def main() -> int:
    parser = argparse.ArgumentParser(description="E-Gen 데이터를 HospitalInfo JSON으로 변환한다")
    parser.add_argument("--region", default="jinju", help="fixture 지역 이름 (기본: jinju, 다른 출처와 무관)")
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--supabase",
        action="store_true",
        help="fixture 대신 Supabase 대체 DB를 읽는다 (SUPABASE_URL, SUPABASE_KEY 필요)",
    )
    source.add_argument(
        "--http",
        action="store_true",
        help="fixture 대신 실제 E-Gen API를 호출한다 (EGEN_SERVICE_KEY 필요)",
    )
    parser.add_argument("--stage1", default="서울특별시", help="--http 전용. 시도 (기본: 서울특별시)")
    parser.add_argument("--stage2", default="", help="--http 전용. 시군구 (기본: 비움 = 시도 전체)")
    parser.add_argument("--out", type=Path, default=OUTPUT_DIR, help="출력 폴더")
    args = parser.parse_args()

    if args.http:
        client = HttpEgenClient()
    elif args.supabase:
        client = SupabaseEgenClient()
    else:
        client = FixtureEgenClient(region=args.region)

    # 세 구현 모두 (시도, 시군구) 두 인자를 같은 자리에서 받는다. fixture와 Supabase는
    # 무시하고, HttpEgenClient만 실제 질의 조건으로 쓴다
    hospitals, report = map_all(
        client.get_realtime_beds(args.stage1, args.stage2),
        client.get_list_info(args.stage1, args.stage2),
        client.get_severe_illness(args.stage1, args.stage2),
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
