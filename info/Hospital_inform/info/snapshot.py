"""E-Gen 응답을 주기적으로 떠서 시계열로 쌓는다.

    conda activate dev
    python info/snapshot.py                  # 1회만 (작업 스케줄러용)
    python info/snapshot.py --interval 600   # 600초마다 반복 (콘솔 상주)

왜 필요한가
----------
E-Gen API는 **"지금 값"만 주고 과거 이력을 주지 않는다.** 나중에 몰아서 받을 방법이
없으므로, 시계열이 필요하면 지금부터 직접 찍어 쌓는 수밖에 없다. 이 파일이 그
축적기다. 여기서 쌓인 데이터가 나중에 아래 세 가지의 재료가 된다.

1. 병상 추정 — 지금 5개인 병원이 15분 뒤 도착 시점에도 남아 있을지
2. 과밀 추세 — `hvec`가 음수인 병원이 얼마나 오래 그 상태로 있는지
3. 입력 성실도 — 병원별로 `hvidate`를 얼마나 자주 갱신하는지

저장 방식
--------
**가공하지 않은 원본 행을 그대로** 하루 1파일 JSONL에 append한다. `HospitalInfo`로
변환한 결과를 저장하지 않는 이유는, `mapper.py`의 매핑표에 아직 [추정]이 남아 있어서
나중에 해석이 바뀔 수 있기 때문이다. 원본을 남겨야 매핑을 고친 뒤 과거 데이터를 다시
해석할 수 있다. 가공본만 남기면 매핑을 고칠 때마다 지난 데이터가 죽는다.

호출 실패도 한 줄로 남긴다. "그 시각에 데이터가 없다"와 "그 시각에 호출이 실패했다"는
다르고, 나중에 빈 구간을 볼 때 이 구분이 없으면 원인을 알 수 없다.

트래픽
-----
개발계정은 일일 호출 한도가 있다. 좌표·기관분류(`getEgytListInfoInqire`)는 거의 안
바뀌므로 **하루 한 번만** 부르고, 실시간으로 변하는 두 오퍼레이션만 매 주기 부른다.
10분 주기 기준 하루 289회 (= 144 x 2 + 1).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from egen.client import (  # noqa: E402
    OP_LIST_INFO,
    OP_REALTIME_BEDS,
    OP_SEVERE_ILLNESS,
    EgenApiError,
    HttpEgenClient,
)

KST = timezone(timedelta(hours=9))
SNAPSHOT_DIR = BASE_DIR / "data" / "snapshots"

#: 매 주기 부르는 오퍼레이션. 실시간으로 바뀌는 것만 넣는다
REALTIME_OPS = (OP_REALTIME_BEDS, OP_SEVERE_ILLNESS)

#: 하루 한 번만 부르는 오퍼레이션. 좌표·기관분류는 거의 안 바뀐다
DAILY_OPS = (OP_LIST_INFO,)


def snapshot_path(now: datetime, directory: Path) -> Path:
    return directory / f"{now.date().isoformat()}.jsonl"


def already_taken_today(path: Path, operation: str) -> bool:
    """오늘 파일에 이 오퍼레이션이 이미 (성공으로) 들어있는지 본다.

    실패한 줄은 세지 않는다 — 아침 첫 호출이 실패했으면 다음 주기에 다시 시도해야
    좌표를 하루 종일 못 받는 일이 없다.
    """
    if not path.exists():
        return False
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("operation") == operation and "error" not in record:
                return True
    return False


def call_operation(client: HttpEgenClient, operation: str, stage1: str, stage2: str) -> list[dict]:
    """오퍼레이션 이름으로 클라이언트의 해당 메서드를 부른다.

    목록정보만 파라미터 이름이 Q0/Q1이라 클라이언트가 그 차이를 이미 흡수하고 있다.
    여기서는 이름만 골라 넘긴다.
    """
    if operation == OP_REALTIME_BEDS:
        return client.get_realtime_beds(stage1, stage2)
    if operation == OP_SEVERE_ILLNESS:
        return client.get_severe_illness(stage1, stage2)
    if operation == OP_LIST_INFO:
        return client.get_list_info(stage1, stage2)
    raise ValueError(f"모르는 오퍼레이션: {operation}")


def fetch_one(client: HttpEgenClient, operation: str, stage1: str, stage2: str) -> dict:
    """오퍼레이션 하나를 호출해 기록 한 줄을 만든다. 실패도 기록으로 남긴다."""
    record: dict = {
        "ts": datetime.now(KST).isoformat(),
        "operation": operation,
        "stage1": stage1,
        "stage2": stage2,
    }
    try:
        items = call_operation(client, operation, stage1, stage2)
    except (EgenApiError, OSError) as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
        return record

    record["count"] = len(items)
    record["items"] = items
    return record


def take_snapshot(
    client: HttpEgenClient,
    stage1: str,
    stage2: str = "",
    directory: Path = SNAPSHOT_DIR,
) -> Path:
    """한 주기 분량을 찍어 오늘 파일에 append한다."""
    directory.mkdir(parents=True, exist_ok=True)
    now = datetime.now(KST)
    path = snapshot_path(now, directory)

    operations = list(REALTIME_OPS)
    operations += [op for op in DAILY_OPS if not already_taken_today(path, op)]

    with path.open("a", encoding="utf-8") as handle:
        for operation in operations:
            record = fetch_one(client, operation, stage1, stage2)
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()  # 상주 실행 중 강제 종료돼도 직전 관측까지는 남게 한다
            if "error" in record:
                print(f"  [{now:%H:%M:%S}] {operation} 실패 — {record['error']}", file=sys.stderr)
            else:
                print(f"  [{now:%H:%M:%S}] {operation} {record['count']}건")

    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="E-Gen 응답을 주기적으로 떠서 시계열로 쌓는다")
    parser.add_argument("--stage1", default="서울특별시", help="시도 (기본: 서울특별시)")
    parser.add_argument("--stage2", default="", help="시군구. 비우면 시도 전체 (기본: 비움)")
    parser.add_argument(
        "--interval",
        type=int,
        default=0,
        help="반복 주기(초). 0이면 1회만 찍고 끝낸다 (작업 스케줄러용, 기본값)",
    )
    parser.add_argument("--dir", type=Path, default=SNAPSHOT_DIR, help="저장 폴더")
    args = parser.parse_args()

    client = HttpEgenClient()

    while True:
        try:
            path = take_snapshot(client, args.stage1, args.stage2, args.dir)
        except KeyboardInterrupt:
            print("\n중단됨.")
            return 0
        except Exception as exc:  # 상주 실행이 한 번의 예외로 죽지 않게 한다
            print(f"  스냅샷 실패: {type(exc).__name__}: {exc}", file=sys.stderr)
        else:
            size_kb = path.stat().st_size / 1024
            lines = sum(1 for _ in path.open(encoding="utf-8"))
            print(f"  -> {path.name} (누적 {lines}줄, {size_kb:,.0f}KB)")

        if args.interval <= 0:
            return 0
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n중단됨.")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
