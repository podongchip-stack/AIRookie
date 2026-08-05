"""E-Gen(국립중앙의료원 응급의료기관 정보 조회 서비스) 데이터를 가져오는 통로.

같은 메서드를 가진 구현이 세 개 있다.

- `FixtureEgenClient`  : 미리 만들어둔 파일을 읽는다. API 키가 없어도 개발이 굴러간다.
- `SupabaseEgenClient` : E-Gen 서비스키 승인 전까지, Supabase에 만들어둔 대체 DB를
                         읽는다 (`supabase/schema.sql` 참고). 실제 서비스 운영 데이터가
                         아니라 임시 대체 데이터다.
- `HttpEgenClient`     : 진짜 API를 호출한다. 키가 나오면 채운다.

쓰는 쪽은 셋 중 어느 것인지 몰라도 되게 만들었다. 나중에 실제 API로 바꿀 때
클라이언트를 만드는 한 줄만 고치면 되고, 매퍼(mapper.py)는 손대지 않는다.

    client = FixtureEgenClient()                    # fixture 파일
    client = SupabaseEgenClient(url, key)           # Supabase 대체 DB
    client = HttpEgenClient(key)                    # 키 나오면 진짜 API

명세 출처
--------
공공데이터포털 "국립중앙의료원_전국 응급의료기관 정보 조회 서비스" (data.go.kr/data/15000563)
기본 주소: http://apis.data.go.kr/B552657/ErmctInfoInqireService/

⚠️ 아직 실제 응답을 받아본 적이 없다. 아래 [확인됨]/[미확인] 표시를 지켜서 읽을 것.
키가 승인되면 `HttpEgenClient`로 실제 응답을 받아 fixture와 대조하고, [미확인]을
전부 [확인됨]으로 바꾸는 작업이 먼저다.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Protocol

BASE_URL = "http://apis.data.go.kr/B552657/ErmctInfoInqireService"

#: 오퍼레이션 이름. [확인됨] 공공데이터포털 명세
OP_REALTIME_BEDS = "getEmrrmRltmUsefulSckbdInfoInqire"  # 응급실 실시간 가용병상정보
OP_SEVERE_ILLNESS = "getSrsillDissAceptncPosblInfoInqire"  # 중증질환자 수용가능정보
OP_LIST_INFO = "getEgytListInfoInqire"  # 응급의료기관 목록정보

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "data" / "fixtures"


def extract_items(payload: dict) -> list[dict]:
    """E-Gen 응답 봉투에서 병원 목록만 꺼낸다.

    응답은 `response.body.items.item` 아래에 들어 있다. 결과가 1건일 때 `item`이
    목록이 아니라 딕셔너리 하나로 오는 경우가 있어서(XML을 딕셔너리로 바꿀 때
    흔히 생기는 일) 양쪽을 모두 받아준다. 0건이면 `items`가 빈 문자열인 사례도
    보고돼 있어 그것도 막는다.
    """
    body = payload.get("response", {}).get("body", {})
    items = body.get("items")
    if not items:  # None, "", {} 전부 여기서 걸린다
        return []
    item = items.get("item") if isinstance(items, dict) else items
    if item is None:
        return []
    return item if isinstance(item, list) else [item]


class EgenClient(Protocol):
    """두 구현이 공통으로 갖는 모양.

    반환값은 전부 "응답 봉투를 벗긴 병원 딕셔너리 목록"이다. 원본 필드명
    (hpid, hvec, dutyName …)을 그대로 유지한다 — 이름을 바꾸는 일은 매퍼가 한다.
    """

    def get_realtime_beds(self, stage1: str, stage2: str) -> list[dict]:
        """응급실 실시간 가용병상정보. STAGE1=시도, STAGE2=시군구 (둘 다 필수)."""
        ...

    def get_severe_illness(self, stage1: str, stage2: str) -> list[dict]:
        """중증질환자 수용가능정보. 재관류·수술 가능 여부가 여기서 나온다."""
        ...

    def get_list_info(self, q0: str, q1: str) -> list[dict]:
        """응급의료기관 목록정보. 좌표(wgs84Lat/Lon)와 기관 분류가 여기서 나온다."""
        ...


class FixtureEgenClient:
    """미리 만들어둔 파일에서 읽는 구현.

    fixture는 명세의 필드명·구조를 그대로 흉내내야 한다. 여기서 형태가 어긋나면
    실제 API로 바꾸는 순간 매퍼를 다시 짜야 한다.
    """

    def __init__(self, fixture_dir: Path | None = None, region: str = "jinju") -> None:
        self._dir = fixture_dir or FIXTURE_DIR
        self._region = region

    def _load(self, name: str) -> list[dict]:
        path = self._dir / f"{name}_{self._region}.json"
        if not path.exists():
            raise FileNotFoundError(
                f"fixture 파일이 없다: {path}\n"
                f"({self._dir} 안에 '{name}_{self._region}.json'이 있어야 한다)"
            )
        return extract_items(json.loads(path.read_text(encoding="utf-8")))

    def get_realtime_beds(self, stage1: str = "경상남도", stage2: str = "진주시") -> list[dict]:
        return self._load("realtime_beds")

    def get_severe_illness(self, stage1: str = "경상남도", stage2: str = "진주시") -> list[dict]:
        return self._load("severe_illness")

    def get_list_info(self, q0: str = "경상남도", q1: str = "진주시") -> list[dict]:
        return self._load("list_info")


class SupabaseEgenClient:
    """Supabase의 `hospitals` 테이블(`supabase/schema.sql`)에서 읽는 구현.

    E-Gen 서비스키 승인 전까지 실제 API를 대체한다. 테이블은 세 오퍼레이션의
    필드를 한 행에 다 갖고 있지만(단일 테이블), 이 클라이언트가 오퍼레이션별로
    필요한 컬럼만 골라 E-Gen 원본 필드명(hpid, dutyName, wgs84Lat …)으로 다시
    이름 붙여 돌려준다 — 매퍼(mapper.py)는 이게 fixture에서 온 건지 Supabase에서
    온 건지 구분할 필요가 없다.

    지금은 지역(STAGE1/STAGE2, Q0/Q1) 필터링을 하지 않고 테이블 전체를 돌려준다
    — 시연 지역이 서울 하나뿐이라 필요 없었다. 여러 지역을 나눠 담게 되면
    테이블에 `stage1`/`stage2` 컬럼을 추가하고 여기서 필터링하면 된다.
    """

    TABLE = "hospitals"

    def __init__(self, url: str | None = None, key: str | None = None) -> None:
        # .env 파일(Hospital_inform/.env)을 환경변수로 로드한다. 이미 환경변수가
        # 있으면 덮어쓰지 않는다 — 코드에 키를 하드코딩하지 않는다는 원칙(CLAUDE.md
        # "외부 API 키 등 환경 변수 관리")은 지키되, 실제 값은 .env로 관리한다.
        from dotenv import load_dotenv

        load_dotenv()
        self._url = url or os.environ["SUPABASE_URL"]
        self._key = key or os.environ["SUPABASE_KEY"]

        try:
            from supabase import create_client
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "supabase-py가 설치되어 있지 않다. `pip install supabase`로 설치할 것 "
                "(info/requirements.txt에 추가되어 있음)."
            ) from exc

        self._client = create_client(self._url, self._key)

    def _select(self, columns: str) -> list[dict]:
        response = self._client.table(self.TABLE).select(columns).execute()
        return response.data or []

    @staticmethod
    def _format_hvidate(raw: object) -> str | None:
        """timestamptz(ISO 8601)로 오는 값을 mapper.py의 parse_hvidate()가 기대하는
        `yyyyMMddHHmmss` 형식으로 되돌린다."""
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt.strftime("%Y%m%d%H%M%S")

    def get_realtime_beds(self, stage1: str = "", stage2: str = "") -> list[dict]:
        rows = self._select("hpid,duty_name,hvec,hvoc,hv11,hv2,hv3,hvidate")
        return [
            {
                "hpid": row["hpid"],
                "dutyName": row["duty_name"],
                "hvec": row.get("hvec"),
                "hvoc": row.get("hvoc"),
                "hv11": row.get("hv11"),
                "hv2": row.get("hv2"),
                "hv3": row.get("hv3"),
                "hvidate": self._format_hvidate(row.get("hvidate")),
            }
            for row in rows
        ]

    def get_severe_illness(self, stage1: str = "", stage2: str = "") -> list[dict]:
        rows = self._select("hpid,severe_illness")
        return [
            {"hpid": row["hpid"], **(row.get("severe_illness") or {})}
            for row in rows
        ]

    def get_list_info(self, q0: str = "", q1: str = "") -> list[dict]:
        rows = self._select("hpid,duty_name,wgs84_lat,wgs84_lon")
        return [
            {
                "hpid": row["hpid"],
                "dutyName": row["duty_name"],
                "wgs84Lat": row.get("wgs84_lat"),
                "wgs84Lon": row.get("wgs84_lon"),
            }
            for row in rows
        ]


class HttpEgenClient:
    """진짜 E-Gen API를 호출하는 구현.

    아직 서비스키가 없어 미구현이다. 키가 승인되면 이 클래스만 채우면 되고,
    매퍼와 나머지 코드는 건드리지 않는다.

    구현할 때 주의할 점 (실제 응답을 받으면 확인할 것):
    - 응답이 XML이다. `xmltodict` 등으로 딕셔너리로 바꾼 뒤 `extract_items()`에 넘긴다.
    - 서비스키는 인코딩/디코딩 두 종류가 발급된다. `requests`에 넘길 때 이중 인코딩되면
      인증 오류가 나므로 어느 쪽을 쓰는지 확인해야 한다.
    - 값이 없는 필드를 어떻게 표현하는지(-1 / 빈 문자열 / 필드 자체 누락) 반드시 확인하고
      fixture와 매퍼에 반영한다. [미확인]
    """

    def __init__(self, service_key: str, base_url: str = BASE_URL) -> None:
        self._key = service_key
        self._base = base_url

    def _call(self, operation: str, params: dict) -> list[dict]:
        raise NotImplementedError(
            "E-Gen 서비스키가 아직 없어 미구현이다. "
            "공공데이터포털 활용신청 승인 후 구현할 것. "
            "그 전까지는 FixtureEgenClient를 쓴다."
        )

    def get_realtime_beds(self, stage1: str, stage2: str) -> list[dict]:
        return self._call(OP_REALTIME_BEDS, {"STAGE1": stage1, "STAGE2": stage2})

    def get_severe_illness(self, stage1: str, stage2: str) -> list[dict]:
        return self._call(OP_SEVERE_ILLNESS, {"STAGE1": stage1, "STAGE2": stage2})

    def get_list_info(self, q0: str, q1: str) -> list[dict]:
        return self._call(OP_LIST_INFO, {"Q0": q0, "Q1": q1})
