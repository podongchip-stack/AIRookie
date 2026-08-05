"""병원 서류 텍스트 → 구조화된 필드. [AI + 규칙]

`goldenlink_ocr`이 이미지에서 글자까지 뽑아주면, 여기서 그 텍스트를 병원 정보
필드로 만든다. 두 패키지를 분리해 둔 이유는 의존성이 다르기 때문이다 —
이쪽은 pydantic만 있으면 돌아서 GPU 없는 장비에서도 추출만 따로 돌릴 수 있다.

    import sys
    sys.path.insert(0, "ocr/src")

    from goldenlink_extract import FieldExtractor, OllamaClient, LlmConfig

    extractor = FieldExtractor(OllamaClient(LlmConfig()))
    fields = extractor.extract(ocr_result, document_id="당직표")

    fields.hospitalName      # 서류에 적힌 기관명
    fields.specialties       # 진료과·인원 (없으면 None)
    fields.capabilities      # 표준 역량 코드 (없으면 None)
    fields.needsReview       # 사람 확인이 필요한가
    fields.evidence          # 값별 원문 근거 (버려진 값 포함)
"""

from .config import ExtractConfig, LlmConfig
from .extractor import FieldExtractor
from .llm import LlmError, OllamaClient, StubLlmClient
from .schema import SCHEMA_VERSION, DocumentFields, Evidence, Specialty

__all__ = [
    "SCHEMA_VERSION",
    "DocumentFields",
    "Evidence",
    "ExtractConfig",
    "FieldExtractor",
    "LlmConfig",
    "LlmError",
    "OllamaClient",
    "Specialty",
    "StubLlmClient",
]
