"""심평원(HIRA) 의료기관별상세정보서비스 클라이언트 — 원본 필드를 그대로 돌려주는 얇은 층.

왜 심평원인가
-------------
E-Gen이 주는 값은 전부 **병원이 스스로 신고한 것**이고, 신고에는 구멍이 있다는 걸
실측으로 확인했다(전국 25곳이 최대 8.6년 묵은 값을 실시간으로 송출, 하위 등급의
수용가능 신고 미상률 88~96%, 화상 전문병원 5곳 중 E-Gen에 화상 역량이 보이는 곳 0).
같은 소스 안에서는 그 구멍을 검증할 수 없다.

목적은 미상 칸을 추정해 채우는 게 아니라 **신고와 대조해 어긋나는 지점을 드러내는
것**이다. (관측된 칸의 97%가 "가능"이라 추정 과제는 상수 기준선을 이기기 어렵고,
라벨이 상위 등급에 편중돼 있어 미신고 병원에 적용하면 "미신고 병원도 대부분 수용
가능"이라는 위험한 방향의 오류가 난다.)

엔드포인트 버전 주의 — 실제로 헤맨 지점
---------------------------------------
**`MadmDtlInfoService2.8`이 현재 버전이다.** `2.7`도 게이트웨이에 실재해서
403(권한 없음)을 돌려주는데, 이걸 보고 "경로는 맞고 승인만 안 났다"고 판단하면
몇 시간을 날린다. 실제로 그렇게 헤맸다.

data.go.kr 게이트웨이는 경로를 서비스+오퍼레이션 **전체**로 검증한다:
    400 `NO_OPENAPI_SERVICE`             = 그런 경로가 없다
    403 `SERVICE_KEY_IS_NOT_REGISTERED`  = 경로는 실재하나 이 키에 권한이 없다
403은 "실재한다"만 알려줄 뿐 **그게 현재 버전이라는 뜻이 아니다.** 버전은 반드시
포털 마이페이지의 활용신청 상세 화면에 적힌 **End Point**로 확인할 것.

- 서비스키는 E-Gen과 같은 값이다(계정당 인증키 하나). 서비스별 활용신청만 따로 필요
- 응답 기본 포맷이 **JSON**이다 (E-Gen은 XML). 둘 다 처리한다
- 일일 트래픽 800,000회로 여유가 크다

`ykiho`(암호화요양기호)가 있어야 한다
------------------------------------
상세정보서비스의 모든 오퍼레이션은 `ykiho`를 입력으로 받는다. 없이 부르면 정상 응답에
`totalCount=0`이 온다(오류가 아니라서 조용히 빈 결과가 된다 — 주의).

`ykiho` 목록은 **병원정보서비스(15001698)**에 있다. 그런데 E-Gen과 심평원은 공통
식별자가 없어서(`hpid` ↔ `ykiho`) 좌표 최근접으로 붙여야 한다. 그 두 단계를 묶은 것이
`--build-join`이다.

    python -m hospital_score.hira --build-join                 # 조인 + 전문의 수까지
    python -m hospital_score.hira --probe --ykiho <요양기호>    # 응답 필드만 확인

`--build-join`이 만드는 두 파일(`data/hira/egen_hira_join.json`,
`data/hira/specialists.json`)을 `scoring.py`가 읽는다. **캐시가 없어도 점수는 나오지만
심평원 근거가 통째로 빠져 미상이 전부 `unknown_bare`로 떨어진다.** `data/`는 커밋되지
않으므로 새 장비에서는 이 명령을 한 번 돌려야 한다.
"""

from __future__ import annotations

import json
import math
import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote

from . import dataset as D

#: 자격증명 파일. 실행 위치와 무관하게 `__file__` 기준으로 고정한다
ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"

#: 조인·전문의 캐시. `scoring.py`가 여기서 읽는다. `data/`는 커밋되지 않는다
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "hira"
JOIN_PATH = CACHE_DIR / "egen_hira_join.json"
SPECIALISTS_PATH = CACHE_DIR / "specialists.json"

BASE_URL = "https://apis.data.go.kr/B551182"

#: 의료기관별상세정보서비스 (15001699). **현재 버전 2.8** — 위 "엔드포인트 버전 주의" 참고
SVC_DETAIL = "MadmDtlInfoService2.8"

#: 병원정보서비스 (15001698). `ykiho`와 좌표의 출처. 활용신청 전이라 현재 403
SVC_HOSP = "hospInfoServicev2"
OP_HOSP_LIST = "getHospBasisList"

#: 상세정보서비스 오퍼레이션 11종. 포털 활용신청 상세기능정보에 적힌 그대로다
OPS: dict[str, str] = {
    "facility": "getEqpInfo2.8",  # 시설정보
    "special_diagnosis": "getSpclDiagInfo2.8",  # 특수진료정보(진료가능분야조회)
    "transport": "getTrnsprtInfo2.8",  # 교통정보
    "detail": "getDtlInfo2.8",  # 세부정보
    "specialists": "getSpcSbjtSdrInfo2.8",  # 전문과목별 전문의 수
    "departments": "getDgsbjtInfo2.8",  # 진료과목정보
    "equipment": "getMedOftInfo2.8",  # 의료장비정보
    "meal_surcharge": "getFoepAddcInfo2.8",  # 식대가산정보
    "nursing_grade": "getNursigGrdInfo2.8",  # 간호등급정보
    "specialty_fields": "getSpclHospAsgFldList2.8",  # 전문병원지정분야
    "other_staff": "getEtcHstInfo2.8",  # 기타인력수
}

#: 사람이 읽는 이름 (로그·프로브 출력용)
OP_LABELS: dict[str, str] = {
    "facility": "시설정보",
    "special_diagnosis": "특수진료(진료가능분야)",
    "transport": "교통정보",
    "detail": "세부정보",
    "specialists": "전문과목별 전문의 수",
    "departments": "진료과목정보",
    "equipment": "의료장비정보",
    "meal_surcharge": "식대가산정보",
    "nursing_grade": "간호등급정보",
    "specialty_fields": "전문병원지정분야",
    "other_staff": "기타인력수",
}

MAX_PAGES = 20
DEFAULT_NUM_OF_ROWS = 1000
SIDO_SEOUL = "110000"


class HiraApiError(RuntimeError):
    """심평원이 오류를 돌려줬을 때 올린다."""


class HiraNotApprovedError(HiraApiError):
    """경로는 실재하나 이 키에 활용신청이 안 돼 있다 (403).

    별도 예외로 둔 이유: "오퍼레이션 이름이 틀렸다"·"버전이 구버전이다"·"신청을 안 했다"가
    전부 다른 문제인데 메시지만 보면 구분이 안 돼 한참 헤맬 수 있다.
    """


class HiraClient:
    """심평원 호출부. 원본 필드명을 그대로 돌려준다 — 해석은 하지 않는다."""

    def __init__(
        self,
        service_key: str | None = None,
        base_url: str = BASE_URL,
        num_of_rows: int = DEFAULT_NUM_OF_ROWS,
        timeout: float = 20.0,
    ) -> None:
        if service_key is None:
            from dotenv import load_dotenv

            load_dotenv(ENV_PATH)
            service_key = os.environ.get("HIRA_SERVICE_KEY")
        if not service_key:
            raise RuntimeError(
                f"심평원 서비스키가 없다. {ENV_PATH} 에 HIRA_SERVICE_KEY=... 한 줄을 넣을 것. "
                "(data.go.kr은 계정당 키가 하나라 E-Gen 키와 같은 값이다)"
            )
        # 인코딩된 키를 그대로 넘기면 requests가 다시 인코딩해 인증에 실패한다 (E-Gen과 동일 규약)
        if "%" in service_key:
            service_key = unquote(service_key)

        self._key = service_key
        self._base = base_url.rstrip("/")
        self._num_of_rows = num_of_rows
        self._timeout = timeout

    @staticmethod
    def _parse(text: str, where: str) -> tuple[list[dict], int]:
        """응답에서 항목과 전체 건수를 꺼낸다. 기본은 JSON, XML도 받는다."""
        if "SERVICE_KEY_IS_NOT_REGISTERED" in text:
            raise HiraNotApprovedError(
                f"{where}: 이 키에 권한이 없다. 포털 활용신청 상세 화면의 End Point와 "
                "오퍼레이션 이름(버전 포함)이 이 경로와 같은지 먼저 확인할 것 — "
                "구버전 경로도 실재해서 같은 403을 돌려준다"
            )
        if "NO_OPENAPI_SERVICE" in text:
            raise HiraApiError(f"{where}: 그런 경로가 없다")
        if "LIMITED_NUMBER_OF_SERVICE_REQUESTS" in text:
            raise HiraApiError(f"{where}: 일일 트래픽 한도 초과")

        body: dict | None = None
        try:
            body = json.loads(text)["response"]["body"]
        except (json.JSONDecodeError, KeyError, TypeError):
            body = None

        if body is not None:
            items = body.get("items")
            rows: list[dict] = []
            if isinstance(items, dict):
                item = items.get("item")
                if isinstance(item, list):
                    rows = [row for row in item if isinstance(row, dict)]
                elif isinstance(item, dict):
                    rows = [item]
            elif isinstance(items, list):
                rows = [row for row in items if isinstance(row, dict)]
            total = body.get("totalCount")
            return rows, int(total) if isinstance(total, (int, str)) and str(total).isdigit() else len(rows)

        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise HiraApiError(f"{where}: 응답을 해석할 수 없다 — {text[:200]}") from exc

        result_code = root.findtext(".//resultCode")
        if result_code not in (None, "00"):
            raise HiraApiError(
                f"{where}: 서비스 오류 [{result_code}] {root.findtext('.//resultMsg')}"
            )
        rows = [
            {child.tag: (child.text or "").strip() for child in item}
            for item in root.findall(".//item")
        ]
        total_text = root.findtext(".//totalCount")
        total = int(total_text) if total_text and total_text.isdigit() else len(rows)
        return rows, total

    def _call(self, service: str, operation: str, params: dict) -> list[dict]:
        import requests

        query = {key: value for key, value in params.items() if value}
        where = f"{service}/{operation}"

        rows: list[dict] = []
        page = 1
        while True:
            response = requests.get(
                f"{self._base}/{service}/{operation}",
                params={
                    "serviceKey": self._key,
                    "pageNo": page,
                    "numOfRows": self._num_of_rows,
                    **query,
                },
                timeout=self._timeout,
            )
            page_rows, total = self._parse(response.text, where)
            rows.extend(page_rows)

            if not page_rows or len(rows) >= total:
                break
            if page >= MAX_PAGES:
                raise HiraApiError(
                    f"{where}: 페이지가 {MAX_PAGES}쪽을 넘었다 (누적 {len(rows)} / 전체 {total})"
                )
            page += 1
        return rows

    def detail_op(self, key: str, ykiho: str) -> list[dict]:
        """상세정보서비스 오퍼레이션 하나를 부른다. `key`는 `OPS`의 키."""
        if key not in OPS:
            raise KeyError(f"모르는 오퍼레이션: {key} (가능: {', '.join(OPS)})")
        return self._call(SVC_DETAIL, OPS[key], {"ykiho": ykiho})

    def hospital_list(self, sido_cd: str = "", cl_cd: str = "") -> list[dict]:
        """기관 목록. `ykiho`와 좌표의 출처 — 15001698 활용신청 전에는 403."""
        return self._call(SVC_HOSP, OP_HOSP_LIST, {"sidoCd": sido_cd, "clCd": cl_cd})


#: 조인 대상 종별코드. 응급의료기관은 대부분 병원급이다.
#: (보건의료원·보건지소는 여기 없어서 안 붙는다 — 매칭 실패가 아니라 조회 범위 문제다)
JOIN_CL_CODES = ("01", "11", "21")  # 상급종합 · 종합병원 · 병원

#: 같은 병원으로 볼 최대 거리. `send_to_hub.py`의 Supabase 대응표 검증과 같은 잣대다
JOIN_MAX_KM = 1.2

#: 네트워크 오류 재시도. 518회를 도는 동안 일시적 실패는 일어나는 게 정상이고,
#: 한 번의 타임아웃으로 전체가 죽으면 그때까지 받은 것이 전부 사라진다
RETRIES = 3


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    rad = math.radians
    inner = (
        math.sin(rad(lat2 - lat1) / 2) ** 2
        + math.cos(rad(lat1)) * math.cos(rad(lat2)) * math.sin(rad(lon2 - lon1) / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(inner))


def _with_retry(call, label: str):
    """일시적 네트워크 오류만 재시도한다. 권한 오류는 재시도해도 소용없으니 즉시 올린다."""
    for attempt in range(RETRIES):
        try:
            return call()
        except HiraNotApprovedError:
            raise
        except Exception as exc:  # noqa: BLE001
            if attempt == RETRIES - 1:
                raise HiraApiError(f"{label}: {type(exc).__name__}") from exc
            time.sleep(2 * (attempt + 1))
    return None


def build_join(
    day: str | None = None,
    max_km: float = JOIN_MAX_KM,
    client: HiraClient | None = None,
) -> dict[str, dict]:
    """E-Gen 병원 ↔ 심평원 요양기관을 좌표 최근접으로 붙여 캐시한다.

    두 기관이 같은 병원에 다른 번호를 붙여놨고 서로 연결표가 없어서(`hpid` ↔ `ykiho`)
    좌표로 붙일 수밖에 없다. 실측에서 533곳 중 518곳(97.2%)이 1.2km 이내였고 오차
    중앙값은 11m였다. 기관명 정규화만으로는 92.7%다 — 같은 병원인데 표기가 달라
    놓치는 것들이 있어서다(`의료법인대산의료재단익산병원` ↔ `익산병원`).
    """
    client = client or HiraClient()

    rows: list[dict] = []
    for code in JOIN_CL_CODES:
        got = _with_retry(lambda c=code: client.hospital_list(cl_cd=c), f"목록 clCd={code}")
        print(f"  심평원 clCd={code}: {len(got)}건", flush=True)
        rows.extend(got)

    points = [
        (float(row["YPos"]), float(row["XPos"]), row)
        for row in rows
        if row.get("XPos") and row.get("YPos")
    ]
    if not points:
        raise HiraApiError("심평원 목록에 좌표가 없다")

    hospitals = D.load_hospitals(D.snapshot_files(day=day))
    if not hospitals:
        raise HiraApiError("E-Gen 스냅샷이 없다 — snapshot_nationwide.bat이 도는지 확인할 것")

    matches: dict[str, dict] = {}
    distances: list[float] = []
    for hospital in hospitals.values():
        if not (hospital.lat and hospital.lon):
            continue
        best = min(
            points, key=lambda p: haversine_km(hospital.lat, hospital.lon, p[0], p[1])
        )
        distance = haversine_km(hospital.lat, hospital.lon, best[0], best[1])
        distances.append(distance)
        if distance > max_km:
            continue
        matches[hospital.hpid] = {
            "hpid": hospital.hpid,
            "egenName": hospital.name,
            "emcls": hospital.emcls,
            "ykiho": best[2]["ykiho"],
            "hiraName": best[2].get("yadmNm"),
            "clCdNm": best[2].get("clCdNm"),
            "drTotCnt": best[2].get("drTotCnt"),
            "distanceKm": round(distance, 4),
        }

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    JOIN_PATH.write_text(
        json.dumps(matches, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    distances.sort()
    median = distances[len(distances) // 2] if distances else 0.0
    print(
        f"  조인 {len(matches)}/{len(distances)}곳 ({len(matches) / max(1, len(distances)):.1%}), "
        f"오차 중앙값 {median * 1000:.0f}m → {JOIN_PATH.name}",
        flush=True,
    )
    return matches


def fetch_specialists(
    matches: dict[str, dict] | None = None, client: HiraClient | None = None
) -> dict[str, list[dict]]:
    """조인된 병원의 전문과목별 전문의 수를 받아 캐시한다.

    이미 받아둔 곳은 건너뛴다(이어받기). 중간에 죽어도 거기까지는 남도록 25곳마다 쓴다.
    """
    client = client or HiraClient(timeout=30.0)
    if matches is None:
        if not JOIN_PATH.exists():
            raise HiraApiError(f"{JOIN_PATH.name}이 없다 — --build-join을 먼저 돌릴 것")
        matches = json.loads(JOIN_PATH.read_text(encoding="utf-8"))

    specialists: dict[str, list[dict]] = {}
    if SPECIALISTS_PATH.exists():
        specialists = json.loads(SPECIALISTS_PATH.read_text(encoding="utf-8"))
        print(f"  기존 캐시 {len(specialists)}곳 이어받기", flush=True)

    todo = [(hpid, row) for hpid, row in matches.items() if hpid not in specialists]
    print(f"  전문의 수 조회 대상 {len(todo)}곳", flush=True)

    failed: list[str] = []
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for index, (hpid, row) in enumerate(todo, 1):
        try:
            specialists[hpid] = _with_retry(
                lambda y=row["ykiho"]: client.detail_op("specialists", y), hpid
            )
        except HiraApiError:
            failed.append(hpid)
        if index % 25 == 0:
            SPECIALISTS_PATH.write_text(
                json.dumps(specialists, ensure_ascii=False), encoding="utf-8"
            )
            print(f"    {index}/{len(todo)} …", flush=True)

    SPECIALISTS_PATH.write_text(
        json.dumps(specialists, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    have = sum(1 for rows in specialists.values() if rows)
    print(
        f"  전문의 수 {len(specialists)}곳 저장 (응답 있는 곳 {have}곳, 실패 {len(failed)}건)"
        f" → {SPECIALISTS_PATH.name}",
        flush=True,
    )
    return specialists


def probe(ykiho: str) -> None:
    """오퍼레이션 11종의 응답 필드를 눈으로 확인한다.

    필드를 추측해서 코드를 쓰지 않기 위한 단계다. E-Gen 때 `hv11`을 소아 병상으로
    가정했다가 소아 병상이 내내 미상이었던 일이 있었고, 그건 실응답을 늦게 본 탓이었다.
    """
    client = HiraClient()
    for key, operation in OPS.items():
        print(f"\n=== {OP_LABELS[key]} ({operation})")
        try:
            rows = client.detail_op(key, ykiho)
        except HiraApiError as exc:
            print(f"  실패: {exc}")
            continue
        print(f"  {len(rows)}건")
        for row in rows[:3]:
            print("  ---")
            for field, value in row.items():
                print(f"    {field:18} = {str(value)[:60]}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="심평원 병원정보 / 의료기관별상세정보")
    parser.add_argument(
        "--build-join", action="store_true", help="E-Gen ↔ 심평원 조인 + 전문의 수 수집"
    )
    parser.add_argument("--day", default=None, help="조인에 쓸 스냅샷 날짜 (예: 2026-08-12)")
    parser.add_argument("--max-km", type=float, default=JOIN_MAX_KM, help="같은 병원으로 볼 최대 거리")
    parser.add_argument("--skip-specialists", action="store_true", help="조인만 하고 멈춘다")
    parser.add_argument("--probe", action="store_true", help="오퍼레이션 11종 응답 필드 확인")
    parser.add_argument("--ykiho", default="", help="암호화요양기호 (probe에 필요)")
    args = parser.parse_args()

    if args.build_join:
        shared = HiraClient(timeout=30.0)
        print("=== E-Gen ↔ 심평원 조인 ===")
        joined = build_join(day=args.day, max_km=args.max_km, client=shared)
        if not args.skip_specialists:
            print("=== 전문과목별 전문의 수 ===")
            fetch_specialists(joined, client=shared)
        print("\n이제 scoring이 심평원 근거를 읽는다: python -m hospital_score.scoring --check --validate")
    elif args.probe:
        if not args.ykiho:
            raise SystemExit(
                "--ykiho 가 필요하다. --build-join을 먼저 돌리면 "
                f"{JOIN_PATH.name}에서 골라 쓸 수 있다"
            )
        probe(args.ykiho)
    else:
        parser.print_help()
