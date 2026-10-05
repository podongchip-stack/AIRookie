"""클라우드 스냅샷 동기화 — Supabase Storage의 E-Gen 수집분을 로컬 아카이브로 복원.

    python snapshot_cloud.py --seed    # (1회, 수집 장비에서) 기존 아카이브를 days/로 업로드
    python snapshot_cloud.py --sync    # 클라우드 수집분을 data/snapshots_nationwide/로 내려받기
    python snapshot_cloud.py --watch   # 상시: 클라우드에 새 수집분이 생기면 바로 sync (start-all이 띄움)

왜 이 구조인가 (2026-10-04)
---------------------------
수집 장비(노트북)를 들고 이동하게 되면서 수집기를 Supabase Edge Function으로
이관했다(supabase/functions/egen-snapshot). 클라우드는 **원본 XML을 그대로** 쌓고,
해석(XML → items)은 여기서 기존 파서(HttpEgenClient._parse)로 한다 — 파서를 한 곳에만
두어, 매핑 해석이 바뀌어도 과거 데이터를 다시 해석할 수 있다는 원칙 그대로.
sync가 복원한 날짜 파일은 snapshot.py가 쓰던 JSONL 형식과 동일해서,
live_board·reliability features 등 기존 소비자는 아무 수정이 필요 없다.

Storage 레이아웃: raw/<KST날짜>/<HHMMSS>_<op>_p<page>.xml.gz (+ .err.json),
days/<KST날짜>.jsonl.gz (노트북 아카이브 시드 — 완결 날짜는 이걸 그대로 쓴다),
partial/<KST날짜>.jsonl.gz (아직 자라는 중인 오늘 파일의 중간본 — seed가 매번 덮어쓰고,
sync는 raw와 (ts, operation)으로 합쳐 쓴다. 완결되면 days/로 승격되고 partial은 지운다).

env (info/.env): SNAPSHOT_SUPABASE_URL(필수),
SNAPSHOT_SUPABASE_ANON_KEY(sync — 공개 버킷이라 읽기 전용),
SNAPSHOT_SUPABASE_SERVICE_KEY(seed 업로드에만 필요).

안전장치: 로컬 수집기(snapshot.py)가 쓰고 있는 오늘 파일은 sync가 건드리지 않는다
(이 스크립트가 만든 파일만 상태 파일에 기록해 두고 그것만 다시 만든다) — 이관
과도기에 양쪽이 같은 파일을 두드려 관측이 사라지는 사고를 막는다.

넘겨받기(2026-10-04 추가): 그 로컬 파일이 ADOPT_IDLE_SEC(기본 1시간) 넘게 안 바뀌었으면
로컬 수집기가 꺼진 것으로 보고 sync가 그 날짜를 넘겨받는다 — 실제로 이관 당일 로컬 수집이
16:52에 멈춘 뒤로 오늘 파일이 계속 "건드리지 않음"이라 신뢰도 그래프가 거기서 멈춰 있었다.
넘겨받을 때 원래 로컬 파일은 <날짜>.jsonl.local-base로 보관하고(*.jsonl이 아니라 다른
소비자는 읽지 않는다), 다시 만들 때마다 그 내용을 바탕으로 깔고 클라우드 수집분을 이어 붙인다
— 로컬에만 있던 관측이 사라지지 않는다.

watch(2026-10-04 추가): 클라우드 수집기가 원본을 올리면 그걸 신호로 바로 sync한다.
Supabase가 이 장비로 직접 알릴 길(들어오는 연결)이 없어서, WATCH_INTERVAL_SEC(기본 60초)마다
오늘 raw/ 목록 개수만 가볍게 보고 늘었으면 sync한다(한 회차의 두 오퍼레이션이 1~2초 차이로
올라오므로 조금 기다렸다 한 번에). 예전 20분 고정 주기보다 그래프 반영이 최대 20분 빨라진다.
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from egen.client import ENV_PATH, HttpEgenClient  # noqa: E402

KST = timezone(timedelta(hours=9))
BUCKET = "egen-snapshots"
SNAPSHOT_DIR = BASE_DIR / "data" / "snapshots_nationwide"
STATE_PATH = SNAPSHOT_DIR / ".cloud_sync_state.json"
# 로컬 수집기가 이만큼 안 쓰면 꺼진 것으로 보고 그 날짜를 sync가 넘겨받는다
ADOPT_IDLE_SEC = int(os.environ.get("SNAPSHOT_ADOPT_IDLE_SEC", "3600"))
WATCH_INTERVAL_SEC = int(os.environ.get("SNAPSHOT_WATCH_INTERVAL_SEC", "60"))
SEED_INTERVAL_SEC = 1200  # watch에서 seed(SERVICE_KEY 있는 장비)는 예전처럼 20분마다만


def _env() -> tuple[str, str, str | None]:
    from dotenv import load_dotenv

    load_dotenv(ENV_PATH)
    url = os.environ.get("SNAPSHOT_SUPABASE_URL", "").rstrip("/")
    anon = os.environ.get("SNAPSHOT_SUPABASE_ANON_KEY", "")
    service = os.environ.get("SNAPSHOT_SUPABASE_SERVICE_KEY")
    if not url or not anon:
        raise SystemExit(f"SNAPSHOT_SUPABASE_URL/ANON_KEY가 없다 — {ENV_PATH} 확인")
    return url, anon, service


def _list_all(url: str, key: str, prefix: str) -> list[dict]:
    """버킷 객체 목록(이름순). Storage list API는 페이지라 끝까지 돈다."""
    out: list[dict] = []
    offset = 0
    while True:
        res = requests.post(
            f"{url}/storage/v1/object/list/{BUCKET}",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            json={"prefix": prefix, "limit": 1000, "offset": offset,
                  "sortBy": {"column": "name", "order": "asc"}},
            timeout=30,
        )
        res.raise_for_status()
        page = res.json()
        out.extend(page)
        if len(page) < 1000:
            return out
        offset += 1000


def _download(url: str, path: str) -> bytes:
    res = requests.get(f"{url}/storage/v1/object/public/{BUCKET}/{path}", timeout=60)
    res.raise_for_status()
    return res.content


def _upload(url: str, service_key: str, path: str, data: bytes, content_type: str) -> None:
    res = requests.post(
        f"{url}/storage/v1/object/{BUCKET}/{path}",
        headers={"apikey": service_key, "Authorization": f"Bearer {service_key}",
                 "Content-Type": content_type, "x-upsert": "true"},
        data=data, timeout=120,
    )
    res.raise_for_status()


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"managedDays": {}}  # date -> 그 날짜를 만들 때 쓴 raw 객체 수


def _save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


# ── seed: 기존 로컬 아카이브 → days/ ─────────────────────────────────────────

def _gzip_bytes(raw: bytes) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write(raw)
    return buf.getvalue()


def _delete(url: str, service_key: str, path: str) -> None:
    requests.delete(
        f"{url}/storage/v1/object/{BUCKET}/{path}",
        headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
        timeout=30,
    )


def seed(url: str, service_key: str) -> None:
    existing = {o["name"] for o in _list_all(url, service_key, "days")}
    files = sorted(SNAPSHOT_DIR.glob("*.jsonl"))
    today = datetime.now(KST).date().isoformat()
    done = skipped = 0
    for path in files:
        raw = path.read_bytes()
        if path.stem == today:
            # 자라는 중인 오늘 파일은 partial/로 매번 덮어쓴다 — 클라우드 수집(raw/)이
            # 시작되기 전의 앞반쪽(이 장비에만 있는 관측)을 당일에도 다른 장비가 받게.
            gz_body = _gzip_bytes(raw)
            _upload(url, service_key, f"partial/{path.stem}.jsonl.gz", gz_body, "application/gzip")
            print(f"  {path.name}: 오늘 중간본 → partial/ ({len(raw) / 1e6:.1f}MB → {len(gz_body) / 1e6:.1f}MB)")
            continue
        if f"{path.stem}.jsonl.gz" in existing:
            skipped += 1
            continue
        gz_body = _gzip_bytes(raw)
        _upload(url, service_key, f"days/{path.stem}.jsonl.gz", gz_body, "application/gzip")
        _delete(url, service_key, f"partial/{path.stem}.jsonl.gz")  # 완결 승격 — 중간본 정리
        done += 1
        print(f"  {path.name}: {len(raw) / 1e6:.1f}MB → {len(gz_body) / 1e6:.1f}MB 업로드")
    print(f"시드 완료 — 업로드 {done}개, 이미 있음 {skipped}개")


# ── sync: days/ + raw/ → 로컬 날짜 파일 ──────────────────────────────────────

def _local_base(date: str) -> Path:
    """넘겨받은 날짜의 원래 로컬 수집분 보관 파일(*.jsonl이 아니라 다른 소비자는 읽지 않는다)."""
    return SNAPSHOT_DIR / f"{date}.jsonl.local-base"


def _rebuild_day(url: str, anon: str, date: str, objects: list[dict], has_partial: bool) -> str:
    """raw/<date>/ 객체들(+ 있으면 partial/ 중간본)로 스냅샷 JSONL 하루치를 만든다
    (snapshot.py fetch_one과 같은 줄). partial은 수집 장비가 올린 로컬 수집분이라
    클라우드 수집 시작 전 시간대를 메꾼다 — (ts, operation)으로 합쳐 중복만 거른다."""
    # (HHMMSS, op) -> 페이지 목록 / 오류
    groups: dict[tuple[str, str], dict] = {}
    for obj in objects:
        name = obj["name"]  # 예: 062000_getEmrrm..._p1.xml.gz / 062000_getEmrrm....err.json
        if name.endswith(".xml.gz"):
            stem = name[: -len(".xml.gz")]
            hms, _, rest = stem.partition("_")
            op, _, page = rest.rpartition("_p")
            groups.setdefault((hms, op), {"pages": []})["pages"].append((int(page), name))
        elif name.endswith(".err.json"):
            stem = name[: -len(".err.json")]
            hms, _, op = stem.partition("_")
            groups.setdefault((hms, op), {}).setdefault("pages", [])
            groups[(hms, op)]["error_obj"] = name

    records: dict[tuple[str, str], dict] = {}
    base = _local_base(date)
    if base.exists():  # 넘겨받은 날짜 — 원래 로컬 수집분을 바탕으로 깐다
        for line in base.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                records[(rec.get("ts", ""), rec.get("operation", ""))] = rec
    if has_partial:
        try:
            text = gzip.decompress(_download(url, f"partial/{date}.jsonl.gz")).decode("utf-8")
            for line in text.splitlines():
                rec = json.loads(line)
                records.setdefault((rec.get("ts", ""), rec.get("operation", "")), rec)
        except Exception as exc:  # noqa: BLE001 — 중간본이 깨져도 raw만으로 진행
            print(f"  {date}: partial 읽기 실패({type(exc).__name__}) — raw만으로 복원")

    for (hms, op) in sorted(groups):
        entry = groups[(hms, op)]
        ts = f"{date}T{hms[:2]}:{hms[2:4]}:{hms[4:6]}+09:00"
        record: dict = {"ts": ts, "operation": op, "stage1": "", "stage2": ""}
        if entry.get("error_obj") and not entry["pages"]:
            err = json.loads(_download(url, f"raw/{date}/{entry['error_obj']}"))
            record["error"] = err.get("error", "unknown")
        else:
            items: list[dict] = []
            try:
                for _, name in sorted(entry["pages"]):
                    xml = gzip.decompress(_download(url, f"raw/{date}/{name}")).decode("utf-8")
                    rows, _total = HttpEgenClient._parse(xml)
                    items.extend(rows)
                record["count"] = len(items)
                record["items"] = items
            except Exception as exc:  # noqa: BLE001 — 깨진 객체도 실패 줄로 보존
                record["error"] = f"{type(exc).__name__}: {exc}"
        records.setdefault((ts, op), record)

    lines = [json.dumps(records[key], ensure_ascii=False) for key in sorted(records)]
    return "\n".join(lines) + ("\n" if lines else "")


def sync(url: str, anon: str) -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    state = _load_state()

    # 1) 완결 날짜(days/)부터 — 없는 것만 내려받는다
    day_objects = {o["name"] for o in _list_all(url, anon, "days") if o["name"].endswith(".jsonl.gz")}
    for name in sorted(day_objects):
        date = name[: -len(".jsonl.gz")]
        local = SNAPSHOT_DIR / f"{date}.jsonl"
        if local.exists():
            continue
        local.write_bytes(gzip.decompress(_download(url, f"days/{name}")))
        print(f"  {date}: days/에서 복원 ({local.stat().st_size / 1e6:.1f}MB)")

    # 2) 클라우드 수집(raw/)·중간본(partial/) 날짜 — days/에 없는 날짜만,
    #    내용이 변한 날(raw 객체 수 또는 partial 갱신 시각)만 다시 만든다
    partials = {
        o["name"][: -len(".jsonl.gz")]: (o.get("updated_at") or o.get("created_at") or "")
        for o in _list_all(url, anon, "partial")
        if o["name"].endswith(".jsonl.gz")
    }
    dates = {o["name"] for o in _list_all(url, anon, "raw") if "." not in o["name"]} | set(partials)
    for date in sorted(dates):
        if f"{date}.jsonl.gz" in day_objects:
            continue
        local = SNAPSHOT_DIR / f"{date}.jsonl"
        if local.exists() and date not in state["managedDays"]:
            idle = time.time() - local.stat().st_mtime
            if idle < ADOPT_IDLE_SEC:
                print(f"  {date}: 로컬 수집기(snapshot.py)가 쓰는 중인 파일 — 건드리지 않음 "
                      f"({ADOPT_IDLE_SEC // 60}분 넘게 안 바뀌면 sync가 넘겨받는다)")
                continue
            # 로컬 수집기가 멈췄다 — 원래 파일을 보관하고 그걸 바탕으로 클라우드 수집분을 이어 붙인다
            base = _local_base(date)
            if not base.exists():
                shutil.copy2(local, base)
            print(f"  {date}: 로컬 수집기가 {idle / 60:.0f}분째 멈춤 — sync가 넘겨받음 "
                  f"(원래 파일은 {base.name}로 보관, 그 위에 클라우드 수집분을 이어 붙임)")
        objects = _list_all(url, anon, f"raw/{date}")
        fingerprint = f"{len(objects)}|{partials.get(date, '')}"
        if state["managedDays"].get(date) == fingerprint and local.exists():
            continue
        body = _rebuild_day(url, anon, date, objects, has_partial=date in partials)
        tmp = local.with_suffix(".jsonl.tmp")
        tmp.write_text(body, encoding="utf-8")
        tmp.replace(local)
        state["managedDays"][date] = fingerprint
        print(f"  {date}: raw {len(objects)}객체{' + partial' if date in partials else ''} "
              f"→ {len(body.splitlines())}줄 복원")
    _save_state(state)
    print("동기화 완료")


def _today_raw_count(url: str, anon: str) -> tuple[str, int]:
    today = datetime.now(KST).date().isoformat()
    return today, len([o for o in _list_all(url, anon, f"raw/{today}") if o.get("name")])


def watch(url: str, anon: str, service: str | None) -> None:
    """클라우드 수집기가 새 원본을 올리면 바로 sync한다(수집 = 트리거). 네트워크가 잠깐 끊겨도 죽지 않는다."""
    print(f"감시 시작 — {WATCH_INTERVAL_SEC}초마다 클라우드 새 수집분 확인, 생기면 바로 동기화", flush=True)
    last_seed = 0.0
    seen: tuple[str, int] | None = None
    while True:
        try:
            if service and time.time() - last_seed >= SEED_INTERVAL_SEC:
                seed(url, service)
                last_seed = time.time()
            current = _today_raw_count(url, anon)
            if current != seen:
                if seen is not None:
                    print(f"[{datetime.now(KST):%H:%M:%S}] 클라우드 새 수집분 감지 "
                          f"(raw/{current[0]}/ {seen[1] if seen[0] == current[0] else 0} → {current[1]}개) — 동기화", flush=True)
                    time.sleep(20)  # 한 회차의 두 오퍼레이션이 다 올라올 때까지 잠깐 기다린다
                sync(url, anon)
                seen = _today_raw_count(url, anon)
        except Exception as exc:  # noqa: BLE001 — 한 번 실패가 상시 감시를 끝내면 안 된다
            print(f"  감시 중 오류, 다음 확인 때 다시: {type(exc).__name__}: {exc}", flush=True)
        time.sleep(WATCH_INTERVAL_SEC)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--seed", action="store_true", help="기존 로컬 아카이브를 days/로 업로드 (수집 장비 1회)")
    group.add_argument("--sync", action="store_true", help="클라우드 수집분을 로컬로 복원")
    group.add_argument("--watch", action="store_true", help="상시 감시 — 클라우드에 새 수집분이 생기면 바로 sync")
    args = parser.parse_args()

    url, anon, service = _env()
    if args.seed:
        if not service:
            raise SystemExit("--seed에는 SNAPSHOT_SUPABASE_SERVICE_KEY가 필요하다")
        seed(url, service)
    elif args.watch:
        try:
            watch(url, anon, service)
        except KeyboardInterrupt:
            print("감시 종료")
    else:
        sync(url, anon)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
