"""수집 로그 확인 — 언제 무엇을 받았는지 한눈에 본다(읽기 전용, 2026-10-04).

    python inspect_logs.py rejections [--date 2026-10-04] [-n 20]   거절·도착 결과 로그(hub → info 5003)
    python inspect_logs.py snapshots  [--date 2026-10-04] [-n 20] [--hpid A1100017]
                                                                    로컬 E-Gen 스냅샷(클라우드 동기화 결과)
    python inspect_logs.py cloud      [--date 2026-10-04] [-n 20]   Supabase 클라우드 수집기가 쌓은 원본(raw/)

날짜를 안 주면 오늘(KST). -n은 최근 몇 건을 볼지(기본 20). 아무것도 쓰거나 지우지 않는다.

-f(--follow)를 붙이면 터미널에 틀어 두고 새로 들어오는 것을 계속 보여준다(Ctrl+C로 끝냄):
    python inspect_logs.py rejections -f        새 거절·도착 결과가 기록되는 즉시
    python inspect_logs.py snapshots -f --hpid A1100017   로컬 스냅샷에 새 회차가 붙는 즉시
    python inspect_logs.py cloud -f             클라우드에 새 원본 파일이 생기면(기본 60초마다 확인)
자정이 지나면 다음 날 파일로 알아서 넘어간다(--date를 주면 그 날짜에 고정).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
KST = timezone(timedelta(hours=9))
REJECTION_DIR = BASE_DIR / "data" / "rejections"
SNAPSHOT_DIR = BASE_DIR / "data" / "snapshots_nationwide"
# E-Gen 오퍼레이션 → 짧은 이름
OP_SHORT = {
    "getEgytListInfoInqire": "목록",
    "getEmrrmRltmUsefulSckbdInfoInqire": "병상",
    "getSrsillDissAceptncPosblInfoInqire": "중증질환",
}


def _kst(ts: str) -> str:
    """ISO 시각을 KST 'MM-DD HH:MM:SS'로."""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(KST).strftime("%m-%d %H:%M:%S")
    except ValueError:
        return ts


def _tail_lines(path: Path, n: int) -> list[str]:
    if not path.exists():
        raise SystemExit(f"파일이 없습니다: {path}")
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return lines[-n:]


def show_rejections(day: str, n: int) -> None:
    path = REJECTION_DIR / f"{day}.jsonl"
    lines = _tail_lines(path, n)
    print(f"[거절 로그] {path}  (최근 {len(lines)}건, 시각은 KST)")
    print(REJECTION_HEADER)
    for line in lines:
        print_rejection(line)


REJECTION_HEADER = f"{'받은 시각':<15} {'단계':<8} {'병원':<10} {'사유':<18} {'중증도':<6} 병상·이동·신뢰도(요청 당시)"


def print_rejection(line: str) -> None:
    r = json.loads(line)
    extra = r.get("extra") or {}
    stage = extra.get("stage") or "response"
    beds = extra.get("availableBedCountAtRequest")
    snap = (f"병상 {'미상' if extra.get('bedCountUnknownAtRequest') else beds} · "
            f"{extra.get('travelMinAtRequest')}분 · 도착 시 유효 {extra.get('bedRArriveAtRequest')}")
    demo = " [demo]" if extra.get("demo") or r.get("demo") else ""
    print(f"{_kst(r.get('timestamp', '')):<15} {stage:<8} {r.get('hospitalId', ''):<10} "
          f"{r.get('reasonCode', ''):<18} {str(r.get('severity')):<6} {snap}{demo}")


def show_snapshots(day: str, n: int, hpid: str | None) -> None:
    path = SNAPSHOT_DIR / f"{day}.jsonl"
    lines = _tail_lines(path, n)
    print(f"[E-Gen 스냅샷] {path}  (최근 {len(lines)}건)")
    for line in lines:
        print_snapshot(line, hpid)


def print_snapshot(line: str, hpid: str | None) -> None:
    r = json.loads(line)
    op = OP_SHORT.get(r.get("operation", ""), r.get("operation", ""))
    head = f"{_kst(r.get('ts', '')):<15} {op:<6} 병원 {r.get('count')}곳"
    if not hpid:
        print(head)
        return
    item = next((i for i in r.get("items", []) if i.get("hpid") == hpid), None)
    if item is None:
        print(f"{head}  | {hpid} 없음")
    elif op == "병상":
        print(f"{head}  | {item.get('dutyName')} 응급실 {item.get('hvec')} · 수술실 {item.get('hvoc')} · "
              f"입원실 {item.get('hvgc')} · 갱신 {item.get('hvidate')}")
    elif op == "중증질환":
        yes = [k for k, v in item.items() if k.startswith("MKioskTy") and v == "Y"]
        print(f"{head}  | {item.get('dutyName')} 수용 가능 신고 {len(yes)}개 항목")
    else:
        print(f"{head}  | {item.get('dutyName')} {item.get('dutyEmclsName', '')}")


def show_cloud(day: str, n: int) -> None:
    from snapshot_cloud import _env, _list_all  # 같은 env·목록 함수를 그대로 쓴다

    url, anon, _service = _env()
    objects = [o for o in _list_all(url, anon, f"raw/{day}/") if o.get("name")]
    print(f"[클라우드 수집기] egen-snapshots/raw/{day}/  — 오늘 {len(objects)}개 파일, 최근 {min(n, len(objects))}개")
    print("  파일 이름 = <수집 시각 HHMMSS>_<오퍼레이션>_p<페이지>. .err.json은 그 회차 호출 실패 기록")
    for o in objects[-n:]:
        print_cloud_object(o)


def print_cloud_object(o: dict) -> None:
    size = (o.get("metadata") or {}).get("size")
    failed = "  ⚠ 호출 실패 기록" if o["name"].endswith(".err.json") else ""
    print(f"  {_kst(o.get('created_at', '')):<15} {o['name']:<60} {size or '':>8} B{failed}", flush=True)


# ── 계속 보기(-f) ──────────────────────────────────────────────────────────


def _today() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def follow_file(folder: Path, fixed_day: str | None, handle, interval: float) -> None:
    """날짜 파일(<folder>/<날짜>.jsonl) 끝에 새 줄이 붙으면 바로 출력한다. 쓰는 중인 마지막 줄(줄바꿈 전)은
    다음 확인 때 읽는다. 날짜를 고정하지 않으면 자정에 다음 날 파일로 넘어간다."""
    day = fixed_day or _today()
    path = folder / f"{day}.jsonl"
    pos = path.stat().st_size if path.exists() else 0
    print(f"── {path.name} 새 기록을 기다립니다 (Ctrl+C로 끝냄) ──", flush=True)
    while True:
        if not fixed_day and _today() != day:
            day = _today()
            path, pos = folder / f"{day}.jsonl", 0
            print(f"── 날짜가 바뀌어 {path.name}로 넘어갑니다 ──", flush=True)
        if path.exists():
            size = path.stat().st_size
            if size < pos:  # 파일이 다시 만들어졌다(클라우드 동기화가 오늘 파일을 새로 쓸 때)
                pos = 0
            if size > pos:
                with path.open("rb") as f:
                    f.seek(pos)
                    chunk = f.read()
                complete = chunk.rfind(b"\n") + 1
                for raw in chunk[:complete].decode("utf-8").splitlines():
                    if raw.strip():
                        handle(raw)
                pos += complete
        time.sleep(interval)


def follow_cloud(fixed_day: str | None, interval: float) -> None:
    from snapshot_cloud import _env, _list_all

    url, anon, _service = _env()
    day = fixed_day or _today()
    seen = {o["name"] for o in _list_all(url, anon, f"raw/{day}/") if o.get("name")}
    print(f"── 클라우드 raw/{day}/ 새 파일을 {interval:g}초마다 확인합니다 (Ctrl+C로 끝냄) ──", flush=True)
    while True:
        time.sleep(interval)
        if not fixed_day and _today() != day:
            day, seen = _today(), set()
            print(f"── 날짜가 바뀌어 raw/{day}/로 넘어갑니다 ──", flush=True)
        try:
            objects = [o for o in _list_all(url, anon, f"raw/{day}/") if o.get("name")]
        except Exception as e:  # noqa: BLE001 — 네트워크가 잠깐 끊겨도 계속 본다
            print(f"  (목록 조회 실패, 다음에 다시: {e})", flush=True)
            continue
        for o in objects:
            if o["name"] not in seen:
                seen.add(o["name"])
                print_cloud_object(o)


def main() -> None:
    parser = argparse.ArgumentParser(description="수집 로그 확인(읽기 전용)")
    parser.add_argument("kind", choices=["rejections", "snapshots", "cloud"])
    parser.add_argument("--date", help="KST 날짜(기본 오늘)")
    parser.add_argument("-n", type=int, default=20, help="최근 몇 건(기본 20)")
    parser.add_argument("--hpid", help="snapshots: 이 병원의 값만 같이 보기 (예: A1100017)")
    parser.add_argument("-f", "--follow", action="store_true", help="계속 보기 — 새로 들어오는 것을 실시간으로 출력")
    parser.add_argument("--interval", type=float, help="계속 보기 확인 간격(초). 기본: 파일 1초, 클라우드 60초")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)  # 계속 보기에서 한 줄씩 바로 보이게
    day = args.date or _today()
    try:
        if args.kind == "rejections":
            shown = not args.follow or (REJECTION_DIR / f"{day}.jsonl").exists()
            if shown:
                show_rejections(day, args.n)
            if args.follow:
                if not shown:
                    print(REJECTION_HEADER)
                follow_file(REJECTION_DIR, args.date, print_rejection,
                            args.interval or 1)
        elif args.kind == "snapshots":
            if not args.follow or (SNAPSHOT_DIR / f"{day}.jsonl").exists():
                show_snapshots(day, args.n, args.hpid)
            if args.follow:
                follow_file(SNAPSHOT_DIR, args.date, lambda line: print_snapshot(line, args.hpid), args.interval or 1)
        else:
            show_cloud(day, args.n)
            if args.follow:
                follow_cloud(args.date, args.interval or 60)
    except KeyboardInterrupt:
        print("\n끝냈습니다.")


if __name__ == "__main__":
    main()
