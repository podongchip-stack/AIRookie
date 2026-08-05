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

from pathlib import Path

from schema import HospitalBedUpdate, HubMatchResult

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "data" / "test" / "output"
VOICE_SUMMARY_SUFFIX = "_call_summary.json"
RESULT_SUFFIX = "_hub_match_result.json"
BED_UPDATE_SUFFIX = "_bed_update.json"


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


def send_to_info(update: HospitalBedUpdate) -> None:
    """TODO(Flask 연동): feature/info 엔드포인트가 정해지면
    requests.post(INFO_URL, json=update.model_dump())로 전송한다. 지금은 info 쪽
    API가 없어 아무 것도 하지 않는다 — 자리만 만들어둔다.
    """
    print(f"  [통신] feature/info로 병상 갱신 전송은 아직 미연동 (자리만 준비됨) — {update.hospitalId}")


def deliver_bed_update(update: HospitalBedUpdate) -> Path:
    """로컬 저장 + (나중에) feature/info로의 통신을 함께 수행하는 단일 진입점.
    deliver()와 이름/구조를 맞춰서, 호출부가 "결과를 어디로 보내든" 같은
    패턴(저장 후 전송 자리 호출)을 따르게 했다.
    """
    saved_path = save_local_bed_update(update)
    send_to_info(update)
    return saved_path
