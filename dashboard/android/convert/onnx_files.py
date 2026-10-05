"""ONNX 파일 정리 — torch가 텐서마다 따로 쓴 외부 가중치(또는 한 파일에 박힌 가중치)를 <이름>.onnx.data 한 파일로 모은다.
그래프(.onnx, 수백 KB)와 가중치(.onnx.data)를 나누면 휴대폰의 onnxruntime이 가중치를 protobuf로 한 번 더 복사하지 않고
읽는다(불러오는 순간 메모리가 두 배로 뛰지 않는다). 값은 바뀌지 않는다."""

from __future__ import annotations

from pathlib import Path

import onnx


def save_one_file(src: Path, dst: Path) -> None:
    model = onnx.load(str(src), load_external_data=True)
    for old in (dst, dst.with_name(dst.name + ".data")):
        if old != src:
            old.unlink(missing_ok=True)
    onnx.save_model(model, str(dst), save_as_external_data=True, all_tensors_to_one_file=True,
                    location=dst.name + ".data", size_threshold=1024)
