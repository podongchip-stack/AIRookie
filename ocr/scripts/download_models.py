"""모델 내려받기 — 저장소 클론 후 최초 1회 실행한다.

configs/models.yaml 의 repo_id + revision 을 그대로 받아오므로 팀원 전원이 같은
가중치를 쓰게 된다. 가중치 자체는 저장소에 커밋하지 않는다(1.8GB, 라이선스 원본 유지).

실행:
    C:/Users/podon/anaconda3/envs/ml/python.exe scripts/download_models.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from goldenlink_ocr.config import MODELS_DIR, apply_hf_environment, load_config

apply_hf_environment()

# 일부 환경에서 certifi 신뢰 체인 문제로 HuggingFace 접속이 실패한다.
# truststore가 있으면 시스템 인증서 저장소를 주입해 우회한다 (없으면 그냥 진행).
try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

from huggingface_hub import hf_hub_download, snapshot_download  # noqa: E402


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    config = load_config()

    print("[1/2] 인식 모델 (PaddleOCR-VL)", flush=True)
    path = snapshot_download(config.recognizer.repo_id, revision=config.recognizer.revision)
    print(f"      {config.recognizer.repo_id} @ {config.recognizer.revision[:8]}", flush=True)
    print(f"      → {path}", flush=True)

    print("[2/2] 레이아웃 모델 (DocLayout-YOLO ONNX)", flush=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    cached = hf_hub_download(
        config.layout.repo_id,
        config.layout.onnx_file,
        revision=config.layout.revision,
    )
    shutil.copyfile(cached, config.layout.onnx_path)
    print(f"      {config.layout.repo_id} @ {config.layout.revision[:8]}", flush=True)
    print(f"      → {config.layout.onnx_path} "
          f"({config.layout.onnx_path.stat().st_size / 1e6:.1f}MB)", flush=True)

    print("\n준비 완료. 다음으로 확인:", flush=True)
    print("  python scripts/run_ocr.py <이미지경로>", flush=True)


if __name__ == "__main__":
    main()
