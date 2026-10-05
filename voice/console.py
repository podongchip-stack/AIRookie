"""콘솔 출력 인코딩 맞추기(2026-10-03).

Windows 콘솔·파이프의 기본 인코딩(cp949)은 이모지 등 일부 문자를 못 써서, 로그 한 줄에 그런 문자가 섞이면
print가 UnicodeEncodeError로 서버를 죽인다. PYTHONUTF8=1을 주면 피할 수 있지만 매번 넣어야 해서, 실행
진입점에서 stdout/stderr를 UTF-8로 바꿔 둔다. 이미 UTF-8인 환경(Linux·Mac)에서는 아무것도 하지 않는다.
파일 읽기·쓰기는 코드에서 전부 encoding="utf-8"을 명시하므로 여기서 다루지 않는다.
"""
from __future__ import annotations

import sys


def use_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        if stream is not None and encoding != "utf8" and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
