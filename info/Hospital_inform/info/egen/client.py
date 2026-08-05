"""E-Gen(국립중앙의료원 응급의료기관 정보 조회 서비스) 데이터를 가져오는 통로.

같은 메서드를 가진 구현이 두 개 있다.

- `FixtureEgenClient` : 미리 만들어둔 파일을 읽는다. API 키가 없어도 개발이 굴러간다.
- `HttpEgenClient`    : 진짜 API를 호출한다. 키가 나오면 채운다.

쓰는 쪽은 둘 중 어느 것인지 몰라도 되게 만들었다. 나중에 실제 API로 바꿀 때
클라이언트를 만드는 한 줄만 고치면 되고, 매퍼(mapper.py)는 손대지 않는다.

    client = FixtureEgenClient()     # 지금
    client = HttpEgenClient(key)     # 키 나오면

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
