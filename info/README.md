# [feature/info] — 병원 정보 수집·정규화 (E-Gen API + 서류 OCR)

> **브랜치 이름 변경 안내**: 이 브랜치는 기존 `feature/vital`에서 이름이
> 변경되었습니다. **병원 매칭·존(Zone) 로직은** `feature/hub`**로 이관하는 것으로
> 확정**되어 구 스키마(존 기반 병원 매칭 결과)는 이 문서에서 제거했습니다.
> dashboard가 보내는 승인 액션(hospital_approve/hospital_reject/final_approval)의
> 수신 주체도 `feature/hub`**로 확정**되었습니다 (dashboard는 feature/hub와만
> 직접 통신하기 때문). 이 브랜치는 승인 액션을 직접 받지 않는 대신, hub가
> 확정 처리 후 내려주는 "병상 갱신 알림"을 받는다 (아래 참고).

## 담당자

- 이름: 김동현
- 역할: 리드 개발자



- 이름: 최준혁
- 역할: 리드 개발자

## 이 브랜치가 하는 일

응급의료기관의 상태를 모아 **표준 형식(`HospitalInfo`)으로 정규화해
`feature/hub`에 공급**한다. 환자에게 어느 병원이 적합한지는 판정하지 않는다 —
그건 `feature/hub`의 몫이다.

데이터 소스가 둘이고 성격이 정반대인 것이 이 브랜치의 특징이다.

| | 경로 A — E-Gen 공개 API | 경로 B — 병원 서류 OCR |
|---|---|---|
| 폴더 | [`Hospital_inform/`](Hospital_inform/README.md) | [`ocr/`](ocr/README.md) |
| 범위 | 전국 전 기관 | 소수 기관 |
| 실시간성 | 실시간 | 정적 (서류 발급 시점) |
| 깊이 | 얕음 — 병상 수, 중증질환 수용 가능 여부 | 깊음 — 당직 전문의, 진료과별 인력 |
| 처리 | 규칙 기반 (AI 미사용) | AI(레이아웃·인식·추출) + 규칙(검증) |
| 현재 상태 | 서비스키 승인 대기 — fixture로 개발 | 로직 완성 — 실측 대기 |

**당직 전문의 정보는 공개 API로 나오지 않는다.** 그 공백을 서류 OCR로 메우는 것이
이 브랜치의 고유 가치다. 다만 E-Gen의 "중증질환 수용가능 정보"가 그 상당 부분을
대체할 수 있는지가 아직 미검증이라, 서비스키 승인 후 커버리지 실측으로 판단한다
([`Hospital_inform/README.md`](Hospital_inform/README.md) "미해결 항목" 참고).

```
[경로 A] E-Gen 공개 API
    ├─ getEgytListInfoInqire               좌표 · 기관분류
    ├─ getEmrrmRltmUsefulSckbdInfoInqire   실시간 가용병상
    └─ getSrsillDissAceptncPosblInfoInqire 중증질환 수용가능
         ↓ [규칙] 3개 응답을 hpid로 합치고 결측 처리 (egen/mapper.py)
      HospitalInfo ──────────────────────────────────────┐
                                                         │
[경로 B] 병원 서류 이미지                                  │
         ↓ [AI]  레이아웃 검출 → 영역별 텍스트 인식        │
      텍스트                                              │
         ↓ [AI]  필드 그룹별 추출 (JSON Schema 제약 디코딩) │
         ↓ [규칙] 근거 대조(환각 필터) · 어휘 검증          │
      DocumentFields ──→ (병합 미구현) ───────────────────┤
                                                         ↓
                                                   feature/hub
```

두 경로의 **합류 지점(`DocumentFields` → `HospitalInfo` 병합)은 아직 미구현**이다.
현재는 각 경로가 독립적으로 자기 산출물을 낸다.

## 사용한 AI / 모델

| 구분 | 모델명 | 용도 | 비고 |
| --- | --- | --- | --- |
| 레이아웃 검출 | [DocLayout-YOLO-DocStructBench-ONNX](https://huggingface.co/podongchip/DocLayout-YOLO-DocStructBench-ONNX) | 서류 이미지에서 영역 위치·종류(10종) 검출 | Apache-2.0. 원본 가중치를 ONNX로 변환해 재배포한 것 — 원본 실행 패키지가 AGPL-3.0이라 `onnxruntime`(MIT)으로 실행 |
| 텍스트 인식 | [PaddleOCR-VL-1.6](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6) (0.9B) | 잘라낸 영역별 텍스트 추출 (표는 표 인식 모드) | Apache-2.0. 로컬 실행, 외부 API 미사용 |
| 정보 구조화 | qwen3:14b (Ollama) | 추출된 텍스트 → 병원 정보 필드 | Apache-2.0. 로컬 실행. JSON Schema 제약 디코딩으로 형식 보장. 모델명은 환경변수로 교체 가능 |

상세 내용은 [`ocr/README.md`](ocr/README.md) 참고.

> CLAUDE.md의 "핵심 AI 활용 원칙" 표 기준으로, 이 기능이 AI 처리 영역인지 규칙 기반 영역인지 명시:
>
> - [x] AI 처리 — 서류 이미지의 레이아웃 검출·텍스트 인식, 텍스트에서 필드 추출
> - [x] 규칙 기반 — 영역 정리·태스크 라우팅, 근거 대조·어휘 검증, E-Gen 정규화, hub 연동

한 브랜치 안에서 두 영역이 나뉜다. 경로 A는 전부 규칙 기반이고, 경로 B는 단계별로
갈린다. **값을 찾아내는 일만 AI가 하고, 그 값을 받아들일지는 전부 규칙이 정한다.**
결과 JSON에 `source: "ai"` / `"rule"` 로 표시된다.

## 개발 환경 / 언어

- 언어: Python 3.11 (`requirements.txt` 상단 주석 참고)
- 실행 환경: 로컬 (On-Premise 원칙 — 환자·병원 데이터가 외부 상용 API로 나가지 않는다)

의존성이 셋으로 나뉜다. 목적이 다르고, 하나만 필요한 경우가 많기 때문이다.

| 파일 | 내용 | 언제 필요한가 |
|---|---|---|
| `requirements.txt` | Flask, Flask-SocketIO, requests, python-dotenv | 서버·E-Gen API 호출. **서버는 아직 미구현**(의존성만 선언) |
| `ocr/requirements.txt` | torch, transformers, onnxruntime, opencv 등 | 서류 이미지 → 텍스트. **NVIDIA GPU 필요** |
| `ocr/requirements-extract.txt` | pydantic | 텍스트 → 필드. GPU 불필요, Ollama 서버만 있으면 됨 |
| `simulation/requirements.txt` | tkinterdnd2, pypdfium2 | 처리 과정을 보는 GUI. 위 두 개 위에 창만 얹는다 |

`LLMdata/`는 코드가 아니라 데이터라 의존성이 없다 — 서류 원본과, 처리하면서 쌓이는
학습용 입력·타깃이 들어간다.

`Hospital_inform/`(경로 A)은 pydantic만 있으면 돌아간다 — torch도 onnxruntime도
필요 없다. GPU 없는 장비에서 E-Gen 정규화와 필드 추출 로직을 개발할 수 있게
의존성을 이렇게 갈라 두었다.

> `requirements.txt`의 주석은 외부 API를 "hv1(전문의 보유) / hvec(병상 현황) /
> hv2(중증질환별 수용 가능)"로 적고 있는데 **이는 CLAUDE.md에서 온 명세 오류다.**
> `hv1`·`hv2`는 별도 API가 아니라 가용병상 응답 안의 필드이고, 뜻도 각각 응급실
> 당직의 직통 전화번호·내과중환자실 병상 수다. 정정 요청 내용은
> [`Hospital_inform/README.md`](Hospital_inform/README.md) "팀 확인 요청" 참고.

## 입출력 데이터 포맷 (약식)

> 환자 바이탈 정보는 더 이상 사용하지 않기로 결정되어, 기존에 있던 "바이탈
> 스트림 → dashboard" 스키마는 이 문서에서 제거했습니다.

> 존 기반 병원 매칭 결과 스키마는 `feature/hub` 신설로 대체되어 이 문서에서
> 제거했습니다. 최신 스키마는 `feature/hub` README.md의 "입출력 데이터 포맷 >
> 출력 스키마 4"를 참고하세요.

### 통합 데이터 모델: HospitalInfo

`feature/info`와 `feature/hub` 사이를 오가는 두 메시지(아래 1·2번)는 서로 다른
스키마가 아니라, **같은 병원 레코드(HospitalInfo)를 서로 다른 크기로 주고받는
것**이다. info가 hub로는 전체 레코드를 보내고, hub가 info로는 병상 수만 담은
부분 갱신(patch)을 돌려준다 — 필드 집합은 아래 표 하나를 기준으로 통일한다.

| 필드                                  | 타입                           | 설명                                            | 1번(info→hub 전체 전송) | 2번(hub→info 부분 갱신)                    |
| ----------------------------------- | ---------------------------- | --------------------------------------------- | ------------------ | ------------------------------------- |
| `hospitalId`                        | string                       | 병원 고유 식별자                                     | 포함                 | 포함 (대상 식별용)                           |
| `name`                              | string                       | 병원명                                           | 포함                 | 미포함 (안 바뀌는 값)                         |
| `gps.lat` / `gps.lng`               | number                       | 병원 위치 좌표 (Hub의 거리 계산에 사용)                     | 포함                 | 미포함                                   |
| `availableBedCount`                 | number                       | 실시간 가용 응급실 병상 수                               | 포함 (현재값)           | 포함 (hub가 확정 처리 후 계산한 최신값 — 이 값으로 덮어씀) |
| `nightDutyAvailable`                | boolean                      | 야간 당직 전문의 존재 여부                               | 포함                 | 미포함                                   |
| `specialties[].department`          | string                       | 진료과명                                          | 포함                 | 미포함                                   |
| `specialties[].doctorCount`         | number                       | 해당 진료과 수술 가능 의사 수                             | 포함                 | 미포함                                   |
| `specialties[].recentProcedureTags` | string[]                     | 최근 수술 이력 기반 전문 분야 태그 (개인정보 블라인드 처리, 가안 DB 기반) | 포함                 | 미포함                                   |
| `status`                            | `"confirmed"` \| `"rejected"` | 이 갱신이 발생한 사유                                 | 미포함 (해당 없음)        | 포함                                    |
| `source`                            | `"rule"`                     | 규칙 기반 데이터임을 나타내는 고정값                          | 포함                 | 포함                                    |
| `updatedAt`                         | string (ISO 8601)            | 이 레코드/갱신이 마지막으로 발생한 시각                        | 포함                 | 포함                                    |

위 표가 **팀 합의 기준**이다. 여기에 더해 `Hospital_inform/`은 아래 두 필드를
optional 확장으로 덧붙여 내보낸다. 기존 필드는 하나도 바꾸지 않았고, hub의
`HospitalInfo`는 모르는 필드를 무시하므로(pydantic 기본 동작) 지금 보내도 아무것도
깨지지 않는다. **아직 합의 전이며 제안 상태다.**

| 필드 | 타입 | 설명 | 상태 |
|---|---|---|---|
| `bedsByType` | `{[코드]: number}` | 병상 종류별 가용 수 (`ER_ADULT`, `ER_PEDIATRIC`, `ICU` …). 성인/소아 분기의 핵심. **미상인 종류는 키 자체를 넣지 않는다** | 확장 (제안) |
| `capabilities` | string[] | 수행 가능한 시술·장비 표준 코드 (`PROC_PCI_EMERGENCY`, `EQP_CT_24H` …). hub의 하드필터 대조 대상 | 확장 (제안) |

배경은 [`Hospital_inform/hospital-info-interface-proposal.md`](Hospital_inform/hospital-info-interface-proposal.md) 참고.

### 1. feature/info → feature/hub (HospitalInfo 전체 전송)

> `feature/hub` 신설에 따라 추가된 스키마. `feature/hub`가 실제로 받는
> 입력 형태와 동일하다. 가안이며 팀 리뷰 후 확정 예정.

**출력** (위 HospitalInfo 표의 "1번" 열에 해당하는 필드 전부)

```json
{
  "hospitalId": "H001",
  "name": "○○병원",
  "gps": { "lat": 35.1795, "lng": 128.1076 },
  "availableBedCount": 12,
  "nightDutyAvailable": true,
  "specialties": [
    {
      "department": "흉부외과",
      "doctorCount": 3,
      "recentProcedureTags": ["기흉", "흉부외상"]
    }
  ],
  "source": "rule",
  "updatedAt": "2026-07-29T10:00:00Z"
}
```

### 2. feature/hub → feature/info (HospitalInfo 부분 갱신 — 병상 수만, 신규)

> dashboard의 승인 액션은 feature/hub가 직접 받는다 (feature/info는 받지 않음).
> 대신 `final_approval`로 이송이 확정되면, 같은 병상에 다른 구급차가 중복
> 매칭되는 걸 막기 위해 hub가 이 브랜치에 갱신된 병상 수를 알려준다. 동시에
> 여러 구급차가 매칭 중일 수 있어서 필요한 흐름이다 — 외부 API의 갱신 주기만으로는
> 확정 시점에 바로 반영이 안 될 수 있기 때문. 위 HospitalInfo의 다른 필드
> (name/gps/nightDutyAvailable/specialties)는 hub가 바꿀 이유가 없어서 이 메시지엔
> 담지 않는다 — 받은 쪽(info)은 `hospitalId`로 기존 레코드를 찾아
> `availableBedCount`만 덮어쓰면 된다.

**입력** (위 HospitalInfo 표의 "2번" 열에 해당하는 필드만)

```json
{
  "hospitalId": "H001",
  "availableBedCount": 11,
  "status": "confirmed",
  "updatedAt": "2026-07-30T14:20:00Z",
  "source": "rule"
}
```

### 3. 서류 1장 → DocumentFields (브랜치 내부 중간 산출물, 신규)

경로 B가 서류 1장에서 뽑아내는 형식이다. **hub로 보내는 계약이 아니라 브랜치
내부 산출물**이며, `HospitalInfo`와 합치는 단계가 아직 없다.

서류에는 좌표도 실시간 병상 수도 없으므로 `HospitalInfo`가 될 수 없다. 그래서
**서류에서 실제로 읽어낸 것만** 담고, 못 읽은 필드는 키 자체를 넣지 않는다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `hospitalName` / `hospitalId` | string | 기관명 · 기관코드(서류에 인쇄된 경우만) |
| `documentType` | string | 당직표 / 진료과안내 / 장비현황 / 병상현황 / 진단서 / 기타 |
| `effectiveDate` | string | **이 서류가 언제 기준인가.** 서류는 정적이라 이게 없으면 3년 전 당직표를 오늘 것으로 쓰게 된다 |
| `nightDutyAvailable` | boolean | 야간 당직 전문의 존재 여부 |
| `specialties[]` | object[] | 진료과 · 의사 수 · 시술 태그 · 당직 편성 여부 |
| `capabilities[]` | string[] | 표준 역량 코드 (위 확장 필드와 같은 어휘) |
| `equipment[]` | string[] | 서류에 적힌 장비명 원문. 표준 코드로 못 바꾼 것도 버리지 않는다 |
| `evidence[]` | object[] | 값별 원문 근거. **근거 대조에서 버려진 값도 남는다** |
| `needsReview` / `reviewReasons` | boolean / string[] | 사람 확인이 필요한가, 그 이유 |
| `source` | `"ai"` | AI 산출물임을 나타내는 고정값 |

```json
{
  "hospitalName": "○○대학교병원 응급의료센터",
  "documentType": "DUTY_ROSTER",
  "effectiveDate": "2026-08",
  "nightDutyAvailable": true,
  "specialties": [
    { "department": "흉부외과", "doctorCount": 2, "procedureTags": [] }
  ],
  "capabilities": ["EQP_ANGIO_SUITE", "EQP_CT_24H", "PROC_PCI_EMERGENCY"],
  "evidence": [
    {
      "field": "specialties[0].department",
      "value": "흉부외과",
      "sourceText": "흉부외과 2명",
      "grounded": true,
      "regionIndex": 2
    }
  ],
  "needsReview": false,
  "reviewReasons": [],
  "documentId": "당직표",
  "extractedAt": "2026-08-03T21:19:13+09:00",
  "schemaVersion": "0.1",
  "source": "ai",
  "modelUsed": { "llm": "qwen3:14b" }
}
```

`0` / `[]` / 키 없음을 절대 섞지 않는다. `[]`는 "읽었는데 없다", 키 없음은
"확인하지 못했다"이고, 이 둘이 뭉개지면 병합할 때 **모르는 값이 없는 값을 덮는다.**

## 실행 방법

> 아래 명령은 모두 저장소 루트가 아니라 `info/` 안에서 실행한다 (`cd info`).
> `Hospital_inform/`·`ocr/`·`simulation/` 등 하위 경로는 전부 `info/` 기준
> 상대 경로다.

### 공통

```bash
cd info
conda create -n <가상환경명> python=3.11
conda activate <가상환경명>
pip install -r requirements.txt
```

`requirements.txt`는 직접 설치 대상(용도별 설명 포함)과 하위 의존성까지 모두 버전이
고정되어 있어, 위 명령 한 번으로 다른 팀원도 동일한 버전 조합을 그대로 재현할 수 있다.

### 경로 A — E-Gen 정규화 (`Hospital_inform/`)

```bash
cd Hospital_inform
pip install pydantic
python info/build_hospitals.py
```

`info/data/fixtures/`를 읽어 `info/data/output/`에 병원 1곳당 JSON 1개를 쓴다.
fixture는 커밋되지 않으므로 처음 클론했다면 먼저 만들어야 한다
([`Hospital_inform/README.md`](Hospital_inform/README.md) "데이터 정책" 참고).

### 경로 B — 서류 OCR·필드 추출 (`ocr/`)

```bat
:: 셋업 (GPU 장비)
pip install torch --index-url https://download.pytorch.org/whl/cu128
pip install -r ocr\requirements.txt -r ocr\requirements-extract.txt
python ocr\scripts\download_models.py
ollama pull qwen3:14b

:: 이미지 → 텍스트만
python ocr\scripts\run_ocr.py <이미지경로> [--json]

:: 이미지 → 필드까지 (OCR + LLM 동시 상주)
python ocr\scripts\run_extract.py --image <이미지경로> [...]

:: 저장된 OCR 결과에서 필드만 (GPU 불필요)
python ocr\scripts\run_extract.py --ocr-json <결과.json>

:: LLM 없이 로직만 / 환각 필터가 실제로 거르는지 확인
python ocr\scripts\run_extract.py --ocr-json <결과.json> --llm stub
python ocr\scripts\run_extract.py --ocr-json <결과.json> --llm stub-hallucinate
```

결과는 `ocr/output/`에 `YYYYMMDD_HHMMSS_<문서명>.json`으로 쌓인다. 덮어쓰지 않는다.

### 경로 B를 눈으로 확인 (`simulation/`) — 팀원용

```bat
pip install -r simulation\requirements.txt
python simulation\gui.py
```

`LLMdata/data_original/`의 서류를 **전부 창에 끌어놓으면** 순서대로 처리된다.
영역 검출 → 인식 → 필드 추출 → 근거 대조가 진행 중에 그려지고, 최종 JSON도 탭에서
바로 볼 수 있다. 결과는 CLI와 같고 다른 것은 과정이 보인다는 점뿐이다.
**PDF를 받는 유일한 경로**이기도 하다 — CLI는 이미지만 받는다.

성능만 확인할 거라면 **설정은 기본값 그대로** 두면 된다 — 학습 데이터는 쌓이지
않고 추출 결과만 `ocr/output/`에 남는다. `[설정…]`에서 추출 방식(Ollama/Stub),
해상도, 저장 위치, 학습 데이터 수집 여부를 정할 수 있고 값은 유지된다.
`Stub`을 고르면 Ollama·GPU 없이도 전 과정이 돈다.

Ollama가 꺼져 있으면 시작할 때 확인창이 떠서 **켤지 Stub으로 갈지** 고르게 되고,
켜기를 고르면 서버를 자동으로 띄운다 ([`simulation/README.md`](simulation/README.md)).

### 필드 추출 모델 학습 데이터 (`LLMdata/`)

`simulation`이나 `run_extract.py --image`로 서류를 처리할 때 **학습 데이터 수집을
켜면** OCR 텍스트(`raw/`)와 LLM 가공 전 응답(`llm_raw/`)이 같은 이름으로 쌓인다.
필드 추출 LLM을 파인튜닝할 때의 입력과 타깃이다. 기본값은 꺼짐이다
([`LLMdata/README.md`](LLMdata/README.md)).

## 폴더 구조

```
info/                              (저장소 루트의 .gitignore, CLAUDE.md, pull-all.sh는 브랜치 공통이라 여기 포함 안 됨)
├── README.md                      이 문서
├── DEVELOPMENT.md                 브랜치 전략
├── requirements.txt               서버 의존성 (Flask·WebSocket) — 서버는 미구현
│
├── Hospital_inform/               [경로 A] E-Gen 공개 API → HospitalInfo   (규칙 기반)
│   ├── README.md                  이 경로의 상세 문서
│   ├── hospital-info-interface-proposal.md   hub 인터페이스 변경 제안
│   └── info/
│       ├── schema.py              HospitalInfo 정의 + 검사기 (hub 계약, 아무것도 import 안 함)
│       ├── egen/
│       │   ├── client.py          데이터 취득 — FixtureEgenClient / HttpEgenClient
│       │   └── mapper.py          E-Gen 원본 → HospitalInfo 변환          ★본체
│       ├── build_hospitals.py     변환 실행 진입점
│       ├── verify_with_hub.py     hub 엔진 연동 검증 (검증 전용, 프로덕션 아님)
│       └── data/                  fixture · 변환 결과 (커밋하지 않음)
│
├── ocr/                           [경로 B] 병원 서류 이미지 → 필드   (AI + 규칙)
│   ├── README.md                  이 경로의 상세 문서
│   ├── requirements.txt           torch·onnxruntime 등 — 이미지 → 텍스트
│   ├── requirements-extract.txt   pydantic — 텍스트 → 필드
│   ├── configs/models.yaml        OCR 모델 저장소 ID·커밋 SHA·임계값
│   ├── models/                    OCR 가중치 (커밋하지 않음, 스크립트로 내려받음)
│   ├── output/                    추출 결과 JSON (커밋하지 않음, 실행마다 누적)
│   ├── scripts/
│   │   ├── download_models.py     OCR 가중치 내려받기
│   │   ├── run_ocr.py             이미지 → 텍스트 CLI
│   │   └── run_extract.py         이미지/텍스트 → 필드 CLI
│   └── src/
│       ├── goldenlink_ocr/        이미지 → 텍스트     (torch·GPU 필요)
│       │   ├── layout.py          ONNX 레이아웃 검출                    [AI]
│       │   ├── router.py          중복 제거·읽기 순서·태스크 배분        [규칙]
│       │   ├── recognizer.py      PaddleOCR-VL 래퍼                     [AI]
│       │   ├── validator.py       반복 생성·잘림 감지 → needs_review    [규칙]
│       │   ├── pipeline.py        위 넷을 엮는 진입점 (진행 콜백 제공)
│       │   └── config.py          models.yaml 로더
│       └── goldenlink_extract/    텍스트 → 필드       (pydantic만 필요)
│           ├── prompts.py         필드 그룹 4종 + JSON Schema
│           ├── llm/
│           │   ├── base.py        LlmClient Protocol (모델 교체 지점)
│           │   ├── ollama.py      Ollama 구조화 출력 호출               [AI]
│           │   └── stub.py        LLM 없이 도는 구현 (개발·테스트)
│           ├── grounding.py       근거 대조 — 환각 필터                 [규칙]
│           ├── schema.py          DocumentFields 정의 + 어휘 검증       [규칙]
│           ├── vocabulary.py      표준 코드(복사본) + 서류 종류
│           ├── extractor.py       위를 엮는 본체 (진행 콜백 제공)
│           └── config.py          모델·동작 설정 (환경변수)
│
├── simulation/                    [경로 B 확인용] 처리 과정을 보는 GUI
│   ├── README.md                  화면 · 설정 · 성능 실측 · 의존성
│   ├── requirements.txt           tkinterdnd2 · pypdfium2
│   ├── gui.py                     화면 (tkinter) · 설정 모달
│   ├── runner.py                  워커 스레드 — 대기열 처리, 이벤트를 큐로 (Tk 의존 없음)
│   ├── settings.py                실행 설정 (무엇을 어디에 남길 것인가)
│   ├── ollama_service.py          Ollama 상태 확인 · 자동 실행
│   └── pdf.py                     PDF 페이지 → 이미지 (pypdfium2)
│
└── LLMdata/                       [경로 B] 서류 원본 · 필드 추출 모델 학습 데이터
    ├── README.md                  학습 단위 · 라벨 4종 · 작업 순서
    ├── data_original/             서류 원본 (합성본 — 여기만 커밋. 용량 때문에 5건만)
    ├── raw/                       OCR 텍스트  = 학습 입력   (커밋하지 않음)
    ├── llm_raw/                   LLM 가공 전 응답 = 학습 타깃 (커밋하지 않음)
    └── 0*_*.jsonl                 데이터 종류별 예시 (SFT · DPO 3종 · 평가셋)
```

`ocr/src/` 아래 패키지를 둘로 나눈 이유는 **의존성이 다르기 때문**이다. 추출만
돌릴 때는 torch도 onnxruntime도 필요 없어서, GPU 없는 장비에서 저장된 OCR
결과(`run_ocr.py --json`)로 추출 로직만 따로 개발할 수 있다.

`simulation/`은 `ocr/`을 가져다 쓰기만 하는 확인용 창이다. 반대 방향 의존은
없다 — `ocr/`은 이 폴더의 존재를 모르고, 폴더를 통째로 지워도 CLI는 그대로 돈다.

`Hospital_inform/`은 개인 작업 공간에서 개발하던 것을 옮겨온 것이라 아직 브랜치
폴더 구조에 편입하지 않았다. hub 연동 검증이 끝난 뒤에 합친다.

## 알려진 제약사항 / TODO

### 외부 대기 (최우선)

- **E-Gen 서비스키 미승인.** 유일한 외부 대기 항목이고, 승인 전까지 아래 항목을
  확정할 수 없다. 신청: [공공데이터포털 15000563](https://www.data.go.kr/data/15000563/openapi.do)
- 실측 전 가정이 남아 있다 — `hv11`=소아 병상, `MKioskTy1/2/3` 번호별 질환,
  결측 표현이 `-1`인지 등. 전부 `egen/mapper.py` 상단 매핑표 한 곳에 모아 뒀으므로
  **키가 나오면 그 표 3개만 고치면 나머지 코드는 손대지 않아도 된다**

### 미구현

- **두 경로의 합류 지점** — `DocumentFields` → `HospitalInfo` 병합. 서류는 정적이라
  좌표·실시간 병상 수는 건드리지 않고, E-Gen이 못 채우는 당직·인력만 덮어야 한다.
  어느 값이 어디서 왔는지(AI / 규칙) 표기하는 방식도 미정
- **서버** — `requirements.txt`에 Flask·Flask-SocketIO가 선언돼 있지만 실제 서버
  코드는 아직 없다. hub와의 실제 송수신은 미구현
- OCR 필드 값 누락 검사 — 워터마크 문서에서 라벨은 읽고 값을 비우는 사례에 대한
  스키마 기반 검사

### 검증 대기

- **재현율을 아직 못 쟀다.** 근거 통과율은 쟀지만(아래 실측 참고), "원문에 있는데
  안 뽑은 값"은 사람이 만든 정답지가 있어야 센다.
  `LLMdata/07_eval_gold.jsonl`이 그 형식이고 손으로 채워야 한다
- **OCR 존폐를 가르는 커버리지 실측** — 대상 지역 병원 중 중증질환 수용가능 값을
  채운 비율과 마지막 갱신 시각. 커버리지가 높으면 E-Gen만으로 충분하다
- hub 엔진 연동 검증(매칭 순위 확인)은 계약 검증(4/4 통과)까지만 됐고 실행 대기

### 유지보수 주의

- **표준 역량·병상 코드 어휘가 두 벌 있다.** `Hospital_inform/info/schema.py`가
  원본이고 `ocr/src/goldenlink_extract/vocabulary.py`가 복사본이다. 두 경로의
  의존성을 갈라 두려고 일부러 복사했으며, 어긋났는지는 아래로 확인한다.
  ```bash
  python ocr/scripts/run_extract.py --check-vocabulary
  ```
- **CLAUDE.md 명세 오류 정정 필요** — `hv1`·`hv2`를 별도 API로 적고 있으나 실제로는
  가용병상 응답 안의 필드다. 호출 설계 자체가 달라진다
- OCR이 읽지 못하는 유형이 있다 — 직인이 덮은 글자, 손글씨, 세로 병합 셀 안쪽,
  팩스 저품질 문서 (실측 268개 항목 중 13개)

## 추가사항

### 필드 추출 실측 (합성 서류 53건 · 81페이지 · qwen3:14b)

`LLMdata/data_original/`을 실제로 돌려 나온 숫자다. 로직이 의도대로 도는지가
아니라 **실제 LLM이 얼마나 뽑는지**를 처음 잰 결과다.

| 지표 | 값 |
|---|---|
| 근거 통과율 | **72.4%** (267/369) |
| 그룹 호출 실패 | 2.5% (8/324) — `시술·장비` 7%, 나머지 대부분 0% |
| 사람 확인 필요 | 57% (46/81) |

기각 102건의 최대 원인은 환각이 아니라 **근거 인용 규율**이었다.

| 기각 사유 | 건수 |
|---|---|
| 원문에 없는 근거 | 63 — 그중 **37건이 프롬프트의 코드·한글 라벨을 근거란에 복사** |
| 근거가 너무 짧음 | 19 |
| 근거가 값과 무관 | 10 |
| 값이 근거에 없음 | 7 |

```
capabilities[0]  근거 <- "CT 24시간 가동"          ← 원문이 아니라 프롬프트의 라벨
hospitalName     근거 <- "문서 상에 명시된 병원명"    ← 원문이 아니라 모델의 설명
```

**값 자체는 맞는데 근거 때문에 버려진 경우**라, 환각을 막은 게 아니라 재현율을
잃은 것이다. 그래서 대응은 모델이 아니라 프롬프트 쪽이었다 — 지시문에 "이
지시문의 코드·설명을 근거로 쓰지 마라 / 떨어진 줄을 이어붙이지 마라"를 명시했고,
같은 서류로 다시 재 비교할 예정이다.

그룹 실패 8건은 전부 `num_predict` 한도(1024)에 걸려 생성이 잘린 것이었다.
구조화 출력은 문법 제약이 걸려 있어 형식이 깨질 수 없는데, 한도에 걸리면 문자열이
열린 채 끝나 파싱이 실패한다. 게다가 `temperature=0`이라 재시도해도 같은 지점에서
같은 실패가 반복됐다. 한도를 2048로 올렸다.

필드별로는 `specialties` 100%, `documentType` 98%, `hospitalName` 88%,
`effectiveDate` 81%로 나왔고, **`nightDutyAvailable`은 1%였다** — 표본에 당직표가
거의 없다는 뜻이다. 이 브랜치가 메우려는 공백(당직 정보)이 바로 그 필드라,
당직표 중심으로 표본을 늘려 다시 봐야 한다.

### 영역별로 나눠 읽는 이유 (실측)

이미지 → 텍스트 변환은 페이지를 통째로 넣지 않고 레이아웃 모델로 영역을 나눈 뒤
종류에 맞는 인식 태스크로 읽는다. 한글 실물 문서 15장(핵심 문자열 268개) 기준:

| 방식 | 재현율 | VRAM 피크 |
|---|---|---|
| 페이지 전체를 한 번에 | 68% | 8,312MB |
| **영역별 분리 + 태스크 라우팅** | **88%** | **2,078MB** |

영역을 나누면 조각이 작아 VRAM이 오히려 4분의 1로 줄고, 무한 반복(루프)도 사라진다.

### 모델이 스스로 보고하는 지표를 믿지 않는다

측정 중 **모델이 같은 토큰을 무한 반복하는 동안에도 confidence가 0.99로 나오는**
사례를 확인했다. 출력은 망가졌는데 신뢰도 지표는 정상으로 보인 것이다. 그래서
OCR 단계는 confidence 대신 토큰 한도 도달·고유 토큰 비율을 본다.

추출 단계도 같은 원칙이다. JSON Schema로 디코딩을 제약하면 형식은 반드시 맞지만
**형식이 맞는 거짓말**은 얼마든지 만들어진다. 그래서 값과 함께 근거 원문을 받아
규칙으로 세 겹 검사한다.

| 검사 | 잡는 것 |
|---|---|
| 근거가 원문에 있는가 | 근거 문장 자체를 지어낸 경우 |
| 값이 근거 안에 있는가 | 근거는 진짜인데 값만 다른 경우 (`"흉부외과 2명"` → `doctorCount: 7`) |
| 근거가 값을 뒷받침하는가 | 둘 다 진짜지만 서로 무관한 경우 (`"흉부외과 2명"` → 개두술 가능) |

걸린 값은 결과에서 빠지되 `evidence`에 `grounded: false`와 이유가 남는다.
무엇을 왜 버렸는지 사람이 볼 수 있어야 하기 때문이다.
