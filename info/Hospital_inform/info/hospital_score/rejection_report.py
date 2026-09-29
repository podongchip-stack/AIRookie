"""거절 로그 확장 리포트 — 결정 시점 스냅샷·무응답 축까지 읽는 집계 CLI.

    python -m hospital_score.rejection_report                 # 전체
    python -m hospital_score.rejection_report --exclude-demo  # 실 로그만
    python -m hospital_score.rejection_report --only-demo     # 데모만

기존 `rejection.summarize()`(4축 집계·신고 오류 후보·Y 신고 거절률)에 더해,
hub가 2026-09-28~29에 페이로드에 확충한 필드들을 읽는다 — 수신구가 모르는
필드를 `extra`에 보존해 둔 덕에(관대 수신 원칙) 스키마 변경 없이 여기서
꺼내 쓰면 된다:

- **정보 무효의 독립 관측 후보**: 시스템이 병상 유효 확률을 높게(≥0.8) 봤는데
  BEDS_FULL로 거절된 건 — infosurv G2 라벨의 원형이자 "E-Gen 값이 틀렸다"의
  E-Gen 밖 증거
- **무응답 3분해**: 도달했는데 무응답(응답성 지표) / 미도달(보급 지표) /
  미결 종료 사건(요청 유효성 모호 — 통계에서 분리). 무응답은 수용성 판정에
  쓰지 않는다는 소비 지침(CLAUDE.md)의 집계 구현
- 데모 필터: `demo_rejections.py`가 심은 `demo: true` 마커로 데모/실 로그 분리
"""
from __future__ import annotations

import argparse
from collections import Counter

from . import rejection as R

#: 정보 무효 관측 후보로 볼 결정 시점 authority 하한
AUTHORITY_HIGH = 0.8


def _get(record: dict, key: str):
    """최상위 또는 extra(관대 수신으로 보존된 미등록 필드)에서 값을 찾는다."""
    if key in record and record[key] is not None:
        return record[key]
    return (record.get("extra") or {}).get(key)


def _is_demo(record: dict) -> bool:
    return bool(_get(record, "demo"))


def extended_report(records: list[dict]) -> str:
    lines: list[str] = []

    # ── 정보 무효의 독립 관측 후보 ──────────────────────────────────────
    invalidated = [
        r for r in records
        if r.get("reasonCode") == "BEDS_FULL"
        and isinstance(_get(r, "bedAuthorityAtRequest"), (int, float))
        and _get(r, "bedAuthorityAtRequest") >= AUTHORITY_HIGH
    ]
    lines.append("")
    lines.append(f"  정보 무효의 독립 관측 후보 (authority ≥ {AUTHORITY_HIGH:.0%}인데 만실 거절): "
                 f"{len(invalidated)}건")
    for r in invalidated[:8]:
        beds = _get(r, "availableBedCountAtRequest")
        lines.append(
            f"      {r['hospitalId']:<12}표시 병상 {beds}석 · "
            f"authority {_get(r, 'bedAuthorityAtRequest'):.0%} → BEDS_FULL "
            f"({r.get('diseaseGroup') or '?'})"
        )
    if invalidated:
        lines.append("      → E-Gen 밖에서 얻은 '값이 틀렸다'의 관측 — infosurv G2 라벨 재료")

    # ── 무응답 3분해 ────────────────────────────────────────────────────
    no_response = [r for r in records if r.get("reasonCode") == "NO_RESPONSE"]
    if no_response:
        finalized = [r for r in no_response if _get(r, "caseFinalized") is not False]
        unresolved = [r for r in no_response if _get(r, "caseFinalized") is False]
        reached = [r for r in finalized if _get(r, "reachedAtBroadcast") is True]
        unreached = [r for r in finalized if _get(r, "reachedAtBroadcast") is False]
        unknown = len(finalized) - len(reached) - len(unreached)
        lines.append("")
        lines.append(f"  무응답(NO_RESPONSE) {len(no_response)}건 — 거절과 다른 축, 수용성 판정에서 제외:")
        lines.append(f"      도달했는데 무응답 (응답성 지표)   {len(reached):>4}건"
                     + ("  ← 반복되면 전화 확인 우선 대상" if reached else ""))
        lines.append(f"      미도달 — 대시보드 미접속 (보급 지표) {len(unreached):>4}건  ← 병원 탓 아님")
        if unknown:
            lines.append(f"      도달 여부 미기록 (구버전 로그)     {unknown:>4}건")
        lines.append(f"      미결 종료 사건 (유효성 모호, 분리)   {len(unresolved):>4}건")

    # ── 병원×질환군: '가능' 신고였는데 거절 상위 ─────────────────────────
    declared_yes = Counter(
        (r["hospitalId"], r.get("diseaseGroup") or "?")
        for r in records
        if r.get("declaredAtRequest") == "Y" and r.get("reasonCode") != "NO_RESPONSE"
    )
    if declared_yes:
        lines.append("")
        lines.append("  '가능(Y)' 신고였는데 거절 — 병원×질환군 상위:")
        for (hospital_id, group), n in declared_yes.most_common(8):
            lines.append(f"      {hospital_id:<12}{group:<14}{n}회")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--exclude-demo", action="store_true", help="데모 마커 제외 (실 로그만)")
    group.add_argument("--only-demo", action="store_true", help="데모 마커만")
    args = parser.parse_args()

    records = R.load_all()
    demo_count = sum(1 for r in records if _is_demo(r))
    if args.exclude_demo:
        records = [r for r in records if not _is_demo(r)]
    elif args.only_demo:
        records = [r for r in records if _is_demo(r)]

    print(R.summarize(records))
    if records:
        print(extended_report(records))
    if demo_count and not args.only_demo and not args.exclude_demo:
        print(f"\n  ⚠ 데모 데이터 {demo_count}건 포함 — 실 통계는 --exclude-demo로 볼 것")


if __name__ == "__main__":
    main()
