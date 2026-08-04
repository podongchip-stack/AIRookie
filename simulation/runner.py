"""서류를 하나씩 끝까지 처리하고 진행 상황을 큐로 흘려보낸다.

    PDF/이미지 → [규칙] 페이지 렌더링 → [AI] OCR → [AI] 필드 추출 → [규칙] 근거 대조

화면(`gui.py`)과 왜 나눴는가
----------------------------
Tk 위젯은 메인 스레드에서만 건드릴 수 있는데, 서류 한 장 읽는 데 수십 초가 걸린다.
메인 스레드에서 돌리면 창이 통째로 얼어 죽은 것과 구분되지 않는다. 그래서 처리는
워커 스레드에서 하고 화면으로는 **큐를 통해서만** 건넨다.
이 파일에 `tkinter` import가 하나도 없는 것이 그 경계다 — 여기서 위젯을 만지는
코드가 생기면 import가 먼저 눈에 띈다.

대기열
------
서류를 여러 개 놓으면 **순서대로 전부** 처리한다. 처리 중에 더 놓아도 뒤에 붙는다.
예전에는 처리 중에 들어온 것을 무시했는데, 자리를 비운 사이 조용히 빠지는 사고가
실제로 났다(54장 중 1장 누락). 무시하지 않는 편이 맞다.

문서 하나가 실패해도 배치는 계속 간다. 12장을 걸어두고 자리를 비웠는데 3번째에서
멈춰 있으면 배치를 돌린 의미가 없다.

내보내는 이벤트
---------------
`stage` 하나로 구분한다. `ocr`·`extract` 단계 이벤트는 `goldenlink_ocr`과
`goldenlink_extract`가 주는 것을 그대로 흘려보내고 `page`만 얹는다.

    queued       added, pending             대기열에 넣었다
    job_start    name, pages, kind, pending 이 서류를 시작한다
    loading      what("ollama"|"ocr"|"llm") 서버를 켜거나 모델을 올리는 중
    page_start   page, pages, image         이 페이지를 시작한다 (미리보기용 이미지)
    detect       page, count                [AI]  레이아웃 검출
    route        page, regions              [규칙] 중복 제거·읽기 순서·태스크 배분
    recognize    page, index, total, region [AI]  영역 하나를 읽었다
    ocr_done     page, result               한 장의 OCR 완료
    group_start  page, label, index, total  [AI]  필드 그룹 추출 시작
    group_done   page, values, evidence, raw [규칙] 근거 대조까지 끝 (raw는 가공 전 응답)
    group_failed page, error                그룹 하나 실패 (나머지는 계속 간다)
    page_done    page, fields, path         한 장을 끝냈다 (path는 저장을 껐으면 None)
    job_done     pages                      이 서류 끝
    error        message                    이 서류는 더 못 간다 (다음 서류로 넘어간다)
    batch_done   processed, failed, flagged 대기열이 비었다
"""

from __future__ import annotations

import queue
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

import ollama_service
import pdf as pdf_reader
from settings import Settings

OCR_ROOT = Path(__file__).resolve().parents[1] / "ocr"
sys.path.insert(0, str(OCR_ROOT / "src"))
sys.path.insert(0, str(OCR_ROOT / "scripts"))

from goldenlink_extract import ExtractConfig, FieldExtractor  # noqa: E402
from goldenlink_extract.config import KST  # noqa: E402
from goldenlink_extract.llm import LlmError, OllamaClient, StubLlmClient  # noqa: E402

# 결과 파일명 규칙(`YYYYMMDD_HHMMSS_문서명.json`, 덮어쓰지 않음)과 학습 데이터
# 수집을 CLI와 공유한다. 여기서 다시 구현하면 두 경로의 규칙이 언젠가 갈라진다
from run_extract import GroupRecorder, _output_path, save_ocr_text  # noqa: E402


def llm_host() -> str:
    """설정된 Ollama 주소. 화면이 서버 상태를 확인할 때 쓴다.

    환경변수 처리를 여기서 다시 하지 않는다 — 기본값도 `GOLDENLINK_OLLAMA_HOST`도
    `goldenlink_extract`가 이미 알고 있고, 두 벌이 되면 언젠가 갈라진다.
    """
    return ExtractConfig.from_env().llm.host


class DocumentRunner:
    """대기열에 쌓인 서류를 워커 스레드에서 하나씩 처리한다.

    모델은 배치 전체에서 한 번만 올리고 계속 재사용한다 — 서류를 연달아 넣어볼 때
    매번 2GB를 다시 올리면 과정을 보기 전에 기다리다 끝난다.
    """

    def __init__(self, events: queue.Queue) -> None:
        self._events = events
        self._pending: queue.Queue = queue.Queue()
        self._ocr = None
        self._thread: threading.Thread | None = None

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def submit(
        self,
        paths: list[str | Path],
        settings: Settings,
        *,
        autostart_ollama: bool = False,
    ) -> int:
        """서류들을 대기열에 넣는다. 넣은 개수를 돌려준다.

        이미 돌고 있으면 뒤에 붙기만 하고, 아니면 워커를 새로 띄운다.

        `autostart_ollama`는 서버가 꺼져 있을 때 켤지 여부다. 켜는 데 수 초가
        걸려서 화면 스레드가 아니라 워커에서 한다. 켤지 말지는 사람이 고른
        결과여야 한다 — 화면이 물어보고 그 답을 넘긴다.
        """
        for path in paths:
            self._pending.put((Path(path), settings, autostart_ollama))
        self._emit(stage="queued", added=len(paths), pending=self._pending.qsize())

        if not self.busy:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return len(paths)

    # --- 워커 스레드 ---------------------------------------------------------

    def _run(self) -> None:
        """대기열이 빌 때까지 하나씩 처리한다.

        모델 준비는 설정이 바뀔 때만 다시 한다. 같은 설정으로 연달아 돌리는 것이
        보통이라, 이러면 배치 전체에서 로드가 한 번이다.
        """
        processed = failed = flagged = 0
        extractor = None
        prepared_with: Settings | None = None

        while True:
            try:
                path, settings, autostart = self._pending.get_nowait()
            except queue.Empty:
                break

            try:
                if extractor is None or settings != prepared_with:
                    extractor = self._prepare(settings, autostart)
                    prepared_with = settings
                flagged += self._process(path, settings, extractor)
                processed += 1
            except ollama_service.OllamaError as error:
                failed += 1
                self._emit(stage="error", message=f"Ollama를 켜지 못했다.\n{error}")
            except LlmError as error:
                # Ollama가 안 떠 있는 경우가 대부분이다. 추적선을 보여줄 이유가 없다
                failed += 1
                self._emit(
                    stage="error",
                    message=f"LLM을 준비하지 못했다 — Ollama가 실행 중인지 확인할 것\n{error}",
                )
            except Exception as error:  # noqa: BLE001
                # 스레드에서 새어나간 예외는 stderr에만 찍히고 화면은 영영 기다린다.
                # 무엇이 터졌든 화면에는 반드시 도달해야 한다
                failed += 1
                self._emit(
                    stage="error",
                    message=f"{path.name} — {type(error).__name__}: {error}",
                    detail=traceback.format_exc(),
                )

        self._emit(
            stage="batch_done", processed=processed, failed=failed, flagged=flagged
        )

    def _prepare(self, settings: Settings, autostart: bool) -> FieldExtractor:
        """모델과 서버를 올리고 추출기를 만든다."""
        config = ExtractConfig.from_env()

        # 서버를 켜는 일이 가장 먼저다. 여기서 실패할 거라면 OCR 모델 2GB를
        # 올리기 전에 알아야 한다
        if settings.use_llm and autostart and not ollama_service.is_running(config.llm.host):
            self._emit(stage="loading", what="ollama", host=config.llm.host)
            ollama_service.start_and_wait(config.llm.host)

        self._emit(stage="loading", what="ocr")
        self._ensure_ocr()

        if settings.use_llm:
            client = OllamaClient(config.llm)
            self._emit(stage="loading", what="llm", model=config.llm.model)
            client.preload()
        else:
            client = StubLlmClient()
        return FieldExtractor(client, config)

    def _process(self, path: Path, settings: Settings, extractor: FieldExtractor) -> int:
        """서류 1건을 끝까지 처리한다. 검토가 필요한 페이지 수를 돌려준다."""
        is_pdf = pdf_reader.is_pdf(path)
        total = pdf_reader.page_count(path) if is_pdf else 1
        self._emit(
            stage="job_start", name=path.name, pages=total,
            kind="pdf" if is_pdf else "image", pending=self._pending.qsize(),
        )

        flagged = 0
        for page, image in self._pages(path, settings.dpi, is_pdf):
            self._emit(stage="page_start", page=page, pages=total, image=image)

            # 페이지마다 별도 문서로 다룬다. 추출기가 문서 1건 단위라 그 편이
            # 자연스럽고, 당직표 3장이 붙어 있으면 기준일도 장마다 다를 수 있다
            document_id = f"{path.stem}_p{page}" if total > 1 else path.stem

            # 시각을 페이지마다 한 번만 찍는다. OCR 텍스트·원시 응답·추출 결과가
            # 같은 이름으로 남아 어느 것에서 어느 것이 나왔는지 짝지어진다
            stamp = datetime.now(KST)

            result = self._ocr.read(
                image, on_progress=lambda event, p=page: self._emit(page=p, **event)
            )
            if settings.collect_training_data:
                save_ocr_text(document_id, result, stamp, out_dir=settings.ocr_text_path())
            self._emit(stage="ocr_done", page=page, result=result)

            # 진행 이벤트를 가로채 그룹별 LLM 원시 응답을 챙긴다. 화면으로는
            # 그대로 흘려보내므로 표시되는 것은 달라지지 않는다
            recorder = GroupRecorder(lambda event, p=page: self._emit(page=p, **event))
            fields = extractor.extract(result, document_id, on_progress=recorder)
            if settings.collect_training_data:
                recorder.save(
                    document_id, result, fields, stamp, out_dir=settings.llm_raw_path()
                )

            out_path = None
            if settings.save_result:
                out_dir = settings.result_path()
                out_dir.mkdir(parents=True, exist_ok=True)
                out_path = _output_path(out_dir, document_id, stamp)
                out_path.write_text(fields.to_json() + "\n", encoding="utf-8")

            flagged += bool(fields.needsReview)
            self._emit(stage="page_done", page=page, fields=fields, path=out_path)

        self._emit(stage="job_done", pages=total)
        return flagged

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
