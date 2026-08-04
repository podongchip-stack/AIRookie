"""PDF → 페이지 이미지.

`goldenlink_ocr`은 이미지 한 장을 받는다. 병원 서류는 PDF로 들어오는 일이 많아
페이지를 이미지로 바꿔 넣어줘야 한다. 이 파일이 그 사이를 메운다.

왜 pypdfium2 인가 (라이선스)
----------------------------
PDF 렌더링에 가장 흔히 쓰이는 PyMuPDF는 **AGPL-3.0**이다. 이 저장소는 레이아웃
모델을 ONNX로 바꿔가며 AGPL 전염을 피했는데(`ocr/README.md`의 "레이아웃 모델을
ONNX로 쓰는 이유"), 여기서 AGPL 라이브러리를 들이면 그 회피가 무의미해진다.
pypdfium2는 BSD-3-Clause이고 내부의 PDFium도 BSD-3-Clause라 같은 문제가 없다.

텍스트 레이어는 쓰지 않는다
---------------------------
PDF에 텍스트가 박혀 있으면 렌더링 없이 바로 꺼낼 수도 있다. 그러나 이 모듈이
읽어야 할 서류는 대부분 스캔·팩스본이라 텍스트 레이어가 없고, 있더라도 표의
셀 구조가 사라져 `Table Recognition:` 태스크가 무의미해진다. 두 경로를 섞으면
같은 서류인데 결과 형태가 달라지므로 **항상 이미지로 렌더링해 OCR을 태운다.**
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

#: 렌더링 해상도. `ocr/configs/models.yaml`의 두 값에서 역산한 기본값이다.
#: 레이아웃 검출은 입력을 1024px(`layout.imgsz`)로 줄여 쓰고, 인식은 잘라낸 조각을
#: 그대로 쓰되 짧은 변이 320px(`router.min_side`) 미만이면 업스케일한다. 200dpi면
#: A4가 1654×2339라 검출에 충분하고, 표 한 칸을 잘라내도 업스케일 구간에 덜 걸린다.
#: 300dpi는 픽셀이 2.25배로 늘지만 인식 입력만 커진다. 실측으로 고른 값은 아니므로
#: `render_pages(dpi=...)`로 바꿀 수 있게 열어 둔다.
DEFAULT_DPI = 200

#: PDF의 길이 단위(pt)는 72dpi 기준이다. 렌더링 배율은 목표 dpi를 이걸로 나눈 값.
_POINTS_PER_INCH = 72


def is_pdf(path: str | Path) -> bool:
    """PDF인지 파일 앞 5바이트로 판단한다.

    확장자를 믿지 않는 이유는 드래그앤드롭으로 무엇이든 들어올 수 있어서다.
    앞에 다른 바이트가 붙은 변종 PDF는 여기서 걸러지지 않고 이미지로 넘어가는데,
    그 경우 PIL이 열지 못해 오류로 드러나므로 조용히 잘못 처리되지는 않는다.
    """
    try:
        with open(path, "rb") as handle:
            return handle.read(5) == b"%PDF-"
    except OSError:
        return False


def page_count(path: str | Path) -> int:
    """페이지 수. 열지 못하면 `pypdfium2.PdfiumError`."""
    document = pdfium.PdfDocument(path)
    try:
        return len(document)
    finally:
        document.close()


def render_pages(
    path: str | Path, dpi: int = DEFAULT_DPI
) -> Iterator[tuple[int, Image.Image]]:
    """페이지를 하나씩 렌더링해 `(페이지 번호, 이미지)`로 내놓는다. 번호는 1부터.

    리스트로 모아 반환하지 않고 제너레이터로 내놓는다. 200dpi A4 한 장이 RGB로
    약 11MB라 30장짜리 서류면 330MB가 한꺼번에 올라간다. OCR은 어차피 한 장씩
    처리하므로 붙들고 있을 이유가 없다.

    암호가 걸렸거나 깨진 파일은 `pypdfium2.PdfiumError`가 난다. 여기서 잡아
    바꾸지 않는다 — 원본 메시지가 원인을 가장 정확히 말해주기 때문이다.
    """
    document = pdfium.PdfDocument(path)
    try:
        scale = dpi / _POINTS_PER_INCH
        for index in range(len(document)):
            page = document[index]
            try:
                yield index + 1, page.render(scale=scale).to_pil().convert("RGB")
            finally:
                page.close()
    finally:
        document.close()
