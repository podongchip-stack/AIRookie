"""관제 지도 원격 조작 검사(2026-11-03) — 시연 콘솔(monitor)이 보낸 map_view가 다른 관제 지도에만 가고, 2D/3D는 따라잡기로 남는다.

    python test_map_view.py
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = tempfile.TemporaryDirectory()
os.environ["HUB_STATE_PATH"] = str(Path(_TMP.name) / "hub_state.json")
os.environ["HUB_DECISION_LOG_PATH"] = str(Path(_TMP.name) / "decision_log.jsonl")
os.environ["HOSPITAL_REJECTION_LOG_DIR"] = str(Path(_TMP.name) / "rejections")
os.environ["HUB_REJECTION_URL"] = "http://127.0.0.1:9/hub/rejection"

import app  # noqa: E402
from schema import DashboardIdentify  # noqa: E402
from test_app_background import _FakeSocket  # noqa: E402


def _views(sock: _FakeSocket) -> list[dict]:
    return [m for m in sock.sent if m.get("type") == "map_view"]


def main() -> None:
    console, board, hospital = _FakeSocket(), _FakeSocket(), _FakeSocket()
    for sock, role, id_ in ((console, "monitor", "control"), (board, "monitor", "map"), (hospital, "hospital", "H1")):
        app._dashboard_sockets.add(sock)
        app._handle_identify(sock, DashboardIdentify(role=role, id=id_))
    console.sent.clear(); board.sent.clear(); hospital.sent.clear()

    app._handle_map_view(console, {"type": "map_view", "view": "2d"})
    assert _views(board) == [{"type": "map_view", "view": "2d"}], board.sent
    assert not _views(console) and not _views(hospital), "보낸 콘솔·병원 화면에는 가지 않는다"

    board.sent.clear()
    app._handle_map_view(console, {"type": "map_view", "fullscreen": "enter"})
    assert _views(board) == [{"type": "map_view", "fullscreen": "enter"}]
    app._handle_map_view(console, {"type": "map_view", "view": "bad", "fullscreen": "x"})
    app._handle_map_view(hospital, {"type": "map_view", "view": "3d"})  # 병원 화면은 조작 못 한다
    assert len(_views(board)) == 1, board.sent

    late = _FakeSocket()
    app._dashboard_sockets.add(late)
    app._handle_identify(late, DashboardIdentify(role="monitor", id="map2"))
    assert _views(late) == [{"type": "map_view", "view": "2d"}], "나중에 연 관제 지도는 마지막 2D/3D를 따른다"
    print("모든 검사 통과")


if __name__ == "__main__":
    main()
