"""클라우드 스냅샷 동기화 — Supabase Storage의 E-Gen 수집분을 로컬 아카이브로 복원.

    python snapshot_cloud.py --seed    # (1회, 수집 장비에서) 기존 아카이브를 days/로 업로드
    python snapshot_cloud.py --sync    # 클라우드 수집분을 data/snapshots_nationwide/로 내려받기

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
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import sys
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
    if has_partial:
        try:
            text = gzip.decompress(_download(url, f"partial/{date}.jsonl.gz")).decode("utf-8")
            for line in text.splitlines():
                rec = json.loads(line)
                records[(rec.get("ts", ""), rec.get("operation", ""))] = rec
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
            print(f"  {date}: 로컬 수집기(snapshot.py)가 만든 파일 — 건드리지 않음 "
                  f"(이관 끝나면 그쪽 수집을 끄고, 이 날짜는 --seed로 올릴 것)")
            continue
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--seed", action="store_true", help="기존 로컬 아카이브를 days/로 업로드 (수집 장비 1회)")
    group.add_argument("--sync", action="store_true", help="클라우드 수집분을 로컬로 복원")
    args = parser.parse_args()

    url, anon, service = _env()
    if args.seed:
        if not service:
            raise SystemExit("--seed에는 SNAPSHOT_SUPABASE_SERVICE_KEY가 필요하다")
        seed(url, service)
    else:
        sync(url, anon)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
