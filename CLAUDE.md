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
- 병원 매칭은 AI가 아닌 **규칙 기반 적합도 엔진**으로 구현한다 (설명 가능한 추천 구조).
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
| `feature/info` | 병원 정보(Hospital Info) DB 관리 및 구조화 (병원 매칭/존 로직은 feature/hub로 이관 확정, 바이탈 수집은 더 이상 사용하지 않음. 승인 액션 수신 주체는 논의 중 — 잠정 보류) |
| `feature/hub` | voice의 환자 정보와 info의 병원 정보를 결합한 규칙 기반 매칭 엔진, 존(Zone) 로직 (승인 액션 수신 주체는 논의 중 — 잠정 보류) |
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
| 병원 적합도 매칭 | 규칙 기반 (hv1/hvec/hv2 API 대조) | AI 미사용, 설명 가능한 구조 유지 |
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
(hospital_approve/hospital_reject/final_approval)를 feature/info와 feature/hub 중 누가
수신할지는 아직 팀 내부에서 논의 중이라 **잠정 보류** 상태다 (아래 2번 포맷 참고).

```
feature/voice ──(의료 정보·예상 병명 JSON)──→ feature/hub
feature/info ──(병원 정보 JSON)──────────────→ feature/hub
feature/hub ──(통합 매칭 결과 JSON: 의료 정보+예상 병명+병원 정보+병원 리스트)──→ feature/dashboard
feature/dashboard ──(승인 액션 JSON)─────────→ (수신 주체 논의 중 — feature/info 또는 feature/hub)
```

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

이 JSON은 feature/hub로 전달되며, feature/hub는 이 중 `summary`(부상 상태·예상 병명·
중증도)만 매칭 스코어링에 사용한다. dashboard는 이 JSON을 직접 받지 않고, feature/hub가
재가공한 통합 결과(아래 feature/hub README.md 참고)를 통해서만 받는다.

> 병원 정보 스키마(feature/info → feature/hub)와 통합 매칭 결과 스키마(feature/hub →
> feature/dashboard)는 feature/hub README.md의 "입출력 데이터 포맷"이 최신 버전이므로,
> 여기서는 중복 정의하지 않는다.

### 2. feature/dashboard → (수신 주체 논의 중) : 승인 액션 (약식)

> feature/info와 feature/hub 중 어느 쪽이 이 액션을 수신할지 아직 확정되지 않았다
> (잠정 보류). 확정 전까지는 아래 스키마 자체만 유효하고, 화살표 대상은 비워둔다.

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

---

## feature/voice 담당자 참고사항

- 입력 데이터는 음성 중심이다: 구급대원 브리핑, 환자·보호자 진술. 영상은 다루지 않는다
- STT 모델: Whisper 또는 Qwen3-ASR (스트리밍 지원)
- 실시간 음성 필터링 처리: STT 결과를 문장/발화 턴 단위로 분리 → 의료 관련 여부 분류(경량 분류기 또는 KM-BERT) → 관련 문장만 sLLM(Llama3 Korean 8B)에 전달해 SBAR 형태로 구조화
- 잡담·인사말·통화 연결 관련 발화는 필터링 대상이며, 필터링된 문장도 원본 로그에는 남겨두고 "요약 제외" 표시만 한다 (완전 삭제 금지 — 사후 검증 및 audit trail 때문)
- 출력 포맷은 위 "데이터 포맷 및 흐름 > 1. feature/voice → feature/hub" 참고. **dashboard로는 직접 전송하지 않고 feature/hub를 거쳐 전달된다**
- 개인정보(이름, 주민등록번호, 주소)는 AI 처리 대상에서 제외

## feature/info 담당자 참고사항

> **브랜치 이름 변경 안내**: 이 브랜치는 기존 `feature/vital`에서 이름이
> 변경되었습니다. **병원 매칭·존(Zone) 로직은 `feature/hub`로 이관하는 것으로
> 확정**되었습니다. 다만 dashboard가 보내는 승인 액션
> (hospital_approve/hospital_reject/final_approval)을 이 브랜치와 `feature/hub`
> 중 어느 쪽이 수신할지는 아직 논의 중이라 **잠정 보류** 상태입니다.

- 환자 바이탈 정보는 더 이상 사용하지 않기로 결정되어, 바이탈 수집·전송 관련 서술은 모두 제거했다
- 병원 매칭·존(Zone) 로직은 더 이상 이 브랜치가 담당하지 않는다 (`feature/hub` 담당자 참고사항 참고)
- 승인 프로세스: 병원의 "승인"은 후보 등록일 뿐이며, 구급대원의 "이송 승인"이 최종 확정이다. 이동 중에도 새 병원이 승인하면 재선택 가능해야 한다
- 출력 포맷은 위 "데이터 포맷 및 흐름 > 1. feature/voice → feature/hub" 참고 (병원 정보 스키마는 feature/hub README.md 참고). 승인 액션(2번 포맷) 수신 처리는 feature/hub와 역할 분담이 확정되면 구현한다 (현재는 대기)

## feature/hub 담당자 참고사항

- 입력은 두 가지: feature/voice가 보내는 환자 정보 JSON(부상 상태, 예상 병명, 중증도)과 feature/info가 보내는 병원 정보 JSON(위치, 병상, 전문성)
- **dashboard와 직접 통신하는 유일한 브랜치다.** feature/voice·feature/info는 dashboard로 보내지 않고 이 브랜치를 거친다
- 처리는 2단계로 진행한다 (규칙 기반 스코어링만 사용, AI 미사용, source: "rule")
  1. GPS와 feature/info의 병원 정보로 먼저 존(Zone) 기반 병원 후보 리스트를 만들어 보관한다
  2. feature/voice의 의료 정보(예상 병명·중증도)가 도착하면, 보관해둔 리스트를 voice 정보와 info의 병원 전문성(specialties)을 결합한 가중합 스코어링으로 재처리한다
- 존 확장은 시간 기반이 아닌 명시적 거절 비율 기준
- 출력은 feature/dashboard로 전송하는 통합 매칭 결과 JSON — 의료 정보·예상 병명·병원 정보·병원 리스트를 모두 포함한다 (feature/hub README.md의 "입출력 데이터 포맷" 참고)
- dashboard가 보내는 hospital_approve / hospital_reject / final_approval 액션을 이 브랜치가 수신할지, feature/info가 수신할지는 아직 논의 중 — **잠정 보류**. 확정되면 매칭 상태(`hospitals[].status`)에 반영하는 처리를 구현한다

## feature/dashboard 담당자 참고사항

- 구급차 대시보드와 병원 대시보드는 유사한 레이아웃을 공유하되, 승인 버튼 종류만 다르다 (병원: 병원 승인/불가, 구급차: 이송 승인)
- 각 정보 패널에는 출처 표시가 필요하다: AI 처리된 정보(통화 요약 등)와 규칙 기반 정보(병원 리스트, 지도)를 시각적으로 구분해서 보여준다
- Override 구조를 UI로 드러낼 것: AI가 생성한 요약은 전송 전 구급대원이 확인·수정할 수 있어야 한다
- 실시간 갱신: WebSocket 기반, 완료된 정보부터 순차적으로 갱신 (전체 처리 완료까지 기다리지 않음)
- **feature/hub와만 직접 통신한다.** voice·info와는 직접 연결하지 않으며, voice의 의료 정보·예상 병명과 info의 병원 정보는 모두 feature/hub가 재가공한 통합 결과로만 받는다. 승인 액션 송신(수신처는 feature/info·feature/hub 간 논의 중)은 위 "데이터 포맷 및 흐름" 참고

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
