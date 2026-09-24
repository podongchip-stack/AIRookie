"""E-Gen(국립중앙의료원 응급의료기관 정보 조회 서비스) 데이터를 가져오는 통로.

같은 메서드를 가진 구현이 세 개 있다.

- `FixtureEgenClient`  : 미리 만들어둔 파일을 읽는다. API 키가 없어도 개발이 굴러간다.
- `SupabaseEgenClient` : E-Gen 서비스키 승인 전까지 쓰던 Supabase 대체 DB를 읽는다
                         (`supabase/schema.sql` 참고). 서비스키가 승인돼 역할이
                         끝났지만, 대조용으로 남겨둔다.
- `HttpEgenClient`     : 진짜 API를 호출한다. 서비스키 승인(2026-08-10)으로 사용 가능.

쓰는 쪽은 셋 중 어느 것인지 몰라도 되게 만들었다. 나중에 실제 API로 바꿀 때
클라이언트를 만드는 한 줄만 고치면 되고, 매퍼(mapper.py)는 손대지 않는다.

    client = FixtureEgenClient()                    # fixture 파일
    client = SupabaseEgenClient(url, key)           # Supabase 대체 DB
    client = HttpEgenClient(key)                    # 키 나오면 진짜 API

명세 출처
--------
공공데이터포털 "국립중앙의료원_전국 응급의료기관 정보 조회 서비스" (data.go.kr/data/15000563)
기본 주소: http://apis.data.go.kr/B552657/ErmctInfoInqireService/

⚠️ `mapper.py` 상단 매핑표에 아직 [추정]/[미확인]이 남아 있다. `HttpEgenClient`로
실제 응답을 받아 그 표부터 교정할 것.
"""

from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import unquote

BASE_URL = "http://apis.data.go.kr/B552657/ErmctInfoInqireService"

#: 오퍼레이션 이름. [확인됨] 공공데이터포털 명세
OP_REALTIME_BEDS = "getEmrrmRltmUsefulSckbdInfoInqire"  # 응급실 실시간 가용병상정보
OP_SEVERE_ILLNESS = "getSrsillDissAceptncPosblInfoInqire"  # 중증질환자 수용가능정보
OP_LIST_INFO = "getEgytListInfoInqire"  # 응급의료기관 목록정보

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "data" / "fixtures"

#: 자격증명 파일. 실행 위치와 무관하게 항상 같은 파일을 찾도록 `__file__` 기준으로 고정한다
#: (load_dotenv()의 기본 동작인 cwd 기준 탐색에 의존하지 않는다).
ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"


class EgenApiError(RuntimeError):
    """E-Gen이 오류를 돌려줬을 때 올린다.

    이 API는 실패해도 HTTP 상태코드는 200으로 주고 본문에 오류를 담아 보낸다.
    `raise_for_status()`만 믿으면 오류 응답을 정상 데이터로 착각하게 된다.
    """


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

    def update_bed_count(self, hpid: str, hvec_value: int) -> None:
        """가용 병상 수(ER_ADULT, `hvec`)를 갱신한다. feature/hub가 이송 확정
        (final_approval)으로 병상이 줄었을 때 보내는 값을 반영하는 쓰기 경로다
        (info/README.md "hub → info" 참고). 읽기 세 메서드와 반대 방향이라
        여기 한 곳에만 추가한다 — 그 외 컬럼(위치, 목록정보 등)은 hub가 바꿀
        이유가 없어 이 메서드의 대상이 아니다."""
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

    def update_bed_count(self, hpid: str, hvec_value: int) -> None:
        """fixture는 파일 기반 읽기 전용이라 쓰기가 의미 없다 — 인터페이스만
        맞추는 no-op. 로컬에서 hub↔info 통신을 파일 fixture로 테스트할 때
        AttributeError 없이 조용히 넘어가게 하는 용도다."""
        return None


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
        # 코드에 키를 하드코딩하지 않는다는 원칙(CLAUDE.md "외부 API 키 등 환경 변수
        # 관리")은 지키되, 실제 값은 .env로 관리한다. 이미 환경변수가 있으면 덮어쓰지
        # 않는다.
        from dotenv import load_dotenv

        load_dotenv(ENV_PATH)
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
        # `hvicc`(일반 중환자실)는 매퍼가 ICU 코드를 만들 때 읽는 컬럼이다. 예전에는
        # ICU를 hv2+hv3 합산으로 만들어서 조회하지 않았는데, 실 API 명세 확인 후
        # 매퍼가 hvicc를 쓰도록 바뀌었으므로 여기서도 같이 가져와야 ICU가 안 빠진다.
        # 이 테이블에는 hv28(소아)·hv29(응급실 음압격리)·hv34(심장내과 중환자실)
        # 컬럼이 없어 해당 병상 종류는 이 경로에서 늘 미상이다 — 실 API(--http)를
        # 쓰면 채워진다.
        rows = self._select("hpid,duty_name,hvec,hvoc,hvicc,hvidate")
        return [
            {
                "hpid": row["hpid"],
                "dutyName": row["duty_name"],
                "hvec": row.get("hvec"),
                "hvoc": row.get("hvoc"),
                "hvicc": row.get("hvicc"),
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

    def update_bed_count(self, hpid: str, hvec_value: int) -> None:
        """`hospitals` 테이블의 `hvec`(응급실 성인 병상, get_realtime_beds()가
        읽는 것과 같은 컬럼)을 갱신한다. `_select()`의 읽기 패턴과 맞춰
        `.update().eq()`를 그대로 쓴다 — hpid로 행을 하나 특정해 그 컬럼만
        바꾸고, 다른 컬럼(위치·중증질환 수용가능 등)은 건드리지 않는다."""
        self._client.table(self.TABLE).update({"hvec": hvec_value}).eq("hpid", hpid).execute()


class HttpEgenClient:
    """진짜 E-Gen API를 호출하는 구현.

    응답이 XML이라 표준 라이브러리(`xml.etree.ElementTree`)로 파싱한다.
    `xmltodict` 같은 의존성을 더하지 않으려는 선택이고, 항목의 자식 요소가 전부
    말단 값이라 이 정도로 충분하다.

    다른 두 구현과 마찬가지로 **원본 필드명(hpid, hvec, dutyName …)을 그대로**
    돌려준다 — 이름을 바꾸는 일은 매퍼가 한다.

    지역 인자를 비우면 시도 전체를 받는다. 개발계정은 일일 트래픽 한도가 있어서,
    시군구를 25번 나눠 부르는 것보다 시도 단위 1회가 훨씬 유리하다.
    """

    #: 한 번에 받을 항목 수. 크게 잡아 1페이지로 끝내면 호출 횟수를 아낀다
    DEFAULT_NUM_OF_ROWS = 1000

    #: 페이지 폭주 방지. 일일 트래픽 한도가 있어서 무한 루프가 곧 하루치 소진이다
    MAX_PAGES = 20

    def __init__(
        self,
        service_key: str | None = None,
        base_url: str = BASE_URL,
        num_of_rows: int = DEFAULT_NUM_OF_ROWS,
        timeout: float = 10.0,
    ) -> None:
        if service_key is None:
            from dotenv import load_dotenv

            load_dotenv(ENV_PATH)
            service_key = os.environ.get("EGEN_SERVICE_KEY")
        if not service_key:
            raise RuntimeError(
                f"E-Gen 서비스키가 없다. {ENV_PATH} 에 EGEN_SERVICE_KEY=... 한 줄을 넣을 것."
            )

        # 서비스키는 인코딩/디코딩 두 종류로 발급된다. requests가 params를 다시 URL
        # 인코딩하므로 인코딩된 키를 그대로 넘기면 이중 인코딩으로 인증에 실패한다.
        # 디코딩된 키는 base64 문자(A-Za-z0-9+/=)뿐이라 '%'가 있으면 인코딩된 쪽이다.
        if "%" in service_key:
            service_key = unquote(service_key)

        self._key = service_key
        self._base = base_url.rstrip("/")
        self._num_of_rows = num_of_rows
        self._timeout = timeout

    @staticmethod
    def _parse(text: str) -> tuple[list[dict], int]:
        """응답 XML에서 항목 목록과 전체 건수를 꺼낸다. 오류면 예외를 올린다.

        오류 봉투가 두 종류다. 인증 실패·트래픽 초과 같은 게이트웨이 오류는 봉투
        자체가 `response`가 아니고, 서비스 수준 오류는 봉투는 같고 `resultCode`만
        다르다. 둘 다 HTTP 200으로 오므로 여기서 걸러야 한다.
        """
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise EgenApiError(f"XML 파싱 실패: {text[:200]}") from exc

        if root.tag != "response":
            code = root.findtext(".//returnReasonCode") or "?"
            msg = root.findtext(".//returnAuthMsg") or root.findtext(".//errMsg") or text[:200]
            raise EgenApiError(f"게이트웨이 오류 [{code}] {msg}")

        result_code = root.findtext("./header/resultCode")
        if result_code not in (None, "00"):
            raise EgenApiError(
                f"서비스 오류 [{result_code}] {root.findtext('./header/resultMsg')}"
            )

        rows = [
            {child.tag: (child.text or "").strip() for child in item}
            for item in root.findall("./body/items/item")
        ]
        total_text = root.findtext("./body/totalCount")
        total = int(total_text) if total_text and total_text.isdigit() else len(rows)
        return rows, total

    def _call(self, operation: str, params: dict) -> list[dict]:
        import requests

        # 빈 지역 인자는 아예 보내지 않는다. 빈 문자열을 보내면 "그 이름의 시군구"를
        # 찾아 0건이 되는 경우가 있어, 생략과 같지 않다
        query = {key: value for key, value in params.items() if value}

        rows: list[dict] = []
        page = 1
        while True:
            response = requests.get(
                f"{self._base}/{operation}",
                params={
                    "serviceKey": self._key,
                    "pageNo": page,
                    "numOfRows": self._num_of_rows,
                    **query,
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            page_rows, total = self._parse(response.text)
            rows.extend(page_rows)

            if not page_rows or len(rows) >= total:
                break
            if page >= self.MAX_PAGES:
                raise EgenApiError(
                    f"{operation}: 페이지가 {self.MAX_PAGES}쪽을 넘었다 "
                    f"(누적 {len(rows)}건 / 전체 {total}건). 응답이 이상하니 확인할 것."
                )
            page += 1

        return rows

    def get_realtime_beds(self, stage1: str = "", stage2: str = "") -> list[dict]:
        return self._call(OP_REALTIME_BEDS, {"STAGE1": stage1, "STAGE2": stage2})

    def get_severe_illness(self, stage1: str = "", stage2: str = "") -> list[dict]:
        return self._call(OP_SEVERE_ILLNESS, {"STAGE1": stage1, "STAGE2": stage2})

    def get_list_info(self, q0: str = "", q1: str = "") -> list[dict]:
        return self._call(OP_LIST_INFO, {"Q0": q0, "Q1": q1})

    def update_bed_count(self, hpid: str, hvec_value: int) -> None:
        raise NotImplementedError(
            "E-Gen은 조회 전용 공개 API라 병상 갱신을 쓸 방법이 없다. "
            "실제 API로 전환해도 이 메서드는 SupabaseEgenClient에서만 의미가 있다."
        )
