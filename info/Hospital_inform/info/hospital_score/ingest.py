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
"""

from __future__ import annotations

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


def create_app():
    """따로 띄울 때 쓰는 최소 앱."""
    from flask import Flask

    app = Flask(__name__)
    app.register_blueprint(rejection_bp)
    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=STANDALONE_PORT)
