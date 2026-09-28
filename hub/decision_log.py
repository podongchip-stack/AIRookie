"""의사결정 로그. CLAUDE.md "보안 및 개인정보 원칙"의 "모든 의사결정 로그는
타임스탬프 + SHA-256 해시로 저장해 사후 위변조 여부를 검증할 수 있게 한다"를
구현한다.

기록 하나(entry)는 {timestamp, eventType, payload, prevHash, hash} 형태다. hash는
timestamp+eventType+payload+prevHash를 정렬된 JSON으로 직렬화한 값의 SHA-256이고,
prevHash는 바로 앞 기록의 hash다(해시 체인, 2026-09-28). append-only(JSONL, 한 줄에
기록 하나)로만 쓰고 수정하지 않는다 — 기존 줄을 고치는 게 곧 위변조이기 때문.

예전엔 줄마다 자기 내용만 해시해서, 내용을 고친 뒤 hash를 다시 계산해 넣거나 줄을
통째로 지우거나 순서를 바꾸면 검증을 통과했다. 체인이면 중간 한 줄을 건드리는 순간 그
뒤 모든 줄의 prevHash가 어긋난다. 한계: 파일 **끝부분**을 잘라내는 것은 체인만으로는
못 잡는다(남은 줄끼리는 여전히 이어진다) — 마지막 hash를 따로 보관해 대조해야 한다.

체인 이전(prevHash 없는) 기록은 예전 방식(자기 내용 해시)으로 검증한다. 다만 체인이
한 번 시작된 뒤에 prevHash 없는 줄이 끼어 있으면 위변조로 본다.
"""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
LOG_PATH = BASE_DIR / "data" / "logs" / "decision_log.jsonl"

# 파일이 비어 있을 때 첫 기록의 prevHash.
GENESIS_HASH = "0" * 64

# 여러 스레드(대시보드 소켓별 스레드, 매칭 작업 스레드)가 동시에 쓰면 prevHash 계산과
# 쓰기 사이에 끼어들어 체인이 갈라지거나 줄이 섞인다. 경로별 마지막 hash도 여기서 들고 있어
# 매번 파일을 다시 읽지 않는다.
_lock = threading.Lock()
_last_hash: dict[Path, str] = {}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash_entry(
    timestamp: str, event_type: str, payload: dict[str, Any], prev_hash: str | None = None
) -> str:
    body: dict[str, Any] = {"timestamp": timestamp, "eventType": event_type, "payload": payload}
    # prevHash가 없는(체인 이전) 기록은 예전과 똑같이 계산해야 기존 로그가 계속 검증된다.
    if prev_hash is not None:
        body["prevHash"] = prev_hash
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _read_last_hash(log_path: Path) -> str:
    """파일 마지막 기록의 hash. 파일이 없거나 비었으면 GENESIS_HASH."""
    if not log_path.exists():
        return GENESIS_HASH
    last_line = ""
    with log_path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                last_line = line
    if not last_line:
        return GENESIS_HASH
    return json.loads(last_line)["hash"]


def log_decision(event_type: str, payload: dict[str, Any], log_path: Path = LOG_PATH) -> dict[str, Any]:
    """의사결정 하나를 기록하고, 저장된 항목(entry)을 그대로 반환한다."""
    with _lock:
        prev_hash = _last_hash.get(log_path)
        if prev_hash is None:
            prev_hash = _read_last_hash(log_path)
        timestamp = _utcnow_iso()
        entry = {
            "timestamp": timestamp,
            "eventType": event_type,
            "payload": payload,
            "prevHash": prev_hash,
            "hash": _hash_entry(timestamp, event_type, payload, prev_hash),
        }
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _last_hash[log_path] = entry["hash"]
        return entry


def verify_log(log_path: Path = LOG_PATH) -> tuple[bool, int]:
    """로그 파일 전체를 검증한다. (위변조 없음 여부, 문제없이 검사한 줄 수)를 반환한다.
    각 줄의 hash를 재계산해 비교하고, 체인 기록은 prevHash가 앞 줄 hash와 같은지도 본다.
    """
    if not log_path.exists():
        return True, 0

    checked = 0
    prev = GENESIS_HASH
    chain_started = False
    with log_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            prev_hash = entry.get("prevHash")
            if prev_hash is None:
                if chain_started:
                    return False, checked  # 체인 뒤에 체인 밖 줄이 끼어듦
            else:
                chain_started = True
                if prev_hash != prev:
                    return False, checked  # 앞 줄이 지워졌거나 순서가 바뀜
            expected = _hash_entry(entry["timestamp"], entry["eventType"], entry["payload"], prev_hash)
            if expected != entry["hash"]:
                return False, checked
            prev = entry["hash"]
            checked += 1
    return True, checked
