"""카카오모빌리티 길찾기 API 호출부 — 도로 기준 도착 예상 시간(ETA)과 경로 좌표.

규칙 기반(source: "rule")이다: 외부 교통 데이터로 거리·시간을 계산할 뿐 AI 판단이 없다.
CLAUDE.md "모델/API 호출부와 비즈니스 로직은 분리" 원칙에 따라 HTTP 호출은 이 파일에만
두고, HubEngine은 결과(병원별 초·미터)만 받아 쓴다. 키가 없거나 호출이 실패해도 매칭은
그대로 진행돼야 하므로(뺑뺑이 방지가 목적 — 길찾기 실패로 병원이 빠지면 안 됨) 모든
실패는 예외 대신 "값 없음"으로 돌려준다. 지금은 표시용(etaMin·지도 경로)이며
finalScore(순위)에는 쓰지 않는다.

- 다중 목적지 길찾기(POST /v1/destinations/directions): 후보 병원 전체의 ETA를 한 번에.
  목적지 30곳·반경 10km 제한이 있어 30곳씩 나눠 부르고, 10km 밖은 값 없음으로 둔다.
- 자동차 길찾기(GET /v1/directions): 지도에 그릴 도로 경로 좌표(한 병원씩, 요청 시에만).

외부 전송 범위: 구급차·병원 좌표만 나간다(환자 정보는 없음). 다만 구급차 좌표는 사고
현장 근처라 On-Premise 원칙과 관련 있어 보고서에 명시할 것.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import requests

from schema import GpsPoint

_DESTINATIONS_URL = "https://apis-navi.kakaomobility.com/v1/destinations/directions"
_DIRECTIONS_URL = "https://apis-navi.kakaomobility.com/v1/directions"
_MAX_DESTINATIONS = 30        # 다중 목적지 API 한도
_MAX_RADIUS_M = 10000         # 다중 목적지 API 반경 한도
_TIMEOUT_SEC = 3.0            # 매칭 응답을 붙잡지 않도록 짧게
_CACHE_TTL_SEC = 300          # 같은 출발지·목적지는 5분간 재사용(교통 변화 대비 짧게)


def _load_key() -> str | None:
    """KAKAO_REST_API_KEY를 환경변수 → hub/.env 순으로 찾는다(hub는 dotenv를 쓰지 않음)."""
    key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    if key:
        return key
    env_file = Path(__file__).resolve().parent / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() == "KAKAO_REST_API_KEY":
                return value.strip().strip("'\"") or None
    return None


def _cache_key(origin: GpsPoint, dest: GpsPoint) -> tuple[float, float, float, float]:
    # 약 10m 단위로 반올림해 GPS 흔들림으로 캐시가 매번 빗나가지 않게 한다.
    return (round(origin.lat, 4), round(origin.lng, 4), round(dest.lat, 4), round(dest.lng, 4))


class KakaoRouting:
    def __init__(self, api_key: str) -> None:
        self._headers = {"Authorization": f"KakaoAK {api_key}"}
        self._eta_cache: dict[tuple, tuple[float, int, int]] = {}      # key -> (저장시각, 초, 미터)
        self._route_cache: dict[tuple, tuple[float, dict]] = {}

    @classmethod
    def from_env(cls) -> "KakaoRouting | None":
        key = _load_key()
        if not key:
            print("  [길찾기] KAKAO_REST_API_KEY 미설정 — ETA·도로 경로 없이 직선거리로만 동작")
            return None
        return cls(key)

    def _fresh(self, cache: dict, key: tuple):
        hit = cache.get(key)
        if hit and time.time() - hit[0] < _CACHE_TTL_SEC:
            return hit
        return None

    def etas(self, origin: GpsPoint, destinations: dict[str, GpsPoint]) -> dict[str, tuple[int, int]]:
        """병원ID -> (소요 초, 도로 거리 m). 못 구한 병원은 결과에서 빠진다."""
        result: dict[str, tuple[int, int]] = {}
        pending: list[tuple[str, GpsPoint]] = []
        for hid, dest in destinations.items():
            hit = self._fresh(self._eta_cache, _cache_key(origin, dest))
            if hit:
                result[hid] = (hit[1], hit[2])
            else:
                pending.append((hid, dest))

        for start in range(0, len(pending), _MAX_DESTINATIONS):
            chunk = pending[start:start + _MAX_DESTINATIONS]
            body = {
                "origin": {"x": origin.lng, "y": origin.lat},   # 카카오는 x=경도, y=위도
                "destinations": [{"key": hid, "x": d.lng, "y": d.lat} for hid, d in chunk],
                "radius": _MAX_RADIUS_M,
                "priority": "TIME",
            }
            try:
                response = requests.post(_DESTINATIONS_URL, json=body, headers=self._headers, timeout=_TIMEOUT_SEC)
                response.raise_for_status()
                routes = response.json().get("routes", [])
            except (requests.RequestException, ValueError) as e:
                print(f"  [길찾기] 다중 목적지 ETA 조회 실패 — 이번 사건은 ETA 없이 진행: {e}")
                continue
            by_id = dict(chunk)
            for route in routes:
                hid, summary = route.get("key"), route.get("summary")
                if route.get("result_code") != 0 or not summary or hid not in by_id:
                    continue  # 반경 10km 밖 등 — 이 병원만 값 없음
                duration, distance = int(summary["duration"]), int(summary["distance"])
                result[hid] = (duration, distance)
                self._eta_cache[_cache_key(origin, by_id[hid])] = (time.time(), duration, distance)
        return result

    def route(self, origin: GpsPoint, dest: GpsPoint) -> dict | None:
        """도로 경로: {"path": [[lat, lng], ...], "durationSec", "distanceM"} 또는 None."""
        key = _cache_key(origin, dest)
        hit = self._fresh(self._route_cache, key)
        if hit:
            return hit[1]
        params = {
            "origin": f"{origin.lng},{origin.lat}",
            "destination": f"{dest.lng},{dest.lat}",
            "priority": "TIME",
        }
        try:
            response = requests.get(_DIRECTIONS_URL, params=params, headers=self._headers, timeout=_TIMEOUT_SEC)
            response.raise_for_status()
            route = response.json()["routes"][0]
        except (requests.RequestException, ValueError, KeyError, IndexError) as e:
            print(f"  [길찾기] 도로 경로 조회 실패 — 직선으로 대체: {e}")
            return None
        if route.get("result_code") != 0:
            print(f"  [길찾기] 도로 경로 없음 — 직선으로 대체: {route.get('result_msg')}")
            return None
        path: list[list[float]] = []
        for section in route.get("sections", []):
            for road in section.get("roads", []):
                v = road.get("vertexes", [])
                path.extend([v[i + 1], v[i]] for i in range(0, len(v) - 1, 2))  # [x,y,...] -> [lat,lng]
        data = {
            "path": path,
            "durationSec": int(route["summary"]["duration"]),
            "distanceM": int(route["summary"]["distance"]),
        }
        self._route_cache[key] = (time.time(), data)
        return data
