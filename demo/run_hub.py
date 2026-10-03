"""[demo 브랜치] 시연 녹화용 hub — 실서버 hub와 같은 코드를 다른 포트로, 모든 기록을 임시 폴더로 돌려 띄운다.

- 포트: DEMO_HUB_PORT(기본 5101) — 실서버(5001)와 동시에 떠 있어도 서로 안 섞인다
- 상태 저장·복구 끔, 의사결정 로그·거절 로그·매칭 결과 사본·출동 지점 풀 → 전부 임시 폴더(끝나면 사라짐)
- 거절 로그 수신구로 중계하지 않는다(시연 사건은 운영 로그가 아니다)
- 출동 시뮬레이션 켬, 대시보드 통화 끔(휴대폰 전화 앱으로 통화)
- 병원 정보는 info가 아니라 고정 스냅샷으로 넣는다(demo/snapshot.py load)

    <hub 파이썬> demo/run_hub.py

⚠ develop에 병합하지 않는다(demo 브랜치 규칙).
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

HUB_DIR = Path(__file__).resolve().parent.parent / "hub"
PORT = int(os.environ.get("DEMO_HUB_PORT", "5101"))
TMP = Path(tempfile.mkdtemp(prefix="goldenlink-demo-hub-"))

os.environ.update({
    "HUB_SIM_DISPATCH": "1",
    "HUB_DASHBOARD_CALL": "0",
    "HUB_PERSIST_STATE": "0",
    "HUB_STATE_PATH": str(TMP / "hub_state.json"),
    "HUB_DECISION_LOG_PATH": str(TMP / "decision_log.jsonl"),
    "HOSPITAL_REJECTION_LOG_DIR": str(TMP / "rejections"),
    "HUB_REJECTION_URL": "http://127.0.0.1:9/hub/rejection",  # 아무도 안 받는 주소 — 중계 실패는 hub가 흡수
    "PYTHONUTF8": "1",
})
os.chdir(HUB_DIR)
sys.path.insert(0, str(HUB_DIR))

import app  # noqa: E402

app.LIVE_OUTPUT_DIR = TMP / "live_output"
if app.sim is not None:
    app.sim._pool_dir = TMP / "sim"  # 무작위 출동 지점 풀도 실서버 파일(hub/data/sim)을 건드리지 않게
print(f"[시연 hub] 포트 {PORT} · 임시 기록 {TMP}")
app.start_background()
app.app.run(host="127.0.0.1", port=PORT, debug=False)
