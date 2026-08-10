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

⚠️ 실측 상태 (2026-08-10, 서울특별시 실응답 기준)
------------------------------------------------
서비스키 승인 후 실제 응답(가용병상 55건 · 중증질환 54건 · 목록 74건)으로 아래를
확인했다.

- [확인됨] `-1` = 미입력. `hv2`/`hv3`/`hv30`/`hvncc`에서 `-1`만 관측됨
- [확인됨] `-2` 이하 = **과밀(정원 초과 수용)**. `hvec`에서 `-24 ~ -2` 관측, `-1`은 없음.
  이 둘을 뭉개면 "환자가 24명 넘치는 병원"이 "모르는 병원"이 된다
- [확인됨] 필드 자체가 빠지는 것도 미입력의 표현이다 (`hv11`은 55건 중 31건만 등장)
- [확인됨] `hvidate` = `yyyyMMddHHmmss` (예: `20260810232018`)
- [확인됨] 중증질환 값은 `Y` / `불가능` / `정보미제공` 3종. `N`은 안 쓴다. `Y`에 뒤쪽
  공백이 붙어 온다(`'Y         '`)
- [확인됨] 필드 이름은 활용가이드 V4로 전부 대조했다. 더 이상 추정이 아니다.
  특히 소아 응급실 병상은 `hv11`이 아니라 **`hv28`**(소아)이고, `hv11`은
  인큐베이터 보유 여부(Y/N)다
- [확인됨] 총 병상보다 많은 가용 병상을 신고하는 병원이 있다(국립중앙의료원이 거의
  전 필드에 `12312` 같은 시험값을 넣어둠). `hvs38`을 상한으로 걸러낸다

고쳐야 할 곳은 아래 매핑표에 모여 있다 — 다른 코드는 손대지 않아도 되게.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from schema import HospitalInfo, Specialty, label_ko

KST = timezone(timedelta(hours=9))

#: E-Gen이 "병원이 입력하지 않음"을 나타내는 값. [확인됨]
#: 이 값**만** 미입력이다. `-2` 이하는 미입력이 아니라 과밀(정원 초과 수용)이다.
MISSING_SENTINEL = -1


# --- 매핑표 (실측 후 여기부터 교정한다) --------------------------------------

#: 중증질환 수용가능 필드 -> 표준 역량 코드. [확인됨 — 활용가이드 V4]
#: 항목은 `MKioskTy1` ~ `MKioskTy28`까지 있다. 어휘에 대응 코드가 있는 것만 매핑한다 —
#: 어휘를 작게 유지해야 voice 담당자가 외울 수 있다는 원칙(schema.py)을 지킨다.
MKIOSK_TO_CAPABILITY: dict[str, tuple[str, ...]] = {
    "MKioskTy1": ("PROC_PCI_EMERGENCY",),  # [재관류중재술] 심근경색
    "MKioskTy2": ("PROC_EVT_THROMBECTOMY",),  # [재관류중재술] 뇌경색
    "MKioskTy3": ("PROC_CRANIOTOMY",),  # [뇌출혈수술] 거미막하출혈
    "MKioskTy4": ("PROC_CRANIOTOMY",),  # [뇌출혈수술] 거미막하출혈 외
    "MKioskTy17": ("PROC_CESAREAN_EMERGENCY",),  # [산부인과응급] 산과수술
}
# `PROC_IV_THROMBOLYSIS`(tPA)에 대응하는 항목은 E-Gen에 없다. 뇌경색은 재관류중재술
# (MKioskTy2)로만 표현되며 정맥 혈전용해술은 따로 묻지 않는다 — 서류 OCR로만 채울 수 있다.

#: 장비 가용 여부(Y/N) -> 표준 역량 코드. [확인됨 — 활용가이드 V4]
#: 중증질환 응답과 달리 가용병상 응답에 같이 실려 온다.
EQUIPMENT_TO_CAPABILITY: dict[str, str] = {
    "hvctayn": "EQP_CT_24H",  # CT가용
    "hvangioayn": "EQP_ANGIO_SUITE",  # 혈관촬영기가용
}

#: 가용병상 필드 -> 표준 병상 코드. [확인됨 — 활용가이드 V4]
#: 어휘(schema.BED_CODES)의 6개 코드가 전부 여기서 채워진다.
BED_FIELD_MAP: dict[str, str] = {
    "hvec": "ER_ADULT",  # 일반
    "hv28": "ER_PEDIATRIC",  # 소아
    "hv29": "ER_NEGATIVE",  # 응급실 음압 격리 병상
    "hvicc": "ICU",  # [중환자실] 일반
    "hv34": "CCU",  # [중환자실] 심장내과
    "hvoc": "OR",  # [기타] 수술실
}
# 내과(`hv2`)·외과(`hv3`) 중환자실은 어휘에 코드가 없어 넣지 않는다. 예전에는 둘을 더해
# ICU로 썼는데, 어휘의 ICU는 "일반 중환자실"이고 그건 `hvicc`다. 서울 55곳 기준으로
# hvicc는 36곳, hv2/hv3는 22곳이 신고해 대상 병원도 hvicc 쪽이 넓다.
#
# `hv11`(인큐베이터)·`hv5`(CT)·`hv7`(혈관촬영기)·`hv10`(VENTI 소아)은 이름과 달리
# 병상 수가 아니라 Y/N로 온다. 예전에 `hv11`을 ER_PEDIATRIC으로 매핑해 두어 소아 병상이
# 늘 "미상"이었다 — 실제 소아 응급실 병상은 `hv28`이다.

#: 병원 총 병상 수(`hvs38`). 가용 병상이 이 값을 넘으면 입력 오류로 본다
TOTAL_BED_FIELD = "hvs38"

#: 중증질환 수용가능 값의 실제 어휘. [확인됨] 이 3종만 온다 — 명세의 `N`은 안 쓰인다.
ACCEPT_NO = {"불가능"}  # 명시적 불가
ACCEPT_UNKNOWN = {"정보미제공"}  # 미상

#: 역량 코드 -> 그 역량을 수행하는 진료과.
#: hub는 아직 `capabilities`를 안 읽고 진료과명을 임베딩으로 대조하므로, 같은
#: 근거에서 진료과도 함께 만들어줘야 매칭이 작동한다. "뇌경색 재관류가 가능하다"는
#: 곧 그 과의 역량이 있다는 뜻이라 추론 자체는 무리가 없다.
#: 장비 역량(EQP_*)은 진료과가 아니므로 여기 넣지 않는다 — 진료과 목록에 "CT"가
#: 끼면 hub의 임베딩 매칭이 흐려진다.
CAPABILITY_TO_DEPARTMENT: dict[str, str] = {
    "PROC_PCI_EMERGENCY": "순환기내과",
    "PROC_EVT_THROMBECTOMY": "신경과",
    "PROC_CRANIOTOMY": "신경외과",
    "PROC_CESAREAN_EMERGENCY": "산부인과",
}


# --- 값 정리 ----------------------------------------------------------------


def clean_count(raw: object) -> int | None:
    """병상 수를 정리한다. 미입력이면 `None`(미상)을 돌려준다.

    세 가지를 구분해야 한다.
      - `0` 이상  : 관측된 가용 병상 수. `0`은 확인된 만실이다
      - `-2` 이하 : 과밀. 정원보다 환자가 그만큼 많다는 뜻이며, 미입력이 아니라 관측값이다
      - `None`    : 병원이 입력을 안 함. 갈 수 있을지 알 수 없다

    과밀을 `None`으로 바꾸면 **가장 갈 수 없는 병원이 "모르는 병원"으로 남는다.**
    `Y` 같은 비수치 값도 `None`으로 본다 — 병상 수 자리에 플래그가 왔다면 매핑이
    틀렸다는 뜻이므로, 조용히 숫자로 바꾸지 않는다.
    """
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return None if value == MISSING_SENTINEL else value


def clamp_available(count: int) -> int:
    """과밀(음수)을 `0`으로 낮춘다. 스키마가 음수 병상 수를 막기 때문이다.

    `0`은 "확인된 만실"이므로 과밀을 0으로 두는 것 자체는 거짓이 아니다 — 지금
    갈 수 없다는 사실은 같고, 미상(`키 없음`)과도 여전히 구분된다. 다만 과밀의
    **정도**(-24인지 -2인지)는 여기서 사라지므로, 그 값이 필요하면 스냅샷 원본을 본다.
    """
    return max(count, 0)


def clean_flag(raw: object) -> bool | None:
    """수용가능 여부를 정리한다. 3상태(가능/불가/미상)를 유지한다.

    실응답 어휘는 `Y` / `불가능` / `정보미제공` 3종이다. [확인됨] "안 된다"와
    "모른다"를 뭉개면 hub가 근거를 설명할 수 없다. `Y`는 뒤에 공백이 붙어 오므로
    반드시 잘라내고 비교한다.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if text == "" or text in ACCEPT_UNKNOWN:
        return None
    if text in ACCEPT_NO:
        return False
    upper = text.upper()
    if upper == "Y":
        return True
    # 명세상 N, N1, N2 … 로 불가 사유가 세분화될 수 있다 (실응답에는 안 보였다)
    if upper.startswith("N"):
        return False
    return None


def parse_hvidate(raw: object) -> str | None:
    """E-Gen 입력일시(`hvidate`)를 ISO 8601 문자열로 바꾼다.

    형식은 `yyyyMMddHHmmss`다. [확인됨 — 실응답 예: `20260810232018`]
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


def total_bed_count(bed_row: dict) -> int | None:
    """병원 총 병상 수(`hvs38`). 가용 병상의 상한으로 쓴다."""
    return clean_count(bed_row.get(TOTAL_BED_FIELD))


def is_implausible(count: int, total: int | None) -> bool:
    """가용 병상이 그 병원의 총 병상보다 많으면 입력 오류로 본다.

    임의의 상한을 두는 대신 병원 자신이 신고한 총 병상과 비교한다. 서울 55곳 중
    한 곳(국립중앙의료원)이 거의 모든 필드에 `12312` 같은 시험값을 넣어두고 있어,
    그대로 두면 대시보드에 "중환자실 12,308석"이 뜬다.
    """
    return total is not None and count > total


def implausible_fields(bed_row: dict) -> list[str]:
    """입력 오류로 판단해 버린 병상 필드. 리포트용 — 무엇을 왜 버렸는지 남긴다."""
    total = total_bed_count(bed_row)
    dropped = []
    for field_name in BED_FIELD_MAP:
        count = clean_count(bed_row.get(field_name))
        if count is not None and is_implausible(count, total):
            dropped.append(f"{field_name}={count}")
    return dropped


def build_beds_by_type(bed_row: dict) -> dict[str, int]:
    """병상 종류별 가용 수를 만든다.

    미상인 종류는 **키 자체를 넣지 않는다.** `{"ER_ADULT": 0}`은 만실을 뜻하므로
    미상을 0으로 채우면 안 된다. 키가 없는 것이 "모른다"의 표현이다.
    입력 오류로 판단한 값도 마찬가지로 키를 넣지 않는다 — 틀린 값은 값이 아니다.
    """
    beds: dict[str, int] = {}
    total = total_bed_count(bed_row)

    for field_name, code in BED_FIELD_MAP.items():
        count = clean_count(bed_row.get(field_name))
        if count is None or is_implausible(count, total):
            continue
        beds[code] = clamp_available(count)

    return beds


def build_capabilities(severe_row: dict | None, bed_row: dict | None = None) -> list[str]:
    """표준 역량 코드 목록을 만든다.

    출처가 둘이다. 시술 역량은 중증질환 수용가능 응답(`MKioskTy*`)에서, 장비 역량은
    가용병상 응답(`hv*ayn`)에서 나온다. 수용가능이 `Y`인 것만 담는다 — 불가(`불가능`)와
    미상(`정보미제공`)은 둘 다 목록에서 빠진다.
    """
    codes: list[str] = []

    if severe_row:
        for field_name, mapped in MKIOSK_TO_CAPABILITY.items():
            if clean_flag(severe_row.get(field_name)) is True:
                codes.extend(mapped)

    if bed_row:
        for field_name, code in EQUIPMENT_TO_CAPABILITY.items():
            if clean_flag(bed_row.get(field_name)) is True:
                codes.append(code)

    return sorted(set(codes))


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
    overcrowded: list[str] = field(default_factory=list)
    implausible_beds: list[str] = field(default_factory=list)
    no_severe_illness_row: list[str] = field(default_factory=list)
    no_capability_reported: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"병원 {self.total}건 중 {self.mapped}건 변환 성공",
            f"  좌표 없어 제외      : {len(self.skipped_no_location)}건 {self.skipped_no_location}",
            f"  병상 수 미입력      : {len(self.bed_count_unknown)}건 {self.bed_count_unknown}",
            f"  응급실 과밀(정원 초과): {len(self.overcrowded)}건 {self.overcrowded}",
            f"  입력 오류로 버림    : {len(self.implausible_beds)}건 {self.implausible_beds}",
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

    capabilities = build_capabilities(severe_row, bed_row)
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

        er_count = clean_count(bed_row.get("hvec"))
        if er_count is None:
            report.bed_count_unknown.append(name)
        elif er_count < 0:
            # 과밀은 미입력이 아니라 관측된 값이다. 정도가 clamp_available()에서
            # 사라지므로 리포트에는 원래 값을 남긴다
            report.overcrowded.append(f"{name}({er_count})")

        dropped = implausible_fields(bed_row)
        if dropped:
            report.implausible_beds.append(f"{name}: {', '.join(dropped)}")

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
