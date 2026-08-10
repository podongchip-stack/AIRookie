# CLAUDE.md

이 파일은 Claude Code가 이 저장소에서 작업할 때 참고하는 공통 컨텍스트입니다.
모든 브랜치(main, develop, feature/voice, feature/info, feature/hub, feature/dashboard)에서 동일하게 적용됩니다.

---

## 프로젝트 개요

**골든링크 (GoldenLink) v2.0** — 2026 AI ROOKIE 대회 출품작

응급이송 과정에서 발생하는 음성, 병원 응답 로그를 자동 수집·구조화하여
병원 수용 판단을 지원하고, 모든 의사결정 과정을 자동 기록하는
**Zero Data Entry 기반 응급이송 지원 플랫폼**이다.

### 핵심 철학
- AI는 의료진의 판단을 대체하지 않는다. 환자 정보 구조화 및 의사결정 기록 자동화 역할만 수행한다.
- 병원 매칭은 거리·병상·존(Zone) 로직은 **규칙 기반 적합도 엔진**으로 구현하되, 예상 병명 ↔ 진료과 매칭만 경량 임베딩 모델로 보조한다 (생성형 LLM은 쓰지 않으며, 결과에 유사도 점수를 노출해 설명 가능한 추천 구조를 유지한다).
- AI가 생성한 모든 환자 프로필은 구급대원이 확인·수정할 수 있으며(Override), 최종 승인된 정보만 병원으로 전송된다.
- On-Premise 운영을 지향한다. 외부 상용 API로 환자 데이터가 나가지 않도록 한다.

### 해결하려는 문제
구급대원이 여러 병원에 순차적으로 전화를 돌리는 "뺑뺑이" 문제. 첫 병원과의 통화 내용을 텍스트로 요약(실시간 음성 필터링 처리)해 존(Zone) 내 모든 후보 병원에 동시에 전달함으로써 순차 전화로 인한 골든타임 손실을 없앤다.

---

## 전체 시스템 흐름

```
사고 발생 → 구급대 도착
    ↓
음성 수집 → 전처리 (FFmpeg 노이즈 제거)
    ↓
현장 정보 구조화 AI
    - Whisper / Qwen3-ASR (STT)
    - sLLM (Llama3 Korean 8B) 정보 추출
    ↓
구급대원 확인 및 수정 (Override) → 환자 프로필 생성
    ↓
존(Zone) 기준 병원 매칭 (규칙 기반 적합도 엔진, AI 미사용)
    - hv1 API (전문의 보유 여부)
    - hvec API (병상 현황)
    - hv2 API (중증 질환별 수용 가능 여부)
    ↓
병원 동시 알림 → 병원 응답 수집 (승인 / 불가)
    ↓
구급대원 최종 승인 (이송 승인) → 카카오내비 자동 연동 → 이송
    ↓
의사결정 블랙박스 AI → 이송 요약 리포트 / 의사결정 근거 보고서 생성
```

---

## 브랜치 구조 및 담당 영역

| 브랜치 | 담당 영역 |
|---|---|
| `main` | 배포 기준 브랜치 |
| `develop` | 통합 개발 브랜치 |
| `feature/voice` | 음성 수집, STT, 실시간 음성 필터링, 정보 구조화 |
| `feature/info` | 병원 정보(Hospital Info) DB 관리 및 구조화 (병원 매칭/존 로직은 feature/hub로 이관 확정, 바이탈 수집은 더 이상 사용하지 않음. 승인 액션 수신 주체는 feature/hub로 확정) |
| `feature/hub` | voice의 환자 정보와 info의 병원 정보를 결합한 규칙 기반 매칭 엔진, 존(Zone) 로직, dashboard와의 WebSocket 통신(승인 액션 수신, 통화 시작/종료 신호를 voice로 중계) |
| `feature/dashboard` | 구급차·병원 대시보드 프론트엔드 |

브랜치 전략: `feature/* → develop → main`

---

## 핵심 AI 활용 원칙 (전 브랜치 공통)

작업하는 기능이 아래 표의 어느 항목에 해당하는지 먼저 확인하고, 표시(AI 처리 / 규칙 기반)에 맞게 구현한다.

| 구분 | 처리 방식 | 비고 |
|---|---|---|
| 음성 → 텍스트 변환 | AI (Whisper / Qwen3-ASR) | 화자 분리 포함 |
| 통화 내용 필터링·구조화 | AI (sLLM + KM-BERT) | 실시간 음성 필터링 처리 — 잡담·불필요 발화 제거 후 의료 관련 문장만 추출 |
| 병원 리스트 정렬 | 규칙 기반 (GPS 거리 · 존 그룹) | AI 미사용 |
| 진료과 매칭 (예상 병명 ↔ 병원 진료과) | AI 보조 (경량 임베딩 유사도, sentence-transformers) | 생성형 LLM 아님, 결정적·설명 가능(유사도 점수 노출), On-Premise |
| 병원 적합도 매칭 (거리·병상·존 스코어링) | 규칙 기반 (hv1/hvec/hv2 API 대조) | AI 미사용, 설명 가능한 구조 유지 |
| 의사결정 기록 · 보고서 생성 | AI (On-Premise sLLM) | Fact Checking Engine으로 원본 로그와 대조 검증 |

이 구분을 코드나 UI에 반영할 때는 각 기능이 "AI 처리"인지 "규칙 기반"인지 명시적으로 구분되게 만든다 (예: 로그, 주석, API 응답 필드에 `source: "ai" | "rule"` 등).

---

## 데이터 포맷 및 흐름

voice·info·hub·dashboard 간 데이터는 아래 흐름으로 오간다. **dashboard는 feature/hub와만
직접 통신한다** — feature/voice와 feature/info는 dashboard로 직접 보내지 않고 전부
feature/hub를 거친다. feature/hub는 GPS와 feature/info의 병원 정보로 먼저 존 기반 병원
후보 리스트를 만들어 두고, feature/voice의 의료 정보(부상 상태·예상 병명·중증도)가
도착하면 이를 반영해 리스트를 재처리한 뒤, 의료 정보·예상 병명·병원 정보·병원 리스트를
합쳐 dashboard로 전달한다. 환자 바이탈 정보는 더 이상 사용하지 않기로 결정되어 관련
스키마를 제거했다. dashboard에서 발생하는 승인 행위
(hospital_approve/hospital_reject/final_approval)의 수신 주체는 **feature/hub로 확정**됐다
(아래 2번 포맷 참고). dashboard↔hub 구간은 REST가 아니라 **WebSocket**이다 — dashboard가
`new WebSocket()`(socket.io 아님)으로 접속해 승인 액션과 통화 시작/종료 신호(3번 포맷)를
보내고, hub는 매칭 결과를 같은 연결로 실시간으로 밀어준다.

```
feature/voice ──(의료 정보·예상 병명·통화 전문 JSON)──→ feature/hub
feature/info ──(병원 정보 JSON)──────────────────────→ feature/hub
feature/hub ──(통합 매칭 결과 JSON, WebSocket)───────→ feature/dashboard
feature/dashboard ──(승인 액션 JSON, WebSocket)──────→ feature/hub
feature/dashboard ──(통화 시작/종료 신호, WebSocket)─→ feature/hub ──(HTTP 중계)──→ feature/voice
feature/hub ──(병상 갱신 JSON, HTTP)─────────────────→ feature/info
```

병상 갱신(hub→info)은 이송 확정(`final_approval`) 시점에만 발생하는 부분
갱신이다 — feature/info의 `send_to_hub.py`가 주기적으로(기본 30분) 다시
가져가는 것과는 별개로, 그 사이에 확정된 병상만 즉시 반영해 중복 매칭을
막는다. 스키마·엔드포인트는 feature/info README.md의 "hub → info" 참고.

아래 포맷은 voice를 제외하고는 아직 약식이다. 병원 매칭 결과 스키마는 feature/hub
README.md의 "입출력 데이터 포맷"이 최신 버전이므로, 아래에는 구 스키마를 남기지 않는다.

### 1. feature/voice → feature/hub : 의료 정보(환자 정보)

```json
{
  "transcript": {
    "raw_text": "구급대원: 환자 50대 남성, 교통사고 흉부 충격입니다... A병원: 네 잠시만요...",
    "filtered_text": "환자 50대 남성, 교통사고 흉부 충격. 의식 저하, 호흡 곤란.",
    "language": "ko",
    "timestamp": "2026-07-28T14:32:31Z",
    "duration_sec": 42.3
  },
  "summary": {
    "patient": "50대 남성",
    "mechanism": "교통사고 · 흉부 충격",
    "symptoms": ["의식 저하", "호흡 곤란"],
    "treatment": ["산소 공급", "지혈 완료"],
    "severity_tag": "high"
  },
  "source": "ai",
  "model_used": {
    "stt": "faster-whisper-large-v3",
    "llm": "qwen3:14b"
  }
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `transcript.raw_text` | string | STT 원본 전문. 필터링 전 전체 발화, 삭제하지 않고 보존 |
| `transcript.filtered_text` | string | 실시간 음성 필터링 처리 후 남은 텍스트. 요약의 실제 입력값 |
| `transcript.language` | string | 언어 코드 |
| `transcript.timestamp` | string (ISO 8601) | 통화 시작 시각 |
| `transcript.duration_sec` | number | 통화 길이(초) |
| `summary.patient` | string | 환자 인적사항 요약 (개인정보 제외) |
| `summary.mechanism` | string | 사고 기전 |
| `summary.symptoms` | string[] | 증상 목록 |
| `summary.treatment` | string[] | 처치 목록 |
| `summary.severity_tag` | `"high"` \| `"medium"` \| `"low"` | 중증도 단계, 이 세 값만 허용 |
| `source` | `"ai"` | AI 처리 결과임을 나타내는 고정값 |
| `model_used.stt` / `model_used.llm` | string | 실제 사용된 모델명 |

이 JSON은 feature/hub로 전달되며, feature/hub는 `summary`(부상 상태·예상 병명·중증도)는
매칭 스코어링에 쓰고, `transcript.raw_text`/`transcript.filtered_text`(통화 원문 전체·
필터링된 텍스트)는 스코어링에는 안 쓰지만 dashboard가 확인할 수 있도록 통합 결과에
그대로 실어 전달한다. dashboard는 이 JSON을 직접 받지 않고, feature/hub가 재가공한
통합 결과(아래 feature/hub README.md 참고)를 통해서만 받는다.

> 병원 정보 스키마(feature/info → feature/hub)와 통합 매칭 결과 스키마(feature/hub →
> feature/dashboard)는 feature/hub README.md의 "입출력 데이터 포맷"이 최신 버전이므로,
> 여기서는 중복 정의하지 않는다.

### 2. feature/dashboard → feature/hub : 승인 액션 (약식)

```json
{
  "action": "final_approval",
  "hospital_id": "C",
  "actor": "paramedic",
  "timestamp": "2026-07-28T14:34:05Z"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `action` | `"hospital_approve"` \| `"hospital_reject"` \| `"final_approval"` | 어떤 승인 행위인지 |
| `hospital_id` | string | 대상 병원 식별자 |
| `actor` | `"hospital"` \| `"paramedic"` | 누가 누른 행위인지 |
| `timestamp` | string (ISO 8601) | 행위 발생 시각 |

### 3. feature/dashboard → feature/hub → feature/voice : 통화 시작/종료 신호

dashboard의 "통화 시작"/"통화 종료" 버튼 신호. 같은 WebSocket 연결로 오며, hub는
오디오 자체는 다루지 않고 이 신호만 **그 구급차(apid)의** feature/voice
인스턴스로 HTTP 중계한다. 실제 STT 입력은 voice의 로컬 마이크로 확정했다 —
dashboard가 브라우저 마이크로 캡처해 보내는 오디오(`sendAudioChunk`)는 화면
시각화 용도로만 쓰고, hub는 그 프레임을 받기만 하고 버린다.

**여러 사건(구급차) 동시 처리를 지원한다.** voice는 구급차마다 별도 장비에서
뜨고, hub는 apid로 그 voice의 주소를 구분한다 (voice가 뜰 때 자기 IP를
자동 탐지해 hub에 자가등록 — feature/hub README.md "입력 스키마 8" 참고).
`caseId`로 사건을 구분해 승인 상태·매칭 결과가 서로 다른 구급차끼리 안 섞인다.

```json
{
  "type": "call_signal",
  "signal": "call_started",
  "timestamp": "2026-07-28T14:15:00Z",
  "apid": "A0000001",
  "caseId": "case-abc123"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `type` | `"call_signal"` | 고정값 |
| `signal` | `"call_started"` \| `"call_ended"` | 통화 시작인지 종료인지 |
| `timestamp` | string (ISO 8601) | 신호 발생 시각 |
| `apid` | string | 어느 구급차인지 — hub가 중계할 voice 주소를 찾는 키 |
| `caseId` | string | 이번 통화의 사건 식별자. dashboard가 통화 시작 시 새로 생성해 보낸다 |

---

## feature/voice 담당자 참고사항

- 입력 데이터는 음성 중심이다: 구급대원 브리핑, 환자·보호자 진술. 영상은 다루지 않는다
- STT 모델: Whisper 또는 Qwen3-ASR (스트리밍 지원)
- 실시간 음성 필터링 처리: STT 결과를 문장/발화 턴 단위로 분리 → 의료 관련 여부 분류(경량 분류기 또는 KM-BERT) → 관련 문장만 sLLM(Llama3 Korean 8B)에 전달해 SBAR 형태로 구조화
- 잡담·인사말·통화 연결 관련 발화는 필터링 대상이며, 필터링된 문장도 원본 로그에는 남겨두고 "요약 제외" 표시만 한다 (완전 삭제 금지 — 사후 검증 및 audit trail 때문)
- 출력 포맷은 위 "데이터 포맷 및 흐름 > 1. feature/voice → feature/hub" 참고. **dashboard로는 직접 전송하지 않고 feature/hub를 거쳐 전달된다**
- 개인정보(이름, 주민등록번호, 주소)는 AI 처리 대상에서 제외
- hub가 중계하는 통화 시작/종료 신호(3번 포맷)를 받는 로컬 서버(`voice/app.py`)가 있다. 통화 시작 시 로컬 마이크 녹음을 시작하고, 종료 시 기존 배치 파이프라인(STT→필터링→SBAR)을 그대로 실행한다 — 동시 통화 여러 건 처리는 다음 단계

## feature/info 담당자 참고사항

> **브랜치 이름 변경 안내**: 이 브랜치는 기존 `feature/vital`에서 이름이
> 변경되었습니다. **병원 매칭·존(Zone) 로직은 `feature/hub`로 이관하는 것으로
> 확정**되었습니다. dashboard가 보내는 승인 액션
> (hospital_approve/hospital_reject/final_approval)의 수신 주체도
> **`feature/hub`로 확정**되었습니다.

- 환자 바이탈 정보는 더 이상 사용하지 않기로 결정되어, 바이탈 수집·전송 관련 서술은 모두 제거했다
- 병원 매칭·존(Zone) 로직은 더 이상 이 브랜치가 담당하지 않는다 (`feature/hub` 담당자 참고사항 참고)
- 승인 프로세스: 병원의 "승인"은 후보 등록일 뿐이며, 구급대원의 "이송 승인"이 최종 확정이다. 이동 중에도 새 병원이 승인하면 재선택 가능해야 한다
- 출력 포맷은 위 "데이터 포맷 및 흐름 > 1. feature/voice → feature/hub" 참고 (병원 정보 스키마는 feature/hub README.md 참고). 승인 액션(2번 포맷)은 feature/hub가 수신하므로 이 브랜치는 별도 구현이 필요 없다
- 병상 수가 미상인 병상 종류는 `bedsByType`에 그 키(`ER_ADULT` 등)를 아예 넣지 않는 방식으로 표시한다(`egen/mapper.py`의 `build_beds_by_type`). `availableBedCount`엔 보수적으로 0을 넣지만, hub가 `bedsByType`의 키 유무로 "미상"과 "확인된 만실"(`{"ER_ADULT": 0}`)을 구분해 재해석한다
- `send_to_hub.py`는 1회성 스크립트가 아니라 **상시 프로세스**다 — hub는 한 번 받은 병원 정보를 메모리에 들고 있을 뿐 스스로 재조회하지 않으므로, 이 스크립트가 주기적으로(기본 30분, `INFO_REFETCH_INTERVAL_SEC` 환경변수로 조절) Supabase를 다시 조회해 재전송한다. Supabase realtime 구독 대신 주기적 재조회 방식을 택했다. hub가 잠깐 안 떠 있어도 죽지 않고 다음 주기에 재시도한다
- hub→info 방향(병상 갱신 쓰기)도 **구현 완료**됐다. `app.py`가 `POST /hub/bed-update`(기본 포트 5002 — 팀 합의로 info 포트 고정, 2026-08-11)로 hub의 병상 갱신을 받아 `SupabaseEgenClient.update_bed_count()`로 Supabase의 `hvec` 컬럼에 즉시 반영한다 — 위 주기적 재조회의 최대 30분 지연을 이송 확정 시점만큼은 보정해준다. 실제 Supabase 병상이 줄어드는 것까지 확인됐다(info/README.md "hub → info" 참고)
- **여러 사건(구급차) 동시 처리를 지원하는 구급차 레지스트리 동기화가 추가됐다.** 병원용과는 **별도의 Supabase 프로젝트**(`ambulances` 테이블, apid/name/gps/voicePort)를 `send_to_hub.py`가 같은 주기로 읽어 `POST /info/ambulances`로 hub에 보낸다. `AMBULANCE_SUPABASE_URL`/`AMBULANCE_SUPABASE_KEY` 환경변수가 없으면 이 부분만 조용히 건너뛰고 병원 정보 동기화는 그대로 진행한다 — voice의 실제 IP는 여기 없고(구급차 노트북마다 네트워크가 달라 자주 바뀔 수 있음) voice가 뜰 때 hub에 직접 자가등록한다(feature/hub 담당자 참고사항 참고)

## feature/hub 담당자 참고사항

- 입력은 두 가지: feature/voice가 보내는 환자 정보 JSON(부상 상태, 예상 병명, 중증도)과 feature/info가 보내는 병원 정보 JSON(위치, 병상, 전문성)
- **dashboard와 직접 통신하는 유일한 브랜치다.** feature/voice·feature/info는 dashboard로 보내지 않고 이 브랜치를 거친다
- 처리는 2단계로 진행한다 (source: "rule" — 거리·존·최종 스코어링은 규칙 기반, 진료과 매칭만 경량 임베딩 모델로 보조)
  1. GPS와 feature/info의 병원 정보로 먼저 존(Zone) 기반 병원 후보 리스트를 만들어 보관한다
  2. feature/voice의 의료 정보(예상 병명·중증도)가 도착하면, 보관해둔 리스트를 voice의 예상 병명과 info의 진료과를 임베딩 유사도로 매칭한 점수 + 거리 점수를 가중합해 재처리한다
- 진료과 매칭이 실패해도(유사도가 낮거나 병원에 진료과 정보가 없어도) 병원을 후보에서 제외하지 않는다 — 거리 기준만으로 순위에 남긴다 (뺑뺑이 방지가 목적이므로 잘못 걸러내는 게 더 위험함)
- 존 확장은 시간 기반이 아닌 명시적 거절 비율 기준
- 출력은 feature/dashboard로 전송하는 통합 매칭 결과 JSON — 의료 정보·예상 병명·통화 전문·병원 정보·병원 리스트를 모두 포함한다 (feature/hub README.md의 "입출력 데이터 포맷" 참고)
- dashboard와는 WebSocket으로 통신한다 (`new WebSocket()`, socket.io 아님 — flask-socketio 대신 순수 WebSocket 라이브러리를 쓴다). hospital_approve/hospital_reject/final_approval 액션의 수신 주체는 **이 브랜치로 확정**됐고, 매칭 상태(`hospitals[].status`) 반영까지 구현·테스트 완료했다
- dashboard의 통화 시작/종료 신호(3번 포맷)를 같은 WebSocket으로 받아 feature/voice의 로컬 마이크 서버로 HTTP 중계한다 — 오디오 자체는 hub를 거치지 않는다
- 병상 수가 미상인 병원과 확인된 만실은 후보에서 안 빼는 결과는 같아도 원인이 다르다 — 섞이면 사후에 데이터 품질 문제인지 실제 만실인지 구분할 수 없다. `HospitalMatch.bedCountUnknown`으로 구분해 내보내며, 미상이어도 `status`는 막지 않는다(미상을 이유로 이송을 막으면 뺑뺑이가 오히려 늘어난다). 승인 처리 시 병상을 안 깎는 이유도 "모르는 병원 / 병상 미상 / 진짜 만실" 세 가지로 나눠 로그에 남긴다
- `delivery.py`의 `send_to_info()`는 더 이상 자리만 있는 TODO가 아니다 — feature/info의 `POST /hub/bed-update`를 실제로 호출한다. URL은 `INFO_BED_UPDATE_URL` 환경변수(기본값 `http://127.0.0.1:5002/hub/bed-update`, info 포트는 5002로 고정)로 바꿀 수 있고, info가 잠깐 안 떠 있어도 예외를 흡수하고 hub 프로세스는 계속 진행한다(voice/info가 서로의 부재를 조용히 흡수하는 것과 같은 방어 패턴)
- 위 전송이 실패하면 그냥 버리지 않고 `hub/data/pending_bed_updates.jsonl`에 쌓아 **재시도 큐**로 관리한다. hub는 상시 백그라운드 루프가 없는 순수 요청-응답 구조라, 재시도 시점은 새 스레드 대신 "다음 `send_to_info()` 호출 기회(=다음 승인 액션)"로 삼았다. `HubEngine.update_hospital_info()`는 해당 병원이 이 대기열에 남아있는 동안은 info발 갱신을 건너뛴다 — 그렇지 않으면 info의 주기적 재조회가 hub가 이미 깎아둔 값을 낡은 값으로 되돌려버리기 때문이다(실제로 재현·복구까지 검증됨)
- **여러 사건(구급차) 동시 처리를 지원한다.** `caseId`로 사건을, `apid`로 구급차(voice 인스턴스)를 구분한다. `HubEngine`은 승인 상태를 `(caseId, hospitalId)` 키로 분리 보관하고, 사건별 최신 매칭 결과를 캐시해뒀다가 승인 액션이 들어오면 재계산 없이 해당 병원 status만 패치해 재브로드캐스트한다(예전엔 이 재브로드캐스트 자체가 없어서 승인 버튼을 눌러도 화면에 반영이 안 됐다)
- `_dashboard_ws` 전역 변수 하나였던 것을 소켓 **집합**으로 바꿔 연결된 모든 dashboard(구급차 여러 개 + 병원 여러 개)에 브로드캐스트한다 — 예전엔 마지막에 연결한 탭만 갱신을 받는 버그가 있었다
- voice는 구급차마다 별도 장비에서 뜬다. voice가 뜰 때 자기 IP를 자동 탐지해 `POST /voice/register`로 hub에 자가등록하면, hub는 `AmbulanceInfo.voicePort`(feature/info가 Supabase `ambulances` 테이블에서 읽어 보내줌)와 합쳐 주소를 기억해뒀다가 통화 시작/종료 신호를 그 구급차로 중계한다. 구급차 GPS도 하드코딩된 고정값 대신 이 `AmbulanceInfo` 조회로 대체했다
- 실제 hub+info 실서버를 동시에 띄우고 소켓 2개(구급차 탭 + 병원 탭 흉내) 동시 연결, apid 기반 신호 중계, 승인 후 재브로드캐스트까지 전부 실제 HTTP/WebSocket으로 검증했다 (`run_match.py`에도 다중 사건 격리 검증 추가됨)

## feature/dashboard 담당자 참고사항

- 구급차 대시보드와 병원 대시보드는 유사한 레이아웃을 공유하되, 승인 버튼 종류만 다르다 (병원: 병원 승인/불가, 구급차: 이송 승인)
- 각 정보 패널에는 출처 표시가 필요하다: AI 처리된 정보(통화 요약 등)와 규칙 기반 정보(병원 리스트, 지도)를 시각적으로 구분해서 보여준다
- Override 구조를 UI로 드러낼 것: AI가 생성한 요약은 전송 전 구급대원이 확인·수정할 수 있어야 한다
- 실시간 갱신: WebSocket 기반, 완료된 정보부터 순차적으로 갱신 (전체 처리 완료까지 기다리지 않음)
- **feature/hub와만 직접 통신한다.** voice·info와는 직접 연결하지 않으며, voice의 의료 정보·예상 병명·통화 전문과 info의 병원 정보는 모두 feature/hub가 재가공한 통합 결과로만 받는다. 승인 액션(수신처는 feature/hub로 확정)과 통화 시작/종료 신호는 위 "데이터 포맷 및 흐름" 2·3번 참고
- 통화 시작/종료 버튼은 WebSocket으로 hub에 신호를 보낸다. 브라우저 마이크로 캡처한 오디오(`sendAudioChunk`)도 같은 연결로 보낼 수 있지만, 실제 STT 입력은 feature/voice의 로컬 마이크로 확정되어 이 오디오는 화면 시각화(파형, 로컬 자막) 용도로만 쓰인다
- hub가 보내는 `hospitals[].bedCountUnknown`이 true면 병상 수를 "0"이나 "병상 없음"이 아니라 **"미상"**으로 표시해야 한다 — 미상을 만실처럼 보여주면 구급대원이 실제로는 자리가 있을 수도 있는 병원을 스스로 후보에서 빼게 되어, 뺑뺑이를 줄이려는 목적과 정반대가 된다

---

## 보안 및 개인정보 원칙 (공통)

- 개인정보 최소 수집: 이름, 주민등록번호, 주소는 AI 처리 대상에서 제외하고 비식별화(Patient ID 기반 관리)한다
- 전송 시 TLS 기반 암호화, 가능한 한 On-Premise로 운영해 외부 상용 API로 환자 데이터가 나가지 않도록 한다
- 모든 의사결정 로그는 타임스탬프 + SHA-256 해시로 저장해 사후 위변조 여부를 검증할 수 있게 한다

---

## 코드 작성 시 유의사항

- 각 기능을 구현하기 전에 위 "핵심 AI 활용 원칙" 표를 참고해 AI 처리 영역인지 규칙 기반 영역인지 먼저 확인한다
- 모델/API 호출부와 비즈니스 로직(존 확장, 승인 처리 등)은 분리해서 구현한다 — 나중에 모델을 교체해도 로직에 영향 없게
- 팀원 전원이 Claude Code를 사용하므로, 함수/변수명과 커밋 메시지는 한글 설명을 포함해도 무방하나 코드 자체는 일관된 컨벤션을 유지한다
