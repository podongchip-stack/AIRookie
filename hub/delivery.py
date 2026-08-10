"""hub_engine.py의 결과물을 feature/dashboard·feature/info로 내보내는 출구(delivery) 계층.

지금은 로컬 파일 저장만 하지만, 나중에 Flask 기반 실시간 통신을 붙일 자리를
미리 분리해뒀다. 엔드포인트가 정해지면 `send_to_dashboard()`/`send_to_info()`
내부만 채우면 되고, 호출부(run_match.py 등)는 `deliver()`/`deliver_bed_update()`
하나씩만 그대로 쓰면 된다 — CLAUDE.md의 "모델/API 호출부와 비즈니스 로직은
분리해서 구현한다" 원칙과 동일하게, 저장 방식이 바뀌어도 매칭 로직
(hub_engine.py)에는 영향이 없다.

파일명 규칙: feature/voice가 실제로 만드는 파일명이
`<stem>_call_summary.json`이므로(예: DrRomantic3v3_call_summary.json), hub의
결과물도 같은 stem을 이어받아 `<stem>_hub_match_result.json`으로 저장한다.
같은 사건(voice 요약 1건)의 입력과 출력이 파일명만으로 짝지어지므로, 여러 건이
동시에 처리돼도 서로 다른 파일로 섞이지 않는다 (실제 통신 계층에 caseId 같은
필드가 추가되기 전까지, 로컬 저장 단계에서 쓰는 임시 상관관계 키다).
"""
from __future__ import annotations

import os
from pathlib import Path

import requests

from schema import HospitalBedUpdate, HubMatchResult

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "data" / "test" / "output"
VOICE_SUMMARY_SUFFIX = "_call_summary.json"
RESULT_SUFFIX = "_hub_match_result.json"
BED_UPDATE_SUFFIX = "_bed_update.json"

# feature/info의 병상 갱신 수신 서버(info/app.py) 주소. hub=5001, voice=5002와
# 겹치지 않게 info는 5002를 쓴다 (info/send_to_hub.py의 HUB_HOSPITALS_URL과
# 같은 방식의 환경변수 처리).
INFO_BED_UPDATE_URL = os.environ.get("INFO_BED_UPDATE_URL", "http://127.0.0.1:5002/hub/bed-update")

# feature/info 전송에 실패한 HospitalBedUpdate를 쌓아두는 재시도 대기열.
# 한 줄에 하나씩 JSON(append-only가 아니라 매번 전체를 다시 씀 — 성공한
# 항목을 지워야 하므로 decision_log.py의 append-only 로그와는 다른 용도다).
PENDING_BED_UPDATES_PATH = BASE_DIR / "data" / "pending_bed_updates.jsonl"


def result_filename(voice_summary_path: Path) -> str:
    """voice 요약 파일명에서 stem을 뽑아 결과 파일명을 만든다.
    예: DrRomantic3v3_call_summary.json -> DrRomantic3v3_hub_match_result.json
    """
    name = voice_summary_path.name
    stem = name[: -len(VOICE_SUMMARY_SUFFIX)] if name.endswith(VOICE_SUMMARY_SUFFIX) else voice_summary_path.stem
    return f"{stem}{RESULT_SUFFIX}"


def save_local(result: HubMatchResult, voice_summary_path: Path, output_dir: Path = OUTPUT_DIR) -> Path:
    """결과를 로컬 JSON 파일로 저장한다. 통신이 붙은 뒤에도, 감사/재현을 위해
    로컬 저장은 계속 같이 한다 (데모 단계에서는 로컬 저장만으로도 충분하다는
    판단 — 실제 사업화 단계에서는 재검토 필요).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / result_filename(voice_summary_path)
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return path


def send_to_dashboard(result: HubMatchResult) -> None:
    """TODO(Flask 연동): feature/dashboard 엔드포인트가 정해지면
    requests.post(DASHBOARD_URL, json=result.model_dump())로 실시간 전송한다.
    지금은 dashboard 쪽 API가 없어 아무 것도 하지 않는다 — 자리만 만들어둔다.
    """
    print("  [통신] feature/dashboard 실시간 전송은 아직 미연동 (자리만 준비됨)")


def deliver(result: HubMatchResult, voice_summary_path: Path) -> Path:
    """로컬 저장 + (나중에) 통신을 함께 수행하는 단일 진입점.
    develop 브랜치에서 실제 feature/dashboard와 병합될 때도 호출부는 이 함수
    하나만 그대로 쓰면 되도록 만들어뒀다.
    """
    saved_path = save_local(result, voice_summary_path)
    send_to_dashboard(result)
    return saved_path


def bed_update_filename(hospital_id: str) -> str:
    """병원 하나당 파일 하나 — 같은 병원이 다시 갱신되면 최신 상태로 덮어쓴다
    (voice 요약처럼 사건 단위가 아니라 병원 단위의 "현재 상태"이기 때문)."""
    return f"{hospital_id}{BED_UPDATE_SUFFIX}"


def save_local_bed_update(update: HospitalBedUpdate, output_dir: Path = OUTPUT_DIR) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / bed_update_filename(update.hospitalId)
    path.write_text(update.model_dump_json(indent=2), encoding="utf-8")
    return path


def _load_pending_bed_updates(path: Path = PENDING_BED_UPDATES_PATH) -> list[HospitalBedUpdate]:
    if not path.exists():
        return []
    updates: list[HospitalBedUpdate] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                updates.append(HospitalBedUpdate.model_validate_json(line))
    return updates


def _save_pending_bed_updates(updates: list[HospitalBedUpdate], path: Path = PENDING_BED_UPDATES_PATH) -> None:
    """대기열을 통째로 다시 쓴다. 남은 게 없으면 파일 자체를 지운다 — "재시도
    대기 중인 병원이 있는가"를 hub_engine.py가 파일 유무만으로도 확인할 수
    있게 하기 위해서다(has_pending_bed_update() 참고)."""
    if not updates:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for update in updates:
            f.write(update.model_dump_json() + "\n")


def has_pending_bed_update(hospital_id: str, path: Path = PENDING_BED_UPDATES_PATH) -> bool:
    """hub_engine.py의 update_hospital_info()가, 이 병원의 병상 갱신이 아직
    feature/info 전송 재시도 대기 중인 동안은 info발 새 정보로 덮어쓰지 않게
    하려고 확인하는 용도다. 재시도가 성공해 대기열에서 빠진 뒤에야 다음
    update_hospital_info() 호출이 정상 반영된다 — 그렇지 않으면 hub가 이미
    깎은 값을, 아직 그 차감을 모르는 info의 낡은 값이 되돌려버린다."""
    return any(u.hospitalId == hospital_id for u in _load_pending_bed_updates(path))


def _post_bed_update(update: HospitalBedUpdate) -> bool:
    """실제 HTTP POST 1회 시도. 성공하면 True."""
    try:
        response = requests.post(INFO_BED_UPDATE_URL, json=update.model_dump(), timeout=10)
        response.raise_for_status()
        print(f"  [통신] feature/info로 병상 갱신 전송 완료 -> {INFO_BED_UPDATE_URL} — {update.hospitalId}")
        return True
    except requests.RequestException as e:
        print(f"  [통신] feature/info로 병상 갱신 전송 실패 — {update.hospitalId}: {e}")
        return False


def send_to_info(update: HospitalBedUpdate) -> None:
    """feature/info의 POST /hub/bed-update로 병상 갱신을 전달한다.

    info가 잠깐 안 떠 있어도(재시작 등) hub 프로세스 전체가 죽으면 안 된다는
    원칙은 그대로 지키되, 이제는 실패를 그냥 흘려버리지 않고
    PENDING_BED_UPDATES_PATH에 쌓아 재시도한다. hub는 별도 백그라운드
    루프·스케줄러가 없는 순수 요청-응답 구조라(voice/info와 달리 상시 폴링
    프로세스를 안 둔다), 재시도 시점은 새 스레드를 만들지 않고 "다음
    send_to_info() 호출 기회(=다음 승인 액션)"로 삼는 게 기존 구조에
    자연스럽게 맞는다.

    호출될 때마다: (1) 대기열에 쌓여있던 이전 실패 건을 먼저 전송 시도하고,
    성공한 것만 대기열에서 지운다. (2) 그다음 이번 update를 시도하고,
    실패하면 대기열 맨 뒤에 추가한다. 순서를 지키므로(오래된 것부터) 같은
    병원에 대한 갱신이 여러 건 밀려 있어도 최종적으로 올바른 값에 수렴한다.
    """
    pending = _load_pending_bed_updates()
    if pending:
        print(f"  [통신] 재시도 대기열 {len(pending)}건 먼저 전송 시도")
    still_pending = [queued for queued in pending if not _post_bed_update(queued)]

    if not _post_bed_update(update):
        still_pending.append(update)

    _save_pending_bed_updates(still_pending)
    if still_pending:
        print(
            f"  [통신] 재시도 대기열에 {len(still_pending)}건 보류 "
            f"(다음 병상 갱신 때 재시도) -> {PENDING_BED_UPDATES_PATH}"
        )


def deliver_bed_update(update: HospitalBedUpdate) -> Path:
    """로컬 저장 + (나중에) feature/info로의 통신을 함께 수행하는 단일 진입점.
    deliver()와 이름/구조를 맞춰서, 호출부가 "결과를 어디로 보내든" 같은
    패턴(저장 후 전송 자리 호출)을 따르게 했다.
    """
    saved_path = save_local_bed_update(update)
    send_to_info(update)
    return saved_path
