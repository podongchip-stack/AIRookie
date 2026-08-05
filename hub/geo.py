"""GPS 거리 계산과 존(Zone) 분류/확장 판단. 순수 규칙 기반, 상태를 갖지 않는다."""
import math

ZONE_BAND_KM = 5.0  # 존 하나의 폭(km). zone 1 = 0~5km, zone 2 = 5~10km, ...
REJECT_RATIO_THRESHOLD = 0.5  # 활성 존 내 명시적 거절 비율이 이 값 이상이면 다음 존까지 확장


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """두 GPS 좌표 사이의 대권 거리(km)."""
    earth_radius_km = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * earth_radius_km * math.asin(math.sqrt(a))


def zone_of(distance_km: float) -> int:
    """거리를 존 번호로 변환한다 (1부터 시작, ZONE_BAND_KM 간격)."""
    return int(distance_km // ZONE_BAND_KM) + 1


def active_zones(max_zone: int) -> list[int]:
    """1번 존부터 max_zone까지의 활성화된 존 번호 목록."""
    return list(range(1, max_zone + 1))


def should_expand_zone(reject_ratio: float, threshold: float = REJECT_RATIO_THRESHOLD) -> bool:
    """시간 기반 타임아웃이 아닌, 명시적 거절 비율 기준으로 존을 확장한다 (CLAUDE.md 원칙)."""
    return reject_ratio >= threshold
