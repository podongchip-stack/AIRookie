"""거절 로그 수신구 — hub의 `hospital_reject` 사유를 받아 축별로 쌓는 서버.

**hub가 실제로 연동됐다(2026-09-10).** hub의 `_handle_dashboard_action()`이
`hospital_reject`마다 `hub/delivery.py`의 `send_rejection_to_info()`로 이 주소에
POST한다. `hospital_id` 하나만 있으면 기록되고(이유 없으면 `UNSPECIFIED`),
모르는 필드는 `extra`에 보존한다 — hub가 어휘를 늘려도 로그가 죽지 않는다.

기동 방법
---------
`send_to_hub.py`(상시 병원 정보 전송)와 별개 프로세스라 따로 띄운다:

    cd info/Hospital_inform/info
    python -m hospital_score.ingest        # 포트 5003

(예전엔 `info/app.py`(병상 갱신 수신 서버)에 Blueprint를 얹는 안도 있었으나,
그 서버는 2026-08-13 삭제됐다. 지금은 이 standalone 실행이 유일한 기동 경로다.)
안 띄우면 hub는 조용히 넘어가고 그 기간의 거절 로그는 사라진다(소급 생성 불가).

엔드포인트
----------
    POST /hub/rejection          한 건 또는 배열
    GET  /hub/rejection/summary  축별 집계 (사람이 읽는 텍스트)
    GET  /verification/summary   시연용 신뢰도 검증 화면 집계(JSON) — hub가 대시보드로 중계한다
                                 (?hpid=를 주면 그 병원 기록 전부를 hospital로 덧붙인다)
"""

from __future__ import annotations

import threading
import time
from collections import Counter

from flask import Blueprint, jsonify, request

from . import rejection as R

rejection_bp = Blueprint("rejection", __name__)

#: 따로 띄울 때 쓰는 포트. info 서버(5002)와 겹치지 않게 둔다
STANDALONE_PORT = 5003


@rejection_bp.post("/hub/rejection")
def receive_rejection():
    """거절 한 건(또는 배열)을 받아 기록한다.

    형식이 조금 달라도 받아준다. 여기서 까다롭게 굴면 저쪽이 붙이지 못하고,
    그 사이 로그는 영영 사라진다 — 받아두고 분류는 나중에 다시 할 수 있다.
    """
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"ok": False, "error": "JSON 본문이 필요하다"}), 400

    items = payload if isinstance(payload, list) else [payload]
    saved, errors = 0, []
    for item in items:
        if not isinstance(item, dict):
            errors.append("객체가 아닌 항목")
            continue
        try:
            R.append(R.normalize(item))
            saved += 1
        except ValueError as exc:
            errors.append(str(exc))

    status = 200 if saved else 400
    return jsonify({"ok": saved > 0, "saved": saved, "errors": errors}), status


@rejection_bp.get("/hub/rejection/summary")
def rejection_summary():
    return R.summarize(R.load_all()), 200, {"Content-Type": "text/plain; charset=utf-8"}


#: 시연용 재생 로그를 이 주기로 다시 만든다 — 그 사이 쌓인 스냅샷이 반영된다(생성 수 초)
REPLAY_REFRESH_SEC = 3600
_replay_lock = threading.Lock()


@rejection_bp.get("/verification/summary")
def verification_summary():
    """시연용 검증 화면 집계: 실제 E-Gen 재생 채점(reliability.replay_demo) + E-Gen↔심평원 대조(crosscheck)
    + 거절 로그 사유 집계."""
    body: dict = {"demo": True}
    try:
        from reliability import replay_demo

        path = replay_demo.OUTPUT_PATH
        if not path.is_file():
            # 첫 생성만 동기 — 이때는 보여줄 과거 산출물 자체가 없다
            with _replay_lock:
                if not path.is_file():
                    replay_demo.generate()
        elif time.time() - path.stat().st_mtime > REPLAY_REFRESH_SEC and _replay_lock.acquire(blocking=False):
            # 낡은 캐시는 뒤에서 다시 만들고, 이번 요청은 지금 있는 파일로 바로 답한다.
            # 예전엔 여기서 생성이 끝날 때까지 블로킹해 hub의 30초 타임아웃을 넘겼다
            # ("검증 집계를 가져오지 못했습니다 … Read timed out" — 1시간마다 재발).
            def _regen_in_background() -> None:
                try:
                    replay_demo.generate()
                finally:
                    _replay_lock.release()

            threading.Thread(target=_regen_in_background, daemon=True).start()
        body["replay"] = replay_demo.summarize()
    except Exception as exc:  # 신뢰도 엔진이 없는 환경 — 거절 로그 집계만 보낸다
        body["replay"] = None
        body["replayError"] = f"{type(exc).__name__}: {exc}"
    try:
        from . import crosscheck

        body["crosscheck"] = crosscheck.summarize()
    except Exception as exc:  # 스냅샷·심평원 캐시가 없는 장비 — 이 블록만 빠진다
        body["crosscheck"] = None
        body["crosscheckError"] = f"{type(exc).__name__}: {exc}"
    hpid = (request.args.get("hpid") or "").strip()
    if hpid:  # 병원 대시보드에서 열었을 때 — 그 병원 기록 전부(hospital_view)
        try:
            from . import hospital_view

            body["hospital"] = hospital_view.summarize(hpid)
        except Exception as exc:
            body["hospital"] = None
            body["hospitalError"] = f"{type(exc).__name__}: {exc}"
    records = R.load_all()
    counts = Counter(r.get("reasonCode") or "UNSPECIFIED" for r in records)
    body["rejections"] = {
        "count": len(records),
        "demoCount": sum(bool(r.get("demo") or (r.get("extra") or {}).get("demo")) for r in records),
        "byReason": [
            {"code": code, "axis": R.REASON_AXIS.get(code, (R.AXIS_UNKNOWN, code))[0],
             "label": R.REASON_AXIS.get(code, (R.AXIS_UNKNOWN, code))[1], "count": n}
            for code, n in counts.most_common()
        ],
    }
    return jsonify(body)


#: 라이브 보드 생성은 수십 초(실제 엔진 재생) — 동시 요청이 이중 생성하지 않게 락으로 감싼다
_live_lock = threading.Lock()


@rejection_bp.get("/verification/live")
def verification_live():
    """라이브 채점 보드(2026-10-03, reliability.live_board): 창 안의 모든 병원 × 폴링을
    실제 서빙 엔진으로 재생·채점한 결과 + 지금 각 병원 값의 유효 확률(진행형).
    /verification/summary(가상 요청 표본·1시간 배치)와 달리 전수·20분 신선도다.
    hub가 GET /verification/live로 그대로 중계한다 — dashboard는 hub와만 통신."""
    try:
        from reliability import live_board

        with _live_lock:
            return jsonify(live_board.cached())
    except Exception as exc:  # 신뢰도 엔진·스냅샷이 없는 장비 — 화면이 라이브 섹션만 숨긴다
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 503


def create_app():
    """따로 띄울 때 쓰는 최소 앱."""
    from flask import Flask

    app = Flask(__name__)
    app.register_blueprint(rejection_bp)
    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=STANDALONE_PORT)
