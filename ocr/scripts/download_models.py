"""모델 내려받기 — 저장소 클론 후 최초 1회 실행한다.

configs/models.yaml 의 repo_id + revision 을 그대로 받아오므로 팀원 전원이 같은
가중치를 쓰게 된다. 가중치 자체는 저장소에 커밋하지 않는다(1.8GB, 라이선스 원본 유지).

실행:
    C:/Users/podon/anaconda3/envs/ml/python.exe scripts/download_models.py
"""

from __future__ import annotations

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

    print("[2/2] 레이아웃 모델 (DocLayout-YOLO)", flush=True)
    onnx_path = config.layout.onnx_path
    if onnx_path.exists():
        print(f"      ONNX 이미 존재: {onnx_path} ({onnx_path.stat().st_size / 1e6:.1f}MB)",
              flush=True)
    else:
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        pt_path = hf_hub_download(
            config.layout.repo_id,
            config.layout.weight_file,
            revision=config.layout.revision,
        )
        print(f"      원본 가중치 → {pt_path}", flush=True)
        print(f"      ONNX 변환본이 없다. scripts/export_layout_onnx.py 를 1회 실행한다:",
              flush=True)
        print(f"        python scripts/export_layout_onnx.py", flush=True)
        print(f"      (변환에는 AGPL-3.0 패키지 doclayout-yolo 가 필요하다. "
              f"제품 실행에는 불필요하다.)", flush=True)
        return

    print("\n준비 완료. 다음으로 확인:", flush=True)
    print("  python scripts/run_ocr.py <이미지경로>", flush=True)


if __name__ == "__main__":
    main()
