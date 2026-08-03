# OCR 모듈 — 병원 서류 이미지 → 구조화된 필드

병원에서 발급되는 서류 이미지를 넣으면 영역별로 나눠 읽어 텍스트를 만들고,
그 텍스트에서 병원 정보 필드를 뽑아 JSON으로 낸다.
모든 처리는 로컬에서 이뤄지며 외부 API를 호출하지 않는다 (On-Premise 원칙).

```
서류 이미지
  → [AI]  레이아웃 검출     영역 위치 + 종류 10종 분류          ┐
  → [규칙] 정리·라우팅       중복 제거 → 읽기 순서 → 태스크 배분  │ goldenlink_ocr
  → [AI]  영역별 인식       표는 표 모드로, 본문은 OCR 모드로    │
  → [규칙] 검증             반복 생성·토큰 한도 → needs_review   ┘
  → [AI]  필드 추출         그룹별 4회 호출, 스키마 제약 디코딩   ┐
  → [규칙] 근거 대조        원문에 없는 값은 버린다               │ goldenlink_extract
  → [규칙] 어휘 검증        표준 역량 코드 밖은 거부              ┘
```

패키지가 둘로 나뉜다. 의존성이 다르기 때문이다 — 추출만 돌릴 때는 torch도
onnxruntime도 필요 없어서, GPU 없는 장비에서 저장된 OCR 결과로 추출 로직만
따로 개발할 수 있다.

| 패키지 | 하는 일 | 필요한 것 |
|---|---|---|
| `goldenlink_ocr` | 이미지 → 텍스트 | NVIDIA GPU, torch, onnxruntime |
| `goldenlink_extract` | 텍스트 → 필드 | pydantic, Ollama 서버 |

CLAUDE.md의 "핵심 AI 활용 원칙"에 따라 각 단계가 AI 처리인지 규칙 기반인지 구분해 두었고,
결과 JSON에도 `source: "ai"` 로 표시된다. 값을 **찾아내는** 일만 AI가 하고,
그 값을 **받아들일지**는 전부 규칙이 정한다.

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

전부 permissive 라이선스이고 전부 로컬에서 돈다.

| 역할 | 모델 | 크기 | 라이선스 | 관리 |
|---|---|---|---|---|
| 레이아웃 검출 | [DocLayout-YOLO-DocStructBench-ONNX](https://huggingface.co/podongchip/DocLayout-YOLO-DocStructBench-ONNX) | 77MB | Apache-2.0 | `configs/models.yaml` |
| 텍스트 인식 | [PaddleOCR-VL-1.6](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6) | 1.8GB | Apache-2.0 | `configs/models.yaml` |
| 필드 추출 | [Qwen3-14B](https://huggingface.co/Qwen/Qwen3-14B) (Ollama `qwen3:14b`, Q4_K_M) | 9.3GB | Apache-2.0 | 환경변수 `GOLDENLINK_LLM_MODEL` |

앞의 두 모델은 가중치를 저장소에 커밋하지 않는다. `configs/models.yaml` 에 저장소
ID와 **커밋 SHA**를 고정해두고 스크립트로 내려받는다 (원본이 갱신돼도 같은 결과가
재현되도록).

LLM은 Ollama가 관리하므로 `models.yaml`에 넣지 않았다. 대신 모델 이름을 코드에
박지 않고 환경변수로 뺐다 — 개발 장비와 실행 장비의 GPU가 달라 쓰는 크기도 다르기
때문이다 (맥 `qwen3:8b` / 5080 `qwen3:14b`, 코드 변경 0).

### 레이아웃 모델을 ONNX로 쓰는 이유 (라이선스)

원본 [DocLayout-YOLO](https://huggingface.co/juliozhao/DocLayout-YOLO-DocStructBench)는
**가중치(Apache-2.0)와 실행 패키지(AGPL-3.0)의 라이선스가 다르다.**
`doclayout_yolo` 패키지를 그대로 쓰면 AGPL이 전염되어, 서버로 서비스할 때
우리 소스도 AGPL로 공개해야 한다.

그래서 Apache-2.0 인 가중치만 ONNX로 변환해 `onnxruntime`(MIT)으로 실행한다.
변환본은 위 저장소에 재배포해 두었고(원본 출처·변경사항·라이선스 명시),
**이 저장소에는 AGPL 코드도, 그것에 의존하는 스크립트도 없다.**
전환해도 정확도 손실은 없었다 (87% → 88%).

가중치는 원본과 동일하며 재학습·파인튜닝하지 않았다.
변환 이력(원본 revision, 변환 설정, 도구 버전)은 위 모델 카드에 기록돼 있다.

## 필드 추출 (`goldenlink_extract`)

텍스트에서 병원 정보 필드를 뽑는다. 서류에는 좌표도 실시간 병상 수도 없으므로
**서류에서 실제로 읽어낸 것만** 담는다. 없는 필드는 키 자체를 넣지 않는다.

| 필드 | 내용 |
|---|---|
| `hospitalName` `hospitalId` | 기관명·기관코드 |
| `documentType` | 당직표 / 진료과안내 / 장비현황 / 병상현황 / 진단서 / 기타 |
| `effectiveDate` | **이 서류가 언제 기준인가.** 서류는 정적이라 이게 없으면 3년 전 당직표를 오늘 것으로 쓰게 된다 |
| `nightDutyAvailable` | 야간 당직 전문의 존재 여부 |
| `specialties[]` | 진료과 · 의사 수 · 시술 태그 · 당직 편성 여부 |
| `capabilities[]` | 표준 역량 코드 7종 (`PROC_PCI_EMERGENCY`, `EQP_CT_24H` …) |
| `equipment[]` | 서류에 적힌 장비명 원문. 표준 코드로 못 바꾼 것도 버리지 않는다 |
| `evidence[]` | 값별 원문 근거. **버려진 값도 남는다** |

`0` / `[]` / 키 없음을 절대 섞지 않는다. `[]`는 "읽었는데 없다", 키 없음은
"확인하지 못했다"이고, 이 둘이 뭉개지면 나중에 합칠 때 모르는 값이 없는 값을 덮는다.

### 환각을 어떻게 막는가

JSON Schema로 디코딩을 제약하면 *형식*은 반드시 맞다. 하지만 **형식이 맞는
거짓말**은 얼마든지 만들어진다. `{"department": "흉부외과", "doctorCount": 3}`은
스키마를 완벽히 만족하지만 서류에 그런 말이 없을 수 있다.

특히 위험한 게 이 모듈의 알려진 실패 사례와 겹친다 — 워터마크 문서에서 **라벨은
읽고 값을 누락**하는 경우(`성명`은 읽고 이름은 비움). 그 빈칸을 LLM이 그럴듯하게
메운다.

그래서 LLM에게 값과 함께 **근거 원문**을 내놓게 하고, 규칙으로 세 겹 검사한다.

| 검사 | 잡는 것 |
|---|---|
| 근거가 원문에 있는가 | 근거 문장 자체를 지어낸 경우 |
| 값이 근거 안에 있는가 | 근거는 진짜인데 값만 다른 경우 (`"흉부외과 2명"` → `doctorCount: 7`) |
| 근거가 값을 뒷받침하는가 | 근거도 진짜, 값도 어휘에 있지만 둘이 무관한 경우 (`"흉부외과 2명"` → 개두술 가능) |

걸린 값은 결과에서 빠지되 `evidence`에 `grounded: false`와 이유가 남는다.
무엇을 왜 버렸는지 사람이 볼 수 있어야 하기 때문이다.

`--llm stub-hallucinate` 로 이 필터가 실제로 거르는지 확인할 수 있다.

### 어휘의 출처

`capabilities`의 역량 코드 7종과 병상 코드 6종은 `Hospital_inform/info/schema.py`
에서 **복사해 왔다.** 최종적으로 `feature/hub`가 대조하는 표준 코드라 우리가
마음대로 만들 수 없다.

import 하지 않고 복사한 이유는, `Hospital_inform/`이 E-Gen API를 다루는 별도
수집 경로라서다. 여기서 의존하면 OCR만 쓰려는 사람도 그 폴더 구조를 갖고 있어야 한다.
대신 복사본이 원본과 어긋나면 알 수 있게 해두었다.

```bat
python ocr\scripts\run_extract.py --check-vocabulary
```

## 셋업

Python 3.11+ / NVIDIA GPU 필요 (VRAM 4GB 이상 권장. 동시 상주는 아래 참고).

```bat
:: 1) GPU에 맞는 PyTorch 먼저 (RTX 50 시리즈는 cu128 필수)
pip install torch --index-url https://download.pytorch.org/whl/cu128

:: 2) 나머지 의존성
pip install -r ocr\requirements.txt -r ocr\requirements-extract.txt

:: 3) OCR 모델 내려받기 (약 1.9GB)
python ocr\scripts\download_models.py

:: 4) LLM 받기 (약 9.3GB)
ollama pull qwen3:14b
```

모델 캐시 위치를 바꾸려면 `HF_HOME` 환경변수를 설정한다 (C드라이브 용량이 빠듯할 때).
OCR 모델 두 개 모두 공개 저장소라 HuggingFace 로그인은 필요 없다.

GPU가 없는 장비에서 추출 로직만 개발한다면 `requirements-extract.txt` 하나면 된다.
저장된 OCR 결과(`run_ocr.py --json`)를 입력으로 넣고, LLM 없이 돌리려면 `--llm stub`.

### 동시 상주 — VRAM 배분

두 모델을 VRAM에 함께 올린 채로 문서를 연달아 처리한다. RTX 5080(16GB) 기준:

| 항목 | VRAM |
|---|---|
| PaddleOCR-VL (영역별 분리) | ~2.1 GB |
| 레이아웃 검출 (onnxruntime CPU) | 0 |
| qwen3:14b Q4_K_M 가중치 | ~9.3 GB |
| KV 캐시 (4K 컨텍스트) + 추론 버퍼 | ~1.2 GB |
| **합계** | **~12.6 GB** |

여유가 부족하면(다른 프로그램이 VRAM을 쓰거나 서류가 아주 클 때) 코드 수정 없이
환경변수만으로 순차 모드로 바꾼다. 실행할 때 실제 점유를 출력하므로 숫자를 보고
판단하면 된다.

```bat
set GOLDENLINK_LLM_KEEP_ALIVE=0     :: 호출이 끝나면 LLM을 내린다
set GOLDENLINK_LLM_MODEL=qwen3:8b   :: 더 작은 모델로 (약 5.2GB)
```

> 실패 방식이 서로 다르다. VRAM이 모자라면 Ollama는 일부 레이어를 CPU로 내려
> **느려지지만** PaddleOCR-VL(torch)은 **OOM으로 죽는다.** 여유는 OCR 쪽에 준다.

## 실행

```bat
:: 이미지 → 텍스트만
python ocr\scripts\run_ocr.py <이미지경로>
python ocr\scripts\run_ocr.py <이미지경로> --json

:: 이미지 → 필드까지 (OCR + LLM 동시 상주)
python ocr\scripts\run_extract.py --image <이미지경로> [...]

:: 저장된 OCR 결과에서 필드만 (GPU 불필요)
python ocr\scripts\run_extract.py --ocr-json <결과.json>

:: LLM 없이 로직만 / 환각 필터 확인
python ocr\scripts\run_extract.py --ocr-json <결과.json> --llm stub
python ocr\scripts\run_extract.py --ocr-json <결과.json> --llm stub-hallucinate
```

결과는 `ocr/output/`에 `YYYYMMDD_HHMMSS_<문서명>.json`으로 **쌓인다.** 덮어쓰지
않는다 — 프롬프트나 모델을 바꿔가며 돌렸을 때 이전 결과와 비교할 수 있어야 하고,
의료 정보 추출 이력은 지우지 않는 편이 맞다. (커밋되지 않는 폴더다.)

라이브러리로 쓸 때:

```python
import sys
sys.path.insert(0, "ocr/src")

from goldenlink_ocr import DocumentOCR
from goldenlink_extract import FieldExtractor, OllamaClient, LlmConfig

ocr = DocumentOCR()
result = ocr.read("당직표.png")

result["text"]            # 읽기 순서로 결합된 전체 텍스트
result["needs_review"]    # 검토가 필요한 영역이 있는가
for region in result["regions"]:
    region["cls"]           # title / plain text / table / figure ...
    region["task"]          # 어떤 인식 태스크로 읽었는지

extractor = FieldExtractor(OllamaClient(LlmConfig()))
fields = extractor.extract(result, document_id="당직표")

fields.hospitalName       # 서류에 적힌 기관명
fields.effectiveDate      # 언제 기준 서류인가
fields.specialties        # 진료과·인원 (못 읽었으면 None)
fields.capabilities       # 표준 역량 코드 (못 읽었으면 None)
fields.needsReview        # 사람 확인이 필요한가
fields.evidence           # 값별 원문 근거 (버려진 값 포함)
print(fields.to_json())
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
| `src/goldenlink_extract/prompts.py` | 필드 그룹 정의 + JSON Schema | — |
| `src/goldenlink_extract/llm/ollama.py` | Ollama 호출 (구조화 출력) | AI |
| `src/goldenlink_extract/llm/stub.py` | LLM 없이 도는 구현 (개발·테스트) | 규칙 |
| `src/goldenlink_extract/grounding.py` | 근거 대조 — 환각 필터 | 규칙 |
| `src/goldenlink_extract/schema.py` | 출력 형식 + 어휘 검증 | 규칙 |
| `src/goldenlink_extract/vocabulary.py` | 표준 코드 (복사본) + 서류 종류 | — |
| `src/goldenlink_extract/extractor.py` | 위를 엮는 본체 | — |
| `src/goldenlink_extract/config.py` | 모델·동작 설정 (환경변수) | — |
| `configs/models.yaml` | OCR 모델 ID·리비전·임계값 | — |
| `scripts/download_models.py` | OCR 가중치 내려받기 | — |
| `scripts/run_ocr.py` | 텍스트 추출 CLI | — |
| `scripts/run_extract.py` | 필드 추출 CLI | — |

### 왜 필드 그룹별로 나눠 호출하는가

서류 한 장을 주고 "필드 전부 뽑아줘"라고 하면 세 가지가 나빠진다.

1. 출력이 길어질수록 뒷부분에서 환각이 는다. 앞에서 만든 문맥에 스스로 끌려간다
2. 한 항목이 틀려도 전체를 다시 불러야 한다. 그룹별이면 실패한 것만 재시도한다
3. 어느 단계가 틀렸는지 분리가 안 돼 프롬프트를 고칠 근거가 안 남는다

그래서 서류 기본정보 / 야간 당직 / 진료과·인력 / 시술·장비 4개로 쪼개
문서 1장당 4회 호출한다. 그룹 하나가 실패해도 나머지는 살린다.

### 모델을 왜 직접 로드하지 않고 Ollama를 쓰는가

- **구조화 출력** — `format`에 JSON Schema를 주면 문법 제약 디코딩이 걸려 형식이
  깨진 출력 자체가 생성되지 않는다. 파싱 실패를 재시도로 때우는 것과는 다른 층위다.
  역량 코드는 `enum`으로 제약해 어휘 밖 값이 **물리적으로 생성될 수 없게** 만든다
- **팀 스택 일치** — CLAUDE.md의 voice 출력 예시가 `"llm": "qwen3:14b"`인데
  이건 Ollama 모델 태그 표기다
- **프로세스 분리** — OCR(torch)과 같은 파이썬 프로세스에 LLM을 올리지 않는다.
  한쪽이 죽어도 다른 쪽은 살아 있다
- **의존성 0** — HTTP 호출은 표준 라이브러리 `urllib`로 한다

호출부는 `LlmClient` Protocol 뒤에 있어서 모델을 바꿔도 추출 로직은 손대지 않는다
(CLAUDE.md의 "모델/API 호출부와 비즈니스 로직은 분리" 규칙).

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
(`성명` 은 읽고 이름은 비우는 식). 이 빈칸을 LLM이 메우는 것이 추출 단계의
가장 큰 위험이라, 근거 대조로 막고 있다 (위 "환각을 어떻게 막는가").

### 추출 단계에서 아직 검증되지 않은 것

**실제 LLM으로 돌린 실측이 없다.** 지금까지 확인한 것은 로직(근거 대조·어휘 검증·
결측 처리)이 의도대로 동작한다는 것까지이고, `qwen3:14b`가 실제 병원 서류에서
필드를 얼마나 뽑는지는 GPU 장비에서 재봐야 한다. 재야 할 숫자는 둘이다.

- **재현율** — 사람이 읽은 정답 대비 몇 개를 뽑는가
- **근거 통과율** — 뽑은 값 중 몇 개가 근거 대조를 통과하는가.
  이 값이 낮으면 프롬프트 문제이고, 높은데 재현율이 낮으면 OCR 품질 문제다

`CAPABILITY_EVIDENCE_TERMS`(역량 코드별 인정 표현)도 실제 서류 표기를 보고
넓혀야 한다. 지금 목록은 예상 표현이라 실물에서 놓치는 것이 있을 수 있다.

## 다음 작업

1. **실측** — 실제 서류로 재현율·근거 통과율 측정 (위 참고)
2. **`HospitalInfo` 병합** — 서류에서 뽑은 필드를 E-Gen 실시간 데이터와 합친다.
   서류는 정적이라 좌표·실시간 병상 수는 건드리지 않고, E-Gen이 못 채우는
   당직·인력만 덮는다. 어느 값이 어디서 왔는지(AI/규칙) 표기하는 방식은 미정
3. **feature/hub 로 전송**

라우팅 개선 여지도 남아 있다. 영역당 `OCR:` / `Table Recognition:` 두 모드를 모두 돌려
더 많이 읽은 쪽을 택하면 격자형 명단에서 생기는 라우팅 오판을 흡수할 수 있다.
