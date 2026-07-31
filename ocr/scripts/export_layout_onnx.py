# DocLayout-YOLO 가중치(.pt, Apache-2.0) → ONNX 변환 [1회성 개발 작업]
#
# 이 스크립트만 AGPL-3.0 패키지(doclayout_yolo)에 의존한다.
# 제품 코드는 변환 결과물(.onnx)과 onnxruntime(MIT)만 사용하므로
# 배포물에 AGPL 코드가 포함되지 않는다. 따라서 이 파일은 제품에 포함하지 않는다.

import os
import shutil
import sys
import types
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _stub_matplotlib() -> None:
    """matplotlib 로드가 실패하는 환경을 위한 우회.

    doclayout_yolo는 import 시점에 matplotlib을 요구하지만 변환 경로에서는 쓰지 않는다.
    (Windows에서 ft2font DLL 로드가 실패하는 사례가 있어 넣어둔 안전장치다.)
    """
    try:
        import matplotlib  # noqa: F401
        return
    except ImportError:
        pass

    def _unavailable(*_a, **_k):
        raise RuntimeError("matplotlib 스텁")

    mpl = types.ModuleType("matplotlib")
    pyplot = types.ModuleType("matplotlib.pyplot")
    for fn in ("get_backend", "switch_backend", "close", "rc_context"):
        setattr(pyplot, fn, _unavailable)
    fm = types.ModuleType("matplotlib.font_manager")
    fm.findSystemFonts = lambda *_a, **_k: []
    mpl.pyplot, mpl.font_manager, mpl.rcParams, mpl.use = pyplot, fm, {}, _unavailable
    sys.modules.update({"matplotlib": mpl, "matplotlib.pyplot": pyplot,
                        "matplotlib.font_manager": fm})


_stub_matplotlib()

try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

from doclayout_yolo import YOLOv10
from huggingface_hub import hf_hub_download

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEST = PROJECT_ROOT / "models" / "doclayout_yolo_docstructbench_imgsz1024.onnx"
IMGSZ = 1024


def main() -> None:
    src = hf_hub_download(
        "juliozhao/DocLayout-YOLO-DocStructBench",
        "doclayout_yolo_docstructbench_imgsz1024.pt")
    print(f"원본 가중치: {src}", flush=True)

    model = YOLOv10(src)
    print(f"클래스: {model.names}", flush=True)

    exported = model.export(format="onnx", imgsz=IMGSZ, opset=17, simplify=False)
    print(f"변환 결과: {exported}", flush=True)

    DEST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(exported, DEST)
    print(f"복사 완료: {DEST} ({DEST.stat().st_size / 1e6:.1f}MB)", flush=True)

    # 출력 텐서 형태 확인 (제품 코드에서 후처리를 어떻게 짤지 결정하는 근거)
    import onnxruntime as ort

    sess = ort.InferenceSession(str(DEST), providers=["CPUExecutionProvider"])
    for inp in sess.get_inputs():
        print(f"입력: {inp.name} {inp.shape} {inp.type}", flush=True)
    for out in sess.get_outputs():
        print(f"출력: {out.name} {out.shape} {out.type}", flush=True)


if __name__ == "__main__":
    main()
