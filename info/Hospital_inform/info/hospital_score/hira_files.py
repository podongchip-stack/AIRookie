"""심평원 파일데이터(odcloud API) — 신고와 대조할 외부 근거.

`hira.py`(apis.data.go.kr 계열)와 다른 경로다. data.go.kr의 **파일데이터** 일부는
활용신청하면 `api.odcloud.kr`로 감싼 REST API가 열린다. 인증키는 계정 공용이라
E-Gen·심평원과 같은 값(`HIRA_SERVICE_KEY`)을 그대로 쓴다.

왜 이쪽을 먼저 쓰는가
--------------------
`apis.data.go.kr`의 병원정보(15001698)·의료기관별상세(15001699)는 활용신청이
승인으로 표시되는데도 계속 `SERVICE_KEY_IS_NOT_REGISTERED`(403)가 나서 막혀 있다
(재신청까지 해봤고 같은 키가 같은 순간 E-Gen·odcloud에서는 정상 동작하므로 계정·키
문제는 아니다). 그 둘이 필요했던 이유는 `ykiho`로 기관을 잇기 위해서였는데,
**기관명 정규화만으로 조인이 실제로 됐다** — 화상 5곳 중 4곳, 뇌혈관 4곳 전부.
그래서 막힌 경로를 기다리지 않고 이쪽으로 간다.

전문병원 지정 현황 (15051054)
-----------------------------
분야별 전문병원 지정 목록 114건. 필드는 `구분 / 소재지 / 의료기관명 / 종별 / 지정분야`.
좌표도 요양기관기호도 없어서 **기관명으로만 붙일 수 있다.**

이 데이터가 중요한 이유: 전문병원 지정은 병원이 스스로 신고한 값이 아니라 **복지부가
지정한 것**이다. E-Gen의 중증질환 수용가능 신고와 대조하면 "역량이 있는데 신고에는
안 보이는" 병원이 드러난다.

⚠️ 지정은 "그 분야 전문성을 인증받았다"이지 "지금 응급 환자를 받을 수 있다"가 아니다.
신고하지 않은 것 자체가 곧 오류는 아니다. 다만 **E-Gen만 보는 매칭 엔진은 그 병원을
후보로 올리지 못한다**는 사실은 그대로 남는다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import unquote

ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "hira"

BASE_URL = "https://api.odcloud.kr/api"

#: 전문병원 지정 현황 (15051054). 연도별로 uddi가 따로 있고 최신본만 쓴다.
#: 나머지: 20210101, 20180101, 20150101, 20111101 — 추이를 보려면 그때 추가한다
SPECIALTY_PATH = "15051054/v1/uddi:c154ba0c-8afe-400f-aff3-8820a7f03848"
SPECIALTY_LABEL = "전문병원 지정 현황_20241231"
SPECIALTY_CACHE = CACHE_DIR / "specialty_hospitals.json"

#: 기관명 정규화에서 떼어낼 법인격 표기. 같은 병원이 소스마다 다르게 적혀 있다
#: (E-Gen "재단법인베스티안재단베스티안병원" ↔ 심평원 "재단법인 베스티안재단 베스티안병원")
NAME_NOISE = (
    "재단법인", "의료법인", "학교법인", "사회복지법인", "특수법인",
    "(재)", "(의)", "(학)", "(사)", "의료재단", "학원",
)

#: 전문병원 지정분야 -> 대조할 MKioskTy 항목 번호.
#: 대응이 분명한 것만 넣는다. "관절"·"척추"·"알코올"처럼 중증질환 28항목에 대응이
#: 없는 분야는 비워둔다 — 억지로 이으면 대조 결과가 오염된다
FIELD_TO_MKIOSK: dict[str, tuple[int, ...]] = {
    "화상": (19,),  # [중증화상] 전문치료
    "수지접합": (20, 21),  # [사지접합] 수족지접합 / 접합 외
    "뇌혈관": (2, 3, 4),  # 뇌경색 재관류 · 거미막하출혈 · 그 외
    "심장": (1,),  # [재관류중재술] 심근경색
    "안과": (25,),  # [안과적수술] 응급
    "산부인과": (16, 17, 18),  # 분만 · 산과수술 · 부인과수술
    "주산기": (15, 16),  # 저체중출생아 집중치료 · 분만
    "소아청소년과": (10, 12, 14),  # 영유아 장중첩 · 위장관/기관지 내시경
}


def normalize_name(name: str | None) -> str:
    """기관명을 조인 키로 쓸 수 있게 정규화한다 (공백·법인격 제거)."""
    text = "".join((name or "").split())
    for noise in NAME_NOISE:
        text = text.replace(noise, "")
    return text


def fetch_specialty_hospitals(service_key: str | None = None) -> list[dict]:
    """전문병원 지정 현황을 받아 캐시에 저장한다. 원본 필드를 그대로 둔다."""
    import requests

    if service_key is None:
        from dotenv import load_dotenv

        load_dotenv(ENV_PATH)
        service_key = os.environ.get("HIRA_SERVICE_KEY")
    if not service_key:
        raise RuntimeError(f"{ENV_PATH} 에 HIRA_SERVICE_KEY 가 없다")
    if "%" in service_key:
        service_key = unquote(service_key)

    rows: list[dict] = []
    page = 1
    while True:
        response = requests.get(
            f"{BASE_URL}/{SPECIALTY_PATH}",
            params={"page": page, "perPage": 100, "serviceKey": service_key},
            timeout=25,
        )
        response.raise_for_status()
        payload = response.json()
        rows.extend(payload.get("data", []))
        if len(rows) >= payload.get("totalCount", 0) or page >= 10:
            break
        page += 1

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    SPECIALTY_CACHE.write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return rows


def load_specialty_hospitals() -> list[dict] | None:
    """캐시된 전문병원 목록. 없으면 None — 리포트가 네트워크 없이 돌아야 해서다."""
    if not SPECIALTY_CACHE.exists():
        return None
    return json.loads(SPECIALTY_CACHE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="심평원 파일데이터(odcloud) 수집")
    parser.add_argument("--fetch", action="store_true", help="전문병원 지정 현황 받아 캐시")
    args = parser.parse_args()

    if args.fetch:
        fetched = fetch_specialty_hospitals()
        print(f"{SPECIALTY_LABEL}: {len(fetched)}건 → {SPECIALTY_CACHE}")
        fields = sorted({field for row in fetched for field in row.get("지정분야", "").split()})
        print(f"지정분야 {len(fields)}종: {', '.join(fields)}")
    else:
        parser.print_help()
