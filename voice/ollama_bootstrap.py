"""오디오 파일만 있으면 구조화(SBAR) 단계까지 전부 자동으로 돌아가도록,
Ollama 설치 -> 서버 실행 -> 모델 준비까지 스스로 처리한다.

summarizer.py가 LLM을 호출하기 직전에 ensure_ollama_ready()만 부르면 된다.
설치는 Homebrew(macOS)로만 시도한다 — 그 외 환경에서는 안내 메시지만 띄우고
사용자가 직접 설치하게 한다 (임의의 설치 스크립트를 실행하는 건 위험하므로).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request

OLLAMA_BASE_URL = "http://localhost:11434"


class OllamaBootstrapError(RuntimeError):
    pass


def _is_server_up() -> bool:
    try:
        urllib.request.urlopen(OLLAMA_BASE_URL, timeout=2)
        return True
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        # 서버가 막 떠서 포트는 열렸지만 아직 응답을 못 주는 콜드스타트 구간도
        # 포함해서 "아직 준비 안 됨"으로 처리하고 폴링을 계속한다.
        return False


def _ensure_binary_installed() -> None:
    if shutil.which("ollama"):
        return
    if not shutil.which("brew"):
        raise OllamaBootstrapError(
            "Ollama가 설치되어 있지 않고, 자동 설치에 필요한 Homebrew도 없습니다. "
            "https://ollama.com 에서 직접 설치한 뒤 다시 실행하세요."
        )
    print("Ollama가 설치되어 있지 않아 Homebrew로 설치를 시작합니다 (brew install ollama)...")
    result = subprocess.run(["brew", "install", "ollama"])
    if result.returncode != 0 or not shutil.which("ollama"):
        raise OllamaBootstrapError("brew install ollama 실패. 수동으로 설치한 뒤 다시 시도하세요.")


def _ensure_server_running(timeout: int = 30) -> None:
    if _is_server_up():
        return
    print("Ollama 서버가 꺼져 있어 백그라운드로 실행합니다 (ollama serve)...")
    subprocess.Popen(
        ["ollama", "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _is_server_up():
            return
        time.sleep(1)
    raise OllamaBootstrapError("Ollama 서버가 제한 시간 내에 뜨지 않았습니다.")


def _is_model_pulled(model: str) -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError):
        return False
    names = {m.get("name") for m in data.get("models", [])}
    # "qwen3:14b"처럼 태그까지 정확히 일치하거나, 태그 생략(:latest) 대응
    return model in names or any(n.startswith(model + ":") for n in names if n)


def _ensure_model_pulled(model: str) -> None:
    if _is_model_pulled(model):
        return
    print(f"'{model}' 모델이 없어 다운로드를 시작합니다 (크기에 따라 수 분~수십 분 소요될 수 있음)...")
    result = subprocess.run(["ollama", "pull", model])
    if result.returncode != 0:
        raise OllamaBootstrapError(f"'{model}' 모델 pull 실패.")


def ensure_ollama_ready(model: str) -> None:
    """설치 -> 서버 실행 -> 모델 pull까지 전부 자동으로 준비한다."""
    _ensure_binary_installed()
    _ensure_server_running()
    _ensure_model_pulled(model)
