# OCR 모듈 — 병원 서류 이미지 → 텍스트

병원에서 발급되는 서류 이미지를 넣으면 영역별로 나눠 읽어 텍스트를 만든다.
모든 처리는 로컬에서 이뤄지며 외부 API를 호출하지 않는다 (On-Premise 원칙).

**이 모듈의 범위는 "글자 추출"까지다.** 추출된 텍스트에서 병원 정보 필드를 뽑아
`HospitalInfo` 포맷으로 만드는 단계는 아직 구현하지 않았다 (아래 "다음 작업" 참고).

```
서류 이미지
  → [AI]  레이아웃 검출     영역 위치 + 종류 10종 분류
  → [규칙] 정리·라우팅       중복 제거 → 읽기 순서 → 종류별 태스크 배분
  → [AI]  영역별 인식       표는 표 모드로, 본문은 OCR 모드로
  → [규칙] 검증             반복 생성·토큰 한도 도달 → needs_review
```

CLAUDE.md의 "핵심 AI 활용 원칙"에 따라 각 단계가 AI 처리인지 규칙 기반인지 구분해 두었고,
결과 JSON에도 `source: "ai"` 로 표시된다.

## 왜 영역별로 나누는가

같은 인식 모델인데 **입력 방식만 바꿔** 성능이 크게 달라진다.
한글 실물 문서 15장(핵심 문자열 268개, 사람이 판독한 정답지)으로 측정한 결과다.

| 방식 | 재현율 | VRAM 피크 |
|---|---|---|
| 페이지 전체를 `OCR:` 프롬프트로 한 번에 | 68% | 8,312MB |
| **영역별 분리 + 태스크 라우팅** | **88%** | **2,078MB** |

영역을 나누면 잘라낸 조각이 작아 VRAM이 오히려 4분의 1로 줄고,
페이지 전체를 하나의 프롬프트로 밀어넣을 때 생기던 무한 반복(루프)도 사라진다.
특히 팩스처럼 품질이 나쁜 문서에서 개선 폭이 컸다 (5% → 68%).

## 사용 모델

가중치는 저장소에 커밋하지 않는다. `configs/models.yaml` 에 저장소 ID와 **커밋 SHA**를
고정해두고 스크립트로 내려받는다 (원본이 갱신돼도 같은 결과가 재현되도록).

| 역할 | 모델 | 크기 | 라이선스 |
|---|---|---|---|
| 레이아웃 검출 | [DocLayout-YOLO-DocStructBench](https://huggingface.co/juliozhao/DocLayout-YOLO-DocStructBench) | 77MB (ONNX) | Apache-2.0 |
| 텍스트 인식 | [PaddleOCR-VL-1.6](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6) | 1.8GB | Apache-2.0 |

### ⚠️ 라이선스 주의사항

DocLayout-YOLO는 **가중치(Apache-2.0)와 실행 패키지(AGPL-3.0)의 라이선스가 다르다.**
`doclayout_yolo` 패키지를 그대로 쓰면 AGPL이 전염되어, 서버로 서비스할 때
우리 소스도 AGPL로 공개해야 한다.

그래서 가중치를 ONNX로 변환해 `onnxruntime`(MIT)으로 실행한다.
변환은 `scripts/export_layout_onnx.py` 에서 **1회만** 수행하며, 이 스크립트는
제품 실행 경로에 포함되지 않는다. 전환해도 정확도 손실은 없었다 (87% → 88%).

## 셋업

Python 3.11+ / NVIDIA GPU 필요 (VRAM 4GB 이상 권장).

```bat
:: 1) GPU에 맞는 PyTorch 먼저 (RTX 50 시리즈는 cu128 필수)
pip install torch --index-url https://download.pytorch.org/whl/cu128

:: 2) 나머지 의존성
pip install -r ocr\requirements.txt

:: 3) 모델 내려받기 (약 1.9GB)
python ocr\scripts\download_models.py
```

모델 캐시 위치를 바꾸려면 `HF_HOME` 환경변수를 설정한다 (C드라이브 용량이 빠듯할 때).

ONNX 변환본이 없다는 안내가 나오면 1회만 실행한다 (개발 전용 패키지 필요):

```bat
pip install doclayout-yolo onnx onnxscript
python ocr\scripts\export_layout_onnx.py
```

## 실행

```bat
python ocr\scripts\run_ocr.py <이미지경로>
python ocr\scripts\run_ocr.py <이미지경로> --json
```

라이브러리로 쓸 때:

```python
import sys
sys.path.insert(0, "ocr/src")

from goldenlink_ocr import DocumentOCR

ocr = DocumentOCR()
result = ocr.read("진단서.png")

result["text"]            # 읽기 순서로 결합된 전체 텍스트
result["needs_review"]    # 검토가 필요한 영역이 있는가
result["source"]          # "ai"
for region in result["regions"]:
    region["cls"]           # title / plain text / table / figure ...
    region["task"]          # 어떤 인식 태스크로 읽었는지
    region["needs_review"]  # 이 영역이 검토 대상인지
```

## 구조

| 경로 | 역할 | 구분 |
|---|---|---|
| `src/goldenlink_ocr/layout.py` | ONNX 레이아웃 검출 | AI |
| `src/goldenlink_ocr/router.py` | 중복 제거·읽기 순서·태스크 매핑 | 규칙 |
| `src/goldenlink_ocr/recognizer.py` | PaddleOCR-VL 래퍼 | AI |
| `src/goldenlink_ocr/validator.py` | 반복 생성·잘림 감지 → needs_review | 규칙 |
| `src/goldenlink_ocr/pipeline.py` | 위 넷을 엮는 진입점 | — |
| `src/goldenlink_ocr/config.py` | models.yaml 로더 | — |
| `configs/models.yaml` | 모델 ID·리비전·임계값 | — |
| `scripts/download_models.py` | 가중치 내려받기 | — |
| `scripts/run_ocr.py` | 실행 CLI | — |
| `scripts/export_layout_onnx.py` | ONNX 변환 (**개발 전용, AGPL 의존**) | — |

## 검증이 confidence 만으로 부족한 이유

측정 중에 **모델이 같은 토큰을 무한 반복하는 동안에도 confidence 가 0.99로 나오는** 사례를
확인했다. 출력은 완전히 망가졌는데 신뢰도 지표는 정상으로 보이는 상황이다.

그래서 `validator.py` 는 confidence 대신 두 가지를 본다.

- **토큰 한도 도달** — 출력이 잘렸다는 것은 대개 반복 생성의 신호다
- **고유 토큰 비율** — 실측상 루프는 0.004~0.021, 정상 출력은 0.205~1.000 으로 명확히 갈린다

## 알려진 한계

측정 대상 268개 항목 중 13개는 어떤 방식으로도 읽지 못했다. 유형은 네 가지다.

- 직인이 글자를 덮은 부분 (PaddleOCR-VL 의 Seal 태스크 미적용 — 개선 여지 있음)
- 손글씨
- 세로 병합 셀 안쪽
- 팩스 저품질 문서

또한 워터마크가 깔린 문서에서 **라벨은 읽고 값을 누락**하는 사례가 관측됐다
(`성명` 은 읽고 이름은 비우는 식). 필드 스키마가 정해지면 이를 잡는 검사를 추가해야 한다.

## 다음 작업

이 모듈은 "글자 추출"까지다. feature/info 가 담당하는 전체 흐름에서 남은 부분:

1. **필드 추출** — 텍스트에서 병원 정보 필드를 뽑아 구조화 (sLLM)
2. **값 누락 검사** — 필드 스키마 확정 후 validator 에 추가
3. **HospitalInfo 포맷 변환 및 DB 관리**
4. **feature/hub 로 전송**

라우팅 개선 여지도 남아 있다. 영역당 `OCR:` / `Table Recognition:` 두 모드를 모두 돌려
더 많이 읽은 쪽을 택하면 격자형 명단에서 생기는 라우팅 오판을 흡수할 수 있다.
