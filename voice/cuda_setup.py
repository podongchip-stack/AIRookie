"""pip으로 설치한 NVIDIA CUDA 런타임 DLL을 Windows DLL 검색 경로에 등록한다.

faster-whisper(ctranslate2)는 GPU를 쓸 때 cublas64_12.dll / cudnn 계열을
LoadLibrary로 찾는다. 그런데 pip의 nvidia-cublas-cu12 / nvidia-cudnn-cu12 패키지는
DLL을 site-packages 안에만 넣고 PATH에는 올리지 않아서, 그대로 두면

    RuntimeError: Library cublas64_12.dll is not found or cannot be loaded

로 죽는다. GPU·드라이버·패키지가 전부 정상인데도 경로를 못 찾아서 나는 실패라
헷갈리기 쉽다 (이 저장소 개발 PC에서 실제로 재현됨).

**faster_whisper보다 먼저 import돼야 한다.** transcribe.py가 `import cuda_setup`을
faster_whisper 위에 두는 이유이고, 모듈 이름이 알파벳순으로 faster_whisper보다
앞서서 import를 정렬해도 순서가 유지된다.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def register_nvidia_dlls() -> None:
    """nvidia 패키지의 bin 폴더를 DLL 검색 경로에 추가한다 (Windows 전용).

    os.add_dll_directory가 Windows에만 있는 함수라 맥/리눅스에서는 아무것도 하지
    않고 빠진다. 맥은 CTranslate2가 Metal/MPS를 지원하지 않아 어차피 CPU로만 돌고,
    리눅스는 DLL이 아니라 LD_LIBRARY_PATH 방식이라 이 함수로는 다룰 수 없다.

    패키지 위치는 sys.executable이 아니라 find_spec으로 찾는다 - conda 환경은
    <env>/Lib/site-packages지만 venv는 sys.executable의 부모가 Scripts/라서,
    경로를 직접 조립하면 venv에서 엉뚱한 곳을 보게 된다.

    nvidia 패키지가 아예 없어도 조용히 넘어간다. 그 경우 GPU를 못 쓸 뿐이고,
    transcribe.py의 cpu 폴백이 받아준다.
    """
    if not hasattr(os, "add_dll_directory"):
        return

    spec = importlib.util.find_spec("nvidia")
    if spec is None or not spec.submodule_search_locations:
        return

    base = Path(next(iter(spec.submodule_search_locations)))
    for sub in ("cublas", "cudnn"):
        bin_dir = base / sub / "bin"
        if bin_dir.is_dir():
            os.add_dll_directory(str(bin_dir))
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


register_nvidia_dlls()
