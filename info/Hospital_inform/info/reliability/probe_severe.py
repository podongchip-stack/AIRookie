"""Phase 0 — 중증질환 수용가능(MKioskTy) 지표의 infosurv 확장 타당성 측정 CLI.

    python -m reliability.probe_severe                # 기본 경로(스냅샷 전체)
    python -m reliability.probe_severe --out <json>   # 수치 저장

infosurv를 병상(hvec) 하나에서 중증질환 수용가능 28항목으로 확장하기 전에,
그게 **성립할 수 있는 지표인지**를 스냅샷 축적본만으로(API 호출 0회) 먼저
판정하기 위한 측정이다. 병상과 달리 이 채널은 신고의 70.8%가 "정보미제공"
이고 값이 Y/불가능 이진이라, **값이 바뀌는 사건 자체가 희소해서 생존모델이
성립 안 될 가능성**이 있다 — 억지로 만들면 "미신고 병원도 대부분 가능" 류의
위험한 오류가 재현되므로(hospital_score의 폐기 판정과 같은 원칙), 이벤트가
부족하면 여기서 정직하게 접는다.

측정은 판정하지 않고 보고만 한다. 판정 기준은 infosurv `check` 모듈의 실측
임계(학습 이벤트 최소 2,000건 등 — check.py:45-48)와 대조해 사람이 내린다.

핵심 설계 갈림길 하나를 미리 양쪽 다 잰다 — `정보미제공`의 지위:
  · 해석 A (3상태): 정보미제공도 값이다 — "신고를 거뒀다/만료됐다"도 변화 사건
  · 해석 B (신고만): Y/불가능만 값, 정보미제공은 결측(관측 없음 취급)
어느 쪽으로 라벨을 설계하느냐에 따라 이벤트 수가 달라지므로 둘 다 보고한다.

claim-version 규칙은 병상 파이프라인과 동일: 값 변화 = 새 버전, 관측 공백
1시간 초과 = 세그먼트 분리(경계 간격은 수명으로 세지 않음), 과거 관측 무시.

⚠ 항목 번호·라벨은 hospital_score/vocabulary.py에서 복사했다(그 폴더를
import하지 않는 이 폴더의 원칙 때문 — hub가 15그룹을 복사해 쓰는 것과 같은
패턴). 어휘가 바뀌면 양쪽을 같이 고칠 것.
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .engine import _DEFAULT_SNAPSHOT_DIR
from .features import SEGMENT_GAP_SEC

SEVERE_OP = "getSrsillDissAceptncPosblInfoInqire"

ACCEPT_YES = "Y"
ACCEPT_NO = "불가능"
ACCEPT_UNKNOWN = "정보미제공"

#: infosurv check 모듈의 실측 임계 (check.py:45-48에서 옮겨 적음 — 대조용)
EVENT_MIN_TRAIN = 2000

#: hospital_score/vocabulary.py ITEMS에서 복사. 28번은 중증질환이 아니라
#: "응급실 운영 여부"(gatekeeper)라 별도 집계한다.
ITEM_LABELS: dict[int, str] = {
    1: "[재관류중재술] 심근경색", 2: "[재관류중재술] 뇌경색",
    3: "[뇌출혈수술] 거미막하출혈", 4: "[뇌출혈수술] 거미막하출혈 외",
    5: "[대동맥응급] 흉부", 6: "[대동맥응급] 복부",
    7: "[담낭담관질환] 담낭질환", 8: "[담낭담관질환] 담도포함질환",
    9: "[복부응급수술] 비외상", 10: "[장중첩/폐색] 영유아",
    11: "[응급내시경] 성인 위장관", 12: "[응급내시경] 영유아 위장관",
    13: "[응급내시경] 성인 기관지", 14: "[응급내시경] 영유아 기관지",
    15: "[저체중출생아] 집중치료", 16: "[산부인과응급] 분만",
    17: "[산부인과응급] 산과수술", 18: "[산부인과응급] 부인과수술",
    19: "[중증화상] 전문치료", 20: "[사지접합] 수족지접합",
    21: "[사지접합] 수족지접합 외", 22: "[응급투석] HD",
    23: "[응급투석] CRRT", 24: "[정신과적응급] 폐쇄병동입원",
    25: "[안과적수술] 응급", 26: "[영상의학혈관중재] 성인",
    27: "[영상의학혈관중재] 영유아", 28: "응급실(gatekeeper)",
}
GATEKEEPER_NO = 28


class Tracker:
    """해석 하나(A 또는 B)에 대한 (병원, 항목) 스트림 전체의 누적 통계."""

    def __init__(self, name: str) -> None:
        self.name = name
        # (hpid, no) -> (마지막 관측시각, 마지막 값, 현재 버전 탄생시각)
        self._state: dict[tuple[str, int], tuple[datetime, str, datetime]] = {}
        self.observations = 0
        self.versions = 0  # 탄생한 버전 수 (세그먼트 첫 버전 포함)
        self.events_by_item: Counter[int] = Counter()
        self.events_by_hpid: Counter[str] = Counter()
        self.transitions: Counter[tuple[str, str]] = Counter()
        self.lifetimes_sec: list[float] = []  # 완결된 버전 수명 (이벤트로 끝난 것만)
        self.changed_streams: set[tuple[str, int]] = set()

    def observe(self, hpid: str, no: int, ts: datetime, value: str) -> None:
        self.observations += 1
        key = (hpid, no)
        prev = self._state.get(key)
        if prev is None or (ts - prev[0]).total_seconds() > SEGMENT_GAP_SEC:
            self._state[key] = (ts, value, ts)
            self.versions += 1
            return
        last_obs, last_value, born = prev
        if ts <= last_obs:
            return
        if value != last_value:
            self.versions += 1
            self.events_by_item[no] += 1
            self.events_by_hpid[hpid] += 1
            self.transitions[(last_value, value)] += 1
            self.lifetimes_sec.append((ts - born).total_seconds())
            self.changed_streams.add(key)
            self._state[key] = (ts, value, ts)
        else:
            self._state[key] = (ts, last_value, born)

    @property
    def streams(self) -> int:
        return len(self._state)

    def events(self, include_gatekeeper: bool = False) -> int:
        return sum(
            n for no, n in self.events_by_item.items()
            if include_gatekeeper or no != GATEKEEPER_NO
        )


def _quantiles_h(values: list[float]) -> str:
    if not values:
        return "(없음)"
    qs = statistics.quantiles(values, n=4) if len(values) >= 4 else [values[0]] * 3
    return (
        f"중위 {statistics.median(values) / 3600:.1f}h "
        f"(p25 {qs[0] / 3600:.1f}h · p75 {qs[2] / 3600:.1f}h)"
    )


def report(tracker: Tracker, span_days: float) -> dict:
    ev = tracker.events()
    print(f"\n── 해석 {tracker.name} ──")
    print(f"  관측 {tracker.observations:,}건 · 스트림 {tracker.streams:,}개 · 버전 {tracker.versions:,}개")
    print(f"  변화 사건(28번 제외) {ev:,}건 = {ev / span_days:,.0f}건/일 · "
          f"값이 한 번이라도 바뀐 스트림 {len(tracker.changed_streams):,}개")
    print(f"  버전 수명(이벤트 완결분): {_quantiles_h(tracker.lifetimes_sec)}")

    print("  항목별 사건 상위:")
    for no, n in tracker.events_by_item.most_common(8):
        print(f"    {ITEM_LABELS[no]:<28s} {n:>8,}건")
    dead = [no for no in range(1, 28) if tracker.events_by_item[no] < 10]
    if dead:
        print(f"  사건 10건 미만 항목({len(dead)}개): {[ITEM_LABELS[n] for n in dead]}")

    total_ev = sum(tracker.events_by_hpid.values())
    top10 = sum(n for _, n in tracker.events_by_hpid.most_common(10))
    concentration = top10 / total_ev if total_ev else 0.0
    print(f"  사건의 병원 집중도: 상위 10곳이 {concentration:.1%} "
          f"(사건 있는 병원 {len(tracker.events_by_hpid):,}곳)")

    if tracker.transitions:
        print("  전이 분포:")
        for (a, b), n in tracker.transitions.most_common():
            print(f"    {a} → {b}: {n:,}건")

    gate = "통과" if ev >= EVENT_MIN_TRAIN else "미달"
    print(f"  [관문 대조] 학습 이벤트 최소 {EVENT_MIN_TRAIN:,}건: {ev:,}건 → {gate}")

    return {
        "observations": tracker.observations,
        "streams": tracker.streams,
        "versions": tracker.versions,
        "events_excl_gatekeeper": ev,
        "events_per_day": ev / span_days,
        "changed_streams": len(tracker.changed_streams),
        "lifetime_median_h": (
            statistics.median(tracker.lifetimes_sec) / 3600 if tracker.lifetimes_sec else None
        ),
        "events_by_item": {ITEM_LABELS[no]: n for no, n in tracker.events_by_item.most_common()},
        "top10_hospital_share": concentration,
        "transitions": {f"{a}→{b}": n for (a, b), n in tracker.transitions.most_common()},
        "gate_event_min_train": ev >= EVENT_MIN_TRAIN,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshots", type=Path, default=_DEFAULT_SNAPSHOT_DIR)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    tracker_a = Tracker("A (3상태 — 정보미제공도 값)")
    tracker_b = Tracker("B (신고만 — Y/불가능, 미제공은 결측)")
    value_counts: Counter[str] = Counter()
    polls = 0
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    hospitals: set[str] = set()

    for path in sorted(args.snapshots.glob("*.jsonl")):
        with path.open("rb") as f:
            for raw_line in f:
                try:
                    record = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                if record.get("operation") != SEVERE_OP or "error" in record:
                    continue
                try:
                    ts = datetime.fromisoformat(record["ts"]).astimezone(timezone.utc)
                except (KeyError, ValueError):
                    continue
                polls += 1
                first_ts = first_ts or ts
                last_ts = ts
                for item in record.get("items") or []:
                    hpid = (item.get("hpid") or "").strip()
                    if not hpid:
                        continue
                    hospitals.add(hpid)
                    for no in range(1, 29):
                        raw = item.get(f"MKioskTy{no}")
                        value = raw.strip() if isinstance(raw, str) else None
                        if value not in (ACCEPT_YES, ACCEPT_NO, ACCEPT_UNKNOWN):
                            if value:
                                value_counts["기타(어휘 밖)"] += 1
                            else:
                                value_counts["필드 없음"] += 1
                            continue
                        value_counts[value] += 1
                        tracker_a.observe(hpid, no, ts, value)
                        if value != ACCEPT_UNKNOWN:
                            tracker_b.observe(hpid, no, ts, value)

    if polls == 0 or first_ts is None:
        raise SystemExit(f"중증질환 응답을 하나도 못 읽었다: {args.snapshots}")
    span_days = max((last_ts - first_ts).total_seconds() / 86400, 1e-9)

    total_vals = sum(value_counts.values())
    print(f"중증질환 폴링 {polls:,}회 · 기간 {span_days:.1f}일 · 병원 {len(hospitals)}곳")
    print("값 분포 (전체 병원×항목×폴링):")
    for value, n in value_counts.most_common():
        print(f"  {value}: {n:,} ({n / total_vals:.1%})")

    result = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "snapshotDir": str(args.snapshots),
        "polls": polls,
        "spanDays": round(span_days, 2),
        "hospitals": len(hospitals),
        "valueCounts": dict(value_counts),
        "A_three_state": report(tracker_a, span_days),
        "B_declared_only": report(tracker_b, span_days),
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n수치 저장: {args.out}")


if __name__ == "__main__":
    main()
