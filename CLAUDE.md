# CLAUDE.md

> ⚠️ **`demo` 브랜치의 작업은 `develop`(과 `main`)에 병합 금지 (2026-10-03 팀 규칙).**
> `demo`는 시연 영상·자동 시연 전용 브랜치다(시나리오 진행기·녹화 도구·시연 전용 입구 등). `develop`의 변경을
> `demo`로 가져가는 것(develop → demo)만 하고, 반대 방향(demo → develop, demo → main) 병합·체리픽은 하지 않는다.
> GitHub 설정으로 막아 두지 않았으니 직접 지켜야 한다.

이 파일은 Claude Code가 이 저장소에서 작업할 때 참고하는 공통 컨텍스트입니다.
모든 브랜치(main, develop, feature/voice, feature/info, feature/hub, feature/dashboard, feature/sim)에서 동일하게 적용됩니다.

---

## 프로젝트 개요

**골든링크 (GoldenLink) v2.0** — 2026 AI ROOKIE 대회 출품작

응급이송 과정에서 발생하는 음성, 병원 응답 로그를 자동 수집·구조화하여
병원 수용 판단을 지원하고, 모든 의사결정 과정을 자동 기록하는
**Zero Data Entry 기반 응급이송 지원 플랫폼**이다.

### 핵심 철학
- AI는 의료진의 판단을 대체하지 않는다. 환자 정보 구조화 및 의사결정 기록 자동화 역할만 수행한다.
- 병원 매칭은 거리·병상·존(Zone) 로직은 **규칙 기반 적합도 엔진**으로 구현하되, 예상 병명 ↔ 진료과 매칭만 경량 임베딩 모델로 보조한다 (생성형 LLM은 쓰지 않으며, 결과에 유사도 점수를 노출해 설명 가능한 추천 구조를 유지한다).
- AI가 생성한 모든 환자 프로필은 구급대원이 확인·수정할 수 있다(Override). ~~최종 승인된 정보만 병원으로 전송된다~~ → **2026-10-13 동작을
  문구에 맞췄다**: 순차 전화를 없애는 목적상 AI 요약은 통화가 끝나자마자 병원에 가되 "AI 요약 · 구급대원 확인 전"으로 표시되고, 구급대원이
  확인·수정하면 갱신본(순위 칸이면 재매칭)이 다시 나가 "구급대원 확인"으로 바뀐다. 고친 칸은 AI 값 → 구급대원 값으로 병원 화면과 의사결정
  로그에 남는다(아래 4번 포맷). 예전엔 대시보드의 [수정]이 화면 안에서만 바뀌고 병원으로 나가지 않았다.
- On-Premise 운영을 지향한다. 외부 상용 API로 환자 데이터가 나가지 않도록 한다.

### 해결하려는 문제
구급대원이 여러 병원에 순차적으로 전화를 돌리는 "뺑뺑이" 문제. 첫 병원과의 통화 내용을 STT로 옮기고 오인식 교정 후 SBAR로 구조화해, 존(Zone) 내 모든 후보 병원에 동시에 전달함으로써 순차 전화로 인한 골든타임 손실을 없앤다.

---

## 전체 시스템 흐름

```
사고 발생 → 구급대 도착
    ↓
음성 수집 → 전처리 (FFmpeg 노이즈 제거)
    ↓
현장 정보 구조화 AI
    - Qwen3-ASR-0.6B + LoRA (STT, 통화 중 발화 단위 인식)
    - KLUE RoBERTa-large + 결정 디코더(MF_BERT 활력징후판) 정보 추출 (환자 수·환자별 13개 항목)
    - Pre-KTAS 추정 (규칙 — 주증상·의식·활력징후)
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
| `feature/voice` | 음성 수집, STT(통화 중 발화 단위 인식), 정보 구조화 |
| `feature/info` | 병원 정보(Hospital Info) DB 관리 및 구조화 (병원 매칭/존 로직은 feature/hub로 이관 확정, 바이탈 수집은 더 이상 사용하지 않음. 승인 액션 수신 주체는 feature/hub로 확정) |
| `feature/hub` | voice의 환자 정보와 info의 병원 정보를 결합한 규칙 기반 매칭 엔진, 존(Zone) 로직, dashboard와의 WebSocket 통신(승인 액션 수신, 통화 시작/종료 신호를 voice로 중계) |
| `feature/dashboard` | 구급차·병원 대시보드 프론트엔드 |
| `feature/sim` | 대량사고(MCI) 분산 이송 시뮬레이션 — 발표·IR 검증 재료 (2026-10-03 신설, 아래 참고사항) |
| `feature/spider` | 거미줄 분배 모델 실험실 `spider/` — 3차원(지리+역량) 공간에서 환자→병원 줄, τ 창 충돌·이동 중 양보 (2026-10-11 신설, 아래 참고사항) |

브랜치 전략: `feature/* → develop → main`

---

## 핵심 AI 활용 원칙 (전 브랜치 공통)

작업하는 기능이 아래 표의 어느 항목에 해당하는지 먼저 확인하고, 표시(AI 처리 / 규칙 기반)에 맞게 구현한다.

| 구분 | 처리 방식 | 비고 |
|---|---|---|
| 음성 → 텍스트 변환 | AI (Qwen3-ASR-0.6B + LoRA 파인튜닝) | 통화 중 말이 끊길 때마다 발화 단위로 인식. 화자 분리는 아직 없음 |
| 통화 내용 구조화 | AI (KLUE RoBERTa-large + 결정 디코더, MF_BERT 활력징후판 4비트 ONNX) + 규칙 해석 | 생성형 LLM 아님 — 환자 수와 환자마다 성별·나이대·주증상(Pre-KTAS 대분류·소분류)·AVPU를 선택지에서 고르고, 활력징후 8개는 모델이 찾은 구간을 규칙으로 숫자로 읽는다. KTAS는 예측하지 않는다. 발화 필터링·오인식 교정 단계는 없음 |
| Pre-KTAS 추정 (2026-10-21) | 규칙 기반 (`voice/pre_ktas.py`) | 모델이 뽑은 주증상·의식·활력징후를 OTAS(KTAS 객관화, Yonsei Med J 2022)·Pre-KTAS 첫인상·Pre-CTAS 혈당 기준에 넣어 가장 위급한 단계. 공식 판정 아님, 덜 위급하게 나올 수 있는 추정값, KTAS 정답으로 검증 전 |
| 병원 리스트 정렬 | 규칙 기반 (GPS 거리 · 존 그룹) | AI 미사용 |
| 진료과 매칭 (예상 병명 ↔ 병원 진료과) | AI 보조 (경량 임베딩 유사도, sentence-transformers) | 생성형 LLM 아님, 결정적·설명 가능(유사도 점수 노출), On-Premise |
| 병원 적합도 매칭 (거리·병상·존 스코어링) | 규칙 기반 (E-Gen 3개 오퍼레이션 대조) | AI 미사용, 설명 가능한 구조 유지 |
| 병상 정보 신뢰도 예측 (병상 숫자가 도착 때까지 유지될 확률) | AI (XGBoost AFT 생존모델, infosurv 벤더링) | 생성형 아님, On-Premise, 캘리브레이트된 확률. **순위(finalScore)에는 관여하지 않는 설명용** — AIROOKIE-EGEN.md 참고. ⚠ 2026-10-10 전제 수정: 응급실 병상은 현재 피드 거의 전부가 환자 단위 실시간 자동 연동. 모델이 재는 "도착 때까지 유지될 확률"(유통기한)은 그대로 맞되, 유통기한이 짧은 원인은 공급자 지연이 아니라 환자 회전이다. "낡음"은 중환자실·수술실 등 배후역량 필드의 문제. 모델이 강해지는 조건은 위급함이 아니라 "승인 병원 적음 + 애매한 포화"(λ≈6~8) — **AIROOKIE-EGEN.md §9**(모델 운영 지침, 상세) 필독 |
| 의사결정 기록 · 보고서 생성 | AI (On-Premise sLLM) | Fact Checking Engine으로 원본 로그와 대조 검증 |

이 구분을 코드나 UI에 반영할 때는 각 기능이 "AI 처리"인지 "규칙 기반"인지 명시적으로 구분되게 만든다 (예: 로그, 주석, API 응답 필드에 `source: "ai" | "rule"` 등).

---

## 데이터 포맷 및 흐름

voice·info·hub·dashboard 간 데이터는 아래 흐름으로 오간다. **dashboard는 feature/hub와만
직접 통신한다** — feature/voice와 feature/info는 dashboard로 직접 보내지 않고 전부
feature/hub를 거친다. feature/hub는 GPS와 feature/info의 병원 정보로 먼저 존 기반 병원
후보 리스트를 만들어 두고, feature/voice의 의료 정보(부상 상태·예상 병명·중증도)가
도착하면 이를 반영해 리스트를 재처리한 뒤, 의료 정보·예상 병명·병원 정보·병원 리스트를
합쳐 dashboard로 전달한다. ~~환자 바이탈 정보는 더 이상 사용하지 않기로 결정되어 관련
스키마를 제거했다.~~ → **회의로 다시 쓰기로 했다(2026-09-29 voice v2).** 활력징후는 voice(MF_BERT)가 통화에서 뽑아 보내고 hub가 dashboard에 표시한다. info가 바이탈을 수집하지는 않는다(병원 정보만 다룬다). dashboard에서 발생하는 승인 행위
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
시점의 병상 차감은 이제 hub 혼자 자기 메모리(차감 오버레이 — 2026-10-08부터 고정 15분이 아니라 사건 기준 유지·해제)로만
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
    "patient_count": 1,
    "patients": [{
      "gender": "남성", "age_group": "60대", "cc_major": "I 심혈관계", "cc_minor": "흉통(심장성)", "avpu": "A",
      "sbp": 150, "dbp": 90, "hr": 110, "rr": null, "spo2": 96, "temp": null, "glucose": null, "gcs": null,
      "pre_ktas": {
        "level": 2,
        "basis": [
          { "rule": "complaint", "level": 2, "text": "주증상 흉통(심장성)" },
          { "rule": "hemodynamic", "level": 3, "text": "수축기혈압 150 + 맥박 110 (100 초과 또는 60 미만)" }
        ],
        "source": "rule"
      }
    }]
  },
  "source": "ai",
  "model_used": {
    "stt": "qwen3-asr-0.6b-119ko-tiny",
    "llm": "mf-bert-vitals-klue-roberta-large-int4"
  }
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `caseId` | string | 여러 구급차가 동시에 사건을 진행할 수 있어, hub가 이 요약을 어느 사건과 짝지을지 구분하는 값. voice가 hub의 통화 시작 신호(3번 포맷)에서 받은 caseId를 그대로 돌려준다 |
| `transcript.raw_text` | string | STT 인식 결과 전문(발화마다 줄바꿈). 전체 발화를 삭제하지 않고 보존 |
| `transcript.filtered_text` | string | 요약의 실제 입력값. 필터링·교정 단계가 없어져 현재는 `raw_text`와 같다 (hub·dashboard와의 계약 필드라 유지) |
| `transcript.language` | string | 언어 코드 |
| `transcript.timestamp` | string (ISO 8601) | 통화 시작 시각 |
| `transcript.duration_sec` | number | 통화 길이(초) |
| `summary.patient_count` | int | 이송할 환자 수(1 이상). `patients` 길이와 같다 |
| `summary.patients[].gender` `age_group` | string | `남성`/`여성`/`판단 보류`, `10대 미만`~`90대이상`/`판단 보류` |
| `summary.patients[].cc_major` `cc_minor` | string | 주증상 대분류(17개)·소분류(169개) — Pre-KTAS 주증상 목록. 모르면 `판단 보류` |
| `summary.patients[].avpu` | string | `A`/`V`/`P`/`U`/`기타`/`언급 없음` |
| `summary.patients[].sbp` `dbp` `hr` `rr` `spo2` `temp` `glucose` `gcs` | number \| null | 통화에서 말한 활력징후 수치. 말하지 않았으면 null. 범위 검사 없음 |
| `summary.patients[].pre_ktas` | object | Pre-KTAS 추정(규칙). `level`(1~5, 걸린 기준이 없으면 null)·`basis`(걸린 기준마다 `rule`·`level`·`text`)·`source: "rule"` |
| `source` | `"ai"` | AI 처리 결과임을 나타내는 고정값 |
| `model_used.stt` / `model_used.llm` | string | 실제 사용된 모델명. `llm`은 계약상 필드명을 유지할 뿐, 현재 값은 생성형이 아닌 MF_BERT 분류 모델이다 |

> **2026-10-21 `summary`가 v2 17필드에서 `{patient_count, patients[]}`(환자별 13개 항목 + `pre_ktas`)로 바뀌었다(MF_BERT 활력징후판).**
> hub(`voice_v2.py`)는 아직 v2를 기대하므로 hub 담당자가 새 형식을 읽도록 고쳐야 한다. 새 형식에는 `ktas_level`(대신 규칙
> 추정 `pre_ktas.level`, null일 수 있음)·`suspected_diagnosis`·`symptoms`·`incidents`·`injuries`·`treatments`·`onset`·
> `medications`·정확한 나이(`age.years`)가 없다. 환자가 여러 명일 수 있다 — 지금 hub는 사건당 환자 한 명을 전제로 한다.
> (그 전: 2026-09-29 v1 6필드 → v2 17필드)

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
인스턴스로 HTTP 중계한다. ~~실제 STT 입력은 voice의 로컬 마이크로 확정했다 —
dashboard가 브라우저 마이크로 캡처해 보내는 오디오(`sendAudioChunk`)는 화면
시각화 용도로만 쓰고, hub는 그 프레임을 받기만 하고 버린다.~~

> **2026-10-03 중앙 voice로 바뀌었다.** voice를 **한 대만** 띄우면(`./voice/start-voice.sh` 인자 없이) 그게
> hub에 "중앙 voice"로 등록되고, 브라우저 마이크 음성(16kHz 모노 16비트 PCM, `lib/pcm-capture.ts`)이 **실제
> STT 입력**이 된다 — hub가 통화 시작 신호를 보낸 소켓의 음성을 사건별로 모아 voice `POST /call/<caseId>/audio`로
> 넘긴다. 휴대폰·태블릿 어디서든 통화할 수 있다. 중앙 voice가 없으면 아래 구급차별 방식(로컬 마이크)으로 돌아간다.
> 자세한 건 hub README "중앙 voice와 휴대폰 통화"

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

### 4. feature/dashboard → feature/hub : 통화 요약 확인·수정 (Override, 2026-10-13)

구급차 대시보드가 같은 WebSocket으로 보낸다. 보낸 칸만 바뀌고, 칸이 하나도 없으면 "수정 없이 확인"이다.

```json
{
  "type": "patient_override",
  "caseId": "case-abc123",
  "ktasLevel": 2,
  "chiefComplaint": "심와부 통증",
  "timestamp": "2026-10-13T14:33:10Z"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `caseId` | string | 고칠 사건. hub는 **그 사건을 연 구급차(apid) 소켓**에서 온 것만 받는다(아니면 `action_refused` reason `not_owner`). 일시정지 중엔 `paused` |
| `expectedDiagnosis` | string? | 예상 병명(비울 수 없음) — 진료과·질환군 매칭 입력 |
| `injuryStatus` | string[]? | 증상 |
| `ktasLevel` | 1~5? | 바꾸면 중증도(`severityTag`)도 1·2 high / 3 medium / 4·5 low로 따라 바뀐다 |
| `requiredDepartment` | string? | 필요 진료과(정확 일치하면 진료과 점수 1.0) |
| `chiefComplaint` | string? | 주 호소(표시용) |

hub는 순위 칸(예상 병명·KTAS·필요 진료과)이 바뀌고 이송 확정 전이면 다시 매칭한다 — 넓힌 존·병원 승인은 유지(승인을 자동으로 풀면
뺑뺑이가 다시 생긴다 — 병원은 고친 칸 상자를 보고 판단을 바꿀 수 있다). 확정 사건이나 표시용 칸만 바뀌면 환자 정보만 바꾼다. 결과는
평소 매칭 결과(`HubMatchResult`)로 그 구급차 탭과 후보 병원 탭에 다시 나가며, `patientInfo.confirmedBy`("ai"|"paramedic")·`confirmedAt`·
`overrides`(칸별 `{field, ai, value, at}`)가 붙는다. 새 통화 회차가 오면 "ai"로 돌아간다. 의사결정 로그 `patient_override`에 칸별 이전값·새 값이
남는다(통화 전문 없음) — 칸별 AI 오류율을 셀 재료다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `type` | `"call_signal"` | 고정값 |
| `signal` | `"call_started"` \| `"call_ended"` | 통화 시작인지 종료인지 |
| `timestamp` | string (ISO 8601) | 신호 발생 시각 |
| `apid` | string | 어느 구급차인지 — hub가 중계할 voice 주소를 찾는 키 |
| `caseId` | string | 이번 통화의 사건 식별자. dashboard가 통화 시작 시 새로 생성해 보낸다 |
| `hospitalId` | string? | 휴대폰 통화 화면에서 고른 첫 통화 병원(2026-10-03). hub가 그 병원 탭에 "📞 통화 중"(`call_status`)을 띄운다 |
| `device` | `"phone"` \| `"tablet"`? | 어느 화면에서 건 통화인지(2026-10-03) |

---

## feature/voice 담당자 참고사항

- 입력 데이터는 음성 중심이다: 구급대원 브리핑, 환자·보호자 진술. 영상은 다루지 않는다
- **STT는 Qwen3-ASR-0.6B + LoRA, 구조화는 MF_BERT 활력징후판(2026-10-20 모델, KLUE RoBERTa-large + 결정 디코더, 4비트 ONNX)이다 (2026-10-21 v2 17필드 모델에서 교체, 2026-10-01 HMM v2에서 교체, 2026-09-29 ASR 교체, 그 전 2026-09-24에 faster-whisper·Ollama 경로를 삭제).** 두 모델은 팀이 따로 파인튜닝한 것으로, 코드는 `voice/asr.py`·`voice/MF_BERT/`에 복사해 넣었다. 가중치는 저장소에 없고 첫 실행 때 자동으로 받는다(`voice/weights.py`) — ASR 어댑터는 `Playedwell03/qwen3-asr-0.6b-119ko-tiny`(베이스 `Qwen/Qwen3-ASR-0.6B-hf`, HF 캐시), MF_BERT는 Hugging Face Hub 공개 저장소 `podongchip/MF_BERT`(ONNX 두 개 + `catalog.json` + `tokenizer/` 약 640MB, CC BY-SA 4.0, 커밋 해시로 고정 — 아래 ⚠ 항목). 이전 HMM 가중치 저장소 `podongchip/goldenlink-voice-models`는 더 이상 쓰지 않는다. `ASR_ADAPTER_DIR`·`MF_BERT_DIR` 환경변수를 주면 Hub 대신 그 로컬 폴더를 쓴다
  - ASR은 AI Hub 119 신고 음성 20시간으로 LoRA 학습(깨끗한 음성 CER 0.187, 1.7B 어댑터와 동등하지만 소음 환경은 1.7B가 낫다). 학습 데이터가 짧은 발화라 통화를 통째로 넣지 않고 발화 단위로 인식한다. 새 어댑터의 실제 음성 인식 품질은 아직 측정하지 않았다
  - MF_BERT는 통화에 질문을 던져 답을 고른다 — 환자 수 질문으로 n명을 정하고, 환자마다 성별·나이대·주증상 대분류·소분류(고른 대분류에 속한 것만)·AVPU는 선택지에서, 활력징후 8개(`sbp` `dbp` `hr` `rr` `spo2` `temp` `glucose` `gcs`)는 통화 토큰 위 구간을 골라 글자를 숫자로 읽는다(`voice/MF_BERT/vitals.py`·`ko_number.py`, 규칙, 한글 숫자 포함, 범위 검사 없음). **KTAS는 예측하지 않는다.** 인코더 MatMul을 4비트(onnxruntime MatMulNBits, 블록 32)로 줄이고 마지막 4층·디코더는 fp32로 둬 1.4GB → 616MB, onnxruntime CPU로 통화 1건 평균 0.58초(실제 통화 테스트셋 612건). 학습 데이터는 합성 통화 + Claude 계열 라벨. **실제 119 통화 바탕 테스트셋 612통화 벤치마크(2026-10-22, `voice/BENCHMARK.md`)에서 배포본 score 0.836·활력징후 0.948** — 같은 데이터로 파인튜닝한 Qwen3.5-0.8B(0.832·0.952)와 비슷하고, 지시문만 준 14~20B LLM(0.62~0.66·0.69~0.80)보다 확실히 높다. 양자화 전 원본은 0.840. 약점은 주증상(대분류 0.67·소분류 0.54). 보강 데이터가 이 테스트셋의 오답 유형을 참고해 실제보다 높게 나왔을 수 있다
  - 긴 통화는 512토큰 조각(128토큰 겹침)으로 나눠 인코딩한 뒤 이어 붙인다(`voice/MF_BERT/chunking.py`). 복사본이 원본(`/mnt/D/Project/MF/2026_10_20/small-MF_BERT_vitals/runtime.py`)과 같은 결과를 내는지 실제 통화 테스트셋 612건(Hub 고정 해시에서 받은 가중치)으로 대조해 전부 같은 것을 확인했다(2026-10-21). 예전 PyTorch 코드(`model.py`·`decode.py`·`labels.py`·`parse.py`)는 삭제했다
  - **Pre-KTAS 추정(`voice/pre_ktas.py`, 규칙, 2026-10-21)** — `transcribe.build_call_summary_message()`가 환자마다 `pre_ktas`를 붙인다. 주증상별 최소 단계(OTAS 보충표 2, 169개 중 153개 대응 — 소아·신생아 전용 등 15개는 없음)·산소포화도·혈역학(수축기혈압·맥박)·의식(AVPU·GCS)·SIRS·외상+수축기혈압 90 미만(Pre-KTAS 첫인상)·혈당(Pre-CTAS) 중 가장 위급한 단계. 어느 기준에도 안 걸리면 단계를 지어내지 않고 null. 통증·사고 기전·출혈·소아 기준·65세 가산은 반영 못 하므로 **덜 위급하게 나올 수 있는 추정값**이다. 검증 데이터 5,165명에서 정답 라벨 기준 단계와 모델 출력 기준 단계가 95.4% 일치(규칙 자체는 KTAS 정답으로 검증 전). 자체 검사 `python voice/pre_ktas.py`
  - Qwen3-ASR이 transformers 5.13 이상을 요구해 voice 환경(`rookie_voice`/`AIRookieProject`)을 torch 2.11(cu128)·transformers 5.17로 올렸다. MF_BERT용으로 onnxruntime 1.31(CPU)을 더했다. conda `ml` 환경은 voice에 쓰지 않는다
- **통화 중 발화 단위 인식**(`voice/live_transcriber.py`): 통화 중 0.5초마다 마이크 버퍼를 보고, 말이 끊기면(음량 기반 무음 감지) 그 발화만 잘라 바로 인식해 둔다. 종료 신호 뒤에는 마지막 발화 인식과 구조화만 남아 hub 도착까지 수 초다(108초 통화 실측 3.7초, 끝나고 한 번에 인식하면 약 61초). 무음 판정은 소리 크기만 보므로 현장 소음에 따라 `VOICE_SILENCE_RMS`·`VOICE_UTTERANCE_HOLD_SEC`로 조절한다
- 원본 로그 보존 원칙(완전 삭제 금지, 사후 검증·audit trail용)은 유지된다 — `transcript.raw_text`/`turns`에 전체 발화가 그대로 남는다
- 출력 포맷은 위 "데이터 포맷 및 흐름 > 1. feature/voice → feature/hub" 참고. **dashboard로는 직접 전송하지 않고 feature/hub를 거쳐 전달된다**
- 개인정보(이름, 주민등록번호, 주소)는 AI 처리 대상에서 제외
- hub가 중계하는 통화 시작/종료 신호(3번 포맷)를 받는 로컬 서버(`voice/app.py`)가 있다. 두 모델은 서버가 뜰 때 한 번만 올려둔다. 통화 시작 시 로컬 마이크 녹음과 발화 단위 인식을 시작하고, 종료 시 남은 발화 인식 → 구조화 → hub 전송을 실행한다
- **중앙 모드(`VOICE_MODE=central`, 2026-10-03)** — `./voice/start-voice.sh`를 인자 없이 띄우면 이 모드(포트 6000). 한 대가 모든 구급차를 처리한다: 사건마다 `StreamRecorder`(`voice/stream_recorder.py`, hub가 넘기는 브라우저 PCM을 쌓음)와 발화 인식기를 따로 두고, 모델은 잠금으로 순서대로 나눠 쓴다. hub에 `{"central": true, ip, port}`로 30초마다 등록, 60초 무음이면 통화 자동 종료. 구급차 번호를 주면(`./voice/start-voice.sh A0000001`) 예전처럼 그 장비 마이크 전용
- **실행은 `./voice/start-voice.sh <apid>`(2026-10-03)** — macOS·Linux·Windows(Git Bash) 공통으로 conda 환경 파이썬·구급차별 포트(역삼 A0000001=6001, 성산 6002, 회현 6003)·hub 주소(`HUB_BASE_URL` 하나로 요약 전송 주소까지)를 맞춘다. Windows 콘솔(cp949) 출력 문제는 진입점의 `console.use_utf8_console()`이 막는다. GPU가 없으면 CPU로 돈다(느림, 미검증). Windows에서는 Hub 다운로드의 심볼릭 링크 경쟁 오류(WinError 1314)를 피하려고 `HF_HUB_DISABLE_SYMLINKS=1`도 켠다
- ⚠ **MF_BERT 가중치는 2026-10-20 활력징후판의 Hub 커밋 해시 `1d7e43e19891e567db6778196ca1cac14ad60c5b`로 고정(2026-10-21, `voice/weights.py`의 `MF_BERT_REVISION` 기본값, 태그 `v3-2026-10-20-rtn`과 가중치 같음)** — `main`이나 태그 대신 해시를 쓰는 이유: Hub에 구조가 바뀐 가중치가 올라오면 `voice/MF_BERT/` 코드와 안 맞아 서버가 뜨지 않는다(2026-10-03 실제로 겪음). 이전 PyTorch 모델(`v2-2026-10-02`·`v1-2026-09-30` 태그)은 지금 코드로 읽지 못한다. MF_BERT는 HF 캐시가 아니라 `$HF_HOME/local/MF_BERT-<해시 앞 12자>/`에 실제 파일로 받는다 — 캐시 파일이 심볼릭 링크라 onnxruntime이 `decoder.onnx.data`를 "모델 폴더 밖 경로"로 거부하기 때문. 새 가중치를 들여올 때는 `voice/MF_BERT/` 코드를 먼저 맞춘 뒤 해시를 바꾼다
- **여러 구급차 동시 처리를 지원한다.** 이 프로세스 자체는 구급차 1대 전용(마이크가 그 장비 하나뿐)이지만, `VOICE_APID` 환경변수로 자신을 식별해 서버 시작 시 자기 IP를 자동 탐지한 뒤 hub의 `POST /voice/register`로 자가등록한다(구급차 노트북마다 네트워크가 달라 IP를 고정 저장하지 않고 매번 탐지). `POST /call/start`로 받은 `caseId`를 세션에 기억해뒀다가, 통화 종료 후 hub로 보내는 `CallSummaryMessage`에 그대로 실어 돌려준다 — hub는 이 caseId로 사건을 구분한다

## feature/info 담당자 참고사항

> **브랜치 이름 변경 안내**: 이 브랜치는 기존 `feature/vital`에서 이름이
> 변경되었습니다. **병원 매칭·존(Zone) 로직은 `feature/hub`로 이관하는 것으로
> 확정**되었습니다. dashboard가 보내는 승인 액션
> (hospital_approve/hospital_reject/final_approval)의 수신 주체도
> **`feature/hub`로 확정**되었습니다.

- 환자 바이탈 정보는 info가 수집하지 않는다. (환자 활력징후는 2026-09-29 회의로 voice v2가 통화에서 뽑아 hub → dashboard로 표시하기로 했다 — info와 무관)
- 병원 매칭·존(Zone) 로직은 더 이상 이 브랜치가 담당하지 않는다 (`feature/hub` 담당자 참고사항 참고)
- 승인 프로세스: 병원의 "승인"은 후보 등록일 뿐이며, 구급대원의 "이송 승인"이 최종 확정이다. 이동 중에도 새 병원이 승인하면 재선택 가능해야 한다
- 출력 포맷은 위 "데이터 포맷 및 흐름 > 1. feature/voice → feature/hub" 참고 (병원 정보 스키마는 feature/hub README.md 참고). 승인 액션(2번 포맷)은 feature/hub가 수신하므로 이 브랜치는 별도 구현이 필요 없다
- 병상 수가 미상인 병상 종류는 `bedsByType`에 그 키(`ER_ADULT` 등)를 아예 넣지 않는 방식으로 표시한다(`egen/mapper.py`의 `build_beds_by_type`). `availableBedCount`엔 보수적으로 0을 넣지만, hub가 `bedsByType`의 키 유무로 "미상"과 "확인된 만실"(`{"ER_ADULT": 0}`)을 구분해 재해석한다
- `send_to_hub.py`는 1회성 스크립트가 아니라 **상시 프로세스**다 — hub는 한 번 받은 병원 정보를 메모리에 들고 있을 뿐 스스로 재조회하지 않으므로, 이 스크립트가 주기적으로(기본 5분 — 2026-10-08 30분에서 단축, E-Gen 공개 API가 정확히 5분 묶음으로 갱신됨을 1분 간격 실측으로 확인, 일일 트래픽 80,000회의 1.6%. `INFO_REFETCH_INTERVAL_SEC` 환경변수로 조절) 다시 조회해 재전송한다. Supabase realtime 구독 대신 주기적 재조회 방식을 택했다. hub가 잠깐 안 떠 있어도 죽지 않고 다음 주기에 재시도한다
- ~~**E-Gen 실 API가 상시 파이프라인에 연결됐다(2026-08-11)** — 목록·좌표·중증질환은 실 API로, 실시간 병상 수(hvec)만 계속 Supabase 대체 DB로 가져와 합친다~~ → **2026-08-13 병원 Supabase 의존을 완전히 제거.** 병상까지 포함해 목록·병상·중증질환 전부 실 E-Gen API(`HttpEgenClient`)에서 가져온다. Supabase에 병상만 남겨뒀던 이유(E-Gen이 조회 전용이라 hub의 `final_approval` 차감을 되돌려 쓸 방법이 없어서)는 hub 쪽 **TTL 병상 오버레이**(`hub/hub_engine.py`의 `BED_OVERLAY_TTL_MIN`, 15분)로 대체됐다 — 자세한 것은 아래 "feature/hub 담당자 참고사항" 참고
- ~~**Supabase 대체 DB의 hpid는 가짜다.**~~ → **해소됨.** 병상 소스가 Supabase에서 E-Gen 실 API로 바뀌면서, 두 소스의 hpid를 맞추던 `SUPABASE_TO_EGEN_HPID`(7곳 수기 대응표)와 `_remap_to_supabase_hpid()`를 통째로 삭제했다. **`hospitalId`가 `S0000001~7` 체계에서 실제 E-Gen hpid(`A1100017` 등)로 바뀌었다** — dashboard 접근 코드(`/hospital?id=`)로 쓰던 값이 전부 무효화된다. 대응표 병목이 없어져 E-Gen이 주는 병원 전체(서울 기준 실측 55곳, 전국 500여 곳)가 hub로 흘러간다
- ~~hub→info 방향(병상 갱신 쓰기)도 **구현 완료**됐다~~ → **2026-08-13 완전히 폐지.** `info/app.py`(`POST /hub/bed-update` 수신 서버)를 삭제했다 — 병원 Supabase 자체가 없어지면서 되돌려 쓸 대상이 사라졌기 때문. hub의 `delivery.py`도 `send_to_info()`/재시도 대기열을 같이 제거했다
- **hub→info 방향은 거절 로그 하나로 다시 생겼다(2026-09-10).** 병상 갱신과 달리
  이건 E-Gen이 아니라 info가 쓰기 가능한 자체 운영 로그(`hospital_score/ingest.py`의
  `POST /hub/rejection`)라 왕복이 성립한다. hub가 `hospital_reject`마다 사유를 중계하고
  (`send_rejection_to_info()`), 수신구는 info 상시 프로세스와 별개로 띄우는 선택적
  서버다(`python -m hospital_score.ingest`, 포트 5003). 아래 "거절 로그" 절 참고
- **여러 사건(구급차) 동시 처리를 지원하는 구급차 레지스트리 동기화가 추가됐다.** 병원용과는 **별도의 Supabase 프로젝트**(`ambulances` 테이블, apid/name/gps/voicePort)를 `send_to_hub.py`가 같은 주기로 읽어 `POST /info/ambulances`로 hub에 보낸다. `AMBULANCE_SUPABASE_URL`/`AMBULANCE_SUPABASE_KEY` 환경변수가 없으면 이 부분만 조용히 건너뛰고 병원 정보 동기화는 그대로 진행한다 — voice의 실제 IP는 여기 없고(구급차 노트북마다 네트워크가 달라 자주 바뀔 수 있음) voice가 뜰 때 hub에 직접 자가등록한다(feature/hub 담당자 참고사항 참고)
- **서울 119 구급차 162대로 교체(2026-10-04, `info/ambulance_registry/`).** 시연용 3대(`A0000001~3` 역삼·성산·회현) 대신 소방청 공공데이터 두 CSV(`dashboard/NationalFireAgency*.csv` — 119안전센터 현황·센터별 구급차 대수)로 **서울 119안전센터 119곳의 구급차 162대**(`SEL0001~SEL0162`, 이름 "<센터명> 구급 N", 좌표 = 센터 주소를 카카오 주소→키워드 검색)를 만든다(`build_seoul.py`). 좌표를 못 구한 센터는 상위 센터 좌표로 대신하지 않고 `result/unregistered_centers.csv`로 따로 뺀다(2026-10-04 실행 0곳). Supabase `ambulances` 테이블에는 보강 컬럼(`sido`·`fire_station`·`center`·`unit_no`·`addr`·`phone`·`coord_source`, `schema_extend.sql`)만 더했고 `send_to_hub.py`는 기존 컬럼만 읽어 **hub로 가는 `AmbulanceInfo` 형식은 그대로**다. 적재는 `upload.py`(기본 확인만, `--apply`로 upsert + 목록에 없는 행 삭제, service_role 키는 `info/ambulance_registry/.env` — 커밋 금지). 위치·대수만 실데이터이고 출동·이동은 여전히 시뮬레이션이다
  - **구급차도 묶음 전송 + 목록 동기화.** `send_to_hub.py`가 구급차를 `POST /info/ambulances/batch`로 한 번에 보낸 뒤 `POST /info/ambulances/roster`로 전체 apid 목록을 보낸다 — hub가 목록에 없는 구급차를 지운다(병원 목록 동기화와 같은 규칙). 한 대씩 보내면 160여 번 관제 지도가 다시 나가고, 목록 동기화가 없으면 테이블을 바꿔도 옛 3대가 hub 메모리·상태 파일에 남았다. 묶음 주소가 없는 예전 hub(404)면 한 대씩 보내고 목록 동기화는 건너뛴다

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
  - ⚠ **전제 교정(2026-10-10)**: 위 구멍들은 사실이지만 **꼬리**다. 응급실 병상(hvec)은
    444곳 중 418곳(94%)이 환자 1명 단위 실시간 자동 연동이고(5분 묶음당 전국 29% 변화, 그중
    ±1이 83%, 변화가 근무시간이 아니라 환자 흐름을 따름 — 정원 6병상 안팎의 군 단위 응급실
    51곳은 드물게 바뀌지만 모양은 같다), 한 번도 안 바뀐 26곳은 위 "방치 25곳"과 같은 집합인
    죽은 피드 24곳(hvidate 2018~2022년, **9/7 이후 피드에서 사라져 지금 416곳에는 없음**)과
    응급실 필드만 끊긴 유령 2곳(장흥우리·성남중앙 — 현재 피드엔 장흥우리만)이다. 진짜 "낡은
    값"은 사람이 평일 10~14시에 고치는 중환자실·수술실 필드의 문제다.
    "E-Gen은 병원마다 갱신이 들쭉날쭉해 믿을 수 없다"는 일반화는 응급실에 대해선 틀렸다 —
    중증질환 신고·역량 대조(hospital_score)의 문제 제기는 그대로 유효하다.
    상세·수치 근거는 `AIROOKIE-EGEN.md` 맨 위 "전제 수정"
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
  python -m hospital_score.hira --build-join     # 조인 + 전문의 수 + 배후진료 재료 (API 약 2,100회)
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
- **거절 로그 수신구가 상시 파이프라인에 연결됐다(2026-09-10).** 수신구
  (`POST /hub/rejection`, `hospital_score/ingest.py`)는 전부터 완성돼 있었고, 이제
  hub도 `hospital_reject` 액션마다 이 주소로 사유를 중계한다(`hub/delivery.py`의
  `send_rejection_to_info()`, `hub/app.py`의 `_build_rejection_payload()`). 수신구는
  info의 상시 프로세스와 별개로 띄우는 선택적 서버라
  (`cd info/Hospital_inform/info && python -m hospital_score.ingest`, 포트 5003),
  안 떠 있으면 hub가 조용히 흡수한다(fire-and-forget). 점수의 진짜 정답은 "병원이
  실제로 받았는가"인데 그건 운영 로그가 쌓여야 나오고, **로그는 소급해서 만들 수
  없다.** 자세한 것은 아래 "거절 로그" 절
- **E-Gen 원본 스냅샷을 20분 주기로 축적 중이다**(`snapshot_nationwide.bat`, 전국 443곳).
  `--stage1`을 비우면 전국이 1회 호출로 오므로 **호출 횟수는 서울만 받을 때와 같다.**
  E-Gen은 과거 이력을 주지 않으므로 시계열이 필요하면 직접 찍어 쌓는 수밖에 없다.
  가공 전 원본을 저장하는 이유는 매핑 해석이 바뀌어도 과거 데이터를 다시 해석할 수 있어야
  해서다(가공본만 남기면 매핑을 고칠 때마다 지난 데이터가 죽는다)
- **스냅샷 수집기가 클라우드로 이관됐다(2026-10-04).** 수집 장비(노트북)를 들고 이동하게
  되면서, Supabase Edge Function(`supabase/functions/egen-snapshot`, 프로젝트
  goldenlink-egen · 서울 리전 · pg_cron **5분** — 2026-10-10 20분에서 단축, 마이그레이션
  `20261010140000_egen_snapshot_5min.sql`. 근거: E-Gen이 전국 값을 정확히 5분 묶음으로 내보내고
  그 묶음마다 응급실 병상이 전국 약 29%에서 환자 1명 단위로 바뀜을 1분 탐침으로 확인, 20분 폴링은
  그 변화의 절반 이상을 놓쳤다. 2026-10-10 13:00 이전 데이터는 전부 20분 해상도)이 E-Gen 응답을 **원본 XML 그대로** Storage
  버킷 `egen-snapshots`(공개 읽기)에 쌓는다. 해석(XML→items)은 로컬
  `info/.../snapshot_cloud.py --sync`가 기존 파서(`HttpEgenClient._parse`)로 해서
  `snapshots_nationwide/` JSONL로 복원한다 — live_board 등 소비 코드는 무수정. 과거 1.4GB
  아카이브는 `--seed`로 버킷 `days/`에 업로드돼 있어 어느 장비든 sync만으로 전체 이력을
  받는다. env는 `SNAPSHOT_SUPABASE_URL`(+sync는 ANON_KEY, seed는 SERVICE_KEY),
  E-Gen 키는 함수 secret. `start-all.sh`는 이제 로컬 수집기 대신 이 동기화(`--watch`, 새 수집분이
  생기면 바로)를 띄운다(SERVICE_KEY 있는 장비는 완결 날짜를 `--seed`로 먼저 올림 — 과거 로컬 수집분이
  클라우드 아카이브로 흘러드는 경로). **이 노트북의 작업 스케줄러 로컬 수집(`GoldenLink-EGen-Snapshot-Nationwide`)은
  2026-10-10 Disabled** — 이관 뒤에도 켜져 있어 같은 키로 둘 다 치고 있었다. 로컬 `snapshots_nationwide/`는
  클라우드 사본일 뿐이라 분석 전 `snapshot_cloud.py --sync`로 받는다. ⚠ 일일 트래픽 한도는 키 기준 합산 —
  `snapshot_nationwide.bat`(작업 스케줄러) 같은 별도 로컬 수집이 남아 있으면 끌 것
- **클라우드 수집 = 동기화 트리거 + 멈춘 로컬 파일 넘겨받기(2026-10-04 저녁).** 이관 당일 로컬 수집이
  16:52에 멈춘 뒤 sync가 그 날짜 파일을 "로컬 수집기 파일 — 건드리지 않음"으로 계속 건너뛰어, 신뢰도
  그래프(live_board)·병상 신뢰도 피처가 16:52에 멈춰 있었다. ① 로컬 파일이 `SNAPSHOT_ADOPT_IDLE_SEC`
  (기본 1시간) 넘게 안 바뀌면 sync가 그 날짜를 넘겨받는다 — 원래 파일은 `<날짜>.jsonl.local-base`로
  보관(*.jsonl이 아니라 다른 소비자는 안 읽음)하고 다시 만들 때마다 그걸 바탕으로 클라우드 수집분을 이어
  붙인다(로컬에만 있던 관측 보존). ② `snapshot_cloud.py --watch`: 1분마다(`SNAPSHOT_WATCH_INTERVAL_SEC`)
  오늘 raw/ 개수만 보고 늘면 바로 sync — Supabase가 장비로 직접 알릴 길이 없어 가벼운 확인으로 트리거를
  대신한다. start-all이 20분 고정 루프 대신 이걸 띄운다(seed는 그 안에서 20분마다). ③ live_board 캐시는
  스냅샷 파일이 캐시보다 새로우면 20분을 기다리지 않고 다시 만든다
- **내려받기 실패로 남은 오류 줄은 다음 sync가 다시 만든다(2026-10-11).** sync가 raw 객체를 내려받다 이 장비의
  망이 끊기면 그 폴링이 `"error": "ConnectionError: ..."` 줄로 남는데, 날짜 지문(raw 객체 수)이 안 바뀌어 영영
  그대로였다 — 2026-10-10에 병상·중증질환 폴링 180줄(08:20~19:25)이 이렇게 비어 신뢰도·피로도 분석이 10일 낮을
  통째로 놓쳤다. 두 군데 고침: ① 지문이 같아도 로컬 파일에 네트워크 계열 오류 줄(`_TRANSIENT_ERROR`)이 있으면
  다시 만들고, 여전히 실패하면 `retryAfter`로 20분 뒤에만 재시도(watch가 1분마다 하루치를 다시 받지 않게)
  ② `_rebuild_day`에서 partial/local-base의 오류 줄이 raw보다 우선되던 문제 — partial은 이 장비의 로컬 파일을
  그대로 올린 것이라 그 안의 오류 줄이 raw 원본을 덮었다(10-10이 지문 재생성으로도 안 고쳐진 진짜 원인). E-Gen 자체
  실패(`.err.json`, 9/6~10/4의 170여 줄)는 원본이 없어 그대로 둔다. days/2026-10-09 완결 아카이브는 복구본으로
  덮어씀(공개 URL은 CDN 캐시가 있어 바로 받으면 옛 것이 올 수 있음)
- **sync가 raw를 로컬에 캐시한다 — Supabase Cached Egress 초과 해결(2026-10-25).** `_rebuild_day`에 로컬
  캐시가 없어서 재조립마다 그날 raw를 처음부터 **전부** 다시 받았다. 오늘 날짜는 5분마다 지문(raw 객체 수)이
  바뀌어 하루 288번 재조립되므로, 하루 raw 16.8MB(실측 10-23, 객체 577개)가 `16.8MB × 288/2` = **하루 약
  2.4GB 다운로드**로 불어났다 — 필요량의 약 145배다. `_download`가 공개 URL(`/object/public/`)을 써 CDN을
  타므로 이 트래픽은 일반 Egress가 아니라 **Cached Egress**로 잡히고, 무료 한도 5GB/월을 이것만으로 넘겼다
  (실측 8.00GB · 160% · 유예 종료 11/20). 누적량이 폴링 횟수의 **제곱**으로 늘어, 20분 → 5분 단축(2026-10-10)
  때 폴링은 4배인데 트래픽은 16배가 됐다 — 수집 해상도를 높인 근거는 그대로 맞고, 읽는 쪽 비용이 제곱으로
  따라오는 걸 그때 계산에 넣지 않았다. 고침: raw는 그 시각의 응답을 적은 **불변** 객체라 `.raw_cache/<날짜>/`에
  한 번만 받아 두고 다시 쓴다(`_cached_raw`, 깨진 내려받기는 gzip 검사로 캐시에 안 남긴다). `days/`로 승격된
  날짜는 재조립하지 않으니 그 캐시를 지운다(`_prune_raw_cache`, 날짜당 약 17MB). **수집 주기·데이터 내용·소비
  코드·사용법은 그대로**이고 바뀐 건 같은 객체를 다시 받지 않는 것뿐이다. 실측 검증: 연속 sync 2회에서 1회차
  535객체 15.59MB → 2회차는 그 사이 새로 올라온 **2객체 0.06MB**만(예전엔 537개 15.6MB 전부), 캐시 바이트는
  새로 받은 원본과 sha256 일치(3/3)

### 병상 정보 신뢰도 서빙 (`reliability/`, 2026-09-24 신설)

모델링 프로젝트(`C:\Dev\Modeling\Source-Action-Based Dynamic Reliability and
Egress Estimation Model` — git remote 없는 로컬 전용)에서 학습한 E-Gen 병상
정보 신뢰도 모델(infosurv)의 서빙 트랙. 배경·모델 상세는 저장소 루트
`AIROOKIE-EGEN.md` 참고.

> ⚠ **전제 수정(2026-10-10) — `AIROOKIE-EGEN.md` 맨 위 "전제 수정" 절이 이 트랙의 역할
> 서술에서 우선한다.** 요지: E-Gen은 전국 값을 5분 묶음으로 내보내고, 응급실 병상은 83%가
> 환자 단위 실시간 연동이라 "낡음" 전제가 응급실에선 성립하지 않는다. info가 5분마다 재조회하는
> 지금 `authority`(정보 나이 감쇠)는 실시간 병원에서 거의 1이고 `ttl`은 풀 문제가 없다.
> 남는 가치는 `rArrive`(도착 때까지 유지될 확률 — 리듬 규칙 대비 C +0.05)이며, 첫 연락
> 추천·설명에만 쓰는 현재 위치가 맞다. "낡음"은 중환자실·수술실(사람이 평일 10~14시에 고침)과
> 응급실 필드만 연동이 끊긴 유령(현재 피드 1곳, 장흥우리)의 문제고, 거기선 모델보다 신고
> 나이·유령 규칙(`probe_regime.py`)이 설명 가능하다. ⚠ 그 유령은 값이 안 바뀌어 모델이
> S≈1("가장 믿을 만함")을 내는 **부호 역전** 구간 — 확률이 아니라 "자동 연동 아님" 플래그로
> 내보내야 하며 `bedDataStale`(hvidate 1일 기준)로는 잡히지 않는다(hvidate는 5분마다 전진).
> 예전 "방치 25곳"(hvidate 2018~2022년 죽은 피드)은 9/7 이후 피드에서 사라져 현재 영향 없음. 20분 스냅샷의 "수명 중위 20분"은 폴링 바닥이었고(5분에서 3석 이상 변화는 2%),
> 2026-10-10 13:25부터 5분 수집이 쌓이면 라벨·θ 정의를 다시 보고 재학습한다.
> **같은 날 infosurv 0.4.0에 심장박동(liveness) 필터를 넣고 검증했다** — 출처 시계가 평소 주기
> 2배 넘게 멈춘 관측은 "관측 없음"으로, 전국 20% 동시 정지는 그 시각 제외. E-Gen에서 죽은 24곳
> 제거·8/14 정지 3,978건 제거, C 0.734→0.737, IBS 3% 개선, GBFS는 무변동(음성 대조). 병원
> 개별 끊김은 관측의 0.53%(중위 2h), 전국 정지 59일에 1번. hub 쪽 같은 규칙은 미구현.
> **모델의 역할·λ·언제 강한지·흐름별 사용처는 `AIROOKIE-EGEN.md` §9가 정본**, 측정 스크립트는
> `reliability/probes/`.

- **벤더링 방식이다.** infosurv의 생존함수(`serve.py`)와 학습 모델 JSON
  (`aft_egen_theta3_ext0923.json`), 병원별 리듬 테이블(`route_med_gap.json`)을
  `info/Hospital_inform/info/reliability/`에 복사해 커밋했다 — pip 로컬 경로
  의존이면 팀원 장비에서 안 돌기 때문. 원본이 재학습되면 모델 JSON을 다시
  복사하고 `python -m reliability.build_route_med_gap`으로 테이블을 재생성한다
  (엔진이 모델의 feature_names를 대조해 피처 정의가 어긋나면 그 자리에서 실패시킨다)
- **실시간 피처 빌더는 infosurv에 없어서 여기서 새로 구현했다**(`features.py`) —
  학습 파이프라인(egen_pipeline.py)의 claim-version 규칙(값 변화 = 새 버전,
  공백 1시간 초과 = 세그먼트 리셋, 첫 버전 리듬 피처 NaN, 시각 피처 **UTC**)을
  관측 스트림 방식으로 재현. 검증은 `python -m reliability.selftest`(API 호출 0회)
- **관측 소스가 둘이다**: 같은 장비의 스냅샷 JSONL(클라우드 수집분 사본 — 2026-10-10부터
  5분 주기, 그 전은 20분, 증분 읽기)이 1순위, 이번 사이클 rows가 2순위. 스냅샷이 없어도
  죽지 않는다(info 재조회 5분 해상도로 낮아질 뿐) — hospital_score와 같은 fail-soft 원칙으로, `reliability/` 폴더를
  통째로 지워도 `send_to_hub.py`는 `bedReliability` 없이 원본 그대로 보낸다
- **hub로는 `HospitalInfo.bedReliability`**(predictedSurvivalSec·bornAt·
  sigma·authorityAtSend·ttlSec·modelTag, source: "ai")로 나간다. authority는 정보
  나이에 따라 계속 떨어지는 값이라 info의 전송 시점 값은 스냅샷일 뿐이고,
  hub가 매칭 시점마다 재계산한다(아래 hub 참고사항)
- **잔차 재보정 + 다필드 확장 (2026-09-28).** ① % 노출의 전제로 hvec raw
  확률의 과신을 홀드아웃 실측으로 교정하는 재보정 상수(μR,σR)를 적합해
  적용했다(`calibrate.py`, τ30분 ECE 0.272→0.114 — 확장 필드들은 raw가 이미
  정직해 관문이 저장 거부). ② 학습을 저장소 안으로 자급화(`train_field.py`,
  infosurv fit·evaluate 벤더링 + 관문: 리듬 단독 baseline 대비 시드 3종 전승)
  해 **수술실(hvoc C 0.867)·입원실(hvgc 0.856)·소아(hv28 0.784)** 모델을
  채택했다 — 배후진료 역량(Capacity)의 신뢰도 확장. 중환자실(hvicc)은 이벤트
  부족으로 정직 기각(축적 후 재시도, `model/train_results_hvicc.json`).
  `HospitalInfo.bedReliabilityByType`(키=E-Gen 필드명)로 hub에 전달
- **라이브 채점 보드(2026-10-03, `reliability/live_board.py`)** — "엔진이 얼마나 좋나"를
  라이브로 보여주는 트랙. 창(기본 48시간) 안의 **모든 병원 × 모든 폴링**을 실제 서빙
  엔진(BedReliabilityEngine을 빈 상태로 만들어 폴링 순서대로 observe → predict)으로
  재생·채점한다 — 시뮬 수식 복제가 아니라 실물 엔진이라 "화면 숫자가 실제 엔진
  출력이냐"에 "네"로 답한다. 채점은 /verify와 같은 θ=3석, 캘리브레이션 쌍은 폴링 단위
  조건부 확률(누적 확률을 쓰면 같은 claim이 중복 집계됨). 산출: 현재 보드(병원별 유효
  확률·감쇠 파라미터, 못 믿을 순 정렬)·판명 피드(값 변화 순간 + 그때 모델이 말했던
  확률)·구간별 예측 vs 실제·headline(큰 어긋남 중 사전 경고/고신뢰 실패 수). 수신구
  `GET /verification/live`(20분 캐시, 생성 수십 초 — 락), hub가 그대로 중계. 첫 실측
  (48h): 값 변화 29,898건, 3석↑ 어긋남 3,551건, 그중 695건은 깨지기 전 확률 50% 미만
  경고 상태. 자체 검사 `python -m reliability.live_board`(API 호출 0회)
- **중증질환 신고 신선도는 모델이 아니라 규칙이다(2026-09-28, `severe.py`).**
  infosurv를 중증질환 28항목으로 확장하려던 타당성 실측(`python -m
  reliability.probe_severe`, 47일)에서 값 변화의 90%가 Y↔정보미제공 왕복이고
  만료 수명의 60.1%가 정확히 9.0시간 = **시스템 자동 만료 규칙**임이 드러나
  AFT 학습은 보류했다(진짜 내용 변화 Y↔불가능은 2,658건뿐 — 축적 후 재평가).
  대신 E-Gen 응답에 신고 시각 필드가 없다는 점을 파고들어, 스냅샷 추적으로만
  알 수 있는 "이 신고가 언제부터 이 값이었는지"를
  `HospitalInfo.severeDeclarations`(source: "rule", 미제공 그룹은 키 없음)로
  내보낸다 — hub가 신고 나이·9h 규칙 잔여로 환산(`severeFreshness`)

### 진료과 확장 · 등급 · 병원 목록 동기화 (2026-10-01)

- **진료과를 심평원 전문의 수로 채운다.** `egen/mapper.build_specialties()`가 E-Gen 역량 4개 과에 `data/hira/specialists.json`의 전문과목별 전문의 수를 합친다(응급 수용 과만 — `ACUTE_HIRA_DEPARTMENTS`, 영상의학과·마취통증의학과·진단검사의학과·치과·한방 등 제외). `doctorCount`에 실제 인원, 분과(순환기내과)는 대분류(내과) 인원을 빌린다. 캐시가 없거나 조인 안 된 병원은 기존 4개 과 그대로(fail-soft). 실측: 415곳 중 403곳 반영. 예전엔 438곳 중 186곳(42%)이 진료과 0개였다
- `HospitalInfo.emergencyLevel`: E-Gen 목록의 `dutyEmclsName`(권역/지역응급의료센터 등). hub가 중증 환자 가산에 쓴다
- **E-Gen 응급실·중증질환 메시지 수집(2026-10-07)**: 같은 E-Gen 서비스의 `getEmrrmSrsillDissMsgInqire`(추가 활용신청 불필요, 전국 1회 호출 — Q0를 주면 0건)를 `egen/messages.py`가 `HospitalInfo.acceptanceMessages`(kind er/severe·원문·진료과·질환 코드·시작/종료, source rule)로 옮긴다. 병원이 직접 거는 "지금 이런 환자는 못 받는다" 공지다(실측 125곳·805건 — 응급실 메시지 580, 중증질환 차단 225). 중증 메시지의 질환 코드(Y0010 등 27종)는 hospital_score 15개 질환군 이름(`diseaseGroup`)으로 옮겨 보낸다(항목명으론 "수족지접합"↔"사지접합"처럼 어긋남). 끝난 메시지는 버리고, 조회 실패 시 메시지 없이 전송(fail-soft). 검사 `python -m egen.messages`
- **병상 정원(2026-10-07)**: 실시간 병상 응답에 이미 있는 정원 필드를 `HospitalInfo.bedCapacityByType`(키는 `bedsByType`과 같음 — 응급실 일반 `hvs01`·소아 `hvs02`·중환자실 `hvs17`·수술실 `hvs22`, 0·미입력은 키 없음)로 보낸다. 추가 API 호출 없음. 짝은 `reliability/probe_regime.py`의 실측과 같고, 응급실 정원은 "내 손안의 응급실" 총 병상과 서울 50곳 전부 일치했다. 실측 416곳 중 415곳. ⚠ mapper의 `TOTAL_BED_FIELD`(`hvs38`, 가용 상한 검사용)는 "병원 총 병상"이라 적혀 있지만 실제로는 입원실 정원(hvgc의 짝)이다 — 상한 검사로는 여전히 동작해 그대로 뒀다
- **배후역량 재료(2026-10-08)**: `HospitalInfo.backupCapacity`(심평원 보유 — 의료장비 대수·수술실·중환자실 총량·신생아 중환자실·일반 입원실·간호등급, `hospital_score/hira.py`의 `load_backup_summary()`, 캐시는 `hira --build-join`/`--fetch-backup`)와 `equipmentOperating`(E-Gen 장비 운영 Y/N/N1 10종 원값 — 고장·점검 때만 바뀌는 운영 상태라 거의 고정이 정상, 남은 대수가 아님). 심평원 장비 목록엔 혈관조영장치 항목이 없다. 실측 404곳/416곳
- `send_to_hub.py`가 한 주기 병원을 다 보낸 뒤 `POST /info/hospitals/roster`로 전체 hpid 목록을 보낸다 — hub가 피드에서 빠진 병원을 지운다
- ~~**스냅샷 수집은 이제 `start-all.sh`가 info와 함께 20분 주기로 띄운다**(`--no-snapshot`으로 끔). Windows 작업 스케줄러(`snapshot_nationwide.bat`)로만 돌아서 이 맥에선 8월 13일 이후 멈춰 있었다~~ → **2026-10-04 수집이 클라우드로 이관되면서 start-all은 수집 대신 동기화(`snapshot_cloud.py --sync`, 20분 주기)를 띄운다** — 아래 "스냅샷 수집기가 클라우드로 이관됐다" 참고
- **응급실 `hvec`의 `-1`은 미상이 아니라 과밀 1명(만실 0)으로 읽는다(2026-10-01).** 다른 병상 필드의 -1은 그대로 미입력. 전국 스냅샷에서 hvec -1의 앞뒤 값 77%가 -3~1(0 → -1 → -2처럼 이어짐)이라 미입력일 수 없다. 예전엔 서울아산처럼 꽉 찬 응급실이 "미상"으로 떠서 만실 표시·승인 차단이 안 걸렸다. 신뢰도 모델은 이미 이렇게 읽고 있었다(`egen/mapper.py`의 `MINUS_ONE_IS_VALUE_FIELDS`, `hospital_score/scoring.py`도 같게). 폐기 판정·리포트 재현 스크립트는 기록된 수치를 바꾸지 않도록 그대로 둠. 검사 `python -m egen.test_hvec_minus_one`
- ⚠️ `info/requirements.txt`의 `xgboost==3.4.1`·`numpy==2.5.1`·`scipy==1.18.0`은 Python 3.12 이상용이라 파일 머리의 "3.11" 환경엔 안 깔린다. 3.11 환경은 호환 버전(xgboost 3.2 등)을 깔면 되고, 모델 로드·selftest 통과를 확인했다(2026-10-01). 이게 빠지면 `[reliability] 엔진 초기화 실패` 한 줄만 남기고 `bedReliability` 없이 조용히 보내진다

### 거절 로그 — dashboard·hub·info 연동 (2026-08-12 인터페이스, 2026-09-10 배선 완료)

info 수신구(`POST /hub/rejection`) → **완성.** dashboard 사유 선택 UI → **완성**
(`ApprovalActions.tsx`, 4축 어휘). hub 중계 배선 → **완성**(`send_rejection_to_info()`).
세 지점이 다 이어져 `hospital_reject`가 실제 로그로 쌓인다.

- **hub는 `_build_rejection_payload()`로 `hospitalId`·`caseId`·`timestamp`·`reasonCode`를
  보내고, 사건 캐시가 있으면 `severity`·`diseaseGroup`·`declaredAtRequest`도 best-effort로
  채운다.** 수신구는 필수 필드가 `hospitalId` 하나뿐이고 이유가 없으면 `UNSPECIFIED`로
  기록하며 모르는 필드는 `extra`에 보존한다 — hub 스키마(`ApprovalAction.reason`)를
  `Optional[str]`로 둔 것도 같은 이유다(어휘를 늘렸을 때 액션 전체가 거부돼 로그가
  사라지는 게 더 나쁘다)
- **dashboard "수용 불가" 버튼의 사유 선택**은 이미 붙었다. 어휘는
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
- **데모 도구 (2026-09-29)**: 거절 로그는 실서비스가 돌아야 쌓이는 데이터라 시범운영
  전에는 통계 근거가 될 수 없다 — 대신 배선의 시연용으로 `python -m
  hospital_score.demo_rejections`(고정 시나리오 10건, 전부 `demo: true` 마커)와
  확장 집계 `python -m hospital_score.rejection_report`(4축 + 결정 시점 스냅샷 기반
  "정보 무효 관측 후보" + 무응답 3분해)가 있다. 실 로그가 쌓이기 시작하면
  `--exclude-demo`로 완전 분리된다

### ~~hub로 흐르는 병원이 7곳뿐인 문제~~ → 2026-08-13 해결됨

과거엔 `send_to_hub.py`의 `_remap_to_supabase_hpid()`가 `SUPABASE_TO_EGEN_HPID`
대응표 밖의 기관을 전부 버려서, E-Gen에서 533곳을 받아도 hub에는 7곳만 갔다 —
원인은 병상만 Supabase에서 읽던 구조였다. 여기 제안됐던 방향(병상 차감을
Supabase가 아니라 짧은 TTL 오버레이로 관리하고 병상 자체는 E-Gen 실값을 쓴다)을
그대로 채택해 구현했다 — `hub/hub_engine.py`의 병상 차감 오버레이(당시 `BED_OVERLAY_TTL_MIN` 15분, 2026-10-08 `BedHold` 규칙으로 교체),
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
- **거절 사유를 feature/info 거절 로그로 중계한다(2026-09-10).** dashboard가 보낸
  `hospital_reject` 액션에 `reason`(4축 어휘)이 실려 있으면, `_handle_dashboard_action()`이
  `_build_rejection_payload()`로 `{hospitalId, caseId, timestamp, reasonCode}` +
  사건 캐시에서 best-effort로 `severity`·`diseaseGroup`·`declaredAtRequest`를 채워
  `delivery.send_rejection_to_info()`로 `POST /hub/rejection`(포트 5003, 선택적 서버)에
  보낸다. fire-and-forget — 수신구가 안 떠 있어도 승인 처리·재브로드캐스트는 계속된다.
  `hub/schema.py`의 `ApprovalAction.reason`은 `Optional[str]`(Literal 아님) — 수신구의
  "관대하게 받는다" 원칙에 맞춰 어휘 확장이 액션 거부로 이어지지 않게 한다.
- **의사결정 로그에서 통화 전문을 지문으로 치환한다(2026-09-10).** `decision_log`의
  `hub_match_result` 항목에 `patientInfo.rawTranscript`/`filteredTranscript`를
  `{"sha256", "chars"}`로 바꿔 남긴다(`_redact_transcript()`). 원본은 feature/voice의
  로컬 파일에 이미 보존되고, 위변조 방지 append-only 파일에 개인정보 섞인 자유 텍스트를
  영구 중복 적재하지 않는다. dashboard로 나가는 `HubMatchResult` 자체는 그대로(전문 표시 유지).
- **확정된 지 오래된 사건은 캐시에서 걷어낸다(2026-09-10).** hub는 상시 정리 스레드가
  없어 `_case_*` dict가 무한 누적됐다. `_prune_old_cases()`가 `process_voice_summary()`/
  `apply_approval_action()` 진입 시 "이송 확정 후 `CASE_RETENTION_MIN=60`분 지난" 사건을
  모든 사건 dict에서 제거한다(`_bed_overlay`와 같은 read-time lazy 정리). 진행 중이거나
  아직 확정 전인 사건은 절대 지우지 않아 다중 사건 격리·따라잡기는 불변.
- **병상 차감은 TTL 오버레이로 처리한다.** `HubEngine._bed_overlay`(hpid -> `BedHold` 목록)에 `final_approval`마다 하나씩 쌓이고, `effective_bed_count()`가 조회 시점에 아직 유효한 개수만큼만 얹어 보여준다. `self._hospitals`의 원본값은 직접 mutate하지 않는다(과거엔 `info.availableBedCount -= 1`로 직접 깎았음). ~~고정 15분(`BED_OVERLAY_TTL_MIN`, 근거: hvidate 갱신 간격 중앙값 5분)~~ → **2026-10-08 사건 기준으로 재설계**: 그 5분은 병원 입력 주기가 아니라 E-Gen 시스템의 5분 묶음 주기였고, hub가 병원의 반영을 보려면 이송 + 병원 입력 + E-Gen 묶음 + info 수집이 지나야 해서 15분이면 구급차 도착 전에 차감이 풀려 같은 병상이 다시 비어 보이고 부하 페널티도 꺼졌다. 새 규칙: 확정 + 예상 이동시간 + 20분은 무조건 유지 → 그 뒤 E-Gen 응급실 원값이 확정 당시보다 줄면 해제(줄어든 만큼만) → 끝까지 안 줄면 도착 예상 + 60분에 해제, 수용 완료 시 기준을 실제 도착으로 재설정(`BED_HOLD_GRACE_MIN=20`·`BED_HOLD_MAX_AFTER_ARRIVAL_MIN=60`, 정답 데이터 없는 초기값). 무작정 늘리지 않은 이유는 병원이 이미 고친 뒤 이중 차감되면 작은 응급실이 "확인된 만실"로 떨어져 병원 승인까지 막히기 때문. 해제 이유는 의사결정 로그 `bed_hold_released`(cause `egen_reflected`/`max_age`)로 남겨 상수 재조정 재료로 쓴다. 검증 `python test_bed_hold.py`
- **여러 사건(구급차) 동시 처리를 지원한다.** `caseId`로 사건을, `apid`로 구급차(voice 인스턴스)를 구분한다. `HubEngine`은 승인 상태를 `(caseId, hospitalId)` 키로 분리 보관하고, 사건별 최신 매칭 결과를 캐시해뒀다가 승인 액션이 들어오면 재계산 없이 해당 병원 status만 패치해 재브로드캐스트한다(예전엔 이 재브로드캐스트 자체가 없어서 승인 버튼을 눌러도 화면에 반영이 안 됐다)
- `_dashboard_ws` 전역 변수 하나였던 것을 소켓 **집합**으로 바꿔 연결된 모든 dashboard(구급차 여러 개 + 병원 여러 개)에 브로드캐스트한다 — 예전엔 마지막에 연결한 탭만 갱신을 받는 버그가 있었다
- **소켓 재연결 시 진행 중인 사건을 놓치던 문제 수정(2026-08-11)**: hub는 매칭 결과를 "그 순간 연결된 소켓"에만 브로드캐스트해서, 사건이 진행 중인 상태로 새 대시보드 탭이 뒤늦게 열리면 그 탭엔 아무것도 안 뜨는 문제가 실제로 있었다(구급1호차·서울대병원 탭 연결 상태에서 매칭이 끝난 뒤 한양대병원 탭을 새로 열면 그 사건이 안 보임). dashboard가 소켓 연결 직후 `{type:"identify", role, id}` 자기소개를 보내면(`DashboardIdentify`), hub가 `HubEngine.get_cases_for_hospital()`/`get_cases_for_apid()`로 관련된 진행 중인 사건들을 찾아 그 소켓에만 즉시 돌려준다(`app.py`의 `_send_catchup()`) — 응답은 평소 브로드캐스트와 같은 `HubMatchResult` 형식이라 dashboard 쪽에 별도 분기가 필요 없다
- **`HubMatchResult`에 `ambulanceName` 추가(2026-08-11)**: dashboard 상단바가 구급차 이름("구급 1호차")을 표시하려는데, 그동안 `hospitals[].name`(병원명)과 달리 구급차 이름을 실어 보내는 필드가 없었다. `process_voice_summary()`가 사건의 apid(`_case_apid`)로 구급차 레지스트리(`_ambulances`)를 조회해 채운다 — 병원명과 같은 패턴이라, 그 구급차가 실제로 사건에 등장하기 전(아직 통화가 없는 상태)에는 `null`이고 dashboard가 URL의 apid로 대체 표시한다
- **`DashboardIdentityInfo` 응답 신설(2026-08-11)**: 위 두 방식(`hospitals[].name`/`ambulanceName`)은 전부 "사건이 있어야만" 이름이 나가는 한계가 있었다. 대시보드를 열자마자(통화 전이라도) 실명이 뜨고, 존재하지 않는 hpid/apid는 "접근 불가"로 막고 싶다는 요청에 따라, `identify` 메시지에 대해 사건 유무와 무관하게 즉시 이름/존재 여부를 알려주는 응답(`{type:"identity_info", role, id, name, known}`)을 추가했다(`app.py`의 `_send_identity_info()`, `hub_engine.py`의 `get_hospital()`). hub가 이미 인메모리로 갖고 있는 레지스트리(`_hospitals`/`_ambulances`, feature/info가 Supabase에서 읽어 보내준 것)에서 바로 조회하므로 dashboard가 Supabase에 직접 붙을 필요가 없다 — dashboard는 hub와만 통신한다는 원칙을 유지하면서 원하는 결과를 얻는 방식
- **`GET /identity` HTTP 엔드포인트 추가(2026-08-11)**: 위 `identity_info`는 `/hospital`/`/ambulance` 페이지가 열린 뒤(WebSocket 연결 후)에야 존재 여부를 알 수 있어서, 잘못된 코드로 들어가면 그 페이지 전체가 "접근 불가" 화면으로 막히는 방식이었다. 코드 입력하는 **첫 페이지에서 넘어가기 전에** 미리 확인하고 싶다는 요청에 따라 `GET /identity?role=&id=`를 REST로 추가했다 — `_resolve_identity()`로 `identity_info`와 같은 조회 로직을 재사용하며, 다른 origin(dashboard:3000 ↔ hub:5001)의 브라우저 `fetch`가 되도록 이 엔드포인트만 `Access-Control-Allow-Origin: *`을 붙였다
- voice는 구급차마다 별도 장비에서 뜬다. voice가 뜰 때 자기 IP를 자동 탐지해 `POST /voice/register`로 hub에 자가등록하면, hub는 `AmbulanceInfo.voicePort`(feature/info가 Supabase `ambulances` 테이블에서 읽어 보내줌)와 합쳐 주소를 기억해뒀다가 통화 시작/종료 신호를 그 구급차로 중계한다. 구급차 GPS도 하드코딩된 고정값 대신 이 `AmbulanceInfo` 조회로 대체했다
- 실제 hub+info 실서버를 동시에 띄우고 소켓 2개(구급차 탭 + 병원 탭 흉내) 동시 연결, apid 기반 신호 중계, 승인 후 재브로드캐스트까지 전부 실제 HTTP/WebSocket으로 검증했다 (`run_match.py`에도 다중 사건 격리 검증 추가됨)
- **info-v2(`hospital_score/`) 신뢰도 판정을 설명용으로 수신·전달한다(2026-08-13).** info-v2는 병원별로 15개 중증질환군에 대해 5단계 신뢰도(`declared_yes` 1.0 ~ `declared_no` 0.2, `confidence`, `basis` 근거 문장)를 심평원(HIRA) 대조로 판정해 `HospitalInfo.assessment`로 보낸다(Optional — 이 필드 없이 오는 구 feature/info 데이터도 그대로 통과). `process_voice_summary()`가 예상 병명을 이 15개 질환군 어휘와 한 번 더 매칭(기존 진료과 임베딩 매칭과는 별도 호출)해, 매칭된 병원의 그 그룹 판정을 `HospitalMatch.reliability`로 dashboard까지 전달한다
  - **finalScore(거리·진료과 가중합) 계산식 자체는 안 건드렸다** — `reliability`는 여전히 "왜 이 순위인지" 설명 근거다. 다만 **2026-08-14부로 정렬 순서에는 예외가 하나 생겼다**: 관련 질환군이 `declared_no`(병원이 명시적으로 "수용 불가"라고 신고)면 finalScore와 무관하게 순위 맨 뒤로 밀린다(`scoring.rank()`의 `demote` 키, `hub_engine.py`의 `_should_demote()`). 가중합으로 점수에 섞지 않은 이유는 실험(민감도 분석)으로 확인됐다 — 모든 경우에 역전을 막으려면 신뢰도 가중치가 70%대까지 필요해서 거리·진료과 반영이 무의미해지므로, hospital_score/README.md의 "제거하지 말고 아래로 내릴 것" 지침을 순서 조정으로만 구현했다. 거절 로그가 쌓여 실측 기반 가중치를 낼 수 있게 되면 가중합으로 승격하는 걸 재검토한다
  - hub의 `hub/schema.py`가 `extra="forbid"`로 막혀 있다는 서술이 hospital_score/README.md에 있었는데, 실제로는 아니다(pydantic BaseModel 기본값은 `extra="ignore"`) — `assessment` 필드가 없어도 파싱은 안 깨졌을 것이나, hub가 그 값을 실제로 읽어 쓰려면 어차피 스키마에 명시적으로 선언해야 해서 이번에 추가했다
- ~~**`feature/info-v2`가 develop에 머지됐다(2026-08-13).** ... `send_to_hub.py` 상시 파이프라인은 여전히 이 폴더를 import하지 않는다~~ → **같은 날 상시 파이프라인 연결까지 완료.** `feature/info-v2`를 `feature/info`에도 머지해 한 브랜치로 합쳤고, `send_to_hub.py`가 병원마다 `hospital_score.scoring`을 호출해 `assessment`를 붙여 보낸다. info-v2가 제안했던 TTL 오버레이도 hub 쪽에 구현 완료 — 위 "hub로 흐르는 병원이 7곳뿐인 문제" 절 참고
- **거절 로그가 결정 시점 스냅샷과 무응답까지 담는다(2026-09-28 보강, 09-29 정밀화).** hub→info 거절 중계 페이로드에 그 순간 화면에 보였던 값들(`availableBedCountAtRequest`·`bedCountUnknownAtRequest`·`bedDataStaleAtRequest`·`travelMinAtRequest`·`finalScoreAtRequest`)과 병상 신뢰도 확률(`bedAuthorityAtRequest`·`bedRArriveAtRequest`)을 동봉한다 — BEDS_FULL 거절과 대조하면 정보 무효의 독립 관측(infosurv G2 라벨)이 되고, 확률의 운영 검증 재료가 된다(소급 생성 불가라 지금부터 담는 게 핵심). 무응답(`NO_RESPONSE`)은 사건이 결말에 이르는 두 시점 — `final_approval` 확정, 또는 확정 없이 `HUB_UNRESOLVED_TIMEOUT_MIN`(기본 120분) 유휴 시 sweep(로그만, 사건은 안 지움) — 에 일괄 기록한다(`app.py`의 `_log_no_responses()`/`_sweep_unresolved_cases()`, 검증 `test_rejection_forward.py`)
  - **⚠ 무응답의 소비 지침 — 거절과 다른 축이다.** 거절은 "수용 능력"에 대한 정보지만 무응답은 "채널"에 대한 정보라, **수용성 판정(G2 라벨·assessment 검증)에는 쓰지 않고** 분리 집계한다: `reachedAtBroadcast`(사건 진행 중 그 병원 대시보드에 요청이 실제 도달했던 이력 — `_case_reach`가 브로드캐스트·따라잡기 시점마다 누적) false = **미도달 → 보급 지표**(병원 탓 아님), true인데 무응답 = **무시 → 응답성 지표**(반복되면 거절보다 심각 — 소비처는 순위 강등이 아니라 "전화 확인 우선 대상" 플래그, 제거 금지 원칙 유지). `caseFinalized` false(미결 종료)는 요청 유효성이 모호(데모·중단 포함)하므로 분석에서 따로 거른다
- **병원 정보 확인 루프(2026-09-29 신설)** — 공급자 쪽 피드백. 병원 대시보드에 "귀원 정보 현황"(`hospital_self_info` — 자기 병상 신뢰도·신고 신선도, identify/30분 upsert/확인 직후 전송)을 보여주고, "현재 정보가 맞습니다"(`info_confirm`) 버튼을 받는다. 확인이 오면 그 병원 병상 신뢰도를 **조건부 생존 S(a)/S(u)**로 되올린다(infosurv `confirmed_at` 메커니즘의 첫 실신호원 — 값이 그대로여도 "방금 사람이 확인한 값"임을 시스템이 알게 되는 유일한 경로). 새 claim이 태어나면 자동 무효, 의사결정 로그에 유효 확인 관측으로 기록(향후 G1+ 라벨 재료), 구급차 칩에 ✓ 표시. hub README "병원 정보 확인 루프" 참고
- **중증질환 신고 신선도를 수신·환산한다(2026-09-28).** info의 `severeDeclarations`(질환군별 현재 신고값·관측 기준 탄생시각, 규칙 기반)를 받아, 매칭된 질환군에 대해 신고 나이와 9시간 만료 규칙 잔여를 `HospitalMatch.severeFreshness`(source: "rule")로 dashboard에 전달한다(`hub_engine.py`의 `_severe_freshness_for()`, 상수 `SEVERE_EXPIRY_RULE_SEC` — 실측 근거는 info의 `probe_severe`). `reliability`(같은 신고를 심평원 대조로 "믿을 만한가" 판정)와 상보적 — 이쪽은 "언제 적 것인가". 순위 불변, Optional 하위호환, 검증은 `run_match.py`의 `test_severe_freshness()`
- **병상 정보 신뢰도 예측(infosurv 모델)을 수신·전달한다(2026-09-24).** feature/info의 `reliability/` 모듈이 `HospitalInfo.bedReliability`(Optional — 이 필드 없이 오는 구 데이터도 그대로 통과)로 보내면, hub가 매칭 시점마다 `hub/bed_reliability.py`의 `evaluate()`로 **authority**(지금 이 병상 숫자를 믿어도 될 확률)와 **rArrive**(도착 시점 — 2026-09-28부터 순위에 쓰는 이동 시간 `travelMin`과 같은 horizon 뒤 — 에도 유효할 확률)를 재계산해 `HospitalMatch.bedReliability`로 dashboard에 전달한다. **finalScore·순위에는 관여하지 않는 설명용이다** — `reliability`(hospital_score)와 같은 원칙이되, 이쪽은 서수 티어가 아니라 캘리브레이트된 확률이라 거절 로그로 효과가 실측되면 rArrive의 랭킹 가중치 승격을 재검토한다(AIROOKIE-EGEN.md §5-1). 생존함수는 info 쪽 벤더링 사본(scipy)과 동일 수식을 hub에서 표준 라이브러리로 재구현했고(브랜치 폴더 원칙상 info/를 import 못 함 + scipy 의존 회피), 수치 등가성은 info의 `python -m reliability.selftest`가 검증한다. 검증 시나리오는 `run_match.py`의 `test_bed_reliability()`
- **hub 내부 정비(2026-09-28, 다른 브랜치 변경 없음)** — 자세한 것은 hub/README.md "순위 규칙"·"서버 운영 동작"
  - **순위**: `finalScore = 0.6×진료과 + 0.4×이동시간 점수`. 이동시간은 카카오 ETA 우선, 없으면 직선거리 × 같은 사건 ETA로 보정한 분/km. 점수는 `0.5^(분/15)`라 20km 밖에서도 0이 되지 않는다(예전 `1-km/20`은 20km 밖을 전부 0으로 봤다). 정렬은 일반 → `declared_no`·`beds_full`(**확인된** 만실만, 미상·1일 넘은 값 제외) → `rejected` 순이고, 병원이 이 사건에 승인·확정했으면 내리지 않는다. 승인 액션 뒤 캐시도 재정렬한다. `nightDutyAvailable`은 info가 `bool(capabilities)`로 채우는 프록시라 순위에 쓰지 않는다
  - **출력 필드 추가**(모두 기본값 있음, dashboard 수정 불필요): `HubMatchResult.type="match_result"`·`ambulanceGpsFallback`, `HospitalMatch.finalScore`·`travelMin`·`travelBasis`·`demoteReasons`·`bedDataStale`
  - **운영**: `/voice/summary`는 202로 바로 답하고 매칭은 작업 스레드에서(voice는 본문을 안 씀). 진행 중 사건을 `HUB_REFRESH_INTERVAL_SEC`(기본 60초)마다 재계산해 바뀐 것만 재전송. 상태(병원·구급차·승인·병상 오버레이·사건·voice 주소)를 `data/state/hub_state.json`에 저장·복구 — **통화 원문은 저장하지 않는다**. 엔진·소켓·로그 쓰기에 락. `debug` 기본 끔(`HUB_DEBUG=1`)
  - **의사결정 로그 해시 체인**: 기록마다 `prevHash`(앞 기록 hash). 예전엔 줄마다 자기 내용만 해시해 수정 후 재해시·삭제·순서 변경을 못 잡았다. 체인 이전 기록은 기존 방식으로 검증
  - 실서버 결과 사본 경로를 `data/test/output/`에서 `data/live/output/`으로 분리
  - **승인 흐름**: 병원 승인·거절은 `hospital`, 이송 승인은 `paramedic`만 받고, 이송 승인은 병원이 `approved`한 병원에만 허용한다(어긋나면 `approval_action_refused` 로그만 남김). 이송 병원을 재선택하면 이전 확정 병원을 `approved`로 되돌리고 병상 차감을 회수한다(`approval_released`). dashboard는 이미 이 규칙대로 버튼을 열어 수정 불필요
- **hub 정비 2차(2026-10-01, dashboard·info·start-all 함께 변경)** — 자세한 것은 hub/README.md "순위 규칙"·"서버 운영 동작"·"출동 시뮬레이션"
  - **순위는 hub 한 곳에서만 정한다.** 정렬은 이 사건의 확정 병원 → 병원 승인 병원 → 나머지(finalScore) → `declared_no`·`beds_full` → `rejected`. dashboard의 자체 정렬(병상 → 상태 → 진료과 점수 → 직선거리)을 없앴다 — 그동안 이 자체 정렬이 9월 28일 순위 규칙(카카오 ETA 이동시간 등)을 화면에서 전부 덮어쓰고 있었다
  - **진료과**: voice `required_department`가 병원 진료과에 있으면 정확 일치 1.0(`specialtyMatch.basis="exact"`), 없으면 임베딩(후보에서 안 뺌). **전문성·등급 가산은 점수가 아니라 이동시간에서 분을 뺀다** — 전문의 수 최대 3분 + 중증(high)일 때 권역센터 5분/지역센터 2분. 가산을 다 받아도 8분(`MAX_BONUS_MIN`) 넘게 먼 병원은 못 이긴다는 불변식을 테스트로 고정. `travelBonusMin`·`bonusReasons`·`emergencyLevel`로 설명 노출
  - **역할별 전송**: 매칭 결과는 그 구급차 탭과 후보에 오른 적 있는 병원 탭에만. **방치 사건 닫기**: 무응답 sweep(120분) 뒤 사건을 캐시에서 지우고 `case_closed` 전송. **현장 후보**: 통화 시작 때 거리순 후보(`scene_candidates`, 규칙)를 구급차 탭에만. **병원 목록 동기화**: `POST /info/hospitals/roster`로 피드에서 빠진 병원 제거(진행 중 사건 후보 보류, 목록 급감 시 안 뺌). **질환군 어휘**: info가 보낸 `assessment.groups`에서 만든다(hub 목록은 폴백). 확정된 사건은 60초 재계산에서 재정렬하지 않는다
  - **출동 위치 지정·자동 배속(2026-10-01)**: 구급차 화면에서 주소 검색(hub `GET /geocode`, 카카오 장소·주소 검색 대리 호출) 또는 지도 클릭으로 출동 위치를 고른다(안 고르면 무작위). 구급차 이동(출동·이송·복귀)은 모든 구간이 거리와 무관하게 **5초 고정**(2026-10-03, `HUB_SIM_TRIP_SEC`) — 먼 곳일수록 배속이 올라간다(예전엔 출동·이송 90초·복귀 30초 상한). 주소 글자는 hub로 안 보내고 로그엔 뭉갠 좌표만. 도메인 라우팅에 `/geocode` 추가
  - **출동 시뮬레이션**(`start-all.sh` 기본값 — 2026-10-03부터, 실제 구급차 GPS 수신 경로가 없어서. 끄려면 `--no-sim-dispatch`. 시연용 가짜 위치): [이동] → 현장(기지 5~12분 거리) → 통화·승인 → 확정 병원 → 수용 완료하면 바로(2026-10-03, 예전 15초) → 기지 복귀. `ambulance_sim.py`, 메시지 `dispatch`·`scene_end`(받음) / `ambulance_phase`·`ambulance_position`(보냄, `simulated: true`). 위치는 레지스트리 GPS를 덮지 않고 조회 시점에 얹는다
  - **start-all이 hub 백그라운드 루프를 안 띄우던 버그 수정** — `app.app.run()`만 불러서 60초 재계산·상태 저장·sweep이 실서버에서 한 번도 돌지 않았다. 이제 `app.start_background()`를 먼저 부른다
  - WebSocket 인증은 여전히 없다(시연 범위 허용, hub/README.md 한계에 명시)
  - **확인된 만실 병원은 병원 승인 불가(2026-10-01)**: 응급실 병상 0이 확인된(미상·1일 넘은 값 제외) 병원의 `hospital_approve`는 hub가 거부한다(`_is_confirmed_full`). 병원 화면은 버튼 대신 "응급실 병상 없음" 안내. 이미 승인한 병원은 나중에 0이 돼도 그대로. 이 병원들은 응답할 수 없었으므로 사건이 끝날 때 무응답으로 기록하지 않는다
  - **존 확장 거절 비율(2026-10-01)**: 분모를 "응답한 병원"에서 "현재 존 안 후보 병원 전체"로, 기준을 50% → **40%**로. 예전엔 첫 응답이 거절이면 1/1=100%라 후보 10곳 중 한 곳의 거절로 바로 넓어졌다(`geo.REJECT_RATIO_THRESHOLD`, `HubEngine.reject_ratio`)
- **구급차 묶음 수신·목록 동기화(2026-10-04)**: `POST /info/ambulances/batch {"ambulances": [...]}`(형식 틀린 한 대는 `rejected`로 돌려주고 나머지 반영, 관제 지도 `map_overview`는 끝에 한 번)와 `POST /info/ambulances/roster {"apids": [...]}`(`HubEngine.apply_ambulance_roster`)를 추가했다. 목록에 없는 구급차는 레지스트리·시뮬레이션 유닛·voice 주소에서 지운다 — 단 진행 중 사건(수용 완료 전)이 있거나 출동 시뮬레이션 중인 구급차는 보류, 목록이 비었거나 절반 미만으로 급감하면 부분 조회 실패로 보고 아무것도 안 뺀다. 의사결정 로그 `ambulance_roster_applied`. 기존 `POST /info/ambulances`(한 대씩)는 그대로 받는다. 검증 `test_ambulance_roster.py`
- **hub 병원 순위 = spider 거미줄 분배 모델의 매칭 규칙(2026-10-15, test 브랜치에서 develop으로)**: `hub/spider_rule.py`(원본
  `spider/map.html`·`spider/voice_to_patient.py` — 한쪽을 고치면 다른 쪽도). finalScore는 이제 **줄 길이**에서 만든 정렬 값이다 —
  줄 길이 = 도로 분 − μ×역량 이득(유효 역량 = 등급 + 응급의학과 전문의 두께 + 야간 감점, 필요 역량 = KTAS 1→4·2→3·3→2·4·5→1;
  μ K1·2 30분/레벨·K3 5분·K4·5 −λ 5분, 이송 중 중증 10명이면 0까지 감쇠) 또는 + ν×모자람(30/15/5, 0.75 넘게 모자라면 줄 없음)
  + 부하(이송 중·포화 — 기존 식). 질환군 벽(심근경색 → 혈관조영 운영, 뇌졸중 → CT + 등급 2↑, 중증외상 = 외상 기전 + K1·2 →
  등급 3↑; voice v2 변환에 `trauma` 추가). ~~τ(10분) 창 충돌·양보: 같은 병원·같은 창에 우선하는 사건의 줄이 한도(2)만큼 있으면
  그 병원을 건너뛴다~~ → **2026-10-22 τ 창은 순위에서 뺐다 — 표시만 한다**(`spiderWindow`에 "같은 10분 안 도착 예정 다른 사건 N건"만
  싣고, 건너뛰거나 내리지 않는다. 수용 판단은 병원이. 근거: replay_probe에서 창을 켜면 서울 밀집 도착 거절이 46→51·56→65로 늘고 시간
  이득이 없음 + 임상 자문 "둘 다 받으려 노력한다", `poc/CLINICAL_CONVERGENCE.md` §3). spider 연구 엔진(`spider/engine/`·`map.html`)은
  창 항을 연구 대상으로 그대로 둔다. 정렬 띠는 줄 있음 > 줄 없음(줄 없는 병원도 후보에서 빼지 않고 맨 뒤로). 승인·확정 앞·거절/만실/
  declared_no 내림은 그대로. **빠진 것**: 진료과 임베딩 점수·전문성/등급 가산·경증 센터 역가산(설명 문구 `bonusReasons`로만 — μ·λ·ν가 대신).
  `plan_mci`(대량사고 분배)도 KTAS 순 + 줄 길이(창 한도는 2026-10-22에 뺌 — 분산은 부하 페널티가). `HospitalMatch.spiderLen·spiderGap·spiderBlocked·spiderWindow`(설명용).
  숫자는 spider 표기 그대로 "전문의 검토 전 초안". 야간 감점(22~06시)은 실제 시각 기준이라 밤에 돌리면 얇은 지역기관이 경증도 못 받는 순위가 나온다 — `HUB_SPIDER_HOUR`로 시각을 고정할 수 있다(검사는 14시 고정). 검증 `python test_spider_rule.py`
- **미선택 병원 통보(2026-10-22, 관제 반영 2026-10-24)**: 이송이 확정되면 수용 승인했지만 선택되지 않은 병원에 `HospitalMatch.notSelected`
  깃발이 서고(status는 approved 그대로 — 이동 중 재선택 대상으로 남는다, 확정이 풀리면 내려감), 그 병원 탭에 WS `selection_released`
  (`confirmedHospitalId·confirmedHospitalName`)를 바로 보낸다. 임상 자문 요구 — 수용 승낙은 처치 공간·진료 조정 같은 자원 선배정이라 선택되지
  않았음을 알려 그 준비를 풀게 한다. 병원 대시보드는 토스트 "○○(으)로 이송이 확정됐습니다 — 귀원은 선택되지 않았습니다"(푸시 + 따라잡기 깃발
  두 경로). 의사결정 로그 `selection_released`(보낼 대상·실제 전달 따로). **2026-10-24** 관제 요약 `case_overview.hospitals[].notSelected`에도
  실어 관제 지도 말풍선·시연 콘솔 ③ 칩이 "선택 안 됨", 콘솔 ④에 "미선택 통보 N곳"을 보인다. 검증 `test_spider_rule.py`(4)·`test_monitor_map.py`
- **질환군 매칭을 임베딩에서 키워드 규칙으로(2026-10-02)**: 예상 병명 → 15개 중증질환군(신뢰도 칩·`declared_no` 내림·신고 신선도에 쓰임)을 고를 때 기준선 없이 임베딩 최근접을 골라, 다리 골절·심근경색·뇌출혈·"미상"이 전부 담낭담관질환으로 붙었다(유사도 0.47~0.93이라 기준선으로도 못 거름). 상관없는 신고로 병원이 뒤로 밀릴 수 있는 오류였다. `hub/disease_group.py`가 E-Gen 항목명 키워드로만 고르고, 해당 없으면 None(칩·내림 없음). 진료과 매칭은 그대로 임베딩. 검사 `python disease_group.py`
- **E-Gen 수용 제한 메시지 수신·강등(2026-10-07)**: info의 `acceptanceMessages`를 매칭 시점에 시작~종료로 다시 걸러 `HospitalMatch.acceptanceMessages`(matched = severe는 사건 질환군 일치, er는 필요 진료과 일치·응급실 전체 공지)로 싣는다. 사건 질환군에 유효한 중증질환 차단이 있으면 `demoteReasons`에 `severe_blocked` — `declared_no`와 같은 원칙(순서만 내림, 후보 유지, 병원이 이 사건에 승인·확정하면 안 내림). 검증 `python test_acceptance_messages.py`(임베딩 모델 없이 가짜 매처)
- **응급실 정원·포화도 + 포화도 페널티(2026-10-07)**: `HospitalMatch.erBedCapacity`·`erOccupancyPct`(=(정원-가용)÷정원, 이송 확정 차감 반영 표시값, info가 과밀을 0으로 보내므로 100% 상한, 병상 미상·1일 넘은 값이면 None). **순위에도 들어간다** — `scoring.occupancy_penalty_min()`이 차감 **전** E-Gen 포화도에 비례해 이동시간에 최대 **+5분**(`OCCUPANCY_PENALTY_MAX_MIN`, 부하 페널티의 절반 — 신고값이라 낡을 수 있어서. 이송 중 환자는 부하 페널티가 세므로 이중 계산 없음). `occupancyPenaltyMin`·`occupancyReason`, `plan_mci`도 같은 값. 불변식: 5분 넘게 가까운 병원은 역전 안 됨. 팀 합의 전 초기값. ⚠ `sim/` goldenlink 팔엔 아직 없음(시뮬↔실코드 로직 일치가 깨짐). 검증 `python test_er_occupancy.py`
- **`GET /hospital-backup?id=<hpid>`(2026-10-08)**: 대시보드 [배후역량] 버튼용. `HubEngine.build_backup_view()`가 병상(보유·E-Gen 정원·지금 가용(이송 확정 차감 반영)·가용 값 신뢰 AI)과 장비(보유 대수·운영 Y/N — 지금 남은 대수는 공개 정보가 없어 칸 없음)·전문의·간호등급·중증 신고·수용 제한 메시지를 모은다. 매칭 결과엔 안 싣는다(누를 때만). 순위 무관. 공개 모드 터널 경로에 추가. 검증 `python test_backup_view.py`
- **시연용 신뢰도 검증 화면(2026-10-02)** — 병원·구급차 상단바 [신뢰도 검증] 모달(3D 뷰어와 같은 `FrameModalButton`) 또는 `/verify` 직접. 가상 이송 요청(시각·병원·이동 5~25분은 무작위)의 결과를 **실제 E-Gen 다음 스냅샷**으로 채점한다 — 도착 때 병상 수가 3석(모델 θ) 이상 안 바뀌었으면 "맞음". info `reliability/replay_demo.py`가 스냅샷 1장당 10건을 만들고(`data/verification/replay_demo.jsonl`, 전부 `demo: true`·`source: "replay"`), 거절 로그 수신구(5003)의 `GET /verification/summary`가 1시간마다 다시 채점해 확률 구간별 예측 vs 실제·거절 사유를 낸다. hub `GET /verification`이 그대로 중계(dashboard는 hub와만 통신, 도메인 라우팅 추가). **실제 운영 검증이 아니다** — "병원이 실제로 받았는가"는 다루지 않고 화면에 늘 "시연용 예시"를 붙인다. 첫 결과(10/1~2, 590건): 구간 순서는 맞고(예측 35→52→71→89% / 실제 83→90→96→98%) 모델이 실제보다 보수적
  - **"우리 병원" 칸(2026-10-02)**: 병원 대시보드에서 열면 `/verify?hpid=` → 맨 위에 그 병원 기록. 무작위 표본이 아니라 그 병원 스냅샷 **전수**(최근 7일)로 "빈 병상이 보였던 모든 시각에 출발했다면 15분 뒤 실제 값은"을 센다(`hospital_score/hospital_view.py`), 빈 병상 수 그래프(수집이 1시간 넘게 끊긴 곳은 선을 끊음)·만실/과밀 시간 비율·E-Gen 15개 질환군 신고·심평원 전문병원 지정과 전문의 수·거절 로그. hub가 `hospitalHub`로 지금 API 값·신뢰도(`_build_self_info`)와 의사결정 로그의 그 병원 활동(`_hospital_activity`)을 덧붙인다. ⚠ 의사결정 로그에는 예전에 테스트를 실로그에 돌린 기록이 섞여 있다(예: A1100017 수용 불가 59건) — 해시 체인이라 지울 수 없음. 첫 수치(서울아산): 출발 53번 중 16번 3석 이상 바뀜·만실, 기록 시간의 51%가 만실·과밀
  - **화면 개편(2026-10-02)**: 맨 위를 "API가 알려준 값 vs 실제"로 — ① 출발 때 병상 수가 도착 때 달라진 비율(100칸 그림, 그대로/1~2석/3석 이상/만실)과 가장 크게 줄어든 실제 사례 ② 심평원 전문병원 지정인데 E-Gen에 "가능" 신고가 없는 병원(`hospital_score/crosscheck.py`, 수신구 응답의 `crosscheck`)·중증질환 신고 "정보 없음" 비율 ③ 크게 바뀐 곳 vs 그대로인 곳에 AI가 준 확률. 확률 구간별 채점은 접어 둠. 첫 수치(1,100건): 54%가 달라짐, 3석 이상 7%, 만실 6건 / 전문병원 9/15곳 미신고 / AI 확률 64% vs 77%
- **병상 없는 병원은 '수용 불가'로 보인다(2026-10-03)**: 응급실 병상 0이 확인된 병원(E-Gen, 미상·1일 넘은 값 제외 — beds_full 내림과 같은 기준)은 병원이 아직 안 눌렀어도 `HospitalMatch.unavailableReason="beds_full"`. status는 pending 그대로라 병원 거절로 세지 않는다(거절 로그·존 확장 비율 X). 관제 지도는 이걸 "✕ 병상 없음"(status rejected로 전송), 병원 카드·구급차 후보는 "수용 불가 · 병상 없음(E-Gen)"으로 보여준다. 매칭·60초 재계산 때마다 E-Gen 값으로 다시 정하므로 병상이 생기면 판단 대기로 돌아온다 — 단 hub가 E-Gen 값을 info의 5분 주기로 받아 반영이 그만큼 늦을 수 있다
- **병원이 고른 거절 사유를 화면에(2026-10-03)**: `HospitalMatch.rejectReason`(status=rejected일 때, 승인으로 번복하면 지움). 병원 [불가] 선택칸이 그 사유를 계속 보여주고, 구급차 후보·관제 지도에도 사유가 붙는다(`lib/rejection.ts` 공용 어휘)
- **수용 완료하면 바로 기지 복귀(2026-10-03)**: 출동 시뮬레이션의 병원 체류 `HUB_SIM_HOSPITAL_DWELL_SEC` 기본 15 → 0
- **거리는 카카오 내비 기준(2026-10-03)**: 매칭 결과·현장 후보·관제 지도 사건 요약에 `roadDistanceKm`(도로 거리)를 싣는다(다중 목적지 ETA 응답의 distance — 예전엔 소요 시간만 쓰고 버렸다). 현장 후보(`scene_candidates`)도 이제 내비 ETA를 받아 **도착 시간순**으로 정렬하고 `etaMin`·`travelMin`·`travelBasis`를 싣는다(첫 연락 추천의 도착 시점 horizon도 이 값). ETA를 못 받은 병원(키 없음·반경 10km 밖)만 직선거리 추정이고, 대시보드는 이를 "직선 X km"로 구분해 보여준다(`lib/distance.ts`). **존 판정은 여전히 직선 반경**(5km 간격)이다
- **병원 탭 연결 시 구급차 상태 전달(2026-10-03)**: 병원 대시보드는 관제 지도에서 눌러 열어서, 구급차가 도착한 뒤에 열면 "도착(at_hospital)"을 받은 적이 없어 [환자 수용 완료]가 꺼진 채였다 — identify 때 그 병원으로 이송 중·도착한 구급차의 시뮬레이션 상태를 한 번 보낸다
- **이송 중엔 확정 병원만(2026-10-03, dashboard)**: 이송이 확정되면 구급차 화면의 후보 목록·지도에 확정 병원만 보인다. 재선택 원칙 때문에 목록 아래 [다른 후보 N곳 보기]로 펼칠 수 있다. 도착 후 수용 불가로 확정이 풀리면 다시 전체가 보인다
- **재시작 뒤 지난 사건이 대시보드에 남던 문제(2026-10-03)**: ① 출동 시뮬레이션 모드에서 hub가 재시작하면 구급차가 전부 기지로 돌아가므로, 복구된 사건을 이송 확정 사건까지 전부 닫는다(`_settle_restored_cases`, 병상 차감은 병원 단위로 TTL대로 남는다) ② 탭은 hub가 꺼졌다 켜져도 자동 재연결하며 화면 상태를 들고 있어서, identify 응답 끝에 `case_sync`(지금 진행 중인 사건 id 목록 — 구급차는 결과 전 사건 포함)를 보내고 대시보드가 목록에 없는 사건을 지운다
- **통화 중 실시간 자막(2026-10-03)**: voice가 발화 하나를 인식할 때마다 `POST /voice/utterance`로 보내면 hub가 그 구급차 탭에만 `call_transcript`로 넘긴다(병원·관제 지도 X, 저장·로그 X). 대시보드 통화 시연 패널이 이걸 우선 보여주고, 없을 때만 브라우저 Web Speech 자막을 예비로 쓴다 — 예전엔 브라우저 자막뿐이라 voice는 잘 인식하는데 화면엔 안 떴다. voice 쪽 주소는 `HUB_VOICE_UTTERANCE_URL`(기본 HUB_BASE_URL/voice/utterance)
- **이송 중 활력징후 모니터링(2.5단계, 2026-10-04 신설)**: 이송 확정 뒤 활력징후를 "입력 구멍"(`POST /vitals` HTTP + dashboard WS `transport_vitals` — 출처 voice/manual/monitor/demo 공용 형식, 장비 구매 없음 원칙)으로 받아, `hub/transport_triage.py` 규칙 엔진(공개 표준 **NEWS2** + 쇼크지수, 생성형·학습 모델 아님)이 record/hold/notify/review/heli_advisory 티어로 판정한다. "지속" = 연속 2회 측정(NEWS2 ≥ 7은 1회 즉시), 초과 1회째는 보류 — "오경보보다 침묵". notify 이상만 확정 병원 탭에 전달, review는 대체 병원 후보(승인/대기, 30분 안쪽, 최대 3곳) 동봉 — **제안일 뿐 결정은 구급대원·관제**. 대체 후보 0곳이면 헬기 대기 권고(관제 지도에도, 활력징후 상세 없이). 기준값은 **전문의 검토 전 초안**(`hub/TRANSPORT_TRIAGE.md` — 출처·한계 명시), 검증 `python test_transport_triage.py`(시연 시나리오 5종 픽스처), notify 이상은 의사결정 로그 기록(demo는 `demo: true`로 분리)
- **이송 중 부하 분산 + 경증 역가산(2026-10-03)**: `scoring.load_penalty_min()` — TTL 오버레이의 이송 중 건수만큼 이동시간에 분을 더해(최대 10분) 만실 절벽 전에 연속적으로 분산시킨다(평시 0건이면 기존 순위와 동일). 경증(low)은 권역·지역센터에 +3분(`MILD_CENTER_PENALTY_MIN`, "경증은 센터를 아껴라" — 제외가 아니라 순위 조정). `inFlightCount`·`loadPenaltyMin`·`loadReason`으로 설명 노출, `final_approval`·도착 결과마다 관제 지도 overview 재전송. 같은 상수로 `sim/`의 MCI 시뮬레이션(일산 여성병원 화재 조건, 세 팔 비교)이 goldenlink 팔을 재현한다 — 쏠림 8.5배→1.0배, 중증→센터 0%→100%, 경증→센터 58%→6%(이태원 조건)
- **관제 지도 역할(role=monitor, 2026-10-03)**: dashboard 관제 지도(보기 전용 — 병원 대시보드와는 분리, 병원 대시보드는 첫 페이지에서 접근 코드로 연다). hub는 monitor 소켓에 `map_overview`(전체 병원·구급차 목록 — 연결 때·병원 목록 한 주기 끝·구급차 정보 갱신 때), `case_overview`(사건 요약 — 매칭 결과가 나갈 때마다, 통화 전문·활력징후 없음, 병원별 status·zone 포함), 구급차 시뮬레이션 위치(전 구급차)를 보낸다. 거절 비율 존 확장은 기존 로직 그대로이고, 넓혀진 존의 병원이 `case_overview.hospitals`에 들어와 지도에 표시된다. hub/README.md "출력 스키마 7", 검증 `test_monitor_map.py`. **2026-10-14** `case_overview`에 spider 실시간 화면용 환자 요약(`ktasLevel`·`expectedDiagnosis`·`chiefComplaint`·`requiredDepartment`·`patient`·`confirmedBy`, 모두 Optional)을 더했다 — 통화 전문·활력징후·의식은 여전히 안 보낸다. spider 페이지(`/spider/?mode=live`)도 같은 monitor 소켓으로 붙는다
- **관제 지도 개편 · 시간 기반 존 확장 · 이송 30초(2026-10-04 밤)**
  - 관제 지도(`/map`)를 디자인 시안("골든링크 관제")대로 다시 그렸다 — 진행 중 사건 목록(번호·중증도·증상·경과·단계·대기/불가/승인 수·새 응답 배지), 선택 사건의 요청 병원 탭(응답 시각 포함), 지도(선택 사건 기준 병원 응답 색·말풍선·요청 범위, 구급차 사각형·사건 번호), 하단 구급차 패널(선택 사건 기준 가까운 순), 지난 사건 모달(오늘 종료 사건·진행 과정 타임라인). 화면 `app/map/page.tsx`·`components/map/ControlMapPanel.tsx`·`lib/control-map.ts`. 사건 상황판(`/case`)은 예전 `MonitorMapPanel` 그대로
  - 재료는 hub의 사건 기록기 `hub/case_history.py`(규칙 기반): 매칭 결과가 나갈 때마다 직전과 비교해 이벤트(요청 시작·첫 거절·범위 확장·승인·확정·완료/취소)와 병원별 응답 시각을 남기고, 사건 번호(하루 단위)·시작 시각·증상 한 줄을 매긴다. `MonitorCase`에 `num`·`startedAt`·`symptom`·`events`·`hospitals[].respondedAt`·`zoneExpandAt`, 새 메시지 `case_meta`(매칭 전 사건)·`case_history`(오늘 종료 사건, hub 상태 파일에 저장). 환자 상세는 여전히 안 보낸다
  - **시간 기반 존 확장**: 거절 비율(40%) 확장은 병원이 거절을 눌러야만 움직여서, 요청 뒤(또는 마지막 확장 뒤) `HUB_ZONE_EXPAND_SEC`(기본 60초 — 2026-10-06에 30초에서 늘림) 동안 승인·확정 병원이 없으면 새 병원이 들어오는 다음 존으로 넓힌다(`_zone_timer_tick`). 시연 콘솔 ③의 [건너뛰기]는 WS `zone_expand_now`로 바로 넓힌다. 더 넓힐 곳이 없으면 멈추고, [정지] 중엔 시간도 멈춘다. 의사결정 로그 `zone_expanded` cause `zone_timeout`/`zone_manual`, 진행 과정에 "60초 동안 수용 병원 없음"/"관제 건너뛰기"
  - **이송 30초 + 빨리감기**: 출동 시뮬레이션의 병원 이송 구간만 `HUB_SIM_TRANSPORT_SEC`(기본 30초) — 이송 중 환자 상태 변화 시나리오를 고를 시간. 콘솔 ④의 [⏩ 빨리감기]는 `sim_fast_forward`로 남은 이동을 3초(`HUB_SIM_FAST_FORWARD_SEC`) 안에 마친다(지금 위치는 그대로, 배속만 바꿈). 출동·복귀는 5초 그대로. 검증 `python test_zone_timer.py`
  - ⚠ `run_match.py`가 실제 의사결정 로그에 쓰고 있어서, 실서버 hub가 떠 있는 동안 돌렸더니 해시 체인이 한 곳 끊겼다(2026-10-04 21:14 KST, `decision_log.jsonl` 2,558번째 줄 — 앞뒤 줄의 prevHash 불일치, 내용 변조 아님). 이제 다른 test_*.py처럼 임시 경로를 쓴다
- **이송 중 수용 철회 · 추가 통화 · 일시정지 잠금(2026-10-05)** — 검증 `python test_transport_withdraw.py`
  - **이송 중 수용 철회**: 새 액션 `transport_withdraw`(병원, 사유 포함) — 구급차가 그 병원으로 **이송 중**일 때만. 도착 후 수용 불가와 같은 처리(확정 해제·병상 회수, 승인 병원이 없으면 존 확장 재요청)에 더해, 철회·도착 후 수용 불가 병원은 **그 사건에서 제외**(`HospitalMatch.excluded`, 다시 승인·이송 승인 거부). 구급차 시뮬레이션은 그 자리에서 `rerouting`. 거절 로그 `stage: "transport"`
  - **추가 통화(덧붙이기)**: "사건당 통화 한 번"은 현장 첫 연결에만 — 이송 중·재선택 대기에도 통화를 받는다(`CALLABLE_PHASES`). 같은 사건의 새 요약은 `HubEngine.add_call_summary()`가 덧붙인다: 최신 요약이 `patientInfo`, 앞선 요약은 `patientInfo.previousCalls`, `callRound`, 통화 전문은 "── N차 통화 ──"로 이어 붙임. 이송 확정 사건은 병원 목록·상태를 그대로 두고 환자 정보만 바꾼다(미확정이면 넓힌 존을 유지한 채 재매칭). `call_status`에 `followup`·`cancelled`
  - **추가 통화 중 이송 멈춤**: 이송 중 추가 통화가 연결되면 hub가 구급차 이동(시뮬레이션)을 `pauseReason: "call"`로 멈추고, 2차 요약이 반영되면(또는 취소 즉시, 전송 뒤 `HUB_CALL_HOLD_AFTER_END_SEC`=120초·통화 최대 600초) 다시 출발시킨다. 운영자의 시연 일시정지(`pauseReason: "manual"`)와 달리 **조작을 잠그지 않는다**(`_apid_paused`는 manual만)
  - **대량사고 분배 확정(중증도 기준)**: 시연 콘솔 대량사고는 시안의 대량 ①~⑤ 단계 화면 — ① 출동(진행 막대) ② 현장 확인(사상자마다 유형 4종 선택 → 한 번에 신고, 현장 도착 자동 신고는 없앰) ③ 병원 × 중증도(중증/중등증/경증) 표 — 병원 행 [승인]/[불가]는 병원 역할 연출(그 병원이 후보인 사건 전부에), 병원 승인이 바뀔 때마다 콘솔이 WS `mci_preview`로 묻고 hub가 `mci_plan`(자동 배정 계획)으로 답해 병원 행 아래에 "자동 배정 → #1 교통사고 다발성 외상 …"을 미리 보여 준다. [분배 확정](WS `mci_allocate`)은 **같은 계획**(`HubEngine.plan_mci` — 중증 → 중등증 → 경증 순, 사건마다 승인 병원 중 finalScore 최고, 앞 배정마다 이송 중 +1·병상 -1로 부하 페널티를 다시 매겨 분산, 중증 센터 가산·경증 센터 역가산 그대로, 캐시 결과만 써서 카카오 호출 없음)대로 이송 확정한다 — 보이는 대로 확정된다(`_mci_allocate`). 사상자는 ③~⑤ 어디서나 번호와 부상 유형을 함께 표시. 콘솔은 분배를 계산하지 않는다(병상 신뢰도는 쓰지 않음 — 순위 원칙 유지). 결과는 콘솔에 `mci_allocated`. ④ 구급대별 이송 ⑤ 병원 × 중증도로 사상자마다 수용/불가를 기록(콘솔 안) → [수용 불가 N명 재분배]만 hub에 도착 후 수용 불가로 보내 ③에서 그 환자만 다시 분배(이미 수용된 환자는 다시 처리 안 함). 검증 `python test_mci_allocate.py`
  - **통화 취소**: `call_signal`의 `cancelled: true`(call_ended와 함께) — 중앙 voice는 녹음만 `_cancelled.wav`로 남기고 인식·요약·전송을 하지 않는다
  - **아이폰 온디바이스 요약은 WebSocket `voice_summary`로**(구급차 소켓, 그 구급차 사건만) — 공개 도메인 터널은 `/voice/*` HTTP를 열지 않아 404였다
  - **일시정지 잠금**: 정지 중인 사건의 승인·불가·이송 승인·도착 결과·철회·건너뛰기·빨리감기·현장 종료·이송 중 활력징후·통화 시작을 hub가 거부하고 그 소켓에 `action_refused`(reason `paused`)를 보낸다. 매칭 결과·`case_overview`에 `paused`를 싣고, 정지·재개 때 다시 보낸다. 대시보드(병원·구급차·콘솔·웹/아이폰 전화 앱)는 버튼을 막고 "현재 시연 일시정지 중입니다." 안내를 잠깐 띄운다(`components/ui/PauseToast.tsx`). [재개]·[시연 초기화]는 그대로
- **voice v2 스키마 수신(2026-10-01, voice MF_BERT 머지와 함께)**: voice가 summary를 v2(MF_BERT 17필드 — `ktas_level`·`chief_complaint`·`incidents`·`injuries`·`vitals` …)로 바꿔 예전 hub 스키마로는 전부 400이 났다. `hub/voice_v2.py`가 v2를 예전 필드로 옮긴다(규칙 기반) — KTAS 1~2→high·3→medium·4~5→low, 예상 병명 = 주 사고/질병 분류 + 주 호소 + 의심 진단 + 손상, 환자 = 나이+성별, 증상 = "확인"된 것, 처치 = 시행한 것. **필요 진료과는 예전 voice의 대응표(`department_mapping.json`)를 그대로 옮겨** `disease_category`·`incidents[].type`·`injuries[].region`으로 도출한다(외상이면 부위 우선, 여러 부위는 다발성→외과). ⚠ 표는 **팀 확인 전 초안**(뇌혈관: 신경과/신경외과, 소화기: 외과/내과 기본값 미확정). 예전 6필드 형식도 그대로 받는다. KTAS·활력징후·의식(AVPU)·발생 시점·주 호소는 `patientInfo`로 dashboard에 간다(순위에는 안 씀)
- **도착 결과 · 신뢰도 정답 데이터(2026-10-01)** — hub/README.md "도착 결과와 신뢰도 정답 데이터"
  - 병원이 확정 사건에 `arrival_accepted`/`arrival_refused`(사유)를 기록한다. 구급차는 결과가 나올 때까지 병원 앞에서 기다린다(시뮬레이션). **도착 후 수용 불가**는 확정 해제·병상 회수 → 그 자리에서 재선택 대기, 승인 병원이 없으면 같은 환자 정보로 존 확장해 재요청(재통화 없음). 거절 로그에 `stage: "arrival"`과 당시 병상 수·신뢰도 확률 스냅샷 — 신뢰도 모델의 독립 관측(G2) 재료
  - 재선택 해제는 `cause: "paramedic_reselect"`로 구분(실패 아님). **무응답은 사건이 끝날 때만 기록**(예전엔 첫 이송 승인 때 기록해 나중에 승인한 병원까지 무응답으로 남았다)
  - **거절 로그 수신구(포트 5003)를 `start-all.sh`가 기본으로 띄운다** — 예전엔 따로 켜야 해서 실제로는 버려지고 있었다
  - 테스트용 경로 분리: `HUB_DECISION_LOG_PATH`·`HOSPITAL_REJECTION_LOG_DIR`(+기존 `HUB_STATE_PATH`) — 실서버 E2E가 진짜 로그(해시 체인·정답 데이터)를 더럽히지 않게
- **현장 후보에 첫 연락 추천(2026-10-03)**: `scene_candidates`의 후보마다 `bedReliability`(AI, 매칭 결과와 같은 `BedReliabilityMatch` 형태·거리 기반 horizon)를 얹고, 빈 병상이 확인된 곳(미상·확인된 만실·1일 넘은 값 제외) 중 rArrive 최고 한 곳에 `firstCallRecommended: true`를 표시한다(`hub_engine.build_zone_candidates`). 신뢰도를 finalScore·순위에 안 쓴다는 원칙은 그대로 — 첫 통화 상대 제안은 틀려도 존 전체 동시 전달이 뒤를 받치는 비용 낮은 결정이라 여기만 확률을 직접 쓴다. 추천은 의사결정 로그 `first_call_recommended`로 남아 적중률(추천 병원이 실제 수용했는가)을 나중에 셀 수 있다. 검증은 `test_app_background.py`
- **이송 중 부하 페널티(2026-10-03)**: 같은 병원으로 확정돼 이송 중(TTL 오버레이)인 건수만큼 이동시간에 분을 더한다 — `10분 × 이송 중/(이송 중+실질 가용)`(`scoring.load_penalty_min`). 예전엔 차감 병상이 표시·만실 판정에만 쓰여 병상 20개 병원에 19명을 확정해도 20번째에 1순위로 떴다(만실 절벽 강등뿐). 평시(이송 중 0건)는 페널티 0이라 동작 불변이고, 대량사고처럼 확정이 쌓일 때만 만실 전에 연속 분산한다. `HospitalMatch.inFlightCount·loadPenaltyMin·loadReason`, 관제 지도 `map_overview` 병원에도 `inFlightCount`(확정·도착 결과마다 재전송). 검증 `run_match.py test_load_penalty()`. 대량사고 시뮬레이션(`sim/`, feature/sim)의 goldenlink 팔과 로직 일치
- **경증 역가산(2026-10-03)**: 경증(`low`) 환자에게는 권역·지역응급의료센터에 거꾸로 **+3분**(`scoring.MILD_CENTER_PENALTY_MIN`, 팀 합의 초기값) — "경증은 센터를 아껴라". 경증이 최근접이라는 이유로 센터 마지막 병상을 차지해 뒤에 오는 중증이 못 들어가는 걸 막는다. 음수 가산으로 나가 스키마·dashboard 수정 없음(`travelBonusMin` 음수 + `bonusReasons` "센터 보존" 문구). 제외가 아니라 순위 조정 — 센터뿐이면 여전히 센터로(뺑뺑이 방지 원칙 유지). 중증 가산·부하 페널티와 합쳐 "중증은 센터로, 경증은 분산, 차면 다음으로"가 규칙만으로 성립. 검증 `test_mild_center_penalty()`

## feature/dashboard 담당자 참고사항

- 구급차 대시보드와 병원 대시보드는 유사한 레이아웃을 공유하되, 승인 버튼 종류만 다르다 (병원: 병원 승인/불가, 구급차: 이송 승인)
- 각 정보 패널에는 출처 표시가 필요하다: AI 처리된 정보(통화 요약 등)와 규칙 기반 정보(병원 리스트, 지도)를 시각적으로 구분해서 보여준다
- Override 구조를 UI로 드러낼 것: AI가 생성한 요약은 구급대원이 확인·수정할 수 있어야 한다. **2026-10-13부터 실제로 hub로 나간다** —
  통화 요약 카드의 [수정](예상 병명·증상·KTAS·필요 진료과·주 호소) → [확인·전송], 맞으면 [확인] 한 번(`patient_override`, 아래 4번 포맷).
  병원 수용 요청 카드엔 "AI 요약 · 구급대원 확인 전"/"✓ 구급대원 확인" 칩과 고친 칸 상자(`components/panels/PatientConfirmation.tsx`)
- 실시간 갱신: WebSocket 기반, 완료된 정보부터 순차적으로 갱신 (전체 처리 완료까지 기다리지 않음)
- **feature/hub와만 직접 통신한다.** voice·info와는 직접 연결하지 않으며, voice의 의료 정보·예상 병명·통화 전문과 info의 병원 정보는 모두 feature/hub가 재가공한 통합 결과로만 받는다. 승인 액션(수신처는 feature/hub로 확정)과 통화 시작/종료 신호는 위 "데이터 포맷 및 흐름" 2·3번 참고
- 통화 시작/종료 버튼은 WebSocket으로 hub에 신호를 보낸다. 브라우저 마이크로 캡처한 오디오(`sendAudioChunk`, 2026-10-03부터 16kHz PCM)도 같은 연결로 보낸다 — 중앙 voice가 떠 있으면 이게 실제 STT 입력이고, 구급차별 voice(로컬 마이크) 방식이면 hub가 버린다
- **"수용 불가" 버튼의 거절 사유 선택(`ApprovalActions.tsx`)**은 4축 어휘를 그대로 쓴다
  (`RejectionReason`, info `hospital_score/rejection.py`의 `REASON_AXIS`와 동일). 사유를
  강제하지 않는다 — "사유 없음"(`UNSPECIFIED`)을 맨 위에 둬 급할 때 바로 거절할 수 있게
  한다. hub가 이 값을 `POST /hub/rejection`으로 중계해 운영 로그로 쌓는다(2026-09-10 배선 완료)
- **`NEXT_PUBLIC_DASHBOARD_WS_URL` 미설정 시 목데이터 모드**로 동작한다(로컬 UI 작업용).
  상단바에 "○ 목데이터 모드" 배지가 뜨고, 콘솔에도 경고를 한 번 남긴다 — 배포 환경에서
  env를 빠뜨리면 가짜 데이터를 실데이터로 오인할 수 있어서다
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
- **휴대폰 전화 앱 (2026-10-03)**: 구급차 대시보드와 **주소를 나눴다** — 대원 휴대폰은 `/phone?id=<apid>`(첫 페이지에 `P-<apid>` 입력, 또는 구급차 대시보드 상단바의 "📞 전화 앱" 링크), 구급차 대시보드 `/ambulance`는 화면 폭과 무관하게 항상 전체 화면(처음엔 폭 640px로 갈랐으나 태블릿을 세로로 세우면 바뀌어 분리). 화면은 `app/phone/page.tsx` → `components/phone/PhoneCallView.tsx`, hub에는 같은 apid의 `role: "ambulance"`로 붙는다. **휴대폰은 전화만 한다** — 출동·현장 종료·이송 승인은 태블릿·PC. 현장 도착 뒤 거리순 병원 목록(첫 통화 추천이 맨 위) → 병원을 누르면 "연결 중" → 통화 중(시간·음성 레벨·실시간 자막·종료) → 종료("후보 병원 N곳에 전달"). 통화는 **연출**이다(병원과 실제 음성 연결 없음, 사건당 한 번). 마이크 음성은 hub를 거쳐 중앙 voice로 가 STT 입력이 된다. 고른 병원 대시보드엔 `CallStatusBanner`로 "📞 ○○ 통화 중 · mm:ss", 관제 지도엔 그 병원에 📞 표시, 태블릿엔 "휴대폰으로 ○○병원과 통화 중" 배너가 뜨고 태블릿의 통화 시작이 막힌다(hub `call_status`). 태블릿 통화 시연도 MediaRecorder(webm) 대신 같은 PCM 캡처를 쓴다. **대시보드 [통화 시작]은 기본으로 없다(2026-10-03)** — 통화는 휴대폰 전화 앱으로만 하고, 구급차 대시보드엔 보기 전용 `CallStatusPanel`(통화 상태·실시간 자막)이 뜬다. `./start-all.sh --dashboard-call`(hub `HUB_DASHBOARD_CALL=1` → `identity_info.dashboardCall`)로 띄우면 예전 통화 시연 패널([통화 시작]·파형)이 돌아온다. 꺼져 있을 때 대시보드의 통화 시작(`device: "tablet"`)은 hub도 거부한다(`call_start_refused`, reason `dashboard_call_off`). `--no-sim-dispatch`면 휴대폰 앱을 쓸 수 없어 start-all이 자동으로 켠다 브라우저 마이크는 https(도메인)·localhost에서만 열린다
- **갤럭시 온디바이스 앱(2026-10-05, `dashboard/android/`)**: 아이폰 앱(`dashboard/iphone/`)과 같은 흐름·화면을 안드로이드(Kotlin·Compose)로 옮겼다. STT(Qwen3-ASR + LoRA)·구조화(MF_BERT)를 휴대폰 안에서 onnxruntime-android(CPU, 1.30.0)로 돌리고, 요약은 hub WebSocket `voice_summary`로 보낸다(`model_used`에 `-android`). **모델은 서버와 같다** — 같은 Hub 저장소·커밋 가중치를 양자화·fp16 없이 **fp32** ONNX로 변환했고(`convert/convert_*.py`), 그래프 밖 계산(멜·프롬프트·그리디·바이트 BPE·반복 정리·512토큰 조각·decode/parse)을 서버 코드에서 그대로 옮겼다. 대조: MF_BERT ONNX·앱 Kotlin 코드 vs 서버 PyTorch summary 완전 일치, ASR은 실제 통화 녹음 16건 177구간 문장 177/177 일치(`convert/check_qwen3_asr.py`), 앱 Kotlin 추론 코드도 서버와 같은 문장·요약(`OnDeviceE2ETest`). ⚠ 서버 특징은 `apply_chat_template` 경로라 특징 추출기가 `padding="longest"`(30초 채움 아님) — 기본값을 옮겼다가 6/68 구간이 달랐다, Kotlin 코어 로직은 아이폰과 같은 Python 정답 파일로 `./gradlew :core:test`. 모델(약 4.6GB)은 APK에 넣지 않고 `push-models.sh`로 adb push. 빌드는 Android Studio 없이 `setup-tools.sh` + `build-apk.sh`. 실기기(S24) 속도·메모리는 아직 미측정(PC CPU fp32에서도 3~5초 구간당 3~8초로 실시간보다 느림)
- **아이패드 구급차 앱(2026-10-14, `dashboard/ipad/`, SwiftUI·XcodeGen, 외부 패키지 없음)**: 구급차에 싣는 화면 — 웹 구급차 대시보드(`/ambulance`)와 같은 디자인(AD 팔레트·흰 카드·상단바·범례)으로 hub에 `role: "ambulance"`(구급차 ID, 설정 `auto`면 `role: "monitor"`로 출동 구급대를 찾아 따라감 — 웹 `?id=auto`·아이폰 앱과 같은 규칙)로 붙는다. 위: 왼쪽 현장 상태 · 통화 요약(KTAS·예상 병명·증상·환자·활력징후·확인 여부·통화 현황/자막) + 오른쪽 spider 거미줄 3D(`/spider/?mode=live&embed=1&apid=`, 그 구급차 사건만, 카메라가 출동→현장, 이송→현장~병원을 따라감) / 아래: **병원 후보 리스트는 사고가 발생했을 때만 올라온다**(통화 전 현장 후보·첫 연락 추천 → 통화 후 hub 순위 카드: 병상·AI 유효·전문의, 칩, 정보 유효 지금→도착 시 막대와 이유 한 줄, [이송 승인]). 카드를 누르면 "왜 이 확률인가" 상세, 상단바 [정보 생존 모델]은 `/verification/live` 라이브 보드 전체 화면. 조작은 [이송 승인] 하나(웹 handleApprove와 같은 final_approval). 지도 핀치가 튀던 문제는 WKWebView 페이지 확대와 deck.gl 확대가 동시에 걸리고 관성까지 붙어서였다 — 웹뷰 확대·스크롤 끔 + 페이지 `user-scalable=no`·gesture 막기 + 터치 기기 관성 끔 + 확대 범위 5~16.5. 같이 고친 spider 버그: 서버가 빨리 답하면 `live.js`가 실리기 전에 실시간 모드를 켜 `hubConnect`를 못 찾고 멈췄다(DOMContentLoaded 뒤 시작). hub `MonitorCaseHospital`에 설명 필드 22개 Optional(`_MONITOR_EXPLAIN_FIELDS`)은 그대로. 빌드 `./dashboard/ipad/setup.sh`(서명 팀 유지) → Xcode. 시뮬레이터 + 임시 hub로 대기→출동→매칭→이송 확정 E2E 확인. **상황판(2026-10-14)**: 상단바 [구급차 | 상황판] — 상황판은 monitor 소켓으로 **전체 사건**(대량사고)을 본다: 상황 요약(단계별 수·KTAS 분포)·사건 목록(누르면 지도 이동)·거미줄 3D 전체(새 사건마다 전체 맞춤)·**병원별 분산**(확정 환자 수·승인·대기·응급실 여유). 병원 후보 리스트·현장 상태·통화 요약은 없다. 구급차 화면 병원 카드는 칩 한 줄(+N)로 줄여 리스트 높이 약 260pt. spider: 이송 확정 사건은 확정 병원 경로만 그린다
- **병원 자기 정보 현황 + 정보 확인 버튼 (2026-09-29)**: 병원 대시보드 상단에 `HospitalSelfInfoPanel`이 hub의 `hospital_self_info`(자기 병상 신뢰도 — 실시간 감쇠, 수술실·입원실, 중증 신고 요약)를 표시하고, "현재 정보가 맞습니다" 버튼이 `info_confirm`을 보낸다. 확인 즉시 자기 화면과 구급차 화면(✓) 양쪽에 반영된다. mock 모드·구버전 hub면 패널 자체가 숨는다(Optional 패턴)
- **info-v2 신뢰도 판정("왜 이 순위인지") 설명 표시 (2026-08-13)**: hub가
  `hospitals[].reliability`(질환군·score·confidence·basis)를 보내주면
  구급차 대시보드 병원 후보 카드에 칩+근거 문장으로 노출한다
  (`HospitalCandidateListPanel.tsx`). 이 값은 순위 정렬에는 안 쓰이는 순수
  설명용 정보다. ~~실제 순위는 여전히 `specialtyMatch`와 `distanceKm`로만 정해진다~~ →
  2026-10-01부터 순위는 hub가 보낸 `hospitals[]` 순서 그대로다(아래 항목). `reliability` 필드 자체가 없는 병원(구
  feature/info 데이터 등)은 칩이 안 뜨는 것으로 자연히 처리된다(Optional
  필드라 별도 분기 불필요).
- **hub 순서 그대로 · 출동 시뮬레이션 화면 (2026-10-01)**
  - 후보 목록은 **hub가 보낸 순서를 그대로** 쓴다(자체 정렬 제거). 이송 승인을 누르면 즉시 "확정"이 아니라 "확정 요청 중"으로 두고, hub가 `confirmed`로 돌려줄 때만 확정 표시(mock 모드는 예전대로)
  - hub 메시지는 `type`으로 구분하고 모르는 `type`은 버린다(type 없는 메시지 = 구 hub의 매칭 결과). 새로 받는 것: `case_closed`(사건 카드 지움), `scene_candidates`(매칭 전 거리순 후보 — 구급차 화면), `ambulance_phase`·`ambulance_position`(출동 시뮬레이션)
  - **현장 후보의 첫 연락 추천(2026-10-03)**: `scene_candidates` 후보에 hub가 `bedReliability`(AI, 매칭 결과와 같은 형태)와 `firstCallRecommended`(빈 병상 확인 + 도착 시점 유효 확률 최고 한 곳)를 실어 보내면, 구급차 화면 현장 후보 카드에 "첫 연락 추천" 배지(mint 테두리)와 "AI · 도착 시 유효 N%" 칩(실시간 감쇠, 매칭 카드와 동일)을 그린다(`HospitalCandidateListPanel.tsx`). 목록 순서(거리순)는 바꾸지 않는다 — 첫 통화 상대 제안일 뿐이고, 둘 다 Optional이라 구버전 hub·신뢰도 없는 병원이면 자연히 안 그려진다
  - 후보 카드: "필요 진료과 일치"/적합도, 전문의 수, 권역·지역센터 칩, 순위 가산 이유(툴팁)
  - 병원 수용 요청 카드: 이송 확정 사건에 **도착 결과 버튼**([환자 수용 완료] / [도착 후 수용 불가(사유)]). 시뮬레이션이면 구급차 도착 전엔 막힘. 구급차 출동 조작부에 "병원 도착 — 수용 결과 대기"·"재선택 대기" 상태 추가
  - 통화 요약(구급차)·수용 요청 카드(병원)에 voice v2의 KTAS·활력징후(최근 측정)·의식·발생 시점·환자(나이·성별)를 표시(`panels/PatientVitals.tsx`, AI 처리). 예전 voice 데이터면 아무것도 안 그린다
  - `identity_info.simDispatch`가 true면 구급차 화면에 출동 조작부([이동]·[현장 종료]·[정지]/[상황 재개], "시뮬레이션 위치" 배지). [정지](2026-10-03)는 출동 중·현장·이송 중 시연을 그 자리에 멈추고 [상황 재개]로 이어 간다(hub `sim_pause`/`sim_resume`). 구급차의 현재 사건은 hub가 보낸 시뮬레이션 상태의 caseId가 기준이다 — 탭 세션 값만 쓰던 때는 브라우저를 껐다 켜면 [현장 종료]가 엉뚱한 caseId로 나가 먹통이 됐다. caseId는 [이동] 때 만들고 통화 시작은 현장 도착 뒤에만 열린다. 지도는 상태가 바뀔 때만 경로·기지·환자 발생 위치를 다시 그리고 1초 위치엔 마커만 옮긴다. 병원 지도도 우리 병원으로 이송 중인 구급차를 보여준다
- **이송 중 모니터링 화면(2026-10-04)**: 구급차 탭 — 이송 확정 사건에 `TransportMonitorPanel`(가상 시나리오 5종 선택·재생 → WS `transport_vitals`로 hub 전송, 판정 `transport_assessment`를 NEWS2·쇼크지수·티어·근거로 표시, "가상 시나리오" 배지 상시). 시나리오 수치는 `hub/test_transport_triage.py` 픽스처와 동일 — 바꿀 땐 같이 바꾼다. 병원 탭 — 자기 확정 사건 카드 위에 이송 중 상태 변화 배너(notify=호박색, review·헬기=적색, hub가 notify 이상만 보내줌). 후보 목록 — 병원 승인이 오면 승인 병원 중 최상위에 "추천" 칩(선착순 자동 확정 대신 추천 + 탭 한 번 — "최종 결정은 사람"), 이송 중 부하가 있는 병원엔 "이송 중 N건 · 순위 +X분" 호박색 칩, 관제 지도 병원 이름표에 "🚑 이송 중 N건"
- **관제 지도와 병원 대시보드 — 분리 (2026-10-03 회의로 확정)**
  - 병원 대시보드는 예전처럼 **첫 페이지에서 병원 접근 코드(H-<hpid>)를 입력해 연다**(`/hospital?id=`, 내용은 `components/hospital/HospitalDashboard.tsx`). 구급차는 A-<apid>. 같은 날 잠시 "관제 지도에서 병원을 눌러 병원 대시보드를 지도 위에 띄우는" 방식이었으나 회의로 되돌렸다
  - **관제 지도**(`/map`, `app/map/page.tsx`, `components/map/MonitorMapPanel.tsx`)는 보기 전용이다. hub에 `role: "monitor"`로 붙어 서울 지도에 병원(남색 원 — **이름 + 접근 코드 H-<hpid>**)·구급차(주황 사각형 + 십자)를 찍는다. 구급차는 출동 시뮬레이션 위치로 1초마다 움직이고 이동 경로·사고 현장도 그린다. 병원 이름·코드는 확대(카카오 레벨 7 이하)했을 때 다 보이고, 축소 상태에선 마커를 눌러 띄운다. 환자 요청이 온 병원·구급차 이름은 항상 보인다. **어디를 눌러도 병원 대시보드는 열리지 않는다**
  - 환자 요청이 온 병원은 마커가 커지고 위에 상태 표시가 붙는다 — 🚨 판단 대기(노랑)·✓ 수용 승인(연두)·✕ 수용 불가(빨강, E-Gen 병상 없음은 "병상 없음")·🚑 이송 확정(초록), 왼쪽에 진행 중 요청 목록(병원 이름·접근 코드·거리·존·상태)과 "병원 응답" 기록. 요청 판정은 병원 대시보드 카드 목록과 같은 규칙(다른 병원으로 이송 확정된 사건은 흐리게, `lib/monitor.ts`)
  - 사건마다 지금 요청 중인 존 범위를 구급차 위치 중심 점선 원(보라색)으로 그린다. 거절 비율로 존이 넓혀지면 원이 커지고 바깥 존 병원이 요청 표시를 받는다(라벨에 "거절로 확장")
  - 관제 지도는 통화 전문 등 환자 상세를 받지 않는다(hub `case_overview` 요약만). 환자 상세는 병원 대시보드를 열어야 보인다
  - 인증은 여전히 없다 — 접근 코드가 관제 지도에 보이므로, 지도를 볼 수 있으면 누구나 그 코드로 병원 대시보드에 들어갈 수 있다(시연 범위)
- **라이브 채점 보드 전면 개편(2026-10-03)**: /verify 라이브 섹션을 "신뢰 등급별 유지율 라이브 그래프" 중심으로 재구성(LiveBoardSection.tsx). 선 3개 — 엔진 선별(조건부 확률 80%↑, 파랑)·전체 평균(회색 점선)·엔진 경고(<50%, 주황, 6시간 이동평균) — 20분 폴링마다 점 추가, 리플레이(90초) 때 차트가 점진 공개로 동기화. 데이터는 live_board timeseries(schemaVersion 2). 숫자 타일 그리드는 디자인 지침상 금지 패턴이라 문장형 헤드라인으로 교체. 첫 실측: 그냥 믿으면 94% vs 엔진 선별 97.9% vs 경고 값 69%. **지역별 격차 섹션**(2026-10-03 추가): 시도별 원값→선별 점-간격 행 — 원값은 울산 90.3~부산 96.3%로 갈리고 서울·경기가 하위권(수도권 회전율)인데 선별 값은 전 지역 96~98.7%로 균일, 원값 나쁜 지역일수록 이득 큼. **레짐 감지(2026-10-03)**: 공통충격(아침 병상 정리 러시 — 토 09:40 실측 128건/폴링, 평시 4배)은 개별 claim 예측으로 못 피하므로(그 폴링만 선별 73% vs 전체 69% 수렴) 감지로 대응 — 폴링 어긋남이 창 중앙값 2배(주의)/3배(급증)면 timeseries.surge·regime으로 내보내고(schemaVersion 4), 화면은 상태 칩·경보 배너·차트 붉은 띠로 표시. 확률 할인은 재보정과 함께 갈 다음 단계
- **미구현 대기(2026-10-03)**: hub가 보내는 이송 중 부하 필드의 화면 표시 — 후보 카드의 `loadPenaltyMin`·`loadReason`(순위 가산 툴팁과 같은 패턴) + 관제 지도 마커의 `MapHospital.inFlightCount`("이송 중 N건"). 둘 다 Optional이라 안 그려도 안 깨지지만, 대량사고 시연에서 분산이 "왜" 일어나는지 보이려면 필요하다
- **병원 공지(E-Gen 메시지) 표시(2026-10-07)**: 구급차 후보 카드에 이 환자에 해당하는 병원 공지(최대 2건, 중증 차단은 빨강)와 나머지 건수, 툴팁에 전체 원문. `severe_blocked`면 "병원 차단 메시지" 칩. 필드가 없으면 안 그림
- **병상 칸 정원·포화도(2026-10-07)**: 구급차 후보 카드 병상 칸이 정원이 오면 "가용/정원"과 라벨에 포화도 %를 보이고, 툴팁에 순위에 더해진 분(`occupancyReason`)을 밝힌다. 정원이 없으면 예전 그대로
- **[배후역량] 버튼(2026-10-08)**: 현장 후보·매칭 후보 카드 칩 줄에 버튼 하나(`components/ambulance/BackupCapacityButton.tsx`) — 누르면 hub `/hospital-backup`을 불러 모달로 병상·장비·전문의·병원 신고를 보여 준다. 맨 위에 "보유는 최대치, 지금 쓸 수 있는지는 E-Gen 가용과 병원 수용 승인으로" 안내 고정, 장비의 지금 남은 수는 "공개 정보 없음". 목데이터 모드면 숨김

---

## feature/sim 담당자 참고사항 (2026-10-03 신설)

발표·IR의 "대량사고 대응"을 계획이 아니라 수치로 검증된 결과로 바꾸기 위한
**대량사고(MCI) 분산 이송 시뮬레이션** 브랜치다. 상세는 `sim/README.md`가 최신.

- **운영 규칙: 다른 폴더의 기존 파일을 수정하지 않는다 — `sim/` 아래 새 파일만.**
  결선 후 통째로 지워도 다른 브랜치에 영향이 없게 하기 위함. info 쪽은 데이터 파일
  읽기와 E-Gen 클라이언트의 읽기 전용 import(`fetch_coords.py`)만 한다
- **무엇을 비교하나**: 같은 장소·요일·시각대의 실제 E-Gen 스냅샷에서 사상자 N명을
  세 방식으로 이송 — `nearest`(최근접 집중, 이태원 당시) / `sequential`(순차 전화,
  평시 뺑뺑이) / `goldenlink`(동시 전달 + 배정 공유). 차이는 정보 전달 방식뿐.
  **반사실("있었다면 살렸다")이 아니라 메커니즘 데모**로 프레이밍한다 — 병원
  위치·병상만 실측이고 사건 재현이 아님을 화면·발표에 항상 명시
- **장면 2개**(`run.py --scene`): **ilsan이 메인** — 2019-12-14 일산 여성병원 화재와
  같은 요일(토)·시각대(10:07), 사상자 138명·중증도 분포가 대한응급의학회지
  32(1):36-47(2021) 실측이고, 논문 Table 3의 실제 병원별 분산(수동 — DMAT·상황실이
  모바일로 병상 정보 공유)이 리포트에 참조선으로 그려진다("2019년의 성공적 수동
  분산을 골든링크가 자동화한다"는 서사가 반사실 없이 성립). itaewon은 배경 서사용.
  ⚠ 실측 A병원 83명 집중은 쏠림 실패가 아니라 경증 전제의 의도된 허브 전략(NICU
  한계 5명, 31명 진찰 후 귀가) — 발표에서도 캡션 그대로 말할 것
- **첫 결과**(시드 20 평균, 수용까지 중앙값): ilsan 19.6/22.0/**14.7**분,
  itaewon 23.0/28.5/**14.8**분 (nearest/sequential/goldenlink). 민감도
  변주(`--sweep`: 전화 시간·환자 수·구급차 수) 전부에서 순서 유지. 베이스라인에도
  구급차별 "직접 겪은 만실 기억"을 넣어 보수적으로 비교했다
- **hub와의 로직 일치**: goldenlink 팔의 배정(가용 병원 중 최단 이동 + 배정 공유)은
  hub의 이송 중 부하 페널티(2026-10-03)가 들어가면서 실제 코드와 같은 메커니즘이
  됐다 — "시뮬과 실코드가 같은 로직이냐"는 질문에 "네"로 답한다
- **데이터**: 가용 병상은 `info/.../data/snapshots_nationwide/*.jsonl`(이 수집
  장비에만 있음 — 다른 장비에선 재실행 불가, 대신 산출물이 커밋돼 있어 열람은 가능),
  전국 좌표 캐시 `sim/data/egen_coords.json`(E-Gen 목록 1회, 529곳, 커밋됨),
  일산 실측 분산 `sim/data/ilsan_actual_2019.json`(출처·주의 문구 포함)
- **산출물**(`sim/out/`, 커밋함): 자가완결 리포트 `mci_report_<장면>.html`(CDF·병원별
  쏠림·구급차 점 재생, `#t=30&arm=nearest` 해시로 장면 점프) + 발표용 1920×1080
  슬라이드 PNG(`make_slides.py --scene`, 순수 SVG). 차트 색은 dataviz 검증 통과
- **실행**: `conda activate rookie_info` 후 `cd sim && python run.py --scene ilsan`
  (Windows는 `PYTHONUTF8=1` 필요). 시간 상수(전화 2.5분 등)의 근거·보수성 원칙은
  sim/README.md "상수의 근거" 절 — 세 팔 공통 상수는 비교 결과의 원인이 될 수 없다
- **v2 자리**: 신고가 처음부터 틀렸을 확률(`SimParams.info_error_rate`, 현재 0)에
  infosurv 생존확률을 거절 확률로 주입하는 확장 — 환경(세계)에만 적용하고 정책에는
  넣지 않는다(양팔 공정성)

---

## feature/spider 담당자 참고사항 (2026-10-11 신설)

hub의 순위 상수들(부하 페널티·경증 역가산·중증 센터 가산·대량사고 그리디)을 **기하 하나로 대체**하려는
새 분배 모델의 실험 폴더 `spider/`. 상세는 `spider/README.md`가 최신.

- **운영 규칙: `sim/`과 같다 — 다른 폴더 파일을 수정하지 않는다.** info 스냅샷·심평원 캐시는 읽기만.
  hub 연동은 아직 없다(연동할 땐 hub가 가져다 쓰는 모듈로 옮기고, 지금 JS 화면은 같은 시나리오로 결과를
  대조하는 검증용으로 둔다 — "시뮬과 실코드가 같은 로직"을 지키기 위해).
- **모델**: 병원 = (x, y, z=역량), 환자는 자기 필요 역량 이상 병원에만 줄을 걸고 줄 길이 = 도로 분 − μ×올라가는
  이득(모자라면 + ν×모자란 양). 유효 역량은 등급 + 전문의 두께 + 야간 감점 − 포화. 같은 τ 창에 한도 넘게 몰리면
  충돌, KTAS 낮은 숫자가 남고 밀린 쪽은 **이동 중 위치에서** 다시 던진다(재전원과 같은 동작). 빈 벽이 없으면
  초과로 붙인다(제외하지 않는 원칙). RVO2(속도 장애물·상호 회피)·Mitzenmacher(낡은 정보의 몰림)에서 착안.
- **신뢰도 모델(infosurv)과의 역할 분담**: 거미줄은 우리끼리 만드는 충돌(τ 창), rArrive는 바깥 흐름(걸어오는
  환자)을 맡는다 — rArrive는 벽 용량 항에 들어갈 자리(아직 미연결). 유령·연동 끊김은 liveness 규칙.
- **숫자는 전부 전문의 검토 전 초안**(μ 30/5, ν 30/15/5, 야간 −0.6, 전문의 ≤1명 −0.4, 질환군 벽). 정답
  데이터는 거절 로그(STAFF_BUSY·도착 후 수용 불가)와 재전원 발생률.
- **실측(2026-10-11)**: 전국 무작위 200명 × 시드 3 — 낮엔 KTAS 2의 권역 비율 두 배(이동 +1~2분), 밤엔 얇은
  지역기관(응급의학 전문의 ≤1명)으로 가는 KTAS 3가 0. 240명까지 초과 0. 피로도 대리 지표(6시간 수용 ÷
  전문의)는 병원 사이 15배·한 병원 안 1.75배 편차라 **동적 피로도 항은 보류, 정적 인력 두께만 z에 반영**.
- **경로**: 외부 서버·RoutingKit 없이 브라우저 안 다익스트라(OSM 남한 pbf → `roads_data.js` 25.8 MB, 전국
  3차로 이상 + 병원 4 km 골목, 노드 100만, 환자당 30 ms). `roads_data.js`는 재생성 가능하지만 팀원이 바로 열
  수 있게 커밋해 둠. pbf(290 MB)는 `spider/data/`에 두고 커밋 안 함.
- **엔진을 파이썬으로, 화면은 서버에서(2026-10-14, develop 머지와 함께)**: `spider/engine/`(roads·model·solve·scenarios —
  numpy·scipy, 다른 폴더 import 없음)이 JS 엔진을 그대로 옮긴 것이고, `spider/serve.py`(Flask, 포트 2700)가 `spider/web/`
  (그리기만 하는 html/js/css + vendor deck.gl·MapLibre)를 `/spider/` 아래로 내준다. `start-all.sh`가 `spider/serve.py`가 있으면
  자동으로 띄우고(`--no-spider`) 터널이 `^/spider(/|$)`를 이 서버로 보낸다 → `https://app.rookie-goldenlink.xyz/spider/`
  (아이패드 앱 WebView 주소). 브라우저는 도로 그래프를 받지 않는다. `map.html`(JS 엔진)은 검증용 쌍둥이로 남기고
  `python parity_check.py`(node 필요)가 14사례를 대조한다 — 모델을 고치면 양쪽을 같이 고친다. 옮긴 이유는 언어 속도가
  아니라 계산 위치: 실제 사건을 받을 때 충돌·양보는 한 곳(hub)에서 계산해야 하고, 태블릿이 25 MB 그래프를 들 이유가 없다.
- **실시간 모드(2026-10-14, `/spider/?mode=live`, `spider/web/live.js`)**: 화면 위 [실시간 (hub 사건)] 버튼. hub WebSocket에
  관제 지도와 같은 `role: "monitor"`로 붙어 `map_overview`·`case_meta`·`case_overview`·`ambulance_phase/position`·`case_closed`를
  받아 실제 사건을 거미줄로 그린다 — 환자 점(휴대폰 통화에서 뽑힌 KTAS·예상 병명·주 호소·필요 진료과·나이/성별·구급대원
  확인 여부), 존 안 병원으로 가는 줄(판단 대기 가는 줄 / 승인 초록 / 불가 회색 / 확정 KTAS색), 확정 뒤엔 hub 이송 경로(지난 구간
  회색·남은 구간 색)와 움직이는 구급차, 도착·수용 고리. "누가 어디로"는 hub 결정 그대로이고, 거미줄 모델의 선택은 같은 환자를
  서버 엔진(`api/solve`)에 넣어 **민트색 "거미줄 제안"**으로만 겹쳐 그린다(hub에 아무것도 보내지 않음, 체크로 끔). 이를 위해 hub
  `MonitorCase`에 `ktasLevel`·`expectedDiagnosis`·`chiefComplaint`·`requiredDepartment`·`patient`·`confirmedBy`를 Optional로
  더했다(통화 전문·활력징후는 여전히 안 보냄). hub 주소는 `api/meta.hubWsUrl`(start-all의 `SPIDER_HUB_WS_URL`; 없으면 같은
  호스트 `/ws/dashboard`, 127.0.0.1이면 접속 호스트로 치환 — 아이패드 LAN용). 임시 hub + 출동 시뮬레이션으로 출동 → 통화 요약 →
  승인/불가 → 확정 → 이송 → 도착까지 E2E 확인(2026-10-14)
- **거미줄 제안 = hub와 같은 재료(2026-10-15)**: 실시간 모드의 민트 "거미줄 제안"이 스냅샷(`hospitals_xyz.json`) 병상으로 계산해 hub가
  이미 만실로 아는 병원(서울대병원 응급실 0)을 제안했다. 이제 spider 서버가 hub `GET /hospital-features`(`HubEngine.spider_features`,
  읽기 전용)를 30초마다 받아 응급실 가용·정원·이송 중(E-Gen 실시간, 차감 반영)·등급·응급의학과 전문의(심평원)·CT·혈관조영 운영을
  덮고, 사건 질환군(`MonitorCase.diseaseGroup` 신설)을 "불가능" 신고·차단 공지한 병원엔 줄을 안 걸며, 사건별로 hub가 수용 불가로 본
  병원(불가·병상 0·제외·차단)도 뺀다. **정보 생존 모델은 hub 순위엔 안 쓰지만 spider에선 병상 용량에 넣는다**(기대 병상 = 가용 ×
  도착 시 유효 확률 — 사용자 결정, README "모델"이 비워 둔 벽 용량 자리). 그래도 고르는 방식은 spider 모델 자신의 것이고 hub에는
  아무것도 보내지 않는다(비교용). start-all이 `SPIDER_HUB_HTTP_URL`(로컬 hub)을 넘긴다
- **오픈소스 검토 중**: 엔진(해소 루프·줄 길이 식·라우터 인터페이스)은 도메인 독립이라 복제본을 따로 만들어
  공개하고, 병원 어댑터·보정값·E-Gen 파이프라인은 비공개로 두는 방향(오픈 코어). 분리가 아니라 **복제**로
  간다(2026-10-11 결정) — 이 폴더는 그대로 두고 복제본에서 병원 흔적을 걷어낸다.
- **실측 벤치마크 함의(2026-10-11, 공개 GPU 복제본에서 Alibaba PAI 2020 트레이스로)**: 중앙 즉시 정보에선 first-fit과 동일;
  다중 제출자·낡은 정보에선 **양보·재투척 규칙이 평균 완료시간 −1/3**로 실제 지렛대, τ 창 혼잡 항은 충돌 −40%지만 완료시간
  효과 없음, 역량 축 이득은 상위 등급이 실제로 빠를 때만 — **트레이스 안 같은 워크로드 비교에선 상위 등급이 더 빠르지 않았다**(μ는
  실측 전 가정). 재투척 이득은 지연·벌점 민감도에 튼튼하고 작업 훔치기 기준선(0~2%)을 크게 앞선다. **그러나 혼잡 항은 단독으로 해롭고(+11~19%),
  무작위·power-of-two가 충돌을 더 줄이며, 우선순위 양보·노화·gang 예약도 전부 해롭다** — 실측 지속시간 기준 GPU 트레이스에서 스파이더 고유
  재료는 하나도 값을 못 했고(등급 축은 상위 등급이 ~10% 이상 빠를 때부터), 재투척은 late binding(Sparrow)이다. 남은 검증은 움직이는
  요청자(병원 `sim/`)뿐. 발표에서 GPU 결과를 모델 근거로 쓰지 말 것. 절제: R 30~35%·G는 속도차 ≥10%부터·Q 혼자는
  해로움(상위 역량 점유)·G와 R은 곱 결합. 스파이더+재투척 교차점 = 역량 간 속도 차 약 10%. 모델은 "스케줄러"가 아니라 **낡은 정보를 가진
  다중 요청자용 분산 배치 규약**으로 말하고 머리글은 재투척·우선순위·제외 없음. 상세 `spider/README.md` 마지막 절.

## 보안 및 개인정보 원칙 (공통)

- 개인정보 최소 수집: 이름, 주민등록번호, 주소는 AI 처리 대상에서 제외하고 비식별화(Patient ID 기반 관리)한다
- 전송 시 TLS 기반 암호화, 가능한 한 On-Premise로 운영해 외부 상용 API로 환자 데이터가 나가지 않도록 한다
- 모든 의사결정 로그는 타임스탬프 + SHA-256 해시로 저장해 사후 위변조 여부를 검증할 수 있게 한다

---

## 코드 작성 시 유의사항

- 각 기능을 구현하기 전에 위 "핵심 AI 활용 원칙" 표를 참고해 AI 처리 영역인지 규칙 기반 영역인지 먼저 확인한다
- 모델/API 호출부와 비즈니스 로직(존 확장, 승인 처리 등)은 분리해서 구현한다 — 나중에 모델을 교체해도 로직에 영향 없게
- 팀원 전원이 Claude Code를 사용하므로, 함수/변수명과 커밋 메시지는 한글 설명을 포함해도 무방하나 코드 자체는 일관된 컨벤션을 유지한다
