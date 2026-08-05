"""E-Gen 원본 응답을 `HospitalInfo`(feature/hub 계약)로 변환한다.

feature/info의 본체다. 하는 일은 세 가지다.

1. **합치기** — E-Gen은 필요한 정보를 오퍼레이션 3개에 나눠서 준다.
   가용병상(병상 수) · 목록정보(좌표) · 중증질환 수용가능(시술 가능 여부)을
   기관코드(`hpid`)로 이어붙여야 병원 1건이 완성된다.

2. **결측 처리** — 여기가 진짜 일이다. E-Gen은 병원이 값을 입력하지 않으면
   `-1`을 보낸다. 이걸 그대로 넘기면 hub가 "병상이 마이너스 1개"로 읽는다.
   더 위험한 건 `0`으로 바꿔버리는 것이다. `0`은 "확인된 만실"이고 `-1`은
   "병원이 입력을 안 함"인데, 이 둘은 완전히 다른 의미다.

3. **표준 코드 만들기** — 중증질환 수용가능 여부(`MKioskTy*`)를 팀 합의 역량
   코드로 바꾼다. hub의 하드필터가 이 코드를 대조한다.

⚠️ 실측 전 주의
--------------
아래 `MKIOSK_TO_CAPABILITY` / `BED_FIELD_MAP` 은 **추정이 섞여 있다.** 서비스키가
승인되면 실제 응답을 받아 이 두 표부터 교정할 것. 이 파일에서 고쳐야 할 곳을
한군데로 모아둔 이유가 그것이다 — 다른 코드는 손대지 않아도 되게.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from schema import HospitalInfo, Specialty, label_ko

KST = timezone(timedelta(hours=9))

#: E-Gen이 "병원이 입력하지 않음"을 나타내는 값. [미확인] 실측으로 확인할 것
MISSING_SENTINEL = -1


# --- 매핑표 (실측 후 여기부터 교정한다) --------------------------------------

#: 중증질환 수용가능 필드 -> 표준 역량 코드.
#: 접두사가 `MKioskTy`인 것은 확인됐으나 **번호별 질환 매핑은 추정**이다.
MKIOSK_TO_CAPABILITY: dict[str, tuple[str, ...]] = {
    "MKioskTy1": ("PROC_PCI_EMERGENCY",),  # 재관류중재술(심근경색) [추정]
    "MKioskTy2": ("PROC_EVT_THROMBECTOMY",),  # 재관류중재술(뇌경색) [추정]
    "MKioskTy3": ("PROC_CRANIOTOMY",),  # 뇌출혈 수술 [추정]
    # MKioskTy10(응급투석 추정) 등 나머지 항목은 시연 시나리오에 필요 없어
    # 일부러 매핑하지 않는다. 어휘를 작게 유지해야 voice 담당자가 외울 수 있다.
}

#: 가용병상 필드 -> 표준 병상 코드.
BED_FIELD_MAP: dict[str, str] = {
    "hvec": "ER_ADULT",  # 응급실 [확인됨]
    "hvoc": "OR",  # 수술실 [확인됨]
    "hv11": "ER_PEDIATRIC",  # 소아 관련 [추정 — 시나리오 2가 여기 걸려 있다]
}

#: 여러 필드를 더해서 만드는 병상 코드. 내과·외과 중환자실을 ICU 하나로 합친다.
BED_FIELD_SUM: dict[str, tuple[str, ...]] = {
    "ICU": ("hv2", "hv3"),  # 내과중환자실 + 외과중환자실 [확인됨]
}

#: 역량 코드 -> 그 역량을 수행하는 진료과.
#: hub는 아직 `capabilities`를 안 읽고 진료과명을 임베딩으로 대조하므로, 같은
#: 근거에서 진료과도 함께 만들어줘야 매칭이 작동한다. "뇌경색 재관류가 가능하다"는
#: 곧 그 과의 역량이 있다는 뜻이라 추론 자체는 무리가 없다.
CAPABILITY_TO_DEPARTMENT: dict[str, str] = {
    "PROC_PCI_EMERGENCY": "순환기내과",
    "PROC_EVT_THROMBECTOMY": "신경과",
    "PROC_CRANIOTOMY": "신경외과",
}


# --- 값 정리 ----------------------------------------------------------------


def clean_count(raw: object) -> int | None:
    """병상 수를 정리한다. 미입력이면 `None`(미상)을 돌려준다.

    `0`과 `None`을 반드시 구분해야 한다.
      - `0`    : 확인된 만실. 갈 수 없다.
      - `None` : 병원이 입력을 안 함. 갈 수 있을지 알 수 없다.
    """
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return None if value <= MISSING_SENTINEL else value


def clean_flag(raw: object) -> bool | None:
    """수용가능 여부를 정리한다. 3상태(가능/불가/미상)를 유지한다.

    빈 문자열은 `False`가 아니라 `None`이다. "안 된다"와 "모른다"를 뭉개면
    hub가 근거를 설명할 수 없다.
    """
    if raw is None:
        return None
    text = str(raw).strip().upper()
    if text == "":
        return None
    if text == "Y":
        return True
    # N, N1, N2 … 불가 사유가 세분화돼 있을 수 있어 N으로 시작하면 전부 불가로 본다
    if text.startswith("N"):
        return False
    return None


def parse_hvidate(raw: object) -> str | None:
    """E-Gen 입력일시(`hvidate`)를 ISO 8601 문자열로 바꾼다.

    형식이 `yyyyMMddHHmmss`라고 보고 파싱한다. [미확인 — 실측으로 확인할 것]
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if len(text) != 14 or not text.isdigit():
        return None
    try:
        dt = datetime.strptime(text, "%Y%m%d%H%M%S").replace(tzinfo=KST)
    except ValueError:
        return None
    return dt.isoformat()


# --- 조각 만들기 ------------------------------------------------------------


def build_beds_by_type(bed_row: dict) -> dict[str, int]:
    """병상 종류별 가용 수를 만든다.

    미상인 종류는 **키 자체를 넣지 않는다.** `{"ER_ADULT": 0}`은 만실을 뜻하므로
    미상을 0으로 채우면 안 된다. 키가 없는 것이 "모른다"의 표현이다.
    """
    beds: dict[str, int] = {}

    for field_name, code in BED_FIELD_MAP.items():
        count = clean_count(bed_row.get(field_name))
        if count is not None:
            beds[code] = count

    for code, field_names in BED_FIELD_SUM.items():
        counts = [clean_count(bed_row.get(name)) for name in field_names]
        known = [c for c in counts if c is not None]
        if known:  # 하나라도 알면 그것만 더한다. 전부 미상이면 키를 넣지 않는다
            beds[code] = sum(known)

    return beds


def build_capabilities(severe_row: dict | None) -> list[str]:
    """중증질환 수용가능 정보에서 표준 역량 코드 목록을 만든다.

    수용가능이 `Y`인 것만 담는다. 불가(`N`)와 미상(빈 값)은 둘 다 목록에서
    빠지는데, 그 구분은 `capability_detail()`이 따로 돌려준다.
    """
    if not severe_row:
        return []
    codes: list[str] = []
    for field_name, mapped in MKIOSK_TO_CAPABILITY.items():
        if clean_flag(severe_row.get(field_name)) is True:
            codes.extend(mapped)
    return sorted(set(codes))


def capability_detail(severe_row: dict | None) -> dict[str, bool | None]:
    """역량별 3상태(가능/불가/미상)를 그대로 돌려준다. 품질 리포트와 검증용."""
    detail: dict[str, bool | None] = {}
    for field_name, mapped in MKIOSK_TO_CAPABILITY.items():
        state = clean_flag(severe_row.get(field_name)) if severe_row else None
        for code in mapped:
            detail[code] = state
    return detail


def build_specialties(capabilities: list[str]) -> list[Specialty]:
    """역량 코드에서 진료과 목록을 만든다.

    hub가 아직 `capabilities`를 안 읽고 진료과명을 임베딩으로 대조하기 때문에,
    같은 근거로 진료과도 채워줘야 매칭이 작동한다. `recentProcedureTags`에는
    역량의 한글 라벨을 넣는다 — hub의 임베딩이 이 텍스트도 참고한다.
    """
    by_dept: dict[str, list[str]] = {}
    for code in capabilities:
        dept = CAPABILITY_TO_DEPARTMENT.get(code)
        if dept:
            by_dept.setdefault(dept, []).append(label_ko(code))

    return [
        Specialty(
            department=dept,
            doctorCount=0,  # 공개 API에 인력 수가 없다. OCR 또는 병원 입력으로만 채울 수 있다
            recentProcedureTags=sorted(tags),
        )
        for dept, tags in sorted(by_dept.items())
    ]


# --- 변환 -------------------------------------------------------------------


@dataclass
class MappingReport:
    """변환 결과의 데이터 품질. 서비스키 승인 후 이 숫자가 OCR 필요성의 근거가 된다."""

    total: int = 0
    mapped: int = 0
    skipped_no_location: list[str] = field(default_factory=list)
    bed_count_unknown: list[str] = field(default_factory=list)
    no_severe_illness_row: list[str] = field(default_factory=list)
    no_capability_reported: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"병원 {self.total}건 중 {self.mapped}건 변환 성공",
            f"  좌표 없어 제외      : {len(self.skipped_no_location)}건 {self.skipped_no_location}",
            f"  병상 수 미입력      : {len(self.bed_count_unknown)}건 {self.bed_count_unknown}",
            f"  수용가능 응답 없음  : {len(self.no_severe_illness_row)}건 {self.no_severe_illness_row}",
            f"  수용가능 전부 미상/불가: {len(self.no_capability_reported)}건 {self.no_capability_reported}",
        ]
        return "\n".join(lines)


def map_hospital(
    bed_row: dict,
    location_row: dict | None,
    severe_row: dict | None,
    fallback_ts: str,
) -> HospitalInfo | None:
    """병원 1곳을 `HospitalInfo`로 변환한다. 좌표가 없으면 `None`을 돌려준다.

    좌표가 없으면 hub가 거리를 계산할 수 없어 후보에 넣는 의미가 없다. 조용히
    기본값을 넣는 대신 제외하고 리포트에 남긴다.
    """
    if not location_row:
        return None
    lat = location_row.get("wgs84Lat")
    lon = location_row.get("wgs84Lon")
    if lat is None or lon is None:
        return None

    capabilities = build_capabilities(severe_row)
    beds_by_type = build_beds_by_type(bed_row)
    er_beds = beds_by_type.get("ER_ADULT")

    return HospitalInfo(
        hospitalId=bed_row["hpid"],
        name=bed_row.get("dutyName") or location_row.get("dutyName", ""),
        gps={"lat": float(lat), "lng": float(lon)},
        # hub의 기존 필드는 정수여야 한다. 미상일 때 0을 넣는 것은 "확인된 만실"과
        # 같은 값이 되지만, 미상을 '가능'으로 취급하지 않는 보수적 선택이다.
        # 대신 bedsByType에 ER_ADULT 키를 넣지 않는 것으로 "미상"을 보존한다.
        availableBedCount=er_beds if er_beds is not None else 0,
        # 공개 API에 당직 전문의 정보가 없다. 중증질환 수용가능을 프록시로 쓴다 —
        # "재관류가 지금 가능하다"는 곧 해당 과 전문의가 대응 가능하다는 뜻이다.
        nightDutyAvailable=bool(capabilities),
        specialties=build_specialties(capabilities),
        updatedAt=parse_hvidate(bed_row.get("hvidate")) or fallback_ts,
        bedsByType=beds_by_type or None,
        capabilities=capabilities,
    )


def map_all(
    bed_rows: list[dict],
    location_rows: list[dict],
    severe_rows: list[dict],
    now: datetime | None = None,
) -> tuple[list[HospitalInfo], MappingReport]:
    """세 오퍼레이션의 응답을 합쳐 `HospitalInfo` 목록을 만든다.

    가용병상 응답을 기준으로 돈다. 거기 없는 기관은 지금 응급실을 운영하지
    않는다고 보고 아예 다루지 않는다.
    """
    fallback_ts = (now or datetime.now(KST)).isoformat()
    locations = {row["hpid"]: row for row in location_rows}
    severes = {row["hpid"]: row for row in severe_rows}

    report = MappingReport(total=len(bed_rows))
    hospitals: list[HospitalInfo] = []

    for bed_row in bed_rows:
        hpid = bed_row["hpid"]
        name = bed_row.get("dutyName", hpid)

        if clean_count(bed_row.get("hvec")) is None:
            report.bed_count_unknown.append(name)
        if hpid not in severes:
            report.no_severe_illness_row.append(name)

        info = map_hospital(bed_row, locations.get(hpid), severes.get(hpid), fallback_ts)
        if info is None:
            report.skipped_no_location.append(name)
            continue

        if not info.capabilities:
            report.no_capability_reported.append(name)

        hospitals.append(info)
        report.mapped += 1

    return hospitals, report
