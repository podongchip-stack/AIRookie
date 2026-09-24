"""스냅샷 JSONL을 분석 가능한 형태로 읽는다.

`snapshot.py`가 쌓아둔 **가공 전 원본**을 그대로 읽는다. 매핑 해석이 또 바뀌어도
과거 데이터를 다시 해석할 수 있어야 하므로 원본을 저장하기로 한 결정(README 참고)의
반대편 짝이 이 파일이다 — 해석은 전부 여기서 한다.

이 모듈은 저장소의 다른 모듈을 import 하지 않는다. `hospital_score/`는 검증 전까지
폴더째 버릴 수 있어야 하고, 반대로 이 폴더가 죽어도 기존 hub 경로가 멀쩡해야 한다.

스냅샷 한 줄의 형태
-------------------
    {"ts", "operation", "stage1", "stage2", "count", "items": [원본 행 …]}
    {"ts", "operation", "error"}            # 호출 실패도 한 줄로 남는다

실패한 호출을 빈 구간과 구분할 수 있어야 해서 실패도 기록한다. 따라서 읽는 쪽도
`items`가 없는 줄을 정상으로 취급하고 건너뛰어야 한다.

수집 경로가 둘이다
------------------
- `data/snapshots/`            서울 55곳, 10분 주기 (2026-08-10 ~ 08-12, 현재 중단)
- `data/snapshots_nationwide/` 전국 443곳, 20분 주기 (2026-08-12 ~, 현재 가동)

전국이 서울을 포함하므로 둘을 합쳐 읽되, 서울만 보고 싶으면 `hpid` 접두어 `A11`로
거른다. 두 경로의 같은 시각 관측이 겹칠 수 있어 `(ts, hpid)` 기준으로 중복을 없앤다.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import vocabulary as V

#: 스냅샷 폴더 (이 파일 기준 고정 — 실행 위치에 의존하지 않는다)
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SEOUL_DIR = DATA_DIR / "snapshots"
NATIONWIDE_DIR = DATA_DIR / "snapshots_nationwide"

OP_BEDS = "getEmrrmRltmUsefulSckbdInfoInqire"
OP_ACCEPT = "getSrsillDissAceptncPosblInfoInqire"
OP_LIST = "getEgytListInfoInqire"

#: E-Gen이 "병원이 입력하지 않음"을 나타내는 값. 이 값**만** 미입력이고,
#: `-2` 이하는 과밀(정원 초과 수용)이다 — mapper.py와 같은 규약
MISSING_SENTINEL = -1


@dataclass(frozen=True)
class Hospital:
    """목록정보에서 오는 병원 기본 정보. 시간에 따라 변하지 않는 축이다."""

    hpid: str
    name: str
    emcls: str | None  # dutyEmclsName — 권역/지역센터/지역기관/응급실운영신고기관
    lat: float | None
    lon: float | None

    @property
    def sido_prefix(self) -> str:
        """hpid 앞 3자리. `A11`이 서울이다."""
        return self.hpid[:3]


@dataclass
class Frame:
    """한 시각의 관측 한 덩어리."""

    ts: datetime
    #: hpid -> {항목번호: 값}. 값은 Y / 불가능 / 정보미제공 중 하나
    accept: dict[str, dict[int, str]] = field(default_factory=dict)
    #: hpid -> {항목번호: Msg 자유텍스트}. 소아 항목에만 있다
    accept_msg: dict[str, dict[int, str]] = field(default_factory=dict)
    #: hpid -> 가용병상 원본 행 (hvec, hvidate, hvs38 …)
    beds: dict[str, dict] = field(default_factory=dict)


def iter_records(paths: list[Path]) -> Iterator[dict]:
    """스냅샷 파일들을 줄 단위로 읽는다. 실패 기록과 깨진 줄은 건너뛴다."""
    for path in paths:
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    # 수집 중 프로세스가 끊기면 마지막 줄이 잘릴 수 있다. 한 줄 버리고 계속
                    continue
                if "items" in record:
                    yield record


def snapshot_files(
    *, seoul: bool = True, nationwide: bool = True, day: str | None = None
) -> list[Path]:
    """읽을 스냅샷 파일 목록. `day`는 `2026-08-12` 형식, 없으면 전부."""
    dirs = []
    if nationwide:
        dirs.append(NATIONWIDE_DIR)
    if seoul:
        dirs.append(SEOUL_DIR)
    pattern = f"{day}.jsonl" if day else "*.jsonl"
    return sorted(p for d in dirs if d.exists() for p in d.glob(pattern))


def load_hospitals(paths: list[Path]) -> dict[str, Hospital]:
    """목록정보에서 병원 축을 만든다. 같은 hpid가 여러 번 나오면 마지막 관측이 이긴다.

    목록정보는 좌표·등급처럼 잘 안 변하는 값이라 `snapshot.py`가 하루 1회만 부른다.
    따라서 여기서 얻는 건 "그 날의 명부"에 가깝다.
    """
    hospitals: dict[str, Hospital] = {}
    for record in iter_records(paths):
        if record.get("operation") != OP_LIST:
            continue
        for row in record["items"]:
            hpid = (row.get("hpid") or "").strip()
            if not hpid:
                continue
            hospitals[hpid] = Hospital(
                hpid=hpid,
                name=(row.get("dutyName") or "").strip(),
                emcls=(row.get("dutyEmclsName") or "").strip() or None,
                lat=_to_float(row.get("wgs84Lat")),
                lon=_to_float(row.get("wgs84Lon")),
            )
    return hospitals


def load_frames(paths: list[Path]) -> list[Frame]:
    """시각별 관측을 모은다.

    병상 응답과 중증질환 응답은 같은 주기에 연달아 호출되지만 타임스탬프가 몇백
    밀리초 다르다. 초 단위로 반올림해 같은 주기로 묶는다 — 주기가 10분·20분이라
    이 정도 묶음으로 충돌할 일이 없다.
    """
    frames: dict[str, Frame] = {}
    for record in iter_records(paths):
        op = record.get("operation")
        if op not in (OP_BEDS, OP_ACCEPT):
            continue
        ts = datetime.fromisoformat(record["ts"])
        key = ts.strftime("%Y-%m-%dT%H:%M")
        frame = frames.get(key)
        if frame is None:
            frame = frames[key] = Frame(ts=ts.replace(second=0, microsecond=0))

        for row in record["items"]:
            hpid = (row.get("hpid") or "").strip()
            if not hpid:
                continue
            if op == OP_BEDS:
                frame.beds[hpid] = row
            else:
                values: dict[int, str] = {}
                messages: dict[int, str] = {}
                for item in V.ITEMS:
                    value = V.normalize_accept(row.get(item.field))
                    if value is not None:
                        values[item.no] = value
                    if item.msg_field:
                        text = (row.get(item.msg_field) or "").strip()
                        if text:
                            messages[item.no] = text
                frame.accept[hpid] = values
                if messages:
                    frame.accept_msg[hpid] = messages

    return [frames[key] for key in sorted(frames)]


def parse_hvidate(raw: str | None) -> datetime | None:
    """`yyyyMMddHHmmss` 형식의 병원 입력 시각. 형식이 어긋나면 None."""
    if not raw:
        return None
    text = raw.strip()
    if len(text) < 14 or not text[:14].isdigit():
        return None
    try:
        return datetime.strptime(text[:14], "%Y%m%d%H%M%S")
    except ValueError:
        return None


def parse_bed_count(raw: str | None) -> int | None:
    """가용 병상 수. 미입력(-1)은 None, 과밀(음수)은 음수 그대로 돌려준다.

    과밀을 0으로 낮추는 건 hub로 내보내는 스키마가 음수를 막기 때문에 하는 일이고
    (mapper.py), 분석에서는 정도를 살려야 해서 여기서는 낮추지 않는다.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        value = int(text)
    except ValueError:
        return None
    return None if value == MISSING_SENTINEL else value


def _to_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        return float(str(raw).strip())
    except ValueError:
        return None
