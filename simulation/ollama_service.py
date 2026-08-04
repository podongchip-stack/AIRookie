"""Ollama 서버가 떠 있는지 보고, 필요하면 켠다.

GUI에서 서류를 놓고 30초를 기다렸는데 "Ollama에 접속하지 못했다"로 끝나는 것을
막으려고 만들었다. 시작하기 전에 미리 알고, 켤지 Stub으로 갈지 사람이 고른다.

화면도 OCR도 모른다 — 표준 라이브러리만 쓴다. `goldenlink_extract`가 Ollama를
`urllib`로만 부르는 것과 같은 이유다. 상태 한 번 보자고 의존성을 더할 이유가 없다.

**서버를 켜면 GUI를 닫아도 남는다.** 그게 Ollama의 정상 동작이라(데스크톱 앱도
백그라운드로 띄워 둔다) 일부러 정리하지 않는다. 다음 실행에서 그대로 재사용된다.
"""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.error
import urllib.request

#: 상태 확인에 쓰는 경로. 모델 목록 조회라 서버에 아무 영향이 없다
_TAGS_PATH = "/api/tags"

#: 켠 뒤 응답할 때까지 기다리는 한도(초).
#: 실측 22초(Windows, 서버가 완전히 꺼진 상태에서)라 30초로는 여유가 없다.
#: 준비되는 즉시 반환하므로 넉넉히 잡아도 손해가 없다 — 이 값은 "포기하는 시점"이다.
DEFAULT_START_TIMEOUT = 60.0


class OllamaError(RuntimeError):
    """서버를 켜지 못했다."""


def is_running(host: str, timeout: float = 0.5) -> bool:
    """서버가 응답하는가.

    타임아웃을 짧게 잡는다. 이 함수는 화면을 그리는 스레드에서도 불리므로
    꺼져 있는 주소를 붙들고 있으면 창이 그만큼 멎는다. 로컬 주소라 살아 있으면
    수 ms 안에 답이 오고, 꺼져 있으면 연결 거부가 즉시 돌아온다.
    """
    try:
        with urllib.request.urlopen(f"{host.rstrip('/')}{_TAGS_PATH}", timeout=timeout) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def start_and_wait(host: str, timeout: float = DEFAULT_START_TIMEOUT) -> None:
    """`ollama serve`를 띄우고 응답할 때까지 기다린다. 이미 떠 있으면 아무것도 안 한다.

    시간이 걸리는 함수다(수 초~수십 초). 화면 스레드에서 부르면 창이 얼어붙으므로
    워커 스레드에서 불러야 한다.
    """
    if is_running(host):
        return

    # 콘솔 창이 따로 뜨지 않게 한다. 서버 로그는 어차피 우리가 읽지 않는다
    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
    except FileNotFoundError:
        raise OllamaError(
            "`ollama` 실행 파일을 찾지 못했다.\n"
            "설치돼 있는지, PATH에 잡히는지 확인할 것 (터미널에서 `ollama --version`)."
        ) from None
    except OSError as error:
        raise OllamaError(f"Ollama를 실행하지 못했다: {error}") from None

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_running(host):
            return
        time.sleep(0.4)

    raise OllamaError(
        f"{timeout:.0f}초 안에 Ollama가 응답하지 않았다 ({host}).\n"
        "다른 프로그램이 포트를 잡고 있거나 서버가 뜨다 말았을 수 있다."
    )
