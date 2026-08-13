# [feature/hub] — 기능 요약 한 줄

<!-- 예: feature/voice — 실시간 음성 필터링 및 환자 정보 구조화 -->

> **폴더 구조 안내(모노레포)**: 이 저장소는 `feature/voice`·`feature/hub`·
> `feature/info`·`feature/dashboard`가 하나의 저장소를 공유하며, 각 브랜치는
> 자기 작업 폴더(`voice/`·`hub/`·`info/`·`dashboard/`)만 갖는다. **지금 이
> 브랜치에는 `hub/` 폴더만 있고 `voice/`·`info/`·`dashboard/`는 없다.** 만약
> 작업 중 낯선 폴더가 보인다면 `develop`을 머지했거나 다른 브랜치를 체크아웃한
> 상태라는 뜻이니, 실수로 만들어진 게 아닌지 걱정하지 않아도 된다.

> **신설 브랜치 안내**: `feature/hub`는 develop 기준으로 새로 만들어진 브랜치입니다.
> 아래 "입출력 데이터 포맷"에 정리된 스키마(feature/voice 입력, feature/info 입력,
> feature/dashboard 입력·출력, feature/info 출력)는 모두 **가안이며 팀 리뷰 후 확정
> 예정**입니다.

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

> dashboard가 보내는 승인 액션(hospital_approve/hospital_reject/final_approval)의
> 수신 주체는 **이 브랜치(feature/hub)로 확정**되었습니다 (dashboard가 feature/hub와만
> 직접 통신하기 때문). 매칭 상태(`hospitals[].status`) 반영과, `final_approval` 시
> 병상을 TTL 오버레이로 차감하는 처리("입출력 데이터 포맷"의 입력 스키마 3 참고)는
> `HubEngine.apply_approval_action()`으로 **구현·테스트 완료**했습니다 (`run_match.py`
> 참고). dashboard와의 실제 WebSocket 통신도 연동 완료됐습니다. feature/info로의
> 병상 갱신 HTTP 전송(`send_to_info()`)은 2026-08-13 병원 Supabase 제거와 함께
> 완전히 폐지됐습니다 — 아래 "출력 스키마 5" 참고.

> **여러 사건(구급차) 동시 처리 지원 완료.** 처음엔 사건 1건 단독 처리만
> 다뤘지만, 이제 `caseId`로 사건을, `apid`로 구급차(voice 인스턴스)를 구분해
> 여러 구급차가 동시에 진행돼도 서로 안 섞인다. 바뀐 것 세 가지:
> 1. **dashboard 연결을 소켓 집합으로 관리하고 전체에 브로드캐스트한다** —
>    예전엔 전역 변수 하나라 마지막에 연결한 탭만 갱신을 받는 버그가 있었다
>    (구급차 대시보드 + 병원 대시보드를 동시에 열면 한쪽만 죽는 문제)
> 2. **승인 액션 처리 후 캐시된 사건 결과를 재브로드캐스트한다** — 예전엔
>    이 단계가 아예 없어서 승인 버튼을 눌러도 화면에 반영되지 않았다
> 3. **voice가 여러 대(구급차마다 한 대씩)로 늘어나 apid로 구분**한다.
>    voice가 뜰 때 자기 IP를 자동 탐지해 hub에 자가등록하면(`POST
>    /voice/register`), hub는 그 IP + `AmbulanceInfo.voicePort`를 합쳐
>    주소를 기억해뒀다가 통화 시작/종료 신호를 그 구급차의 voice로 중계한다.
>    구급차 GPS도 하드코딩된 고정값 대신 이 `AmbulanceInfo`(feature/info가
>    Supabase `ambulances` 테이블에서 읽어 보내줌) 조회로 대체했다.

> **존(zone) 확장이 실제 서버(`app.py`)에 배선됐다(2026-08-11).** 그 전까지는
> `MAX_ZONE = 1`(0~5km)이 상수로 고정돼 있어서, 실제 E-Gen/Supabase 병원
> 7곳이 서울 전역에 흩어진 데이터로 테스트했을 때 zone 1 안에 후보가
> 하나도 없어 매칭 결과가 0건으로 나오는 문제가 실제로 재현됐다(`reject_ratio`/
> `expand_if_needed`는 이미 구현·`run_match.py`에서 검증돼 있었지만, 그건
> 스크립트가 수동으로 호출하는 테스트 경로였을 뿐 `/voice/summary`가 실제로
> 쓰는 경로엔 연결돼 있지 않았다). 두 가지를 추가했다:
> 1. `HubEngine.resolve_start_zone()` — 첫 매칭 시 zone 1부터 후보가 하나라도
>    잡힐 때까지 넓힌다. 거절 비율 기반 확장은 "후보가 있는데 다 거절당함"만
>    감지해서, 애초에 후보가 0개인 사각지대(거절할 대상이 없어 비율이 항상
>    0)는 못 잡는다 — 그 사각지대를 메운다.
> 2. `HubEngine.maybe_expand_zone()` — `hospital_reject` 액션 처리 후에만
>    호출한다(`app.py`가 gating). `reject_ratio`가 누적 계산이라, 승인/최종승인
>    뒤에도 이걸 부르면 새 거절이 하나도 없는데 계속 확장되는 문제가 있어서
>    (실제로 재현·수정됨) 거절 액션에만 배선했다.

> **승인 후 캐시된 병상 수가 안 바뀌던 문제 수정(2026-08-11).** `final_approval`로
> `apply_approval_action()`이 `self._hospitals`의 병상 수를 실제로 깎아도,
> dashboard로 나가는 캐시(`_case_results`)의 `HospitalMatch.availableBedCount`는
> 별도 스냅샷이라 반영이 안 됐다 — "이송 확정" 상태는 바뀌는데 병상 배지는 옛날
> 값 그대로 보이는 문제가 실제로 재현됐다(Supabase 자체는 정상 차감돼서 더
> 헷갈렸음). `_patch_case_result_status()`가 status와 함께 `self._hospitals`의
> 최신 병상 수·`bedCountUnknown`도 같이 다시 읽어오도록 고쳤고, 호출 시점도
> 병상 차감 **이후**로 옮겼다.

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

> 아래 스키마 모두 가안이며 팀 리뷰 후 확정 예정.

### 입력 스키마 1: feature/voice로부터 (환자 정보)

기존 feature/voice README.md에 정의된 출력 스키마를 그대로 참조한다
(`transcript`, `summary.mechanism`, `summary.symptoms`, `summary.treatment`,
`summary.severity_tag` 등, 자세한 필드 설명은 feature/voice README.md 참고).
feature/hub는 `summary` 필드(부상 상태, 예상 병명, 중증도)는 매칭 스코어링에
쓰고, `transcript.raw_text`/`transcript.filtered_text`(원본·필터링 전문)는
스코어링에는 안 쓰지만 dashboard가 확인할 수 있도록 "출력 스키마 4"의
`patientInfo`에 그대로 실어 전달한다.

### 입력 스키마 2: feature/info로부터 (병원 정보)

```json
{
  "hospitalId": "H001",
  "name": "○○병원",
  "gps": { "lat": 35.1795, "lng": 128.1076 },
  "availableBedCount": 12,
  "bedsByType": { "ER_ADULT": 12, "ICU": 3 },
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
| `availableBedCount` | number | 현재 실시간 가용 응급실 병상 수. **미상일 때도 0이 들어온다** — 아래 `bedsByType`으로 구분한다 |
| `bedsByType` | object (optional) | 병상 종류별 가용 수(`ER_ADULT`·`ICU` 등). feature/info는 **미상인 종류의 키를 아예 넣지 않는 것**으로 "확인된 만실(`{"ER_ADULT": 0}`)"과 "미상(키 없음)"을 구분한다. hub는 `availableBedCount == 0`이면서 `ER_ADULT` 키가 없을 때만 미상으로 판정한다 |
| `nightDutyAvailable` | boolean | 야간 당직 전문의 존재 여부 |
| `specialties[].department` | string | 진료과명 |
| `specialties[].doctorCount` | number | 해당 진료과 수술 가능 의사 수 |
| `specialties[].recentProcedureTags` | string[] | 최근 수술 이력 기반 전문 분야 태그 (개인정보 블라인드 처리, 가안 DB 기반이며 향후 실제 데이터로 교체 예정) |
| `source` | `"rule"` | 규칙 기반 데이터임을 나타내는 고정값 |
| `updatedAt` | string (ISO 8601) | 이 정보가 마지막으로 갱신된 시각 |

### 입력 스키마 3: feature/dashboard로부터 (승인 액션)

dashboard는 feature/hub와만 직접 통신하므로, 승인 액션(hospital_approve/
hospital_reject/final_approval)의 수신 주체는 이 브랜치로 확정한다. **전송
방식은 WebSocket이다** — dashboard가 `new WebSocket()`(socket.io 아님)으로
`ws://<hub 주소>/ws/dashboard`에 연결해 JSON 문자열 프레임으로 보낸다
(`app.py`의 `/ws/dashboard` 참고).

```json
{
  "caseId": "case-abc123",
  "action": "final_approval",
  "hospital_id": "H001",
  "actor": "paramedic",
  "timestamp": "2026-07-30T14:20:00Z"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `caseId` | string | 어느 사건(구급차)에 대한 승인인지. 여러 사건이 동시에 진행되면 `hospital_id`만으로는 특정할 수 없어 추가됐다. dashboard는 자기가 보고 있는 사건의 caseId를 "출력 스키마 4"로 이미 받아 알고 있다 |
| `action` | `"hospital_approve"` \| `"hospital_reject"` \| `"final_approval"` | 어떤 승인 행위인지 |
| `hospital_id` | string | 대상 병원 식별자 |
| `actor` | `"hospital"` \| `"paramedic"` | 누가 누른 행위인지 |
| `timestamp` | string (ISO 8601) | 행위 발생 시각 |

이 액션을 받으면 해당 병원의 `hospitals[].status`를 갱신하고, `final_approval`인
경우 아래 "출력 스키마 5"로 feature/info에도 병상 갱신을 알린다.

### 입력 스키마 6: feature/dashboard로부터 (통화 시작/종료 신호)

같은 `/ws/dashboard` 연결로 dashboard의 "통화 시작"/"통화 종료" 버튼 신호도
받는다. hub는 이 신호를 **그 구급차(apid)의 voice 인스턴스로** HTTP POST
중계한다 — 오디오 자체는 hub를 거치지 않는다 (dashboard가 `sendAudioChunk()`로
브라우저 마이크 오디오도 같이 보내지만, 실제 STT 입력은 voice의 로컬 마이크로
확정되어 hub는 그 바이너리 프레임을 받기만 하고 버린다).

구급차마다 voice가 별도 장비에서 뜨기 때문에(apid별로 다름), hub는 이 apid로
`POST /voice/register`(아래 "입력 스키마 8" 참고)로 등록된 주소를 찾아 그
주소로 중계한다 — 아직 등록 전이면 조용히 건너뛴다. `call_started` 시점에
`(caseId -> apid)`를 기억해뒀다가, 나중에 그 caseId로 도착하는 voice 요약이
어느 구급차의 GPS를 써야 하는지 찾는 데도 쓴다.

```json
{
  "type": "call_signal",
  "signal": "call_started",
  "timestamp": "2026-07-30T14:15:00Z",
  "apid": "A0000001",
  "caseId": "case-abc123"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `type` | `"call_signal"` | 고정값 |
| `signal` | `"call_started"` \| `"call_ended"` | 통화 시작인지 종료인지 |
| `timestamp` | string (ISO 8601) | 신호 발생 시각 |
| `apid` | string | 어느 구급차(voice 인스턴스)인지. hub가 중계 대상 주소를 찾는 키 |
| `caseId` | string | 이번 통화가 어느 사건인지. dashboard가 `call_started` 시점에 새로 생성해 보낸다 |

### 입력 스키마 7: feature/info로부터 (구급차 정보)

병원 정보(입력 스키마 2)와 짝을 이루는 구급차 레지스트리. feature/info가
Supabase `ambulances` 테이블에서 읽어 보내준다.

```json
{
  "apid": "A0000001",
  "name": "구급 1호차",
  "gps": { "lat": 37.4979, "lng": 127.0276 },
  "voicePort": 6000,
  "source": "rule",
  "updatedAt": "2026-08-11T00:00:00Z"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `apid` | string | 구급차 고유 식별자 |
| `name` | string | 표시용 이름 |
| `gps.lat` / `gps.lng` | number | 구급차 위치. 대회 데모 단계라 서울 랜드마크로 고정한 값(실시간 GPS 아님) |
| `voicePort` | number | 이 구급차 voice 인스턴스가 뜰 포트. 장비마다 미리 정해둔 값이라 안정적이다 — IP는 여기 없다(아래 "입력 스키마 8" 참고) |
| `source` | `"rule"` | 규칙 기반 데이터임을 나타내는 고정값 |
| `updatedAt` | string (ISO 8601) | 마지막 갱신 시각 |

### 입력 스키마 8: feature/voice로부터 (voice 자가등록)

voice는 구급차 노트북마다 별도로 뜨고, 노트북이 붙는 네트워크(와이파이/
핫스풋)가 자주 바뀔 수 있어 IP를 Supabase 등에 고정 저장하지 않는다. 대신
voice가 뜰 때 자기 IP를 자동 탐지해 이 엔드포인트로 hub에 알려준다.

```json
{
  "apid": "A0000001",
  "ip": "192.168.0.101"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `apid` | string | 이 voice 인스턴스가 담당하는 구급차 |
| `ip` | string | 이 voice 인스턴스가 자동 탐지한 자기 IP. hub는 `AmbulanceInfo.voicePort`와 합쳐 `http://{ip}:{voicePort}` 주소로 저장한다 |

이 apid의 `AmbulanceInfo`가 아직 hub에 등록되기 전이면(포트를 모르므로)
`409`를 반환하고 등록을 보류한다 — feature/info가 구급차 정보를 먼저 보낸
뒤에 voice가 자가등록하는 순서를 전제로 한다.

### 입력 스키마 9: feature/dashboard로부터 (소켓 연결 시 자기소개, 2026-08-11 신설)

hub는 `/ws/dashboard` 연결을 그동안 완전히 익명으로 취급해서, 매칭 결과를
"그 순간 연결된 소켓"에만 브로드캐스트했다. 그래서 진행 중인 사건이 있는
상태로 새 대시보드 탭이 뒤늦게 열리면, 그 탭은 이전 브로드캐스트를 놓쳐
화면에 아무것도 안 뜨는 문제가 실제로 있었다(구급1호차·서울대병원 탭이
연결된 상태에서 매칭이 끝난 뒤 한양대병원 탭을 새로 열면 그 사건이 안
보임). 이 메시지로 자기가 병원인지 구급차인지, 어느 hpid/apid인지
알려주면 hub가 연결 시점에 관련된 사건들을 즉시 그 소켓에만 돌려준다.

```json
{
  "type": "identify",
  "role": "hospital",
  "id": "S0000001"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `type` | `"identify"` | 고정값 |
| `role` | `"hospital"` \| `"ambulance"` | 이 소켓이 병원 대시보드인지 구급차 대시보드인지 |
| `id` | string | `role="hospital"`이면 hpid, `role="ambulance"`면 apid |

**응답은 두 가지다(2026-08-11, 순서대로 전송):**
1. **"출력 스키마 6"(`DashboardIdentityInfo`)** — 사건 유무와 무관하게
   즉시 보내는 신원 확인. hub가 이미 인메모리로 갖고 있는 병원/구급차
   레지스트리에서 이름을 바로 조회해 돌려준다(사건이 하나도 없어도, 즉
   통화 전이라도 상단바에 실명이 뜬다). `known=false`면 hub가 그
   hpid/apid를 모른다는 뜻이라 dashboard가 "존재하지 않는 접근 코드"로
   판단할 수 있다.
2. 관련된 사건 각각에 대해, 평소 브로드캐스트와 동일한 형식의
   "출력 스키마 4"(`HubMatchResult`)를 그 소켓에만 개별 전송(따라잡기) —
   새 메시지 포맷을 따로 안 만들어서 dashboard 쪽은 이 부분에 별도 분기가
   필요 없다. `role="hospital"`이면 `HubEngine.get_cases_for_hospital()`로
   그 hpid가 `hospitals[]`에 들어있는 사건 전부를, `role="ambulance"`면
   `HubEngine.get_cases_for_apid()`로 그 apid가 등록한 사건을 찾아 돌려준다.

### 출력 스키마 4: feature/hub → feature/dashboard (통합 매칭 결과)

```json
{
  "caseId": "case-abc123",
  "patientInfo": {
    "injuryStatus": ["의식 저하", "호흡 곤란"],
    "expectedDiagnosis": "흉부 손상",
    "severityTag": "high",
    "rawTranscript": "구급대원: 환자 50대 남성, 교통사고 흉부 충격입니다...",
    "filteredTranscript": "환자 50대 남성, 교통사고 흉부 충격. 의식 저하, 호흡 곤란."
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
      "bedCountUnknown": false,
      "status": "confirmed",
      "etaMin": 6
    }
  ],
  "source": "rule",
  "ambulanceName": "구급 1호차"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `caseId` | string | 이 매칭 결과가 어느 사건 것인지. dashboard는 여러 사건을 동시에 받을 수 있어 자기가 보는 사건의 caseId로 걸러 써야 한다 |
| `patientInfo.injuryStatus` | string[] | voice가 추출한 부상 상태 목록 (원본 `summary.symptoms` 기반) |
| `patientInfo.expectedDiagnosis` | string | voice가 추출한 예상 병명 (원본 `summary.mechanism` 기반) |
| `patientInfo.severityTag` | `"high"` \| `"medium"` \| `"low"` | 중증도 |
| `patientInfo.rawTranscript` | string | voice의 통화 원문 전체 (`transcript.raw_text` 그대로) |
| `patientInfo.filteredTranscript` | string | 실시간 음성 필터링을 거친 텍스트 (`transcript.filtered_text` 그대로) |
| `zoneActive` | number[] | 현재 활성화된 존 번호 목록 |
| `hospitals[].hospitalId` / `name` | string | 병원 식별자 및 병원명 |
| `hospitals[].gps` | object | 병원 위치 좌표 (대시보드 지도 표시용) |
| `hospitals[].distanceKm` | number | GPS 기준 거리 |
| `hospitals[].specialtyMatch.department` | string | 예상 병명에 매칭된 진료과 |
| `hospitals[].specialtyMatch.score` | number (0~1) | 해당 진료과의 수술 전문성 적합도 점수. `distanceKm`과 가중합되어 최종 순위 산출 |
| `hospitals[].availableBedCount` | number | 실시간 가용 병상 수 |
| `hospitals[].bedCountUnknown` | boolean | `availableBedCount`가 0일 때 그게 **"확인된 만실"(false)**인지 **"미상"(true)**인지. **dashboard는 true면 "0"이 아니라 "미상"으로 표시해야 한다** — 미상을 0으로 보여주면 구급대원이 멀쩡한 병원을 직접 후보에서 빼게 되어, 뺑뺑이를 줄이려는 목적과 정반대가 된다 |
| `hospitals[].status` | `"pending"` \| `"approved"` \| `"rejected"` \| `"confirmed"` | 병원 응답 상태 |
| `hospitals[].etaMin` | number | 도착 예상 시간(분), `confirmed` 병원만 필요 |
| `source` | `"rule"` | 규칙 기반 데이터임을 나타내는 고정값 |
| `ambulanceName` | string \| null (2026-08-11 신설) | 구급차 대시보드 상단바 표시용. `hospitals[].name`(병원명)과 같은 패턴 — 이 사건의 apid를 `register_case()`로 기억해둔 값에서 찾아 구급차 레지스트리(`AmbulanceInfo.name`)를 그대로 채운다. apid를 못 찾으면(통화 시작 신호 없이 직접 `/voice/summary`를 부른 테스트 등) `null`이고, dashboard는 URL의 apid로 대체 표시한다. **병원명과 마찬가지로 그 구급차가 실제로 사건에 등장해야만 채워진다** — 사건이 아예 없는 상태(대시보드를 열었지만 아직 통화가 없음)에서는 아직 이 필드 자체를 못 받으므로 ID 폴백이 계속 보인다 |

### ~~출력 스키마 5: feature/hub → feature/info (병상 갱신 알림)~~ → 2026-08-13 폐지

> 예전엔 `final_approval` 확정 즉시 hub가 `POST /hub/bed-update`
> (`info/app.py`, 포트 5002)로 병상 갱신을 info에 알려 Supabase에 반영시켰다
> (+ 재시도 큐, `hub/data/pending_bed_updates.jsonl`). info가 병원 Supabase
> 자체를 없애면서(E-Gen 실 API로 병상까지 직접 조회 — 조회 전용이라 원래
> 쓰기가 불가능한 곳이었다) 이 왕복이 의미를 잃어 **완전히 제거했다.**
> `info/app.py`, `hub/delivery.py`의 `send_to_info()`/재시도 큐/
> `has_pending_bed_update()`, `hub/schema.py`의 `HospitalBedUpdate` 전부
> 삭제됐다.
>
> 대신 병상 차감은 **hub 혼자 자기 메모리에서 짧게(TTL)만 처리**한다.
> `HubEngine._bed_overlay`(hpid -> 만료 시각 목록)에 `final_approval`마다
> 기록 하나가 쌓이고, `effective_bed_count()`가 조회 시점에 만료 안 된
> 개수만큼만 원본(`HospitalInfo.availableBedCount`)에서 빼서 보여준다.
> `BED_OVERLAY_TTL_MIN=15`(분)는 `hvidate` 갱신 간격 실측(중앙값 5분,
> 88.7%가 10분 이내)에서 여유를 둔 값 — 그 안에는 E-Gen 자신도 아직 안
> 바뀌었을 가능성이 높아 오버레이가 유효한 근거가 된다. 예전 대기열 방어
> 로직(`HubEngine.update_hospital_info()`가 재시도 중인 병원은 upsert
> 건너뛰기)도 필요 없어졌다 — 오버레이가 read-time에 적용되므로 info가
> 보내는 최신 원본값을 매번 그대로 덮어써도 안전하다.

### 출력 스키마 6: feature/hub → feature/dashboard (신원 확인 응답, 2026-08-11 신설)

"입력 스키마 9"(자기소개)에 대한 첫 번째 응답. `_send_catchup()`(사건
기반 따라잡기)과 달리, 사건이 하나도 없어도(대시보드를 막 열어서 아직
통화 전인 상태라도) hub가 이미 인메모리로 갖고 있는 병원/구급차
레지스트리(`HubEngine._hospitals`/`_ambulances` — feature/info가 Supabase에서
읽어 보내준 것)에서 이름을 즉시 찾아 돌려준다. "병원 ID: S0000001",
"구급 A0000001호차"처럼 사건 발생 전까지 ID로만 표시되던 문제를 없애기
위해 추가됐다(`app.py`의 `_send_identity_info()`).

```json
{
  "type": "identity_info",
  "role": "hospital",
  "id": "S0000001",
  "name": "서울대학교병원",
  "known": true
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `type` | `"identity_info"` | 고정값 |
| `role` | `"hospital"` \| `"ambulance"` | 요청받은 `DashboardIdentify.role` 그대로 |
| `id` | string | 요청받은 `DashboardIdentify.id` 그대로 |
| `name` | string \| null | hub가 아는 실제 이름. 모르면(레지스트리에 없으면) `null` |
| `known` | boolean | hub의 레지스트리에 이 hpid/apid가 등록돼 있는지. `false`면 dashboard가 "존재하지 않는 접근 코드"로 판단해 접근을 막는 근거로 쓸 수 있다 |

### `GET /identity` (HTTP, 랜딩 페이지 사전 확인용, 2026-08-11 신설)

처음엔 `/hospital`, `/ambulance` 페이지가 열린 뒤(WebSocket `identify` 이후)에만
존재 여부를 알 수 있어서, 존재하지 않는 코드로 들어가면 그 페이지 전체가
"존재하지 않는 접근 코드입니다" 화면으로 막히는 방식이었다. 코드를 입력하는
**첫 페이지에서, 넘어가기 전에** 바로 확인하고 싶다는 요청에 따라 REST
엔드포인트로 별도 노출했다 — 랜딩 페이지는 아직 어느 사건에도 속하지 않은
1회성 확인만 하면 되니, 지속 연결(WebSocket)을 열었다 바로 닫는 것보다 단순
요청-응답이 더 잘 맞는다. `_resolve_identity()`로 위 `identity_info`와 완전히
같은 조회 로직을 재사용한다.

```
GET /identity?role=hospital&id=S0000001
```

응답(200):
```json
{
  "role": "hospital",
  "id": "S0000001",
  "name": "서울대학교병원",
  "known": true
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `role` | `"hospital"` \| `"ambulance"` | 요청 그대로 |
| `id` | string | 요청 그대로 |
| `name` | string \| null | hub가 아는 실제 이름. 모르면 `null` |
| `known` | boolean | hub의 레지스트리에 등록돼 있는지 |

`role`이 `hospital`/`ambulance`가 아니거나 `id`가 없으면 `400`. dashboard(포트
3000)와 hub(포트 5001)는 다른 origin이라 브라우저 `fetch`가 CORS로 막히므로,
이 엔드포인트만 `Access-Control-Allow-Origin: *`을 붙인다 — 인증이 없는 단순
조회라 전체 허용해도 안전하다고 판단했다.

## 결과 저장 및 전송 방식 (`delivery.py`)

로컬 파일 저장은 항상 하고, 실시간 dashboard 전송은 `app.py`가 처리한다.

- **파일명 규칙**: feature/voice가 실제로 만드는 파일이 `<stem>_call_summary.json`
  형태이므로(예: `DrRomantic3v3_call_summary.json`), hub의 결과물도 같은 stem을
  이어받아 `<stem>_hub_match_result.json`으로 저장한다. 입력과 출력이 파일명만으로
  짝지어지기 때문에, 여러 사건이 동시에 처리돼도 결과 파일이 서로 덮어써지거나
  섞이지 않는다 (ERD에는 없는, 사건 단위로 voice↔hub를 연결할 임시 상관관계 키다).
- **저장 위치**: `data/test/output/<stem>_hub_match_result.json`
- **`deliver()`는 로컬 저장 전용으로 남겨뒀다**: `save_local()`이 로컬 저장을
  담당하고, `send_to_dashboard()`는 원래 계획대로라면 `requests.post(...)`를
  채울 자리였는데, 실제 전송 채널이 살아있는 WebSocket 연결(dashboard가
  `new WebSocket()`으로 접속)이라 그 연결 객체를 쥐고 있는 `app.py`의
  `/voice/summary` 핸들러에서 직접 `ws.send(...)`로 처리한다 (`app.py`의
  `_send_to_dashboard()` 참고). `send_to_dashboard()` 자체는 로그만 남기는
  자리로 남아 있다.
- ~~**`feature/info`로 보내는 병상 갱신도 같은 패턴**: `deliver_bed_update()`가...~~
  → **2026-08-13 삭제.** `deliver_bed_update()`/`save_local_bed_update()`/
  `send_to_info()` 전부 없앴다 — 위 "출력 스키마 5" 참고. 병상 차감은 이제
  파일로도 안 남기고 `HubEngine._bed_overlay`(메모리)에만 있다가 TTL이
  지나면 조용히 사라진다.
- 데모 단계에서는 통신을 붙인 뒤에도 로컬 저장을 계속 같이 한다 (감사·재현 목적).
  실제 사업화 단계에서는 이 부분을 재검토해야 한다.

## 의사결정 로그 (`decision_log.py`)

CLAUDE.md "보안 및 개인정보 원칙"의 "모든 의사결정 로그는 타임스탬프 + SHA-256
해시로 저장해 사후 위변조 여부를 검증할 수 있게 한다"를 구현한다.

- `hub_engine.py`가 매칭 결과(`process_voice_summary`)를 만들거나 승인 액션
  (`apply_approval_action`)을 처리할 때마다 `decision_log.log_decision()`을 호출해
  `data/logs/decision_log.jsonl`에 한 줄씩 append한다 (기존 줄은 절대 수정하지 않음)
- 기록 하나는 `{timestamp, eventType, payload, hash}` 형태이고, `hash`는
  `timestamp+eventType+payload`를 정렬된 JSON으로 직렬화한 값의 SHA-256이다.
  누군가 로그 파일의 `payload`를 사후에 고치면 저장된 `hash`와 재계산한 `hash`가
  달라져서 위변조를 바로 알 수 있다
- `decision_log.verify_log()`로 로그 파일 전체를 검증할 수 있다 — 위변조 여부와
  검사한 줄 수를 반환한다 (`run_match.py` 맨 마지막에서 실행함)

## 실행 방법

```bash
cd hub
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
hub/                        (저장소 루트의 .gitignore, CLAUDE.md는 브랜치 공통이라 여기 포함 안 됨)
├── DEVELOPMENT.md
├── README.md
├── requirements.txt
├── schema.py            입출력 pydantic 모델 (voice/info/dashboard 스키마와 1:1 대응)
├── geo.py                GPS 거리 계산, 존(Zone) 분류·확장 판단
├── specialty_matcher.py  임베딩 기반 예상 병명 ↔ 진료과 매칭
├── scoring.py             거리·진료과 점수 가중합 및 순위 결정
├── hub_engine.py         2단계 매칭 오케스트레이션 + 승인 액션 반영(상태 보관 + 재처리)
├── decision_log.py       의사결정 로그 (타임스탬프 + SHA-256 해시, 위변조 검증 가능)
├── delivery.py           결과 저장 + dashboard로의 실제 통신 — 파일명을 voice 입력에서 이어받음
│                         (info로의 병상 갱신 전송은 2026-08-13 삭제됨)
├── run_match.py          테스트 데이터로 엔진을 실행하는 CLI
└── data/
    ├── test/
    │   ├── hospitals/                        병원 정보 샘플 (feature/info 역할, H001~H004.json)
    │   ├── DrRomantic3v3_call_summary.json    voice 요약 샘플 (feature/voice 역할)
    │   └── output/
    │       └── DrRomantic3v3_hub_match_result.json  매칭 결과 (delivery.py가 생성)
    └── logs/
        └── decision_log.jsonl   의사결정 로그 (decision_log.py가 생성, append-only)
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
   ├─→ scoring.py            점수 가중합 · 순위 결정 (다른 모듈에 의존하지 않음)
   └─→ decision_log.py       매칭 결과·승인 처리마다 로그 기록 (다른 모듈에 의존하지 않음)

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
- **`decision_log.py`도 매칭 로직과 분리돼 있다.** `hub_engine.py`가 매칭 결과를
  만들거나 승인 액션을 처리할 때마다 호출만 하고, "어떻게 기록·검증할지"는
  전적으로 이 모듈이 책임진다.

> 위 다이어그램은 "코드가 무엇을 import하는지"(의존 관계)이고, 실제 운영 중 데이터가
> 오가는 순서("데이터 포맷 및 흐름" 섹션에서 설명한 voice/info → hub → dashboard)는
> 별개의 축이다. 예를 들어 `geo.py`는 다른 모듈에 의존하지 않지만, 실제로는
> feature/info의 GPS 데이터가 들어와야 의미가 생긴다.

## 알려진 제약사항 / TODO

- 존 확장 임계값(`REJECT_RATIO_THRESHOLD`), 스코어링 가중치(`W_SPECIALTY`/`W_DISTANCE`)는
  `scoring.py`/`geo.py`에 상수로 박아뒀다 — 실제 운영 데이터 없이 정한 값이라 테스트하며
  조정 필요
- 구급차 GPS는 실시간이 아니라 `AmbulanceInfo`에 고정 저장된 값이다(대회 데모 단계라
  구급차가 실제로 이동하지 않아 서울 랜드마크로 고정) — 진짜 실시간 GPS 연동은
  이번 범위가 아니다
- voice 자가등록(`/voice/register`)이 온 apid의 `AmbulanceInfo`가 아직 없으면(즉
  feature/info가 그 구급차 정보를 아직 안 보냈으면) 409로 거부하고 재시도 큐 없이
  그냥 실패한다 — voice 쪽에서 재시도 로직을 두거나, info가 먼저 뜨는 걸 운영 순서로
  못박아야 한다
- dashboard가 브라우저 마이크 오디오를 실시간으로 hub에 보내는 코드
  (`sendAudioChunk`)는 이미 있지만, 실제 STT 입력은 voice의 로컬 마이크로
  확정되어 hub는 그 오디오 프레임을 받기만 하고 버린다 — 필요해지면 재검토

## 추가사항
