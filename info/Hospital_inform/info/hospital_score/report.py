"""신뢰도 진단 리포트 — 신고 데이터가 어디서 어떻게 비어 있는지 보여준다.

이 트랙의 전제는 "E-Gen이 주는 값은 병원의 **신고**이고, 신고에는 구멍이 있다"는
것이다. 그 구멍을 말이 아니라 숫자로 내놓는 게 이 파일의 일이다. 모델보다 먼저
만드는 이유는 병상 트랙을 `P(만실 전환)` 숫자 하나로 접었던 것과 같다 — 눈에 보이는
산출물이 빨리 나와야 방향이 맞는지 판정된다.

손계산이 아니라 스크립트 출력이어야 하는 이유도 같다. 발표에서 인용할 숫자는
언제든 재현 가능해야 하고, 스냅샷이 쌓이면 같은 명령으로 다시 뽑을 수 있어야 한다.

실행 (API 호출 0회 — 이미 쌓인 스냅샷만 읽는다)
패키지 상대 import를 쓰므로 `info/Hospital_inform/info`에서 `-m`으로 부른다.

    python -m hospital_score.report                 # 전국+서울 전체 기간
    python -m hospital_score.report --day 2026-08-12
    python -m hospital_score.report --seoul-only
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from . import dataset as D
from . import hira_files as HF
from . import vocabulary as V

#: Windows 기본 콘솔은 cp949라 아래 출력에 쓰인 em dash 하나에 UnicodeEncodeError로
#: 죽는다. 문서 여러 곳이 이 파일을 "재현 명령"으로 내세우는데, 정작 기본 환경에서는
#: 첫 섹션도 못 넘기고 실패했다 — 재현 가능성이 이 파일의 존재 이유이므로
#: 출력 인코딩을 맨 먼저 고정한다.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

#: 등급 표기 순서. 역량 순이라 표가 읽기 쉬워진다
EMCLS_ORDER = [
    "권역응급의료센터",
    "지역응급의료센터",
    "지역응급의료기관",
    "응급실운영신고기관",
]

#: 이 시간을 넘게 갱신이 없으면 "실시간"이라 부를 수 없다고 본다.
#: 근거(표본을 밝혀둔다 — 두 값이 문서마다 달라 보이는 이유다): 서울 55곳 실측에서
#: `hvidate` 갱신 간격 중앙값 3.5분, 50곳이 10분 이내. 전국 443곳으로 넓히면
#: 중앙값 5분, 88.7%가 10분 이내다(`scoring.py`의 같은 상수 주석).
#: 어느 표본이든 하루는 그 분포에서 한참 벗어난 값이라 판정 기준으로 안전하다
STALE_THRESHOLD = timedelta(days=1)

#: 두 관측을 "연속"으로 볼 최대 간격의 배수. `discarded.py`와 같은 값이며 이유도 같다 —
#: 수집이 끊긴 구간을 그대로 이으면 관측하지 않은 시간이 지속시간에 섞인다.
#: 실제로 2026-08-16 ~ 09-05 3주가 비어 있어, 이 필터가 없으면 "3주 연속 과밀"이
#: 최장 기록으로 올라온다
GAP_TOLERANCE = 2.0


def _emcls_key(name: str | None) -> str:
    return name if name in EMCLS_ORDER else "(등급미상)"


def _sorted_emcls(keys) -> list[str]:
    known = [e for e in EMCLS_ORDER if e in keys]
    return known + sorted(k for k in keys if k not in EMCLS_ORDER)


def section_coverage(frames: list[D.Frame], hospitals: dict[str, D.Hospital]) -> None:
    print("=" * 78)
    print("1. 수집 현황")
    print("=" * 78)
    if not frames:
        print("  스냅샷이 없다. snapshot.bat이 도는지 확인할 것")
        return
    first, last = frames[0].ts, frames[-1].ts
    span = last - first
    print(f"  기간      : {first:%Y-%m-%d %H:%M} ~ {last:%Y-%m-%d %H:%M}  ({span})")
    print(f"  관측 시각 : {len(frames)}개")
    print(f"  병원 명부 : {len(hospitals)}곳")

    by_emcls = Counter(_emcls_key(h.emcls) for h in hospitals.values())
    beds_reported = {hpid for f in frames for hpid in f.beds}
    accept_reported = {hpid for f in frames for hpid in f.accept}
    print()
    print(f"  {'등급':<20}{'명부':>6}{'병상API':>9}{'중증질환API':>12}")
    for emcls in _sorted_emcls(by_emcls):
        members = [h.hpid for h in hospitals.values() if _emcls_key(h.emcls) == emcls]
        in_beds = sum(1 for hpid in members if hpid in beds_reported)
        in_accept = sum(1 for hpid in members if hpid in accept_reported)
        print(f"  {emcls:<20}{len(members):>6}{in_beds:>9}{in_accept:>12}")
    print()
    print("  명부에는 있는데 병상API에 안 나오는 병원이 있다 — 등급이 낮을수록 심하다.")
    print("  이 병원들은 '병상이 0'이 아니라 '애초에 응답에 등장하지 않는다'.")


def section_staleness(frames: list[D.Frame], hospitals: dict[str, D.Hospital]) -> None:
    """`hvidate`(병원이 마지막으로 입력한 시각)가 얼마나 묵었는지."""
    print()
    print("=" * 78)
    print("2. 피드 신선도 — 실시간이라 부를 수 있는가")
    print("=" * 78)
    if not frames:
        return
    last = frames[-1]
    now = last.ts.replace(tzinfo=None)

    ages: dict[str, timedelta] = {}
    for hpid, row in last.beds.items():
        updated = D.parse_hvidate(row.get("hvidate"))
        if updated is not None:
            ages[hpid] = now - updated

    if not ages:
        print("  hvidate를 읽을 수 있는 병원이 없다")
        return

    ordered = sorted(ages.values())
    median = ordered[len(ordered) // 2]
    within_10min = sum(1 for a in ordered if a <= timedelta(minutes=10))
    stale = {hpid: age for hpid, age in ages.items() if age > STALE_THRESHOLD}

    print(f"  기준 시각      : {now:%Y-%m-%d %H:%M}")
    print(f"  갱신 경과 중앙값: {_fmt_age(median)}")
    print(f"  10분 이내 갱신 : {within_10min}/{len(ages)}곳 ({within_10min / len(ages):.1%})")
    print(f"  하루 넘게 방치 : {len(stale)}곳")

    if stale:
        print()
        print(f"  {'마지막 갱신':<12}{'경과':>10}  {'병상(hvec)':>10}  {'등급':<18}병원")
        for hpid, age in sorted(stale.items(), key=lambda kv: -kv[1]):
            row = last.beds[hpid]
            updated = D.parse_hvidate(row.get("hvidate"))
            beds = D.parse_bed_count(row.get("hvec"))
            hospital = hospitals.get(hpid)
            name = hospital.name if hospital else hpid
            emcls = _emcls_key(hospital.emcls if hospital else None)
            beds_text = "미상" if beds is None else str(beds)
            print(
                f"  {updated:%Y-%m-%d}  {_fmt_age(age):>10}  {beds_text:>10}  {emcls:<18}{name}"
            )
        print()
        print("  이 값들이 지금도 '실시간 가용병상'으로 나간다. mapper.py는 hvidate를")
        print("  updatedAt으로 옮기기만 하고 오래됐다고 거르지 않는다 — hub가 병상 수로")
        print("  순위를 매기기 시작하면 방치된 병원이 상위로 올라온다.")

    # 병상 상위권이 신선한 값인지 — 순위와 신선도를 붙여 봐야 문제가 드러난다
    ranked = [
        (D.parse_bed_count(row.get("hvec")), hpid)
        for hpid, row in last.beds.items()
        if D.parse_bed_count(row.get("hvec")) is not None
    ]
    ranked.sort(reverse=True)
    print()
    print("  가용병상(hvec) 상위 10곳의 신선도:")
    for beds, hpid in ranked[:10]:
        hospital = hospitals.get(hpid)
        name = hospital.name if hospital else hpid
        age = ages.get(hpid)
        flag = "  ← 방치" if age and age > STALE_THRESHOLD else ""
        print(f"    {beds:>4}병상  {_fmt_age(age) if age else '?':>10}  {name}{flag}")


def overcrowding_runs(
    frames: list[D.Frame], gap_tolerance: float = GAP_TOLERANCE
) -> dict:
    """`hvec`가 음수(과밀)로 연속 관측된 구간을 병원별로 잘라낸다.

    `snapshot.py`가 스냅샷의 용도로 선언한 세 가지 중 "과밀 추세 — hvec가 음수인
    병원이 얼마나 오래 그 상태로 있는지"가 이 함수다. 나머지 둘(병상 추정 ·
    입력 성실도)과 달리 **시계열이 아니면 계산할 수 없다** — 한 시점만 보면
    지금 과밀인지는 알아도 그게 10분째인지 이틀째인지 구분되지 않는다.

    과밀의 정의
    ----------
    `-1`은 미입력이고 `-2` 이하가 과밀(정원 초과 수용)이다(`mapper.py`와 같은
    규약). `parse_bed_count()`가 `-1`을 이미 `None`으로 돌려주므로, 여기서는
    "값이 있고 음수"면 과밀이다.

    구간을 끊는 세 가지
    ------------------
    - **미상** : 직전이 `-1`이면 그 사이 과밀이 이어졌는지 알 수 없다. `discarded.py`가
      전이를 셀 때 미상에서 연속성을 끊는 것과 같은 이유로, 미상을 건너뛰고 앞뒤를
      잇지 않는다. 이으면 관측하지 않은 구간을 과밀로 셈해 지속시간이 부풀어 오른다
    - **수집 중단** : 08-16 ~ 09-05처럼 3주가 비어 있는 구간이 실제로 있다. 이걸 그대로
      이으면 "3주 연속 과밀"이라는 가짜 기록이 나온다. 주기 중앙값의 `gap_tolerance`
      배까지만 한 쌍으로 인정한다(`discarded.py`와 같은 상수)
    - **정상 복귀** : `hvec >= 0`이 관측되면 그 지점에서 구간이 닫힌다

    절단(censoring)을 구분한다
    -------------------------
    구간의 양 끝이 모두 관측으로 막혀 있어야(앞에 정상값, 뒤에 정상값) 지속시간을
    "이만큼이었다"고 말할 수 있다. 한쪽이라도 수집 중단·미상·관측 종료로 끝났으면
    **하한만 아는 것**이다. 이 구분을 안 하면 오래 가는 과밀일수록 관측 끝에 걸릴
    확률이 높다는 편향(length bias)이 그대로 중앙값에 섞인다.

    완결 구간이라도 지속시간은 여전히 **과소추정**이다. 과밀이 시작된 실제 시각은
    직전 정상 관측과 첫 과밀 관측 사이 어딘가이고, 끝난 시각도 마찬가지다. 따라서
    참값은 `[관측된 span, span + 2 x 주기]` 안에 있다.
    """
    with_beds = [frame for frame in frames if frame.beds]
    if len(with_beds) < 2:
        return {"frames": len(with_beds)}

    gaps = sorted(
        (later.ts - earlier.ts).total_seconds() / 60
        for earlier, later in zip(with_beds, with_beds[1:])
    )
    cadence = gaps[len(gaps) // 2]
    max_gap = cadence * gap_tolerance

    #: 열려 있는 과밀 구간. hpid -> [시작ts, 마지막ts, 최저hvec, 관측수, 좌측막힘]
    open_runs: dict[str, list] = {}
    last_seen: dict[str, datetime] = {}
    closed: list[dict] = []

    cells_total = cells_over = 0
    ever: set[str] = set()
    depth_counter: Counter = Counter()

    def close(hpid: str, reason: str) -> None:
        """구간을 닫는다. `reason`은 오른쪽 끝이 무엇으로 막혔는지다.

        절단 사유를 남기지 않으면 "완결 233 / 절단 664"를 봤을 때 수집 설계가
        나쁜 건지 데이터가 원래 그런 건지 구분할 수 없다. 사유별로 나눠야
        "우리가 놓친 것"과 "E-Gen이 안 준 것"이 갈린다.
        """
        run = open_runs.pop(hpid, None)
        if run is None:
            return
        start, last, depth, n_obs, left_bounded = run
        closed.append({
            "hpid": hpid,
            "start": start,
            "end": last,
            "span": last - start,
            "depth": depth,
            "n_obs": n_obs,
            "complete": left_bounded and reason == "recovered",
            "reason": reason if left_bounded else "left_open",
        })

    for frame in with_beds:
        for hpid, row in frame.beds.items():
            count = D.parse_bed_count(row.get("hvec"))
            previous = last_seen.get(hpid)

            if count is None:
                close(hpid, "unknown")  # 미상 — 이후를 알 수 없다
                last_seen.pop(hpid, None)
                continue

            cells_total += 1
            if previous is None:
                bounded = False
            else:
                gap = (frame.ts - previous).total_seconds() / 60
                bounded = 0 < gap <= max_gap
                if not bounded:
                    close(hpid, "gap")  # 수집이 끊겼거나 병원이 응답에서 빠졌다
            last_seen[hpid] = frame.ts

            if count < 0:
                cells_over += 1
                ever.add(hpid)
                depth_counter[count] += 1
                run = open_runs.get(hpid)
                if run is None:
                    open_runs[hpid] = [frame.ts, frame.ts, count, 1, bounded]
                else:
                    run[1] = frame.ts
                    run[2] = min(run[2], count)
                    run[3] += 1
            else:
                close(hpid, "recovered")

    for hpid in list(open_runs):
        close(hpid, "still_open")  # 관측이 끝날 때까지 과밀이었다

    last_frame = with_beds[-1]
    now_over = {
        hpid: D.parse_bed_count(row.get("hvec"))
        for hpid, row in last_frame.beds.items()
        if (D.parse_bed_count(row.get("hvec")) or 0) < 0
    }

    return {
        "frames": len(with_beds),
        "cadence_min": cadence,
        "max_gap_min": max_gap,
        "cells_total": cells_total,
        "cells_over": cells_over,
        "ever": ever,
        "depth": depth_counter,
        "runs": closed,
        "now_over": now_over,
        "last_ts": last_frame.ts,
    }


def section_overcrowding(frames: list[D.Frame], hospitals: dict[str, D.Hospital]) -> None:
    """과밀(hvec 음수)이 얼마나 오래 지속되는지 — 시계열이어야만 나오는 값."""
    print()
    print("=" * 78)
    print("3. 응급실 과밀 지속시간 — 음수는 얼마나 오래 음수인가")
    print("=" * 78)

    stats = overcrowding_runs(frames)
    if stats.get("frames", 0) < 2:
        print("  관측이 2개 미만이라 지속시간을 볼 수 없다")
        return

    cells_total, cells_over = stats["cells_total"], stats["cells_over"]
    if not cells_over:
        print(f"  관측 {cells_total:,}칸에 과밀(hvec <= -2)이 하나도 없다")
        return

    print(f"  수집 주기(중앙값): {stats['cadence_min']:.0f}분   "
          f"연속 인정 상한: {stats['max_gap_min']:.0f}분")
    print(f"  병상값이 있는 관측 {cells_total:,}칸 중 과밀 "
          f"{cells_over:,}칸 ({cells_over / cells_total:.2%})")
    print(f"  한 번이라도 과밀이었던 병원: {len(stats['ever'])}곳")
    print(f"  마지막 관측({stats['last_ts']:%m-%d %H:%M}) 시점에 과밀: "
          f"{len(stats['now_over'])}곳")

    runs = stats["runs"]
    complete = [r for r in runs if r["complete"]]
    censored = [r for r in runs if not r["complete"]]

    print()
    print(f"  과밀 구간 {len(runs)}개 — 완결 {len(complete)}개 / 절단 {len(censored)}개")
    print("    완결 = 앞뒤로 정상값(hvec >= 0)이 관측돼 시작과 끝이 모두 막힌 구간")
    print("    절단 = 한쪽이라도 막히지 않은 구간. 지속시간은 하한만 안다")

    reasons = Counter(r["reason"] for r in censored)
    labels = {
        "left_open": "앞이 안 막힘 (구간 도중에 관측이 시작됨)",
        "gap": "수집 끊김 / 병원이 병상API 응답에서 빠짐",
        "unknown": "hvec가 -1(미입력)로 바뀜",
        "still_open": "관측 마지막까지 과밀 상태",
        "recovered": "(완결 조건 미충족)",
    }
    for reason, n in reasons.most_common():
        print(f"      {n:>4}개  {labels.get(reason, reason)}")

    if complete:
        spans = sorted((r["span"] for r in complete), key=lambda d: d.total_seconds())
        median = spans[len(spans) // 2]
        longest = spans[-1]
        single = sum(1 for r in complete if r["n_obs"] == 1)
        print()
        print(f"  완결 구간 지속시간  중앙값 {_fmt_age(median):>6}   최대 {_fmt_age(longest):>6}")
        print(f"    한 번만 관측되고 끝난 구간: {single}/{len(complete)}개 "
              f"(지속시간이 0으로 기록된다)")
        print(f"    참값은 [관측값, 관측값 + {stats['cadence_min'] * 2:.0f}분] 안에 있다 —")
        print("    과밀이 시작·종료된 실제 시각은 관측 사이 어딘가라 항상 과소추정이다.")

    longest_any = sorted(runs, key=lambda r: -r["span"].total_seconds())[:10]
    print()
    print(f"  가장 오래 이어진 과밀 10건:")
    print(f"    {'지속':>8} {'관측':>5} {'최저':>6}  {'상태':<5}{'등급':<18}병원")
    for run in longest_any:
        hospital = hospitals.get(run["hpid"])
        name = hospital.name if hospital else run["hpid"]
        emcls = _emcls_key(hospital.emcls if hospital else None)
        mark = "완결" if run["complete"] else "절단"
        print(f"    {_fmt_age(run['span']):>8} {run['n_obs']:>5} {run['depth']:>6}  "
              f"{mark:<5}{emcls:<18}{name}")

    depth = stats["depth"]
    worst = min(depth) if depth else 0
    print()
    print(f"  과밀 깊이(정원 초과 인원): 최저 {worst}   관측된 값 "
          + ", ".join(f"{v}({n:,}회)" for v, n in sorted(depth.items())[:8])
          + (" …" if len(depth) > 8 else ""))
    print()
    print(f"  → 이 {cells_over:,}칸은 hub로 나갈 때 전부 `0`이 된다. mapper.py의")
    print("     clamp_available()이 스키마 제약(음수 불가) 때문에 음수를 0으로 낮추기")
    print(f"     때문이다. 즉 정원을 {abs(worst)}명 초과한 병원과 딱 만실인 병원이")
    print("     dashboard에서 같은 '0병상'으로 보인다. 미상과 만실은 bedCountUnknown으로")
    print("     구분해왔지만, 만실과 과밀은 구분되지 않는다.")


def section_accept(frames: list[D.Frame], hospitals: dict[str, D.Hospital]) -> None:
    """중증질환 수용가능 신고가 등급별·항목별로 얼마나 비어 있는지."""
    print()
    print("=" * 78)
    print("4. 중증질환 수용가능 신고 — 미상이 어디에 몰려 있나")
    print("=" * 78)
    if not frames:
        return
    last = frames[-1]

    by_emcls: dict[str, Counter] = defaultdict(Counter)
    by_item: dict[int, Counter] = defaultdict(Counter)
    for hpid, values in last.accept.items():
        emcls = _emcls_key(hospitals[hpid].emcls if hpid in hospitals else None)
        for no, value in values.items():
            by_emcls[emcls][value] += 1
            by_item[no][value] += 1

    total = Counter()
    for counter in by_emcls.values():
        total.update(counter)
    grand = sum(total.values())
    if not grand:
        print("  수용가능 응답이 없다")
        return

    print(f"  전체 {grand:,}칸 (병원 {len(last.accept)}곳 × {len(V.ITEMS)}항목)")
    print(
        f"    가능 {total[V.ACCEPT_YES] / grand:6.1%}   "
        f"불가능 {total[V.ACCEPT_NO] / grand:6.1%}   "
        f"정보미제공 {total[V.ACCEPT_UNKNOWN] / grand:6.1%}"
    )
    print()
    print(f"  {'등급':<20}{'병원':>5}{'가능':>8}{'불가능':>9}{'정보미제공':>12}")
    for emcls in _sorted_emcls(by_emcls):
        counter = by_emcls[emcls]
        n = sum(counter.values())
        members = sum(
            1
            for hpid in last.accept
            if _emcls_key(hospitals[hpid].emcls if hpid in hospitals else None) == emcls
        )
        print(
            f"  {emcls:<20}{members:>5}"
            f"{counter[V.ACCEPT_YES] / n:>8.1%}"
            f"{counter[V.ACCEPT_NO] / n:>9.1%}"
            f"{counter[V.ACCEPT_UNKNOWN] / n:>12.1%}"
        )

    print()
    print("  미상률이 높은 항목 10개:")
    ranked = sorted(
        by_item.items(),
        key=lambda kv: -kv[1][V.ACCEPT_UNKNOWN] / max(1, sum(kv[1].values())),
    )
    for no, counter in ranked[:10]:
        n = sum(counter.values())
        item = V.BY_NO[no]
        print(f"    {counter[V.ACCEPT_UNKNOWN] / n:6.1%}  {item.field:<13}{item.full_label}")


def section_pediatric_msg(frames: list[D.Frame]) -> None:
    """소아 항목에만 있는 Msg(연령·체중 조건)가 미상을 얼마나 메워주는지."""
    print()
    print("=" * 78)
    print("5. 소아 항목의 조건 메시지 — 미상을 메울 재료가 되나")
    print("=" * 78)
    if not frames:
        return
    last = frames[-1]

    filled = Counter()
    contradiction = 0
    for hpid, values in last.accept.items():
        messages = last.accept_msg.get(hpid, {})
        for no in sorted(V.MSG_ITEMS):
            value = values.get(no)
            if value is None:
                continue
            text = messages.get(no, "")
            filled[(value, bool(text))] += 1
            if value == V.ACCEPT_UNKNOWN and text.strip() == V.ACCEPT_NO:
                contradiction += 1

    unknown_total = filled[(V.ACCEPT_UNKNOWN, True)] + filled[(V.ACCEPT_UNKNOWN, False)]
    if not unknown_total:
        print("  소아 항목 관측이 없다")
        return
    print(f"  대상: {len(V.MSG_ITEMS)}개 소아 항목 ({', '.join(V.BY_NO[n].field for n in sorted(V.MSG_ITEMS))})")
    print(f"  '정보미제공'인 칸 {unknown_total:,}개 중 조건 메시지가 있는 칸: "
          f"{filled[(V.ACCEPT_UNKNOWN, True)]:,}개 "
          f"({filled[(V.ACCEPT_UNKNOWN, True)] / unknown_total:.1%})")
    print(f"  그중 메시지가 '{V.ACCEPT_NO}'이라 사실상 거절인 칸: {contradiction:,}개")
    print()
    print("  → 미상을 메우는 재료로는 작다. 다만 값과 메시지가 어긋나는 칸이 존재한다는")
    print("     사실 자체가 '신고를 그대로 믿으면 안 된다'의 또 다른 실물 사례다.")


def section_volatility(frames: list[D.Frame]) -> None:
    """관측 사이에 신고가 실제로 움직이는지 — 움직이지 않으면 추정할 것도 없다."""
    print()
    print("=" * 78)
    print("6. 신고의 변동성 — 추정할 여지가 있는가")
    print("=" * 78)
    if len(frames) < 2:
        print("  관측이 2개 미만이라 변동을 볼 수 없다")
        return

    changes = Counter()
    intervals = 0
    for prev, curr in zip(frames, frames[1:]):
        if not prev.accept or not curr.accept:
            continue
        intervals += 1
        for hpid, values in curr.accept.items():
            before = prev.accept.get(hpid)
            if not before:
                continue
            for no, value in values.items():
                if no in before and before[no] != value:
                    changes[hpid] += 1

    total_changes = sum(changes.values())
    print(f"  비교 구간 {intervals}개, 상태 변경 {total_changes}회 "
          f"(병원 {len(changes)}곳에서 발생)")
    if changes:
        print("  변경이 잦은 병원 5곳: " + ", ".join(
            f"{hpid}({n}회)" for hpid, n in changes.most_common(5)
        ))
    print()
    print("  병상은 값이 움직여도 0까지 가는 일이 거의 없어 예측을 접었다")
    print("  (그 판정의 근거는 여기서 계산하지 않는다 — python -m hospital_score.discarded).")
    print("  수용가능 신고는 미상이 절반을 넘고 값도 움직인다 — 관측된 칸이 자동 라벨이")
    print("  되므로 사람이 정답을 쓸 필요가 없다.")


def section_specialty_crosscheck(
    frames: list[D.Frame], hospitals: dict[str, D.Hospital]
) -> None:
    """전문병원 지정(외부 근거)과 E-Gen 신고를 대조한다.

    같은 소스 안에서는 신고의 구멍을 검증할 수 없다. 전문병원 지정은 병원이 신고한
    값이 아니라 복지부가 지정한 것이라, 대조하면 "역량이 있는데 신고에는 안 보이는"
    병원이 드러난다.
    """
    print()
    print("=" * 78)
    print("7. 외부 근거 대조 — 전문병원 지정 ↔ E-Gen 신고")
    print("=" * 78)

    specialty = HF.load_specialty_hospitals()
    if specialty is None:
        print("  전문병원 지정 현황 캐시가 없다.")
        print("  python -m hospital_score.hira_files --fetch 로 먼저 받을 것")
        return
    if not frames:
        return
    last = frames[-1]

    by_name: dict[str, D.Hospital] = {}
    for hospital in hospitals.values():
        by_name.setdefault(HF.normalize_name(hospital.name), hospital)

    print(f"  전문병원 {len(specialty)}곳 · E-Gen 명부 {len(hospitals)}곳 (기관명으로 대조)")
    print()
    print(f"  {'지정분야':<12}{'지정':>4}{'명부매칭':>9}   신고 상태")

    unreported: list[tuple[str, str, str]] = []
    for field, item_nos in HF.FIELD_TO_MKIOSK.items():
        designated = [row for row in specialty if row.get("지정분야") == field]
        matched = [
            (row, by_name[HF.normalize_name(row.get("의료기관명"))])
            for row in designated
            if HF.normalize_name(row.get("의료기관명")) in by_name
        ]
        status = Counter()
        for _, hospital in matched:
            values = last.accept.get(hospital.hpid)
            if not values:
                # 명부에는 있지만 중증질환 응답에 아예 등장하지 않는다
                status["응답없음"] += 1
                continue
            observed = [values[no] for no in item_nos if no in values]
            if V.ACCEPT_YES in observed:
                status["가능"] += 1
            elif V.ACCEPT_NO in observed:
                status["불가능"] += 1
                unreported.append((field, hospital.name, "불가능"))
            else:
                status["정보미제공"] += 1
                unreported.append((field, hospital.name, "정보미제공"))
        summary = "  ".join(f"{k} {v}" for k, v in status.items()) or "-"
        print(f"  {field:<12}{len(designated):>4}{len(matched):>9}   {summary}")

    if unreported:
        print()
        print("  전문병원으로 지정됐는데 그 역량이 E-Gen 신고에 없는 곳:")
        for field, name, why in unreported:
            print(f"    [{why:5}] {field:<10}{name}")

    print()
    print("  지정은 '그 분야 전문성을 인증받았다'이지 '지금 받을 수 있다'가 아니다 —")
    print("  신고하지 않은 것 자체가 곧 오류는 아니다. 다만 E-Gen만 보는 매칭 엔진은")
    print("  이 병원들을 후보로 올리지 못한다.")
    print("  명부 매칭이 0인 분야는 대부분 응급의료기관이 아니어서다(안과·소아청소년과 등).")


def _fmt_age(age: timedelta) -> str:
    if age.days >= 1:
        return f"{age.days}일"
    hours = age.seconds // 3600
    if hours:
        return f"{hours}시간"
    return f"{max(0, age.seconds // 60)}분"


def main() -> None:
    parser = argparse.ArgumentParser(description="신고 데이터 신뢰도 진단 리포트")
    parser.add_argument("--day", default=None, help="특정 날짜만 (예: 2026-08-12)")
    parser.add_argument("--seoul-only", action="store_true", help="서울 수집분만")
    parser.add_argument("--nationwide-only", action="store_true", help="전국 수집분만")
    args = parser.parse_args()

    paths = D.snapshot_files(
        seoul=not args.nationwide_only,
        nationwide=not args.seoul_only,
        day=args.day,
    )
    if not paths:
        raise SystemExit("읽을 스냅샷 파일이 없다")

    # 서울/전국 파일이 같은 이름(날짜.jsonl)이라 폴더까지 붙여야 구분된다
    print(f"읽는 파일 {len(paths)}개: " +
          ", ".join(f"{p.parent.name}/{p.name}" for p in paths[:6]) +
          (" …" if len(paths) > 6 else ""))
    hospitals = D.load_hospitals(paths)
    frames = D.load_frames(paths)

    section_coverage(frames, hospitals)
    section_staleness(frames, hospitals)
    section_overcrowding(frames, hospitals)
    section_accept(frames, hospitals)
    section_pediatric_msg(frames)
    section_volatility(frames)
    section_specialty_crosscheck(frames, hospitals)


if __name__ == "__main__":
    main()
