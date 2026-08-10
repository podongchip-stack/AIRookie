"""feature/hub가 이송 확정(final_approval)으로 병상이 줄었을 때 보내는
갱신을 받아 Supabase에 반영하는 HTTP 레이어. `send_to_hub.py`(info → hub,
주기적 재조회)의 반대 방향이다 — 그 스크립트가 최대 재조회 주기(기본 30분)
만큼 늦게 반영하는 것과 달리, 이 서버는 hub가 확정 시점에 직접 밀어주는
값을 즉시 반영한다. 서로 다른 문제를 풀 뿐 어느 한쪽이 다른 쪽을 대체하지
않는다.

지금은 SupabaseEgenClient 하나만 대상으로 한다. FixtureEgenClient는 쓰기가
no-op이라(egen/client.py 참고) fixture로 로컬 테스트를 해도 에러 없이
조용히 넘어간다.
"""
from __future__ import annotations

import sys
from pathlib import Path

from flask import Flask, jsonify, request
from pydantic import ValidationError

HOSPITAL_INFORM_INFO_DIR = Path(__file__).resolve().parent / "Hospital_inform" / "info"
sys.path.insert(0, str(HOSPITAL_INFORM_INFO_DIR))

from egen.client import SupabaseEgenClient  # noqa: E402
from schema import HospitalBedUpdate  # noqa: E402

app = Flask(__name__)
app.json.ensure_ascii = False  # 한글 필드를 유니코드 이스케이프 없이 그대로 응답

# hub_engine.py가 한 번 만든 HubEngine을 계속 쓰는 것과 같은 패턴 — 요청마다
# 새로 만들지 않고 프로세스 수명 동안 하나만 쓴다.
_client = SupabaseEgenClient()


@app.post("/hub/bed-update")
def bed_update():
    """hub의 HospitalBedUpdate(hub/schema.py와 필드 1:1 대응)를 받아
    Supabase의 hvec 컬럼에 반영한다."""
    try:
        update = HospitalBedUpdate.model_validate(request.get_json(force=True))
    except ValidationError as exc:
        return jsonify({"error": "invalid HospitalBedUpdate", "detail": exc.errors()}), 400

    _client.update_bed_count(update.hospitalId, update.availableBedCount)
    print(
        f"  [통신] {update.hospitalId} 병상 {update.availableBedCount}로 갱신 "
        f"(status={update.status}, updatedAt={update.updatedAt})"
    )
    return jsonify({"status": "ok", "hospitalId": update.hospitalId}), 200


if __name__ == "__main__":
    # hub=5001, voice=5002와 겹치지 않게 5003을 쓴다.
    app.run(host="0.0.0.0", port=5003, debug=True)
