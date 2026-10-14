"""spider 서버 — 거미줄 3D 화면(web/)을 내주고 계산은 파이썬 엔진(engine/)이 한다. Flask(hub와 같은 스택).

브라우저는 그리기만 한다. 도로 그래프(25 MB)는 이 프로세스가 한 번 올려 두고, 화면은 환자 목록과 슬라이더 값을
`POST api/solve`로 보내 줄·충돌·재투척 결과(경로 좌표 포함)를 받아 그린다. 그래서 아이패드 같은 가벼운 기기에서도
도로 데이터를 내려받지 않는다.

경로는 SPIDER_PREFIX(기본 /spider) 아래에 둔다 — start-all.sh의 Cloudflare 터널이 `^/spider(/|$)`를 이 서버로 보내고
나머지는 dashboard로 가므로, 다른 대시보드와 같은 도메인에서 열린다. 화면의 주소는 전부 상대 경로라 접두어를 바꿔도 된다.

    SPIDER_PORT=5050 python serve.py            # http://127.0.0.1:5050/spider/
    python serve.py --port 5050 --host 0.0.0.0  # LAN(아이패드 개발용)
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from flask import Flask, abort, jsonify, redirect, request, send_from_directory

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from engine import KDIST, SCN, SCN_LABEL, SITES, Params, SpiderEngine  # noqa: E402
import voice_to_patient as vtp  # noqa: E402

PREFIX = os.environ.get("SPIDER_PREFIX", "/spider").rstrip("/")
WEB = os.path.join(HERE, "web")
MAX_PATIENTS = 300

app = Flask(__name__, static_folder=None)
app.json.ensure_ascii = False
ENGINE: SpiderEngine | None = None


def engine() -> SpiderEngine:
    global ENGINE
    if ENGINE is None:
        t0 = time.time()
        ENGINE = SpiderEngine()
        print(f"[spider] 엔진 로드 {time.time() - t0:.1f}s — {ENGINE.describe()}", flush=True)
    return ENGINE


# ── 화면(정적) ──
@app.get("/")
def root():
    return redirect(f"{PREFIX}/")


@app.get(f"{PREFIX}/")
def index():
    r = send_from_directory(WEB, "index.html")
    r.headers["Cache-Control"] = "no-cache"
    return r


@app.get(f"{PREFIX}/<path:name>")
def static_file(name: str):
    if name.startswith("api/"):
        abort(404)
    # vendor 라이브러리는 오래 캐시, 우리 파일은 매번 확인(아이패드 새로고침으로 바로 반영)
    r = send_from_directory(WEB, name, max_age=86400 * 30 if name.startswith("vendor/") else 0)
    if not name.startswith("vendor/"):
        r.headers["Cache-Control"] = "no-cache"
    return r


# ── API ──
@app.get(f"{PREFIX}/api/health")
def health():
    return jsonify({"ok": True, "engine": engine().describe(), "prefix": PREFIX})


@app.get(f"{PREFIX}/api/meta")
def meta():
    """화면이 처음에 한 번 받는 것 — 시나리오·위치 목록·슬라이더 기본값. 한 곳(engine/scenarios.py)에서만 정의한다."""
    return jsonify({
        "sites": SITES,
        "scenarios": [{"id": k, "label": SCN_LABEL[k], "patients": v} for k, v in SCN.items()],
        "kdist": list(KDIST.keys()),
        "defaults": Params().__dict__,
        "engine": engine().describe(),
    })


@app.get(f"{PREFIX}/api/hospitals")
def hospitals():
    return jsonify(engine().hospitals_json())


@app.post(f"{PREFIX}/api/solve")
def solve():
    body = request.get_json(silent=True) or {}
    patients = body.get("patients") or []
    if not isinstance(patients, list) or len(patients) > MAX_PATIENTS:
        return jsonify({"error": f"patients는 {MAX_PATIENTS}명까지의 목록이어야 합니다"}), 400
    try:
        clean = [{"id": int(p["id"]), "site": str(p.get("site", "")), "k": int(p["k"]), "t0": float(p["t0"]),
                  "lat": float(p["lat"]), "lng": float(p["lng"]), "z": float(p.get("z", {1: 4, 2: 3, 3: 2, 4: 1, 5: 1}[int(p["k"])])),
                  "cond": p.get("cond") or None, "text": p.get("text") or None} for p in patients]
    except (KeyError, TypeError, ValueError) as e:
        return jsonify({"error": f"환자 형식이 잘못됐습니다: {e}"}), 400
    return jsonify(engine().solve(clean, body.get("params")))


@app.post(f"{PREFIX}/api/random")
def random_patients():
    body = request.get_json(silent=True) or {}
    n = max(1, min(200, int(body.get("n", 12))))
    width = max(0.0, float(body.get("width", 20)))
    scope = "korea" if body.get("scope") == "korea" else "seoul"
    kdist = body.get("kdist") if body.get("kdist") in KDIST else "real"
    seed = body.get("seed")
    return jsonify(engine().random_patients(n, width, scope, kdist, int(seed) if seed is not None else None))


@app.post(f"{PREFIX}/api/voice")
def voice():
    """voice v2 통화 요약(MF_BERT 17필드) → {k, cond, text}. 규칙은 voice_to_patient.py 하나뿐이다."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "JSON 객체가 필요합니다"}), 400
    return jsonify(vtp.to_patient(body.get("summary", body)))


def main():
    ap = argparse.ArgumentParser(description="spider 거미줄 3D 서버")
    ap.add_argument("--port", type=int, default=int(os.environ.get("SPIDER_PORT", "5050")))
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    engine()  # 요청 전에 미리 올려 둔다(첫 요청이 수 초 걸리지 않게)
    print(f"[spider] http://{args.host}:{args.port}{PREFIX}/", flush=True)
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
