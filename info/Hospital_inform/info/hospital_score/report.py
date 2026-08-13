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
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from . import dataset as D
from . import hira_files as HF
from . import vocabulary as V

#: 등급 표기 순서. 역량 순이라 표가 읽기 쉬워진다
EMCLS_ORDER = [
    "권역응급의료센터",
    "지역응급의료센터",
    "지역응급의료기관",
    "응급실운영신고기관",
]

#: 이 시간을 넘게 갱신이 없으면 "실시간"이라 부를 수 없다고 본다.
#: 근거: 실측한 `hvidate` 갱신 간격 중앙값이 3.5분이고 55곳 중 50곳이 10분 이내다.
#: 하루는 그 분포에서 한참 벗어난 값이라 판정 기준으로 안전하다
STALE_THRESHOLD = timedelta(days=1)


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


def section_accept(frames: list[D.Frame], hospitals: dict[str, D.Hospital]) -> None:
    """중증질환 수용가능 신고가 등급별·항목별로 얼마나 비어 있는지."""
    print()
    print("=" * 78)
    print("3. 중증질환 수용가능 신고 — 미상이 어디에 몰려 있나")
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
    print("4. 소아 항목의 조건 메시지 — 미상을 메울 재료가 되나")
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
    print("5. 신고의 변동성 — 추정할 여지가 있는가")
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
    print("  병상은 값이 움직여도 0까지 가는 일이 거의 없어(P(만실 전환) 0.618%) 예측을")
    print("  접었다. 수용가능 신고는 미상이 절반을 넘고 값도 움직인다 — 관측된 칸이")
    print("  자동 라벨이 되므로 사람이 정답을 쓸 필요가 없다.")


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
    print("6. 외부 근거 대조 — 전문병원 지정 ↔ E-Gen 신고")
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
    section_accept(frames, hospitals)
    section_pediatric_msg(frames)
    section_volatility(frames)
    section_specialty_crosscheck(frames, hospitals)


if __name__ == "__main__":
    main()
