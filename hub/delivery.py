"""hub_engine.py의 결과물을 feature/dashboard로 내보내는 출구(delivery) 계층.

지금은 로컬 파일 저장만 하지만, 나중에 Flask 기반 실시간 통신을 붙일 자리를
미리 분리해뒀다. 엔드포인트가 정해지면 `send_to_dashboard()` 내부만 채우면
되고, 호출부(run_match.py 등)는 `deliver()` 하나만 그대로 쓰면 된다 —
CLAUDE.md의 "모델/API 호출부와 비즈니스 로직은 분리해서 구현한다" 원칙과
동일하게, 저장 방식이 바뀌어도 매칭 로직(hub_engine.py)에는 영향이 없다.

파일명 규칙: feature/voice가 실제로 만드는 파일명이
`<stem>_call_summary.json`이므로(예: DrRomantic3v3_call_summary.json), hub의
결과물도 같은 stem을 이어받아 `<stem>_hub_match_result.json`으로 저장한다.
같은 사건(voice 요약 1건)의 입력과 출력이 파일명만으로 짝지어지므로, 여러 건이
동시에 처리돼도 서로 다른 파일로 섞이지 않는다 (실제 통신 계층에 caseId 같은
필드가 추가되기 전까지, 로컬 저장 단계에서 쓰는 임시 상관관계 키다).

병상 갱신을 feature/info로 되돌려 보내던 경로(`send_to_info()`,
`deliver_bed_update()`, 재시도 대기열)는 2026-08-13부로 제거했다 — info가
병원 Supabase 없이 E-Gen 실 API만 쓰면서(조회 전용이라 쓰기 자체가 불가능)
그 왕복이 의미가 없어졌다. 병상 차감은 이제 hub_engine.py의 TTL 오버레이
(`HubEngine._bed_overlay`)가 읽는 시점에만 적용하고 끝낸다 — 어디에도 쓰지
않으므로 재시도할 대상 자체가 없다.
"""
from __future__ import annotations

from pathlib import Path

from schema import HubMatchResult

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "data" / "test" / "output"
VOICE_SUMMARY_SUFFIX = "_call_summary.json"
RESULT_SUFFIX = "_hub_match_result.json"


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
