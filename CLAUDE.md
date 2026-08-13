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
    - E-Gen 목록정보 (getEgytListInfoInqire — 좌표 · 응급의료기관 등급)
    - E-Gen 실시간 가용병상 (getEmrrmRltmUsefulSckbdInfoInqire — hvec 등 병상 6종 · 장비 가용)
    - E-Gen 중증질환 수용가능 (getSrsillDissAceptncPosblInfoInqire — MKioskTy 28항목)
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
| 병원 적합도 매칭 (거리·병상·존 스코어링) | 규칙 기반 (E-Gen 3개 오퍼레이션 대조) | AI 미사용, 설명 가능한 구조 유지 |
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
feature/info ──(병원 정보 JSON, assessment 포함)─────→ feature/hub
feature/hub ──(통합 매칭 결과 JSON, WebSocket)───────→ feature/dashboard
feature/dashboard ──(승인 액션 JSON, WebSocket)──────→ feature/hub
feature/dashboard ──(통화 시작/종료 신호, WebSocket)─→ feature/hub ──(HTTP 중계)──→ feature/voice
```

~~병상 갱신(hub→info)은 이송 확정(`final_approval`) 시점에만 발생하는 부분
갱신이다~~ → **2026-08-13 이 화살표 자체가 없어졌다.** info가 병원
Supabase 없이 E-Gen 실 API로 병상까지 직접 읽으면서(조회 전용이라 hub가
쓸 방법이 원래 없었음), hub→info 방향 통신이 통째로 사라졌다. 이송 확정
시점의 병상 차감은 이제 hub 혼자 자기 메모리(TTL 오버레이, 15분)로만
처리한다 — feature/info로 아무것도 되돌려 쓰지 않는다. 자세한 것은
"feature/hub 담당자 참고사항"의 "병상 차감은 TTL 오버레이로 처리한다" 참고.

아래 포맷은 voice를 제외하고는 아직 약식이다. 병원 매칭 결과 스키마는 feature/hub
README.md의 "입출력 데이터 포맷"이 최신 버전이므로, 아래에는 구 스키마를 남기지 않는다.

### 1. feature/voice → feature/hub : 의료 정보(환자 정보)

```json
{
  "caseId": "case-abc123",
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
| `caseId` | string | 여러 구급차가 동시에 사건을 진행할 수 있어, hub가 이 요약을 어느 사건과 짝지을지 구분하는 값. voice가 hub의 통화 시작 신호(3번 포맷)에서 받은 caseId를 그대로 돌려준다 |
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
- **"실시간 음성 필터링"(`filtering.py`, 의료 관련 여부 분류) 단계는 파이프라인에서 뺐다.** threshold가 검증 안 된 상태라 false negative(중요 문장 오제외) 리스크가 있었고, SBAR 구조화 LLM 프롬프트가 이미 잡담·인사말을 스스로 걸러낼 정도로 구체적이라 얻는 이득이 불확실했다(실측 후 결정, `voice/README.md` 참고). 대신 STT 자체의 오인식을 줄이려고 `initial_prompt`로 "이 통화가 어떤 종류의 대화인지"(장르·구조)를 서술해 넘긴다 — 구체 시나리오 어휘를 넣으면 그 샘플에만 맞는 오버피팅이 되므로 일부러 뺐다. `filtering.py`·`live_transcribe.py` 파일 자체는 데드 코드로 삭제됐다(2026-08-12) — 그 대신 `corrections.json`/`text_postprocess.py` 기반 **오인식 교정**(STT와 LLM 사이에서 사전과 정확히 일치하는 구간만 치환, `raw_text`는 교정 전 원문 그대로 보존)이 새로 들어갔다
- 원본 로그 보존 원칙(완전 삭제 금지, 사후 검증·audit trail용)은 유지된다 — `transcript.raw_text`/`turns`에 전체 발화가 그대로 남는다
- 출력 포맷은 위 "데이터 포맷 및 흐름 > 1. feature/voice → feature/hub" 참고. **dashboard로는 직접 전송하지 않고 feature/hub를 거쳐 전달된다**
- 개인정보(이름, 주민등록번호, 주소)는 AI 처리 대상에서 제외
- hub가 중계하는 통화 시작/종료 신호(3번 포맷)를 받는 로컬 서버(`voice/app.py`)가 있다. 통화 시작 시 로컬 마이크 녹음을 시작하고, 종료 시 기존 배치 파이프라인(STT→SBAR)을 그대로 실행한다
- **여러 구급차 동시 처리를 지원한다.** 이 프로세스 자체는 구급차 1대 전용(마이크가 그 장비 하나뿐)이지만, `VOICE_APID` 환경변수로 자신을 식별해 서버 시작 시 자기 IP를 자동 탐지한 뒤 hub의 `POST /voice/register`로 자가등록한다(구급차 노트북마다 네트워크가 달라 IP를 고정 저장하지 않고 매번 탐지). `POST /call/start`로 받은 `caseId`를 세션에 기억해뒀다가, 통화 종료 후 hub로 보내는 `CallSummaryMessage`에 그대로 실어 돌려준다 — hub는 이 caseId로 사건을 구분한다

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
- `send_to_hub.py`는 1회성 스크립트가 아니라 **상시 프로세스**다 — hub는 한 번 받은 병원 정보를 메모리에 들고 있을 뿐 스스로 재조회하지 않으므로, 이 스크립트가 주기적으로(기본 30분, `INFO_REFETCH_INTERVAL_SEC` 환경변수로 조절) 다시 조회해 재전송한다. Supabase realtime 구독 대신 주기적 재조회 방식을 택했다. hub가 잠깐 안 떠 있어도 죽지 않고 다음 주기에 재시도한다
- ~~**E-Gen 실 API가 상시 파이프라인에 연결됐다(2026-08-11)** — 목록·좌표·중증질환은 실 API로, 실시간 병상 수(hvec)만 계속 Supabase 대체 DB로 가져와 합친다~~ → **2026-08-13 병원 Supabase 의존을 완전히 제거.** 병상까지 포함해 목록·병상·중증질환 전부 실 E-Gen API(`HttpEgenClient`)에서 가져온다. Supabase에 병상만 남겨뒀던 이유(E-Gen이 조회 전용이라 hub의 `final_approval` 차감을 되돌려 쓸 방법이 없어서)는 hub 쪽 **TTL 병상 오버레이**(`hub/hub_engine.py`의 `BED_OVERLAY_TTL_MIN`, 15분)로 대체됐다 — 자세한 것은 아래 "feature/hub 담당자 참고사항" 참고
- ~~**Supabase 대체 DB의 hpid는 가짜다.**~~ → **해소됨.** 병상 소스가 Supabase에서 E-Gen 실 API로 바뀌면서, 두 소스의 hpid를 맞추던 `SUPABASE_TO_EGEN_HPID`(7곳 수기 대응표)와 `_remap_to_supabase_hpid()`를 통째로 삭제했다. **`hospitalId`가 `S0000001~7` 체계에서 실제 E-Gen hpid(`A1100017` 등)로 바뀌었다** — dashboard 접근 코드(`/hospital?id=`)로 쓰던 값이 전부 무효화된다. 대응표 병목이 없어져 E-Gen이 주는 병원 전체(서울 기준 실측 55곳, 전국 500여 곳)가 hub로 흘러간다
- ~~hub→info 방향(병상 갱신 쓰기)도 **구현 완료**됐다~~ → **2026-08-13 완전히 폐지.** `info/app.py`(`POST /hub/bed-update` 수신 서버)를 삭제했다 — 병원 Supabase 자체가 없어지면서 되돌려 쓸 대상이 사라졌기 때문. hub의 `delivery.py`도 `send_to_info()`/재시도 대기열을 같이 제거했다
- **여러 사건(구급차) 동시 처리를 지원하는 구급차 레지스트리 동기화가 추가됐다.** 병원용과는 **별도의 Supabase 프로젝트**(`ambulances` 테이블, apid/name/gps/voicePort)를 `send_to_hub.py`가 같은 주기로 읽어 `POST /info/ambulances`로 hub에 보낸다. `AMBULANCE_SUPABASE_URL`/`AMBULANCE_SUPABASE_KEY` 환경변수가 없으면 이 부분만 조용히 건너뛰고 병원 정보 동기화는 그대로 진행한다 — voice의 실제 IP는 여기 없고(구급차 노트북마다 네트워크가 달라 자주 바뀔 수 있음) voice가 뜰 때 hub에 직접 자가등록한다(feature/hub 담당자 참고사항 참고)

### 신뢰도 진단·외부 대조 트랙 (`hospital_score/`, 2026-08-12 신설 — `feature/info-v2`)

> ~~**아직 hub로 나가지 않는다.**~~ → **2026-08-13 상시 파이프라인에 연결 완료.**
> `send_to_hub.py`가 이제 병원마다 `hospital_score.scoring.score_hospital()`을
> 그 자리에서 호출해 `HospitalInfo.assessment`에 실어 hub로 보낸다(스냅샷 파일이
> 아니라 이번 사이클에 이미 받은 raw rows로 `D.Hospital`/`D.Frame`을 구성 —
> `snapshot_nationwide.bat`이 항상 떠 있어야 하는 숨은 의존을 피하려는 선택).
> hub는 이 값을 순위 계산에는 안 쓰고 `HospitalMatch.reliability`로 dashboard에
> "왜 이 순위인지" 설명 근거로만 전달한다(feature/hub 담당자 참고사항 참고).
> `hospital_score/`는 여전히 바깥 모듈을 import 하지 않으므로, 이 트랙만 통째로
> 지워도 `send_to_hub.py`가 `assessment` 없이 원본 그대로 보내는 것으로 안전하게
> 낮아진다(코드는 `try/except`로 감싸둠).

- **왜 만들었나** — E-Gen이 주는 값은 전부 **병원이 스스로 신고한 것**이고, 같은 소스
  안에서는 그게 맞는지 검증할 방법이 없다. 실측으로 확인된 구멍: 하루 넘게 방치된 병상
  값을 실시간으로 송출하는 병원이 **전국 25곳(최고 8.6년)**이고, **전국 가용병상 1위가
  2,457일 묵은 값**이다(한림대학교한강성심병원 30병상 — 2위부터는 전부 10분 이내 갱신이라
  오염된 건 정렬 맨 윗칸 하나다). 중증질환 수용가능 신고의 "정보미제공"은 전체 70.8%이고
  등급별로 21.4% → 53.0% → 88.2% → 96.4%로 계단식이다. 그리고 **화상 전문병원 5곳 중
  E-Gen에 화상 역량이 보이는 곳은 0곳**이다
- **심평원(HIRA) 3종을 붙였다.** 서비스키는 E-Gen과 **같은 값**이다(data.go.kr은 계정당
  인증키 하나, 서비스별 활용신청만 따로 필요). `.env`에 `HIRA_SERVICE_KEY` 한 줄 추가 필요
  - 병원정보(15001698) `hospInfoServicev2/getHospBasisList` — `ykiho`·좌표·의사 수
  - 의료기관별상세(15001699) **`MadmDtlInfoService2.8/`** 11종 — 전문과목별 전문의 수 등
  - 전문병원 지정 현황(15051054) `api.odcloud.kr` — 분야별 114곳
- ⚠️ **엔드포인트 버전 함정 (여기서 몇 시간을 날렸다)**: 구버전 `MadmDtlInfoService2.7`도
  게이트웨이에 실재해서 **403(권한 없음)**을 돌려준다. 이걸 보고 "경로는 맞고 승인만 안
  났다"고 오진하기 쉽다. data.go.kr은 경로를 서비스+오퍼레이션 전체로 검증하며,
  `400 NO_OPENAPI_SERVICE`는 없는 경로, `403 NOT_REGISTERED`는 실재하나 권한 없음이다.
  **403은 "현재 버전"이라는 뜻이 아니다** — 버전은 반드시 포털 마이페이지 활용신청 상세
  화면의 **End Point** 줄로 확인할 것
- **E-Gen ↔ 심평원 조인은 좌표 최근접으로 푼다.** 공통 식별자가 없다(`hpid` ↔ `ykiho`).
  **533곳 중 518곳(97.2%)이 1.2km 이내, 오차 중앙값 11m.** 기관명 정규화만으로는 92.7%라,
  좌표 없는 데이터(전문병원 지정)를 이름으로 붙인 결과는 **하한**으로 읽어야 한다
- **새 장비에서는 명령 두 개를 먼저 돌려야 한다.** 심평원 수집 결과는 `data/` 아래라
  커밋되지 않는다. 캐시가 없어도 점수는 나오지만 **심평원 근거가 통째로 빠져 미상이 전부
  `unknown_bare`로 떨어지고**, 홀드아웃 검증(화상 0→4)도 재현되지 않는다
  ```bash
  cd info/Hospital_inform/info
  python -m hospital_score.hira_files --fetch    # 전문병원 지정 (API 2회)
  python -m hospital_score.hira --build-join     # 조인 + 전문의 수 (API 약 520회)
  ```
  `--build-join`은 재시도 3회·25곳마다 중간저장·이어받기를 한다. 캐시를 치우고 처음부터
  재생성해 대조한 결과 조인 518곳이 **내용까지 동일**했고, 전문의 수는 오히려 3곳 늘었다
  (이전 실행에서 커넥션 오류로 놓친 곳들)
- **산출물은 `[여건 스칼라 + 15그룹 역량 벡터] + 신뢰도 + 근거`다.** 병원당 단일 점수는
  만들지 않는다 — 심근경색 환자와 화상 환자에게 같은 병원의 수용가능성이 다르다.
  점수는 "정답이 없으므로" 최적화하지 않고 **근거 강도의 계층 5단계 + 불변식**으로 정한다
  (`불가능 0.2 < 근거없는미상 0.4 < 전문의있는미상 0.6 < 전문병원지정미상 0.8 < 가능신고 1.0`).
  **`score`와 `confidence`는 끝까지 곱하지 않는다** — 섞으면 "확실히 낮음"과 "모르겠음"이
  구분되지 않는다(미상과 확인된 만실을 구분해온 원칙과 같다).
  전문병원 지정을 홀드아웃 정답으로 쓴 검증에서 **화상 후보가 0곳 → 4곳**이 됐다
- **hub로 보낼 형태는 기존 `HospitalInfo`에 `assessment` 키 하나를 얹은 superset**이다
  (`scoring.build_payload()`, 병원당 약 5.1KB). 기존 필드는 그대로다. ⚠️ 이름 주의 —
  기존 `capabilities`는 역량 코드 7종 `list[str]`이고, 판정의 15그룹은 `assessment.groups`다.
  **hub의 pydantic이 unknown 필드를 거부하면 보내는 순간 기존 연동이 깨지므로 동시 배포가
  필요하다**(`schema.py`는 `extra="forbid"`인 팀 합의 계약 파일)
- **폐기 판정 (되살리지 말 것)**: 병상 수 예측은 `P(만실 전환) = 0.568%`(서울 6,519쌍,
  10분 지평 / 전국은 0.301%. 사전 등록 기준 2% 미달)로 접었고, 미상 추정 모델은 관측
  3,574칸 중 **95.6%가 "가능"**이라 상수 기준선이 이미 95점인 데다 라벨이 상위 등급에
  편중된 MNAR이라 접었다 — 그대로 적용하면 "미신고 병원도 대부분 수용 가능"이라는
  **위험한 방향**의 오류가 난다. 편중의 크기는 실측된다: **명부의 21.8%인 최하위 등급이
  라벨의 0.7%만 내놓는다**
  - **이 두 판정은 `python -m hospital_score.discarded`로 재현된다**(API 호출 0회,
    2026-08-14 추가). 그전까지 관측치는 `report.py`로 재현됐지만 이 두 판정만 근거
    코드가 없었다. 최초 분석(2026-08-11)의 `0.618%`와 신뢰구간이 겹쳐 교차검증됐다
- **거절 로그 수신구를 미리 세워뒀다** (`POST /hub/rejection`, 기본 포트 5003 또는 `app.py`에
  Blueprint 두 줄). 점수의 진짜 정답은 "병원이 실제로 받았는가"인데 그건 운영 로그가 쌓여야
  나오고, **로그는 소급해서 만들 수 없다.** 자세한 것은 아래 "거절 로그" 절
- **E-Gen 원본 스냅샷을 20분 주기로 축적 중이다**(`snapshot_nationwide.bat`, 전국 443곳).
  `--stage1`을 비우면 전국이 1회 호출로 오므로 **호출 횟수는 서울만 받을 때와 같다.**
  E-Gen은 과거 이력을 주지 않으므로 시계열이 필요하면 직접 찍어 쌓는 수밖에 없다.
  가공 전 원본을 저장하는 이유는 매핑 해석이 바뀌어도 과거 데이터를 다시 해석할 수 있어야
  해서다(가공본만 남기면 매핑을 고칠 때마다 지난 데이터가 죽는다)

### 거절 로그 — dashboard·hub에 요청하는 인터페이스 (2026-08-12)

info 쪽 수신구는 **이미 완성돼 있다.** `POST /hub/rejection`으로 보내기만 하면 된다.

- **hub는 지금 보내는 형태 그대로도 연동된다.** 필수 필드는 `hospitalId`(또는
  `hospital_id`/`hpid`) 하나뿐이고, 이유가 없으면 `UNSPECIFIED`로 기록된다. 모르는 필드는
  버리지 않고 `extra`에 보존한다 — 받는 쪽에서 까다롭게 굴면 저쪽이 못 붙이고 그 사이 로그가
  영영 사라지기 때문이다
- **dashboard는 "수용 불가" 버튼에 사유 선택을 추가**해야 한다. 어휘는
  `python -m hospital_score.rejection --vocab`
- **이유를 4축으로 나누는 이유**: 화상 병동이 아예 없어서 거절한 것과 그날 당직이
  정형외과라서 거절한 것을 같게 다루면, **일시적 사정 때문에 그 병원을 영구히 후보에서
  밀어내게 된다.** 축이 다르면 갱신 대상도 다르다 — 구조적(`NO_WARD`/`NO_DEPARTMENT`/
  `NO_EQUIPMENT` → 역량 벡터 수정) / 주기적(`ON_CALL_MISMATCH`/`NIGHT_UNAVAILABLE` →
  시간대 패턴) / 순간적(`BEDS_FULL`/`OR_OCCUPIED`/`STAFF_BUSY` → 그때의 여건) /
  환자 요인(`SEVERITY_EXCEEDED`/`AGE_LIMIT` → 병원 속성이 아님)
- `declaredAtRequest`(물어볼 당시 E-Gen 신고값)를 같이 넘기면 **"가능이라 신고했는데 거절"**을
  셀 수 있어, 신고 정확도를 운영 데이터로 직접 측정할 수 있다
- **무응답(`NO_RESPONSE`)도 반드시 남길 것.** 거절 로그는 우리가 후보로 올린 병원에서만
  생기므로, 그것마저 없으면 낮은 점수가 낮은 점수를 재생산하는 되먹임이 생긴다

### ~~hub로 흐르는 병원이 7곳뿐인 문제~~ → 2026-08-13 해결됨

과거엔 `send_to_hub.py`의 `_remap_to_supabase_hpid()`가 `SUPABASE_TO_EGEN_HPID`
대응표 밖의 기관을 전부 버려서, E-Gen에서 533곳을 받아도 hub에는 7곳만 갔다 —
원인은 병상만 Supabase에서 읽던 구조였다. 여기 제안됐던 방향(병상 차감을
Supabase가 아니라 짧은 TTL 오버레이로 관리하고 병상 자체는 E-Gen 실값을 쓴다)을
그대로 채택해 구현했다 — `hub/hub_engine.py`의 `BED_OVERLAY_TTL_MIN`(15분),
`send_to_hub.py`의 Supabase 병상 조회·대응표 삭제. 이제 E-Gen이 주는 병원
전체(서울 실측 55곳, 전국 500여 곳)가 hub로 흘러간다. 예고됐던 대로
`hospitalId`가 `S0000001~7`에서 실 hpid(`A1100017` 등)로 바뀌었다 —
dashboard 접근 코드로 쓰던 값은 재발급이 필요하다.

## feature/hub 담당자 참고사항

- 입력은 두 가지: feature/voice가 보내는 환자 정보 JSON(부상 상태, 예상 병명, 중증도)과 feature/info가 보내는 병원 정보 JSON(위치, 병상, 전문성)
- **dashboard와 직접 통신하는 유일한 브랜치다.** feature/voice·feature/info는 dashboard로 보내지 않고 이 브랜치를 거친다
- 처리는 2단계로 진행한다 (source: "rule" — 거리·존·최종 스코어링은 규칙 기반, 진료과 매칭만 경량 임베딩 모델로 보조)
  1. GPS와 feature/info의 병원 정보로 먼저 존(Zone) 기반 병원 후보 리스트를 만들어 보관한다
  2. feature/voice의 의료 정보(예상 병명·중증도)가 도착하면, 보관해둔 리스트를 voice의 예상 병명과 info의 진료과를 임베딩 유사도로 매칭한 점수 + 거리 점수를 가중합해 재처리한다
- 진료과 매칭이 실패해도(유사도가 낮거나 병원에 진료과 정보가 없어도) 병원을 후보에서 제외하지 않는다 — 거리 기준만으로 순위에 남긴다 (뺑뺑이 방지가 목적이므로 잘못 걸러내는 게 더 위험함)
- 존 확장은 시간 기반이 아닌 명시적 거절 비율 기준. **`app.py`(실서버)에도 배선 완료(2026-08-11)** — 그 전까지는 `MAX_ZONE=1`(0~5km)이 상수로 고정돼 있어서, 서울 전역에 흩어진 실제 병원 데이터로는 zone 1 안에 후보가 하나도 없어 매칭 0건이 나오는 문제가 실제로 재현됐다. `HubEngine.resolve_start_zone()`(첫 매칭 시 후보가 하나라도 잡힐 때까지 zone을 넓힘 — 거절 비율 기반 확장은 "후보가 있는데 다 거절당함"만 감지해서 후보 0개인 사각지대는 못 잡기 때문에 별도로 필요)과 `HubEngine.maybe_expand_zone()`(거절 액션 처리 후에만 호출 — `reject_ratio`가 누적 계산이라 승인 뒤에도 부르면 새 거절 없이 계속 확장되는 문제가 있어 `hospital_reject`에만 gating)로 나눠 구현했다
- **승인 후 캐시된 병상 수가 안 바뀌던 문제 수정(2026-08-11)**: `final_approval`로 실제 병상은 깎이는데, dashboard로 나가는 캐시(`_case_results`)의 병상 수는 별도 스냅샷이라 반영이 안 되던 문제(Supabase 자체는 정상 차감돼서 더 헷갈렸음)를 고쳤다. `_patch_case_result_status()`가 status와 함께 최신 병상 수·`bedCountUnknown`도 다시 읽어오고, 호출 시점도 병상 차감 이후로 옮김
- 출력은 feature/dashboard로 전송하는 통합 매칭 결과 JSON — 의료 정보·예상 병명·통화 전문·병원 정보·병원 리스트를 모두 포함한다 (feature/hub README.md의 "입출력 데이터 포맷" 참고)
- dashboard와는 WebSocket으로 통신한다 (`new WebSocket()`, socket.io 아님 — flask-socketio 대신 순수 WebSocket 라이브러리를 쓴다). hospital_approve/hospital_reject/final_approval 액션의 수신 주체는 **이 브랜치로 확정**됐고, 매칭 상태(`hospitals[].status`) 반영까지 구현·테스트 완료했다
- dashboard의 통화 시작/종료 신호(3번 포맷)를 같은 WebSocket으로 받아 feature/voice의 로컬 마이크 서버로 HTTP 중계한다 — 오디오 자체는 hub를 거치지 않는다
- 병상 수가 미상인 병원과 확인된 만실은 후보에서 안 빼는 결과는 같아도 원인이 다르다 — 섞이면 사후에 데이터 품질 문제인지 실제 만실인지 구분할 수 없다. `HospitalMatch.bedCountUnknown`으로 구분해 내보내며, 미상이어도 `status`는 막지 않는다(미상을 이유로 이송을 막으면 뺑뺑이가 오히려 늘어난다). 승인 처리 시 병상을 안 깎는 이유도 "모르는 병원 / 병상 미상 / 진짜 만실" 세 가지로 나눠 로그에 남긴다
- ~~`delivery.py`의 `send_to_info()`는 더 이상 자리만 있는 TODO가 아니다 — feature/info의 `POST /hub/bed-update`를 실제로 호출한다~~ → **2026-08-13 폐지.** info가 병원 Supabase를 안 쓰면서(E-Gen 실 API로 병상까지 직접 조회) 되돌려 쓸 대상이 사라졌다. `send_to_info()`·재시도 대기열(`pending_bed_updates.jsonl`)·`HubEngine.update_hospital_info()`의 "대기열에 남아있으면 upsert 보류" 방어 로직을 전부 제거했다 — info가 보내는 최신값을 매번 그대로 덮어써도 안전해졌다(아래 TTL 오버레이가 read-time에 적용되므로).
- **병상 차감은 TTL 오버레이로 처리한다.** `HubEngine._bed_overlay`(hpid -> 만료 시각 목록, `BED_OVERLAY_TTL_MIN=15`)에 `final_approval`마다 하나씩 쌓이고, `effective_bed_count()`가 조회 시점에 만료 안 된 개수만큼만 얹어 보여준다. 15분은 `hvidate` 갱신 간격 실측(중앙값 5분, 88.7%가 10분 이내)에서 여유를 둔 값 — 그 안엔 E-Gen 자신도 아직 안 바뀌었을 가능성이 높다. `self._hospitals`의 원본값은 이제 직접 mutate하지 않는다(과거엔 `info.availableBedCount -= 1`로 직접 깎았음)
- **여러 사건(구급차) 동시 처리를 지원한다.** `caseId`로 사건을, `apid`로 구급차(voice 인스턴스)를 구분한다. `HubEngine`은 승인 상태를 `(caseId, hospitalId)` 키로 분리 보관하고, 사건별 최신 매칭 결과를 캐시해뒀다가 승인 액션이 들어오면 재계산 없이 해당 병원 status만 패치해 재브로드캐스트한다(예전엔 이 재브로드캐스트 자체가 없어서 승인 버튼을 눌러도 화면에 반영이 안 됐다)
- `_dashboard_ws` 전역 변수 하나였던 것을 소켓 **집합**으로 바꿔 연결된 모든 dashboard(구급차 여러 개 + 병원 여러 개)에 브로드캐스트한다 — 예전엔 마지막에 연결한 탭만 갱신을 받는 버그가 있었다
- **소켓 재연결 시 진행 중인 사건을 놓치던 문제 수정(2026-08-11)**: hub는 매칭 결과를 "그 순간 연결된 소켓"에만 브로드캐스트해서, 사건이 진행 중인 상태로 새 대시보드 탭이 뒤늦게 열리면 그 탭엔 아무것도 안 뜨는 문제가 실제로 있었다(구급1호차·서울대병원 탭 연결 상태에서 매칭이 끝난 뒤 한양대병원 탭을 새로 열면 그 사건이 안 보임). dashboard가 소켓 연결 직후 `{type:"identify", role, id}` 자기소개를 보내면(`DashboardIdentify`), hub가 `HubEngine.get_cases_for_hospital()`/`get_cases_for_apid()`로 관련된 진행 중인 사건들을 찾아 그 소켓에만 즉시 돌려준다(`app.py`의 `_send_catchup()`) — 응답은 평소 브로드캐스트와 같은 `HubMatchResult` 형식이라 dashboard 쪽에 별도 분기가 필요 없다
- **`HubMatchResult`에 `ambulanceName` 추가(2026-08-11)**: dashboard 상단바가 구급차 이름("구급 1호차")을 표시하려는데, 그동안 `hospitals[].name`(병원명)과 달리 구급차 이름을 실어 보내는 필드가 없었다. `process_voice_summary()`가 사건의 apid(`_case_apid`)로 구급차 레지스트리(`_ambulances`)를 조회해 채운다 — 병원명과 같은 패턴이라, 그 구급차가 실제로 사건에 등장하기 전(아직 통화가 없는 상태)에는 `null`이고 dashboard가 URL의 apid로 대체 표시한다
- **`DashboardIdentityInfo` 응답 신설(2026-08-11)**: 위 두 방식(`hospitals[].name`/`ambulanceName`)은 전부 "사건이 있어야만" 이름이 나가는 한계가 있었다. 대시보드를 열자마자(통화 전이라도) 실명이 뜨고, 존재하지 않는 hpid/apid는 "접근 불가"로 막고 싶다는 요청에 따라, `identify` 메시지에 대해 사건 유무와 무관하게 즉시 이름/존재 여부를 알려주는 응답(`{type:"identity_info", role, id, name, known}`)을 추가했다(`app.py`의 `_send_identity_info()`, `hub_engine.py`의 `get_hospital()`). hub가 이미 인메모리로 갖고 있는 레지스트리(`_hospitals`/`_ambulances`, feature/info가 Supabase에서 읽어 보내준 것)에서 바로 조회하므로 dashboard가 Supabase에 직접 붙을 필요가 없다 — dashboard는 hub와만 통신한다는 원칙을 유지하면서 원하는 결과를 얻는 방식
- **`GET /identity` HTTP 엔드포인트 추가(2026-08-11)**: 위 `identity_info`는 `/hospital`/`/ambulance` 페이지가 열린 뒤(WebSocket 연결 후)에야 존재 여부를 알 수 있어서, 잘못된 코드로 들어가면 그 페이지 전체가 "접근 불가" 화면으로 막히는 방식이었다. 코드 입력하는 **첫 페이지에서 넘어가기 전에** 미리 확인하고 싶다는 요청에 따라 `GET /identity?role=&id=`를 REST로 추가했다 — `_resolve_identity()`로 `identity_info`와 같은 조회 로직을 재사용하며, 다른 origin(dashboard:3000 ↔ hub:5001)의 브라우저 `fetch`가 되도록 이 엔드포인트만 `Access-Control-Allow-Origin: *`을 붙였다
- voice는 구급차마다 별도 장비에서 뜬다. voice가 뜰 때 자기 IP를 자동 탐지해 `POST /voice/register`로 hub에 자가등록하면, hub는 `AmbulanceInfo.voicePort`(feature/info가 Supabase `ambulances` 테이블에서 읽어 보내줌)와 합쳐 주소를 기억해뒀다가 통화 시작/종료 신호를 그 구급차로 중계한다. 구급차 GPS도 하드코딩된 고정값 대신 이 `AmbulanceInfo` 조회로 대체했다
- 실제 hub+info 실서버를 동시에 띄우고 소켓 2개(구급차 탭 + 병원 탭 흉내) 동시 연결, apid 기반 신호 중계, 승인 후 재브로드캐스트까지 전부 실제 HTTP/WebSocket으로 검증했다 (`run_match.py`에도 다중 사건 격리 검증 추가됨)
- **info-v2(`hospital_score/`) 신뢰도 판정을 설명용으로 수신·전달한다(2026-08-13).** info-v2는 병원별로 15개 중증질환군에 대해 5단계 신뢰도(`declared_yes` 1.0 ~ `declared_no` 0.2, `confidence`, `basis` 근거 문장)를 심평원(HIRA) 대조로 판정해 `HospitalInfo.assessment`로 보낸다(Optional — 이 필드 없이 오는 구 feature/info 데이터도 그대로 통과). `process_voice_summary()`가 예상 병명을 이 15개 질환군 어휘와 한 번 더 매칭(기존 진료과 임베딩 매칭과는 별도 호출)해, 매칭된 병원의 그 그룹 판정을 `HospitalMatch.reliability`로 dashboard까지 전달한다
  - **finalScore(거리·진료과 가중합)는 전혀 안 건드렸다** — 순위 계산은 지금과 완전히 동일하고, `reliability`는 "왜 이 순위인지" 설명 근거로만 추가된다(팀 확정: 순위 반영 여부는 hospital_score/README.md의 "hub가 쓰는 방법" 제안 중 이번엔 채택하지 않고 다음 단계로 미룸)
  - hub의 `hub/schema.py`가 `extra="forbid"`로 막혀 있다는 서술이 hospital_score/README.md에 있었는데, 실제로는 아니다(pydantic BaseModel 기본값은 `extra="ignore"`) — `assessment` 필드가 없어도 파싱은 안 깨졌을 것이나, hub가 그 값을 실제로 읽어 쓰려면 어차피 스키마에 명시적으로 선언해야 해서 이번에 추가했다
- ~~**`feature/info-v2`가 develop에 머지됐다(2026-08-13).** ... `send_to_hub.py` 상시 파이프라인은 여전히 이 폴더를 import하지 않는다~~ → **같은 날 상시 파이프라인 연결까지 완료.** `feature/info-v2`를 `feature/info`에도 머지해 한 브랜치로 합쳤고, `send_to_hub.py`가 병원마다 `hospital_score.scoring`을 호출해 `assessment`를 붙여 보낸다. info-v2가 제안했던 TTL 오버레이도 hub 쪽에 구현 완료 — 위 "hub로 흐르는 병원이 7곳뿐인 문제" 절 참고

## feature/dashboard 담당자 참고사항

- 구급차 대시보드와 병원 대시보드는 유사한 레이아웃을 공유하되, 승인 버튼 종류만 다르다 (병원: 병원 승인/불가, 구급차: 이송 승인)
- 각 정보 패널에는 출처 표시가 필요하다: AI 처리된 정보(통화 요약 등)와 규칙 기반 정보(병원 리스트, 지도)를 시각적으로 구분해서 보여준다
- Override 구조를 UI로 드러낼 것: AI가 생성한 요약은 전송 전 구급대원이 확인·수정할 수 있어야 한다
- 실시간 갱신: WebSocket 기반, 완료된 정보부터 순차적으로 갱신 (전체 처리 완료까지 기다리지 않음)
- **feature/hub와만 직접 통신한다.** voice·info와는 직접 연결하지 않으며, voice의 의료 정보·예상 병명·통화 전문과 info의 병원 정보는 모두 feature/hub가 재가공한 통합 결과로만 받는다. 승인 액션(수신처는 feature/hub로 확정)과 통화 시작/종료 신호는 위 "데이터 포맷 및 흐름" 2·3번 참고
- 통화 시작/종료 버튼은 WebSocket으로 hub에 신호를 보낸다. 브라우저 마이크로 캡처한 오디오(`sendAudioChunk`)도 같은 연결로 보낼 수 있지만, 실제 STT 입력은 feature/voice의 로컬 마이크로 확정되어 이 오디오는 화면 시각화(파형, 로컬 자막) 용도로만 쓰인다
- hub가 보내는 `hospitals[].bedCountUnknown`이 true면 병상 수를 "0"이나 "병상 없음"이 아니라 **"미상"**으로 표시해야 한다 — 미상을 만실처럼 보여주면 구급대원이 실제로는 자리가 있을 수도 있는 병원을 스스로 후보에서 빼게 되어, 뺑뺑이를 줄이려는 목적과 정반대가 된다
- **다중 사건(multi-case) 지원 (2026-08-11)**: hub가 `caseId`(구급차 1건의 이송
  이벤트 식별자)·`apid`(구급차 식별자)를 도입함에 따라, dashboard의 상태도 사건
  하나가 아니라 `matchResults: Record<caseId, HubMatchResult>` 맵으로 관리한다.
  - 구급차 대시보드(`/ambulance?id=<apid>`)는 URL의 `?id=`를 자신의 apid로 쓰고,
    "통화 시작" 버튼을 누를 때마다 `crypto.randomUUID()`로 새 `caseId`를 만들어
    통화 시작 신호·승인 액션에 실어 보낸다. 구급차 1대는 항상 자기 사건 하나만
    다루므로 화면에는 그 `caseId` 하나만 `matchResults`에서 꺼내 보여준다.
  - 병원 대시보드(`/hospital?id=<hpid>`)는 자기 hpid가 `hospitals[]`에 들어있는
    **모든** 사건을 `matchResults`에서 걸러 카드 리스트로 나열한다 — 여러 구급차가
    동시에 같은 병원을 후보로 걸 수 있기 때문에, 사건 하나만 보여주던 이전 구조로는
    다른 구급차의 요청이 화면에서 사라져 보이는 문제가 있었다. 카드를 선택하면 그
    사건 기준으로 지도가 갱신된다.
  - ~~apid/hpid는 아직 URL 쿼리값만으로 구분하며, Supabase 레지스트리에 실제 존재하는
    값인지 서버 사이드 검증은 하지 않는다~~ → **2026-08-11 해결.** dashboard가
    Supabase에 직접 붙지 않고, hub의 신원 확인 응답으로 검증한다. 아래 "이름
    표시" 항목과 같은 메커니즘.
- **접근 코드(hpid/apid) 기반 이름 표시 + 존재 검증 (2026-08-11)**: 상단바가
  "구급 A0000001호차", "병원 ID: S0000001"처럼 ID로만 뜨던 걸 "구급 1호차",
  "서울대학교병원"처럼 실명으로 표시하고 싶었는데, `hospitals[].name`/
  `ambulanceName`은 둘 다 사건(매칭 결과)에 등장해야만 값이 와서 통화 전엔
  이름이 안 떴다. hub가 `identify` 자기소개에 대해 사건 유무와 무관하게 즉시
  이름/존재 여부를 알려주는 응답(WebSocket `identity_info`)을 추가로 보내주는
  방식으로 해결했다 — `useDashboardSocket`의 `state.identity`(`{name, known}`)가
  이 결과를 담고, `matchResults`(사건 데이터)와는 완전히 분리된 상태다. 이
  과정에서 "dashboard가 병원/구급차 Supabase에 직접 붙어서 해결하자"는 대안도
  검토했지만 기각했다 — hub가 이미 info를 통해 두 Supabase 데이터를 인메모리로
  갖고 있어서, dashboard가 Supabase 자격증명을 새로 들고 있을 필요가 없고
  (`dashboard/.env.local`의 `AMBULANCE_SUPABASE_URL`/`KEY`와
  `package.json`의 `@supabase/supabase-js`는 애초에 한 번도 안 쓰여서 이번에
  제거함), "dashboard는 feature/hub와만 직접 통신한다"는 원칙도 그대로
  유지된다.
  - **존재하지 않는 코드 처리 위치를 랜딩 페이지로 이동(2026-08-11 후속)**:
    처음엔 `/hospital`, `/ambulance` 페이지가 열린 뒤(`identity_info`로
    `known=false` 확인 후) 전체 화면을 "존재하지 않는 접근 코드입니다"로
    막는 방식이었는데, 코드 입력하는 첫 페이지(`src/app/page.tsx`)에서
    라우팅하기 전에 바로 알려주고 싶다는 요청으로 바뀌었다. hub에
    `GET /identity?role=&id=`(HTTP, CORS 허용) 엔드포인트를 새로 추가해
    "입장" 버튼을 누르면 라우팅 전에 먼저 조회하고, 존재하지 않으면 입력칸과
    버튼 사이에 빨간 글씨로 안내한다. `/hospital`, `/ambulance` 페이지
    자체의 전체 화면 차단은 제거했다 — 직접 URL로 들어온 경우엔 상단바
    이름이 ID 폴백으로 남는 정도로만 티가 난다(랜딩 페이지 우회는 이번
    범위에서 막지 않기로 함).
- **info-v2 신뢰도 판정("왜 이 순위인지") 설명 표시 (2026-08-13)**: hub가
  `hospitals[].reliability`(질환군·score·confidence·basis)를 보내주면
  구급차 대시보드 병원 후보 카드에 칩+근거 문장으로 노출한다
  (`HospitalCandidateListPanel.tsx`). 이 값은 순위 정렬에는 안 쓰이는 순수
  설명용 정보라 — 실제 순위는 여전히 `specialtyMatch`(진료과 임베딩)와
  `distanceKm`로만 정해진다. `reliability` 필드 자체가 없는 병원(구
  feature/info 데이터 등)은 칩이 안 뜨는 것으로 자연히 처리된다(Optional
  필드라 별도 분기 불필요).

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
