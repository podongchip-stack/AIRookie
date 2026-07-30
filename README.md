# [feature/hub] — 기능 요약 한 줄

<!-- 예: feature/voice — 실시간 음성 필터링 및 환자 정보 구조화 -->

> **신설 브랜치 안내**: `feature/hub`는 develop 기준으로 새로 만들어진 브랜치입니다.
> 아래 "입출력 데이터 포맷"에 정리된 세 가지 스키마(feature/voice 입력, feature/info
> 입력, feature/dashboard 출력)는 모두 **가안이며 팀 리뷰 후 확정 예정**입니다.

## 담당자

- 이름: 이승주
- 역할: 리드 개발자

## 이 브랜치가 하는 일

feature/voice가 보내는 환자 정보(부상 상태, 예상 병명, 중증도)와 feature/info가
보내는 병원 정보(위치, 병상, 전문성)를 결합해 규칙 기반 스코어링으로 병원 후보를
매칭하고, 존(Zone) 로직을 수행하는 브랜치입니다. **feature/dashboard와 직접
통신하는 유일한 브랜치**로, feature/voice·feature/info는 dashboard로 직접 보내지
않고 이 브랜치를 거칩니다.

처리는 2단계다: (1) GPS와 feature/info의 병원 정보로 먼저 존 기반 병원 후보
리스트를 만들어 보관하고, (2) feature/voice의 의료 정보가 도착하면 이를 반영해
리스트를 재처리한다. 최종적으로 의료 정보·예상 병명·병원 정보·병원 리스트를 모두
합쳐 feature/dashboard로 전달한다.

> dashboard가 보내는 승인 액션(hospital_approve/hospital_reject/final_approval)을
> 이 브랜치와 feature/info 중 어느 쪽이 수신할지는 아직 논의 중이라 **잠정
> 보류** 상태입니다. 확정되면 매칭 상태(`hospitals[].status`) 반영 처리를 구현합니다.

## 사용한 AI / 모델

거리·병상·존(Zone) 분류는 규칙 기반이지만, "예상 병명 ↔ 병원 진료과" 매칭만은
가벼운 임베딩 모델로 보조한다. `expectedDiagnosis`가 voice의 LLM이 만든 자유
텍스트라서, 하드코딩된 문자열 매칭으로는 실제 데이터를 안정적으로 못 잡기
때문이다 (예: "흉부 손상" ↔ "흉부외과").

| 구분 | 모델명 | 용도 | 비고 |
|---|---|---|---|
| 진료과 매칭 | paraphrase-multilingual-MiniLM-L12-v2 (sentence-transformers) — [sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2) | 예상 병명과 병원 진료과명 임베딩 간 코사인 유사도로 최적 진료과 선택 | feature/voice의 "실시간 음성 필터링"과 동일 모델 재사용. 결정적(deterministic)이고 로컬에서만 동작해 On-Premise 원칙 유지 |
| 거리 / 병상 / 존(Zone) 분류·확장 | — (규칙 기반) | GPS 거리 계산, 존 분류, 거절 비율 기반 존 확장 | 숫자 비교이므로 순수 규칙으로 충분 |

> CLAUDE.md의 "핵심 AI 활용 원칙" 표 기준으로, 이 기능이 AI 처리 영역인지 규칙 기반 영역인지 명시:
> - [x] AI 처리 (진료과 매칭만, 임베딩 유사도 보조)
> - [x] 규칙 기반 (거리·병상·존 로직, 최종 스코어링)

**설명 가능성 유지**: 진료과 매칭도 결과에 `specialtyMatch.score`(0~1 유사도 점수)를
그대로 노출하므로, 왜 이 병원이 이 순위인지 구급대원이 화면에서 확인할 수 있다.
생성형 LLM은 이 브랜치 어디에도 쓰지 않는다 (매번 같은 입력엔 같은 점수가 나와야
하는 매칭 단계라 재현성이 중요함).

## 개발 환경 / 언어

- 언어: Python 3.11 (`requirements.txt` 상단 주석 참고)
- 주요 라이브러리·프레임워크: pydantic(스키마 검증), sentence-transformers(진료과 매칭), numpy
- 실행 환경: 로컬 (CPU로 충분 — MiniLM은 경량 모델이라 GPU 불필요)
- **가상환경 이름 컨벤션**: `rookie_hub`. 이 저장소는 5개 브랜치가 작업 폴더를 공유하기
  때문에, feature/voice는 `rookie_voice`, feature/hub는 `rookie_hub`처럼 브랜치별로
  가상환경 이름을 분리해서 쓴다 (같은 이름의 환경을 여러 브랜치가 같이 쓰면 서로 다른
  의존성 버전이 섞여 꼬일 수 있음). `rookie_hub`는 hub의 `requirements.txt`만으로 처음부터
  새로 설치해서 검증했다 — voice 쪽 라이브러리(faster-whisper 등)는 안 들어있는 깔끔한
  환경이다.

## 입출력 데이터 포맷

> 아래 세 스키마 모두 가안이며 팀 리뷰 후 확정 예정.

### 입력 스키마 1: feature/voice로부터 (환자 정보)

기존 feature/voice README.md에 정의된 출력 스키마를 그대로 참조한다
(`transcript`, `summary.mechanism`, `summary.symptoms`, `summary.treatment`,
`summary.severity_tag` 등, 자세한 필드 설명은 feature/voice README.md 참고).
feature/hub는 이 중 `summary` 필드(부상 상태, 예상 병명, 중증도)만 매칭
스코어링에 사용한다.

### 입력 스키마 2: feature/info로부터 (병원 정보)

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

| 필드 | 타입 | 설명 |
|---|---|---|
| `hospitalId` | string | 병원 고유 식별자 |
| `name` | string | 병원명 |
| `gps.lat` / `gps.lng` | number | 병원 위치 좌표 (Hub의 거리 계산에 사용) |
| `availableBedCount` | number | 현재 실시간 가용 응급실 병상 수 |
| `nightDutyAvailable` | boolean | 야간 당직 전문의 존재 여부 |
| `specialties[].department` | string | 진료과명 |
| `specialties[].doctorCount` | number | 해당 진료과 수술 가능 의사 수 |
| `specialties[].recentProcedureTags` | string[] | 최근 수술 이력 기반 전문 분야 태그 (개인정보 블라인드 처리, 가안 DB 기반이며 향후 실제 데이터로 교체 예정) |
| `source` | `"rule"` | 규칙 기반 데이터임을 나타내는 고정값 |
| `updatedAt` | string (ISO 8601) | 이 정보가 마지막으로 갱신된 시각 |

### 출력 스키마 3: feature/hub → feature/dashboard (통합 매칭 결과)

```json
{
  "patientInfo": {
    "injuryStatus": ["의식 저하", "호흡 곤란"],
    "expectedDiagnosis": "흉부 손상",
    "severityTag": "high"
  },
  "zoneActive": [1, 2],
  "hospitals": [
    {
      "hospitalId": "H001",
      "name": "○○병원",
      "gps": { "lat": 35.1795, "lng": 128.1076 },
      "distanceKm": 2.1,
      "specialtyMatch": {
        "department": "흉부외과",
        "score": 0.82
      },
      "availableBedCount": 12,
      "status": "confirmed",
      "etaMin": 6
    }
  ],
  "source": "rule"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `patientInfo.injuryStatus` | string[] | voice가 추출한 부상 상태 목록 (원본 `summary.symptoms` 기반) |
| `patientInfo.expectedDiagnosis` | string | voice가 추출한 예상 병명 (원본 `summary.mechanism` 기반) |
| `patientInfo.severityTag` | `"high"` \| `"medium"` \| `"low"` | 중증도 |
| `zoneActive` | number[] | 현재 활성화된 존 번호 목록 |
| `hospitals[].hospitalId` / `name` | string | 병원 식별자 및 병원명 |
| `hospitals[].gps` | object | 병원 위치 좌표 (대시보드 지도 표시용) |
| `hospitals[].distanceKm` | number | GPS 기준 거리 |
| `hospitals[].specialtyMatch.department` | string | 예상 병명에 매칭된 진료과 |
| `hospitals[].specialtyMatch.score` | number (0~1) | 해당 진료과의 수술 전문성 적합도 점수. `distanceKm`과 가중합되어 최종 순위 산출 |
| `hospitals[].availableBedCount` | number | 실시간 가용 병상 수 |
| `hospitals[].status` | `"pending"` \| `"approved"` \| `"rejected"` \| `"confirmed"` | 병원 응답 상태 |
| `hospitals[].etaMin` | number | 도착 예상 시간(분), `confirmed` 병원만 필요 |
| `source` | `"rule"` | 규칙 기반 데이터임을 나타내는 고정값 |

## 결과 저장 및 전송 방식 (`delivery.py`)

지금은 dashboard 쪽 API가 없어서 로컬 파일 저장만 하지만, 나중에 Flask로 실시간
통신을 붙일 자리를 미리 분리해뒀다.

- **파일명 규칙**: feature/voice가 실제로 만드는 파일이 `<stem>_call_summary.json`
  형태이므로(예: `DrRomantic3v3_call_summary.json`), hub의 결과물도 같은 stem을
  이어받아 `<stem>_hub_match_result.json`으로 저장한다. 입력과 출력이 파일명만으로
  짝지어지기 때문에, 여러 사건이 동시에 처리돼도 결과 파일이 서로 덮어써지거나
  섞이지 않는다 (ERD에는 없는, 사건 단위로 voice↔hub를 연결할 임시 상관관계 키다).
- **저장 위치**: `data/test/output/<stem>_hub_match_result.json`
- **`deliver()` 하나로 로컬 저장 + 통신을 함께 수행**: `save_local()`이 로컬 저장,
  `send_to_dashboard()`가 통신 담당인데, 지금은 `send_to_dashboard()`가 아무 것도
  하지 않는 자리만 잡아둔 상태다. 나중에 `feature/dashboard`와 `develop`에서
  병합할 때, 이 함수 내부에 `requests.post(...)`만 채우면 되고 `run_match.py`
  같은 호출부는 코드를 바꿀 필요가 없다.
- 데모 단계에서는 통신을 붙인 뒤에도 로컬 저장을 계속 같이 한다 (감사·재현 목적).
  실제 사업화 단계에서는 이 부분을 재검토해야 한다.

## 실행 방법

```bash
conda create -n rookie_hub python=3.11
conda activate rookie_hub
pip install -r requirements.txt
```

**테스트 데이터로 매칭 엔진 실행** (`data/test/`의 병원 정보·voice 요약 샘플을 사용)
```bash
python run_match.py
```
1단계(GPS+병원 정보로 존 기반 후보 리스트 생성)와 2단계(voice 정보 반영 재처리) 결과를
각각 터미널에 출력하고, 최종 결과는 `data/test/output/DrRomantic3v3_hub_match_result.json`에도
저장한다 (파일명 규칙은 아래 "결과 저장 및 전송 방식" 참고).

## 폴더 구조

```
hub/
├── .gitignore
├── CLAUDE.md
├── DEVELOPMENT.md
├── README.md
├── requirements.txt
├── schema.py            입출력 pydantic 모델 (voice/info/dashboard 스키마와 1:1 대응)
├── geo.py                GPS 거리 계산, 존(Zone) 분류·확장 판단
├── specialty_matcher.py  임베딩 기반 예상 병명 ↔ 진료과 매칭
├── scoring.py             거리·진료과 점수 가중합 및 순위 결정
├── hub_engine.py         2단계 매칭 오케스트레이션 (상태 보관 + 재처리)
├── delivery.py           결과 저장(+ 자리만 준비된 통신) — 파일명을 voice 입력에서 이어받음
├── run_match.py          테스트 데이터로 엔진을 실행하는 CLI
└── data/
    └── test/
        ├── hospitals/                        병원 정보 샘플 (feature/info 역할, H001~H004.json)
        ├── DrRomantic3v3_call_summary.json    voice 요약 샘플 (feature/voice 역할)
        └── output/
            └── DrRomantic3v3_hub_match_result.json  실행 결과 (delivery.py가 생성)
```

## 코드 구조 — 모듈 간 관계

```
run_match.py  (테스트 실행 진입점)
   │  HospitalInfo · VoiceCallSummaryMessage를 JSON에서 읽어들임
   ▼
hub_engine.py  (HubEngine — 병원 정보 상태 보관 + 2단계 매칭 오케스트레이션)
   │
   ├─→ schema.py             모든 모듈이 공유하는 데이터 형태 (다른 모듈에 의존하지 않음)
   ├─→ geo.py                거리 계산 · 존 분류/확장 판단 (다른 모듈에 의존하지 않음)
   ├─→ specialty_matcher.py  진료과 임베딩 매칭 (다른 모듈에 의존하지 않음)
   └─→ scoring.py            점수 가중합 · 순위 결정 (다른 모듈에 의존하지 않음)

run_match.py
   │  hub_engine.py가 만든 HubMatchResult를 그대로 넘김
   ▼
delivery.py  (로컬 저장 + 자리만 준비된 통신, schema.py에만 의존)
```

- **`schema.py`가 가장 아래 계층**이다. 나머지 5개 파일이 전부 이 파일의 타입을 가져다
  쓰지만, `schema.py` 자신은 아무것도 import하지 않는다 — 데이터 "형태"만 정의하고
  로직은 하나도 없기 때문.
- **`geo.py` / `specialty_matcher.py` / `scoring.py`는 서로를 전혀 모른다.** 셋 다
  `hub_engine.py`에서만 쓰이고, 서로 독립적이라 하나를 통째로 바꿔도(예: 진료과 매칭
  모델을 다른 임베딩 모델로 교체) 나머지 둘과 `hub_engine.py`의 흐름 자체는 안 바뀐다.
  CLAUDE.md의 "모델/API 호출부와 비즈니스 로직은 분리해서 구현한다" 원칙을 그대로
  코드 구조에 반영한 것이다.
- **`hub_engine.py`가 유일하게 저 세 계산 모듈을 전부 알고 조립하는 곳**이다. "1단계:
  GPS로 존 후보 생성 → 2단계: voice 도착 시 진료과 매칭+스코어링으로 재처리"라는
  실제 업무 흐름이 여기에만 있다.
- **`run_match.py`는 `hub_engine.py`와 `schema.py`만 알면 된다.** geo/specialty_matcher/
  scoring 내부 구현을 몰라도 `HubEngine`을 통해 실행할 수 있다.
- **`delivery.py`는 매칭 로직(`hub_engine.py`)과 완전히 분리돼 있다.** `schema.py`만
  알고, "결과를 어떻게 내보낼지"(로컬 저장/통신)만 책임진다. 나중에 Flask 통신을
  붙일 때 이 파일만 고치면 되고, `hub_engine.py`는 건드릴 필요가 없다.

> 위 다이어그램은 "코드가 무엇을 import하는지"(의존 관계)이고, 실제 운영 중 데이터가
> 오가는 순서("데이터 포맷 및 흐름" 섹션에서 설명한 voice/info → hub → dashboard)는
> 별개의 축이다. 예를 들어 `geo.py`는 다른 모듈에 의존하지 않지만, 실제로는
> feature/info의 GPS 데이터가 들어와야 의미가 생긴다.

## 알려진 제약사항 / TODO

- 존 확장 임계값(`REJECT_RATIO_THRESHOLD`), 스코어링 가중치(`W_SPECIALTY`/`W_DISTANCE`)는
  `scoring.py`/`geo.py`에 상수로 박아뒀다 — 실제 운영 데이터 없이 정한 값이라 테스트하며
  조정 필요
- 승인 액션 수신(hospital_approve/hospital_reject/final_approval)은 아직 미연동이라,
  `hospitals[].status`는 현재 항상 `"pending"`으로만 채워진다 (수신 주체 확정 후 반영)
- feature/voice·feature/info로부터의 실시간 통신, feature/dashboard로의 실시간 전송(Flask
  예정)은 아직 미구현. 지금은 로컬 JSON 파일을 읽고 쓰는 형태로만 검증했고,
  `delivery.py`의 `send_to_dashboard()`에 통신 붙일 자리만 미리 마련해뒀다
- 위 세 스키마 모두 가안이며 feature/voice, feature/info, feature/dashboard 팀과 리뷰 후 확정 필요

## 추가사항
