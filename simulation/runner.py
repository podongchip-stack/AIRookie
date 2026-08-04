"""서류 한 건을 끝까지 처리하고 진행 상황을 큐로 흘려보낸다.

    PDF/이미지 → [규칙] 페이지 렌더링 → [AI] OCR → [AI] 필드 추출 → [규칙] 근거 대조

화면(`gui.py`)과 왜 나눴는가
----------------------------
Tk 위젯은 메인 스레드에서만 건드릴 수 있는데, 서류 한 장 읽는 데 수십 초가 걸린다.
메인 스레드에서 돌리면 창이 통째로 얼어 죽은 것과 구분되지 않는다. 그래서 처리는
워커 스레드에서 하고 화면으로는 **큐를 통해서만** 건넨다.
이 파일에 `tkinter` import가 하나도 없는 것이 그 경계다 — 여기서 위젯을 만지는
코드가 생기면 import가 먼저 눈에 띈다.

내보내는 이벤트
---------------
`stage` 하나로 구분한다. `ocr`·`extract` 단계 이벤트는 `goldenlink_ocr`과
`goldenlink_extract`가 주는 것을 그대로 흘려보내고 `page`만 얹는다.

    job_start    name, pages, kind          처리 시작
    loading      what("ocr"|"llm")          모델 올리는 중 (첫 회만 실제로 걸린다)
    page_start   page, pages, image         이 페이지를 시작한다 (미리보기용 이미지)
    detect       page, count                [AI]  레이아웃 검출
    route        page, regions              [규칙] 중복 제거·읽기 순서·태스크 배분
    recognize    page, index, total, region [AI]  영역 하나를 읽었다
    ocr_done     page, result               한 장의 OCR 완료
    group_start  page, label, index, total  [AI]  필드 그룹 추출 시작
    group_done   page, values, evidence     [규칙] 근거 대조까지 끝
    group_failed page, error                그룹 하나 실패 (나머지는 계속 간다)
    page_done    page, fields, path         결과 JSON을 썼다
    job_done     pages                      전부 끝
    error        message                    더 못 간다
"""

from __future__ import annotations

import queue
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

import pdf as pdf_reader

OCR_ROOT = Path(__file__).resolve().parents[1] / "ocr"
sys.path.insert(0, str(OCR_ROOT / "src"))
sys.path.insert(0, str(OCR_ROOT / "scripts"))

from goldenlink_extract import ExtractConfig, FieldExtractor  # noqa: E402
from goldenlink_extract.config import KST  # noqa: E402
from goldenlink_extract.llm import LlmError, OllamaClient, StubLlmClient  # noqa: E402

# 결과 파일명 규칙(`YYYYMMDD_HHMMSS_문서명.json`, 덮어쓰지 않음)을 CLI와 공유한다.
# 여기서 다시 구현하면 두 경로의 규칙이 언젠가 갈라진다
from run_extract import _output_path  # noqa: E402


class DocumentRunner:
    """드롭된 파일을 워커 스레드에서 처리한다. 한 번에 한 건만.

    모델은 처음 한 번만 올리고 계속 재사용한다 — 서류를 연달아 넣어볼 때
    매번 2GB를 다시 올리면 과정을 보기 전에 기다리다 끝난다.
    """

    def __init__(self, events: queue.Queue, out_dir: Path | None = None) -> None:
        self._events = events
        self._out_dir = out_dir or (OCR_ROOT / "output")
        self._ocr = None
        self._thread: threading.Thread | None = None

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def submit(self, path: str | Path, *, use_llm: bool = True, dpi: int = pdf_reader.DEFAULT_DPI) -> bool:
        """처리를 시작한다. 이미 돌고 있으면 아무것도 하지 않고 False."""
        if self.busy:
            return False
        self._thread = threading.Thread(
            target=self._run, args=(Path(path), use_llm, dpi), daemon=True
        )
        self._thread.start()
        return True

    # --- 워커 스레드 ---------------------------------------------------------

    def _run(self, path: Path, use_llm: bool, dpi: int) -> None:
        try:
            self._process(path, use_llm, dpi)
        except LlmError as error:
            # Ollama가 안 떠 있는 경우가 대부분이다. 추적선을 보여줄 이유가 없다
            self._emit(
                stage="error",
                message=f"LLM을 준비하지 못했다 — Ollama가 실행 중인지 확인할 것\n{error}",
            )
        except Exception as error:  # noqa: BLE001
            # 스레드에서 새어나간 예외는 stderr에만 찍히고 화면은 영영 기다린다.
            # 무엇이 터졌든 화면에는 반드시 도달해야 한다
            self._emit(
                stage="error",
                message=f"{type(error).__name__}: {error}",
                detail=traceback.format_exc(),
            )

    def _process(self, path: Path, use_llm: bool, dpi: int) -> None:
        is_pdf = pdf_reader.is_pdf(path)
        total = pdf_reader.page_count(path) if is_pdf else 1
        self._emit(
            stage="job_start", name=path.name, pages=total, kind="pdf" if is_pdf else "image"
        )

        self._emit(stage="loading", what="ocr")
        ocr = self._ensure_ocr()

        config = ExtractConfig.from_env()
        if use_llm:
            client = OllamaClient(config.llm)
            self._emit(stage="loading", what="llm", model=config.llm.model)
            client.preload()
        else:
            client = StubLlmClient()
        extractor = FieldExtractor(client, config)

        self._out_dir.mkdir(parents=True, exist_ok=True)

        for page, image in self._pages(path, dpi, is_pdf):
            self._emit(stage="page_start", page=page, pages=total, image=image)

            # 페이지마다 별도 문서로 다룬다. 추출기가 문서 1건 단위라 그 편이
            # 자연스럽고, 당직표 3장이 붙어 있으면 기준일도 장마다 다를 수 있다
            document_id = f"{path.stem}_p{page}" if total > 1 else path.stem

            result = ocr.read(image, on_progress=lambda event, p=page: self._emit(page=p, **event))
            self._emit(stage="ocr_done", page=page, result=result)

            fields = extractor.extract(
                result, document_id,
                on_progress=lambda event, p=page: self._emit(page=p, **event),
            )
            out_path = _output_path(self._out_dir, document_id, datetime.now(KST))
            out_path.write_text(fields.to_json() + "\n", encoding="utf-8")
            self._emit(stage="page_done", page=page, fields=fields, path=out_path)

        self._emit(stage="job_done", pages=total)

    def _pages(self, path: Path, dpi: int, is_pdf: bool):
        if is_pdf:
            return pdf_reader.render_pages(path, dpi)
        # 미리보기에 쓸 이미지가 필요해 여기서 연다. 실물 촬영본은 EXIF 회전 정보를
        # 반영하지 않으면 누운 채로 처리된다 (pipeline._load_image와 같은 이유)
        return [(1, ImageOps.exif_transpose(Image.open(path)).convert("RGB"))]

    def _ensure_ocr(self):
        # torch를 여기서 처음 import한다. 창을 띄우는 데만 10초씩 걸리지 않도록
        # 모듈 최상단이 아니라 첫 처리 때로 미룬다
        if self._ocr is None:
            from goldenlink_ocr import DocumentOCR

            self._ocr = DocumentOCR()
        return self._ocr

    def _emit(self, **event) -> None:
        self._events.put(event)
