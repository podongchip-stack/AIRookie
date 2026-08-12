"""거절 로그 수신구 — hub가 부르기만 하면 되도록 미리 세워두는 구멍.

hub·dashboard 쪽 작업(거절 사유 선택 UI, 액션 스키마에 reasonCode 추가)이 끝나기를
기다리면 그동안의 로그가 0건이 된다. 로그는 나중에 소급해서 만들 수 없으므로,
**받는 쪽을 먼저 세워두고 저쪽이 준비되는 대로 붙게** 한다.

지금 hub가 보내는 형태 그대로도 받는다 — `hospital_id` 하나만 있으면 기록된다
(이유는 `UNSPECIFIED`). 즉 저쪽은 **스키마를 안 바꿔도 지금 당장 연동할 수 있고**,
나중에 `reasonCode`를 얹으면 그때부터 분류가 정밀해진다.

붙이는 방법 두 가지
-------------------
1. 기존 info 서버(`info/app.py`, 포트 5002)에 얹기 — 두 줄이면 된다:

       from hospital_score.ingest import rejection_bp
       app.register_blueprint(rejection_bp)

   `app.py`는 팀원 담당 파일이라 여기서 직접 고치지 않았다. 붙일지는 팀 합의로 정한다.

2. 따로 띄우기 (팀원 파일을 아예 안 건드리는 쪽):

       python -m hospital_score.ingest        # 포트 5003

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
