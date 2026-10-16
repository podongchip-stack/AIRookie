"""보호자 사이트의 `data.json`을 5분마다 다시 만드는 **상시 프로세스**.

수동 빌드로는 의미가 없다 — 화면에 박힌 "○○ 기준"은 그 시각에만 참이고,
신뢰도는 시간이 갈수록 떨어지는 값이라 멈춘 데이터로는 거짓이 된다.

왜 가벼운가
  신뢰도 엔진은 **증분 관측**(observe_rows)을 지원한다. 그래서 200MB짜리 스냅샷
  재생은 **처음 한 번(콜드 스타트)**만 필요하고, 그 뒤로는 5분마다 E-Gen 3콜을
  받아 엔진에 먹이면 된다. 메모리에 claim 상태가 남아 있어 "이 값이 언제 태어났는지"를
  계속 안다.

주기
  · 5분   병상·중증질환 → 혼잡도·소아 정원·신뢰도 재계산 → data.json
  · 1시간 기관 목록(좌표·전화·등급은 거의 안 바뀐다)
  · 6시간 병원 공지(하루 단위로 바뀐다)
  심평원 전문의 수와 달빛어린이병원 목록은 정적이라 캐시 파일을 그대로 쓴다.

E-Gen 호출량
  5분마다 2콜 + 1시간마다 1콜 + 6시간마다 1콜 ≒ 하루 600콜.
  일일 한도 80,000의 0.8%다(info 상시 파이프라인과 별개로 잡아도 여유).

HTML은 건드리지 않는다. 화면은 뜰 때 data.json을 먼저 보므로 이 파일만 갱신되면
내용이 따라 바뀐다. 정적 호스팅이면 이 프로세스가 같은 자리에 파일을 덮어쓰면 된다.

배포할 때
  정적 호스팅(Cloudflare Pages·Vercel 등)은 파이썬 루프를 못 돌린다. 그래서
  **파일만 올리는 곳**과 **값을 만드는 곳**을 나눈다 —
      Pages(index.html) → fetch → Supabase Storage(data.json) ← 이 프로세스가 업로드
  Storage 버킷(egen-snapshots)은 이미 공개 읽기라 추가 비용이 없고, 공개 URL은
  CDN을 타므로 사이트가 어디에 있든 같은 값을 본다.

실행:
    conda activate dev
    cd poc && python serve_data.py                      # 로컬 out/data.json만
    python serve_data.py --upload                       # + Supabase Storage에 업로드
    python serve_data.py --once --upload                # 한 번만
    python serve_data.py --out /srv/www/data.json       # 다른 자리에 쓰기
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
INFO = os.path.join(ROOT, "info", "Hospital_inform", "info")
sys.path.insert(0, INFO)

import build_peds_finder as B  # noqa: E402  (파싱·조립 규칙을 한 곳에 둔다)
from egen.client import HttpEgenClient  # noqa: E402

KST = timezone(timedelta(hours=9))
LIST_EVERY = 3600          # 기관 목록
MSG_EVERY = 6 * 3600       # 병원 공지
#: 이미 쓰고 있는 스냅샷 버킷에 얹는다(공개 읽기). 새 자원을 만들지 않는다
BUCKET = "egen-snapshots"
OBJECT = "peds/data.json"
ENV_PATH = os.path.join(ROOT, "info", "Hospital_inform", ".env")


def storage_upload(body: bytes) -> str:
    """Supabase Storage에 data.json을 덮어쓴다. 공개 URL을 돌려준다.

    CDN이 옛 값을 주지 않도록 캐시를 짧게(60초) 건다 — 5분 주기보다 짧아야
    보호자가 방금 값을 본다.
    """
    from dotenv import load_dotenv
    load_dotenv(ENV_PATH)
    base = os.environ["SNAPSHOT_SUPABASE_URL"].rstrip("/")
    key = os.environ["SNAPSHOT_SUPABASE_SERVICE_KEY"]
    url = f"{base}/storage/v1/object/{BUCKET}/{OBJECT}"
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "apikey": key, "Authorization": f"Bearer {key}",
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "max-age=60",
        "x-upsert": "true",
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        resp.read()
    return f"{base}/storage/v1/object/public/{BUCKET}/{OBJECT}"


def log(msg: str) -> None:
    print(f"[{datetime.now(KST):%m-%d %H:%M:%S}] {msg}", flush=True)


class Builder:
    """E-Gen을 주기적으로 읽어 data.json을 만든다."""

    def __init__(self) -> None:
        self.client = HttpEgenClient()
        self.listing: list[dict] = []
        self.msgs: dict[str, list[list]] = {}
        self.spec = B.load_specialists()
        self.moon = B.load_moonlight()
        self.last_list = 0.0
        self.last_msg = 0.0

        log("신뢰도 엔진 콜드 스타트 — 스냅샷을 한 번 재생한다(수십 초)")
        from reliability.engine import BedReliabilityEngine
        self.engine = BedReliabilityEngine(warmup_days=14)
        log(f"  관측 {self.engine.warmed_up_observations:,}건 적재")

    # ── 조각별 수집 ────────────────────────────────────────────
    def refresh_listing(self) -> None:
        self.listing = self.client.get_list_info("", "")
        self.last_list = time.time()
        log(f"기관 목록 {len(self.listing)}곳")

    def refresh_messages(self) -> None:
        rows = self.client.get_er_messages()
        with open(B.MSG_CACHE, "w", encoding="utf-8") as fp:
            json.dump({"fetchedAt": datetime.now(KST).isoformat(timespec="seconds"),
                       "count": len(rows), "items": rows}, fp, ensure_ascii=False)
        self.msgs = B.load_messages()
        self.last_msg = time.time()
        log(f"병원 공지 {len(rows)}건 → 소아 관련 {len(self.msgs)}곳")

    # ── 한 주기 ────────────────────────────────────────────────
    def tick(self, out_path: str, upload: bool = False) -> None:
        now_utc = datetime.now(timezone.utc)
        if time.time() - self.last_list > LIST_EVERY or not self.listing:
            self.refresh_listing()
        if time.time() - self.last_msg > MSG_EVERY or not self.msgs:
            self.refresh_messages()

        beds = self.client.get_realtime_beds("", "")
        severe = self.client.get_severe_illness("", "")

        # 엔진에 이번 관측을 먹인다 — 이게 증분이라 재생이 필요 없다
        self.engine.observe_rows(beds, now_utc)
        preds = self.engine.predict(now_utc).get("hvec", {})
        rel = {
            hpid: [round(p.pred_t_sec), round((now_utc - p.born).total_seconds()), round(p.sigma, 4)]
            for hpid, p in preds.items()
        }

        rows = B.assemble(self.listing, beds, severe, self.msgs, rel, self.spec)
        as_of = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
        tmp = out_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump({"asOf": as_of, "rows": rows, "moon": self.moon},
                      fp, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, out_path)          # 읽는 쪽이 반쯤 쓰인 파일을 보지 않게
        busy = sum(1 for r in rows if (r.get("oc") or 0) >= 50)
        log(f"data.json 갱신 — 병원 {len(rows)}곳 · 신뢰도 {len(rel)}곳 · 붐빔 {busy}곳 · {as_of}")
        if upload:
            with open(out_path, "rb") as fp:
                public = storage_upload(fp.read())
            log(f"  업로드 완료 → {public}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "out", "data.json"))
    ap.add_argument("--interval", type=int, default=300, help="초 단위, 기본 5분")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--upload", action="store_true", help="Supabase Storage에도 올린다")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    b = Builder()
    while True:
        started = time.time()
        try:
            b.tick(args.out, upload=args.upload)
        except Exception:
            # 한 주기 실패로 멈추지 않는다 — 다음 주기에 다시 시도한다
            log("이번 주기 실패:\n" + traceback.format_exc().rstrip())
        if args.once:
            return
        time.sleep(max(5.0, args.interval - (time.time() - started)))


if __name__ == "__main__":
    main()
