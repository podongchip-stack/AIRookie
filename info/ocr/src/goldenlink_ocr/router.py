"""영역 라우팅 — 검출된 영역을 정리하고 어떤 인식 태스크로 보낼지 정한다. [규칙 기반]

AI를 쓰지 않는 결정론적 코드다. 어떤 영역이 왜 표 모드로 갔는지 설명 가능해야 하므로
임계값과 매핑을 전부 설정(configs/models.yaml)으로 노출한다.
"""

from __future__ import annotations

from .config import RouterConfig

# 영역 종류는 라우팅에만 쓰고 필터링에는 쓰지 않는다.
# DocLayout-YOLO는 학술 문서 위주로 학습돼 우리 문서에서는 분류가 어긋나는 경우가 있다:
#   - 워터마크가 깔린 증명서 본문 → figure 로 분류되지만 실제로는 핵심 필드값
#   - 발급일·문서번호 헤더 → abandon 으로 분류되지만 실제로는 필요한 데이터
# 잘못 분류된 영역을 버리면 정보가 통째로 사라지므로 전 영역을 인식 대상으로 삼는다.


def iou(a: tuple[int, ...], b: tuple[int, ...]) -> float:
    """두 박스의 교집합/합집합 비율."""
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter)


def deduplicate(regions: list[dict], iou_threshold: float) -> list[dict]:
    """겹치는 검출을 confidence 높은 쪽으로 정리한다.

    같은 영역이 table/figure 또는 title/plain text 로 이중 검출되는 일이 잦다.
    """
    kept: list[dict] = []
    for region in sorted(regions, key=lambda r: -r["conf"]):
        if any(iou(region["xyxy"], k["xyxy"]) >= iou_threshold for k in kept):
            continue
        kept.append(region)
    return kept


def sort_reading_order(regions: list[dict], row_height: int = 50) -> list[dict]:
    """위에서 아래로, 같은 높이대는 왼쪽에서 오른쪽으로 정렬한다.

    row_height 는 같은 줄로 볼 세로 허용 범위(픽셀)다.
    """
    return sorted(regions, key=lambda r: (r["xyxy"][1] // row_height, r["xyxy"][0]))


def plan_regions(regions: list[dict], config: RouterConfig) -> list[dict]:
    """검출 결과를 인식 계획으로 바꾼다.

    각 항목에 `task`(인식 프롬프트)를 붙여 반환한다.
    """
    ordered = sort_reading_order(deduplicate(regions, config.iou_threshold))
    return [
        {**region, "task": config.task_by_class.get(region["cls"], config.default_task)}
        for region in ordered
    ]
