"""폐기 판정의 근거를 다시 계산한다 — 병상 예측 · 미상 추정.

왜 이 파일이 필요한가
--------------------
`README.md`와 `CLAUDE.md`는 두 트랙을 "만들기 전에 숫자로 접었다"고 적어두고
그 근거로 `P(만실 전환) = 0.618%`와 `관측 4,215칸 중 97.0%가 가능`을 인용한다.
그런데 **그 두 숫자를 계산하는 코드가 저장소에 없었다.** 관측치(미상률·방치
병원·조인율·신선도)는 `report.py`로 전부 재현되는데, 정작 "그래서 안 만들기로
했다"는 판정만 재현 경로가 없는 상태였다.

이 문서들이 스스로 내건 기준("숫자는 전부 코드와 대조해 확인했다")을 그 두
항목이 못 지키고 있었다는 뜻이다. 결론이 틀렸다는 증거는 없지만, 검증할 수 없는
숫자를 근거로 인용하는 것과 검증할 수 있는 숫자를 인용하는 것은 다르다.
그래서 결론을 고치는 대신 **근거를 되살린다.**

원래 숫자와 어긋날 수 있다
--------------------------
스냅샷은 계속 쌓이므로 오늘 돌린 값은 2026-08-12 당시 값과 다르다. 그건 오류가
아니라 정상이다. 중요한 것은 **결론의 방향이 유지되는가**이지 소수점이 같은지가
아니다. 판정 기준(사전 등록한 2%, 상수 기준선 우위)을 함께 출력해 그 자리에서
판단할 수 있게 했다.

실행 (API 호출 0회 — 이미 쌓인 스냅샷만 읽는다)

    python -m hospital_score.discarded
    python -m hospital_score.discarded --seoul-only      # 10분 주기 (원 분석과 같은 조건)
    python -m hospital_score.discarded --nationwide-only # 20분 주기
    python -m hospital_score.discarded --day 2026-08-12
"""

from __future__ import annotations

import argparse
import math
import sys
from collections import Counter, defaultdict

from . import dataset as D
from . import vocabulary as V

#: Windows 기본 콘솔은 cp949라 em dash 하나에도 UnicodeEncodeError로 죽는다.
#: `report.py`가 실제로 그렇게 죽어서, 문서에 적힌 재현 명령이 기본 환경에서
#: 실패했다. 출력이 곧 근거인 파일이므로 여기서 먼저 막는다.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

#: 병상 예측 트랙을 접은 사전 등록 기준. 이 값을 넘지 못하면 예측의 최대 이득이
#: 모델 오차보다 작다고 보고 만들지 않기로 **미리** 정해둔 값이다.
#: 결과를 보고 기준을 옮기면 그건 검증이 아니라 사후 정당화가 된다.
DROP_THRESHOLD = 0.02

#: 두 관측을 "연속"으로 볼 최대 간격의 배수. 수집이 끊긴 구간(실측 최대 501분)을
#: 그대로 이으면 "10분 뒤 만실이 됐다"가 아니라 "8시간 뒤"가 섞여 확률이 부풀거나
#: 꺼진다. 주기 중앙값의 이 배수까지만 한 쌍으로 인정한다.
GAP_TOLERANCE = 2.0

#: 등급 표기 순서 (report.py와 동일)
EMCLS_ORDER = [
    "권역응급의료센터",
    "지역응급의료센터",
    "지역응급의료기관",
    "응급실운영신고기관",
]


def _emcls_key(name: str | None) -> str:
    return name if name in EMCLS_ORDER else "(등급미상)"


def _sorted_emcls(keys) -> list[str]:
    known = [e for e in EMCLS_ORDER if e in keys]
    return known + sorted(k for k in keys if k not in EMCLS_ORDER)


# --- 구간 추정 ---------------------------------------------------------------


def wald_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wald 구간. 원 문서가 인용한 `95% CI 0.41~0.82%`가 이 방식이라 같이 낸다."""
    if n == 0:
        return 0.0, 0.0
    p = k / n
    half = z * math.sqrt(p * (1 - p) / n)
    return max(0.0, p - half), min(1.0, p + half)


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson 구간.

    비율이 0에 가까울 때 Wald는 하한이 음수로 내려가거나 폭이 실제보다 좁게 나온다.
    `P(만실 전환)`은 1%도 안 되는 값이라 이쪽이 더 맞다. 원 숫자와 대조할 수 있게
    Wald도 같이 내되, 판단은 이 값으로 하는 편이 낫다.
    """
    if n == 0:
        return 0.0, 0.0
    p = k / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, center - half), min(1.0, center + half)


# --- ① 병상 예측 -------------------------------------------------------------


def bed_transitions(frames: list[D.Frame], gap_tolerance: float = GAP_TOLERANCE) -> dict:
    """연속한 두 관측 사이에서 응급실 병상(`hvec`)이 어떻게 움직이는지 센다.

    세는 단위는 **(병원, 연속한 관측 한 쌍)**이다. "지금 자리가 있는 병원이 다음
    관측에서 자리가 없어지는가"가 질문이므로, 분모는 **직전 관측에서 병상이
    1 이상이었던 쌍**이다.

    세 가지를 구분한다.
      - `== 0`  확인된 만실
      - `<= 0`  만실 + 과밀(정원 초과 수용). 실제로 못 가는 것은 이쪽이다
      - 미상    직전이든 이번이든 `-1`이면 전이를 판정할 수 없다

    미상이 끼면 그 병원의 연속성을 끊는다(직전 상태를 버린다). 미상을 건너뛰고
    그 앞뒤를 이으면 실제로는 40분 떨어진 두 관측이 "연속한 한 쌍"이 되어,
    간격 필터를 우회해버린다.
    """
    with_beds = [frame for frame in frames if frame.beds]
    if len(with_beds) < 2:
        return {"pairs": 0}

    gaps = sorted(
        (later.ts - earlier.ts).total_seconds() / 60
        for earlier, later in zip(with_beds, with_beds[1:])
    )
    cadence = gaps[len(gaps) // 2]
    max_gap = cadence * gap_tolerance

    previous: dict[str, tuple] = {}
    pairs = to_zero = to_nonpositive = unchanged = 0
    zero_pairs = zero_to_positive = 0
    dropped_gap = 0
    accepted_gaps: list[float] = []

    for frame in with_beds:
        for hpid, row in frame.beds.items():
            count = D.parse_bed_count(row.get("hvec"))
            if count is None:
                previous.pop(hpid, None)  # 연속성을 끊는다 (위 docstring 참고)
                continue

            before = previous.get(hpid)
            previous[hpid] = (frame.ts, count)
            if before is None:
                continue

            gap = (frame.ts - before[0]).total_seconds() / 60
            if gap <= 0 or gap > max_gap:
                dropped_gap += 1
                continue
            accepted_gaps.append(gap)

            if before[1] > 0:
                pairs += 1
                if count == 0:
                    to_zero += 1
                if count <= 0:
                    to_nonpositive += 1
                if count == before[1]:
                    unchanged += 1
            else:
                zero_pairs += 1
                if count > 0:
                    zero_to_positive += 1

    accepted_gaps.sort()
    return {
        "cadence_min": cadence,
        "max_gap_min": max_gap,
        "median_gap_min": accepted_gaps[len(accepted_gaps) // 2] if accepted_gaps else 0.0,
        "frames": len(with_beds),
        "pairs": pairs,
        "to_zero": to_zero,
        "to_nonpositive": to_nonpositive,
        "unchanged": unchanged,
        "zero_pairs": zero_pairs,
        "zero_to_positive": zero_to_positive,
        "dropped_gap": dropped_gap,
    }


def section_bed_prediction(stats: dict) -> None:
    print("=" * 78)
    print("1. 병상 수 예측 — 값이 0까지 가는가")
    print("=" * 78)
    if not stats.get("pairs"):
        print("  연속한 관측이 부족해 전이를 셀 수 없다")
        return

    print(f"  수집 주기(중앙값)   : {stats['cadence_min']:.0f}분")
    print(f"  연속 인정 상한      : {stats['max_gap_min']:.0f}분 "
          f"(수집 중단 구간 {stats['dropped_gap']:,}쌍 제외)")
    print(f"  실제 예측 지평      : {stats['median_gap_min']:.0f}분 뒤")
    print(f"  관측 프레임         : {stats['frames']}개")
    print()

    n = stats["pairs"]
    print(f"  분모: 직전 관측에 병상이 1 이상이었던 (병원 x 구간) {n:,}쌍")
    print()
    print(f"  {'전이':<28}{'건수':>8}{'비율':>10}{'95% CI (Wilson)':>22}")
    for label, k in (
        ("만실로 전환 (== 0)", stats["to_zero"]),
        ("갈 수 없게 됨 (<= 0, 과밀 포함)", stats["to_nonpositive"]),
    ):
        p = k / n
        low, high = wilson_ci(k, n)
        print(f"  {label:<28}{k:>8,}{p:>9.3%}{f'{low:.3%} ~ {high:.3%}':>22}")

    # 원 문서가 인용한 값과 직접 대조할 수 있게 Wald도 같이 낸다
    k = stats["to_zero"]
    low, high = wald_ci(k, n)
    print(f"  {'(참고) Wald 구간':<28}{'':>8}{'':>9}{f'{low:.3%} ~ {high:.3%}':>22}")

    print()
    print(f"  값이 그대로인 쌍     : {stats['unchanged']:,} / {n:,} "
          f"({stats['unchanged'] / n:.1%})")
    if stats["zero_pairs"]:
        print(f"  0이었다가 자리가 생김: {stats['zero_to_positive']:,} / {stats['zero_pairs']:,} "
              f"({stats['zero_to_positive'] / stats['zero_pairs']:.1%})")

    p = stats["to_zero"] / n
    print()
    print(f"  사전 등록한 폐기 기준: {DROP_THRESHOLD:.0%}")
    if p < DROP_THRESHOLD:
        print(f"  -> 판정 유지. {p:.3%} < {DROP_THRESHOLD:.0%} 이므로 예측을 만들지 않는다.")
        print("     병상은 움직이지만 0까지 가는 일이 거의 없어, 맞혀서 얻는 최대 이득이")
        print("     모델 오차보다 작다.")
    else:
        print(f"  -> **판정 재검토 필요.** {p:.3%} >= {DROP_THRESHOLD:.0%} 로 기준을 넘었다.")


# --- ② 미상 추정 -------------------------------------------------------------


def label_distribution(
    frames: list[D.Frame], hospitals: dict[str, D.Hospital], all_frames: bool = False
) -> dict:
    """미상이 아닌 칸(= 자동 라벨이 되는 칸)이 어떻게 분포하는지 센다.

    기본은 **마지막 관측 한 장**이다. 여러 프레임을 합치면 같은 (병원, 항목)이
    관측 횟수만큼 중복돼 표본이 실제보다 커 보인다. `--all-frames`로 그 값도 볼 수
    있게 열어뒀다 — 문서가 인용한 `4,215칸`이 어느 집계 단위였는지 대조하기 위함이다.
    """
    targets = frames if all_frames else frames[-1:]

    total = Counter()
    by_grade = defaultdict(Counter)
    hospitals_seen: set[str] = set()

    for frame in targets:
        for hpid, values in frame.accept.items():
            hospitals_seen.add(hpid)
            grade = _emcls_key(hospitals[hpid].emcls if hpid in hospitals else None)
            for value in values.values():
                total[value] += 1
                by_grade[grade][value] += 1

    # 명부 기준 등급 분포 — 관측 칸이 어느 등급에 쏠렸는지 비교할 기준선
    roster = Counter(_emcls_key(h.emcls) for h in hospitals.values())

    return {
        "total": total,
        "by_grade": dict(by_grade),
        "roster": roster,
        "hospitals": len(hospitals_seen),
        "frames_used": len(targets),
    }


def section_unknown_estimation(stats: dict) -> None:
    print()
    print("=" * 78)
    print("2. 미상 칸 추정 — 상수 기준선을 이길 수 있는가")
    print("=" * 78)

    total = stats["total"]
    yes, no = total[V.ACCEPT_YES], total[V.ACCEPT_NO]
    observed = yes + no
    grand = sum(total.values())
    if not observed:
        print("  관측된(미상이 아닌) 칸이 없다")
        return

    print(f"  집계 단위: 관측 프레임 {stats['frames_used']}장, 병원 {stats['hospitals']}곳")
    print(f"  전체 {grand:,}칸 중 미상(정보미제공) {total[V.ACCEPT_UNKNOWN]:,}칸 "
          f"({total[V.ACCEPT_UNKNOWN] / grand:.1%})")
    print()
    print(f"  라벨이 되는 칸(미상 아님): {observed:,}칸")
    print(f"    {'가능':<10}{yes:>8,}{yes / observed:>10.1%}")
    print(f"    {'불가능':<10}{no:>8,}{no / observed:>10.1%}")

    baseline = yes / observed
    low, high = wilson_ci(yes, observed)
    print()
    print(f"  상수 기준선(\"전부 가능\"이라 답하기)의 정확도: {baseline:.1%} "
          f"(95% CI {low:.1%} ~ {high:.1%})")
    print(f"  모델이 이기려면 전국을 통틀어 오답 {observed - yes:,}칸 중 상당수를")
    print("  기준선보다 더 맞혀야 한다. 그 여지 자체가 작다.")

    # --- MNAR 근거: 라벨이 어느 등급에서 나왔는가 ---
    print()
    print("  라벨이 어디서 나오는가 (MNAR 근거)")
    print(f"  {'등급':<20}{'라벨 칸':>9}{'라벨 점유율':>12}{'명부 점유율':>12}{'과대표집':>10}{'가능률':>9}")

    roster = stats["roster"]
    roster_total = sum(roster.values())
    for grade in _sorted_emcls(stats["by_grade"]):
        counter = stats["by_grade"][grade]
        labeled = counter[V.ACCEPT_YES] + counter[V.ACCEPT_NO]
        if not labeled:
            continue
        label_share = labeled / observed
        roster_share = roster.get(grade, 0) / roster_total if roster_total else 0.0
        ratio = label_share / roster_share if roster_share else float("inf")
        yes_rate = counter[V.ACCEPT_YES] / labeled
        print(f"  {grade:<20}{labeled:>9,}{label_share:>12.1%}{roster_share:>12.1%}"
              f"{ratio:>9.1f}x{yes_rate:>9.1%}")

    print()
    print("  '과대표집'이 1보다 크면 그 등급이 명부에서 차지하는 비중보다 라벨을 더 많이")
    print("  내놓았다는 뜻이다. 라벨이 상위 등급에 쏠려 있으면(MNAR), 그 분포로 배운 모델을")
    print("  미신고 병원(주로 하위 등급)에 그대로 적용할 수 없다.")
    print("  적용하면 '미신고 병원도 대부분 수용 가능'이라는 위험한 방향의 오류가 난다 —")
    print("  받을 수 없는 병원을 후보 상위로 올리는 쪽이라, 뺑뺑이 방지 목적과 정반대다.")


# --- 실행 --------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="폐기 판정(병상 예측 · 미상 추정)의 근거를 다시 계산한다"
    )
    parser.add_argument("--day", default=None, help="특정 날짜만 (예: 2026-08-12)")
    parser.add_argument("--seoul-only", action="store_true", help="서울 수집분만 (10분 주기)")
    parser.add_argument("--nationwide-only", action="store_true", help="전국 수집분만 (20분 주기)")
    parser.add_argument(
        "--all-frames",
        action="store_true",
        help="라벨 분포를 마지막 관측 1장이 아니라 전 프레임 누적으로 센다 (중복 포함)",
    )
    parser.add_argument(
        "--gap-tolerance",
        type=float,
        default=GAP_TOLERANCE,
        help=f"연속으로 인정할 최대 간격 = 주기 x 이 값 (기본 {GAP_TOLERANCE})",
    )
    args = parser.parse_args()

    paths = D.snapshot_files(
        seoul=not args.nationwide_only,
        nationwide=not args.seoul_only,
        day=args.day,
    )
    if not paths:
        raise SystemExit("읽을 스냅샷 파일이 없다")

    print(f"읽는 파일 {len(paths)}개: " +
          ", ".join(f"{p.parent.name}/{p.name}" for p in paths[:6]) +
          (" ..." if len(paths) > 6 else ""))
    print()

    hospitals = D.load_hospitals(paths)
    frames = D.load_frames(paths)
    if not frames:
        raise SystemExit("관측 프레임이 없다")

    section_bed_prediction(bed_transitions(frames, args.gap_tolerance))
    section_unknown_estimation(label_distribution(frames, hospitals, args.all_frames))

    print()
    print("=" * 78)
    print("두 판정 모두 '만들기 전에 접은' 것이다. 위 숫자가 기준을 넘으면 그때 다시 연다.")
    print("=" * 78)


if __name__ == "__main__":
    main()
