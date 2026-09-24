"""의사결정 로그. CLAUDE.md "보안 및 개인정보 원칙"의 "모든 의사결정 로그는
타임스탬프 + SHA-256 해시로 저장해 사후 위변조 여부를 검증할 수 있게 한다"를
구현한다.

기록 하나(entry)는 {timestamp, eventType, payload, hash} 형태다. hash는
timestamp+eventType+payload를 정렬된 JSON으로 직렬화한 값의 SHA-256이라서,
누군가 payload를 사후에 고치면 저장된 hash와 재계산한 hash가 달라져 위변조를
바로 알아챌 수 있다. append-only(JSONL, 한 줄에 기록 하나)로만 쓰고 수정하지
않는다 — 기존 줄을 고치는 게 곧 위변조이기 때문.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
LOG_PATH = BASE_DIR / "data" / "logs" / "decision_log.jsonl"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash_entry(timestamp: str, event_type: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"timestamp": timestamp, "eventType": event_type, "payload": payload},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def log_decision(event_type: str, payload: dict[str, Any], log_path: Path = LOG_PATH) -> dict[str, Any]:
    """의사결정 하나를 기록하고, 저장된 항목(entry)을 그대로 반환한다."""
    timestamp = _utcnow_iso()
    entry = {
        "timestamp": timestamp,
        "eventType": event_type,
        "payload": payload,
        "hash": _hash_entry(timestamp, event_type, payload),
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def verify_log(log_path: Path = LOG_PATH) -> tuple[bool, int]:
    """로그 파일 전체를 검증한다. (위변조 없음 여부, 검사한 줄 수)를 반환한다.
    각 줄의 hash를 payload로부터 재계산해서 저장된 hash와 비교한다.
    """
    if not log_path.exists():
        return True, 0

    checked = 0
    with log_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            expected = _hash_entry(entry["timestamp"], entry["eventType"], entry["payload"])
            if expected != entry["hash"]:
                return False, checked
            checked += 1
    return True, checked
