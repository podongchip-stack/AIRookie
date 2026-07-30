# CLAUDE.md

이 파일은 Claude Code가 이 저장소에서 작업할 때 참고하는 공통 컨텍스트입니다.
모든 브랜치(main, develop, feature/voice, feature/info, feature/hub, feature/dashboard)에서 동일하게 적용됩니다.

---

## 프로젝트 개요

**골든링크 (GoldenLink) v2.0** — 2026 AI ROOKIE 대회 출품작

응급이송 과정에서 발생하는 음성, 바이탈, 병원 응답 로그를 자동 수집·구조화하여
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
음성·바이탈 수집 → 전처리 (FFmpeg 노이즈 제거)
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
| `feature/info` | 병원 정보(Hospital Info) DB 관리 및 구조화 (역할 범위 확정 중) |
| `feature/hub` | voice의 환자 정보와 info의 병원 정보를 결합한 규칙 기반 매칭 엔진, 존(Zone) 로직, 승인 상태 관리 |
| `feature/dashboard` | 구급차·병원 대시보드 프론트엔드 |

브랜치 전략: `feature/* → develop → main`

---

## 핵심 AI 활용 원칙 (전 브랜치 공통)

작업하는 기능이 아래 표의 어느 항목에 해당하는지 먼저 확인하고, 표시(AI 처리 / 규칙 기반)에 맞게 구현한다.

| 구분 | 처리 방식 | 비고 |
|---|---|---|
| 음성 → 텍스트 변환 | AI (Whisper / Qwen3-ASR) | 화자 분리 포함 |
| 통화 내용 필터링·구조화 | AI (sLLM + KM-BERT) | 실시간 음성 필터링 처리 — 잡담·불필요 발화 제거 후 의료 관련 문장만 추출 |
| 바이탈 수집 | 규칙 기반 (센서 직결) | AI 미사용 |
| 병원 리스트 정렬 | 규칙 기반 (GPS 거리 · 존 그룹) | AI 미사용 |
| 병원 적합도 매칭 | 규칙 기반 (hv1/hvec/hv2 API 대조) | AI 미사용, 설명 가능한 구조 유지 |
| 의사결정 기록 · 보고서 생성 | AI (On-Premise sLLM) | Fact Checking Engine으로 원본 로그와 대조 검증 |

이 구분을 코드나 UI에 반영할 때는 각 기능이 "AI 처리"인지 "규칙 기반"인지 명시적으로 구분되게 만든다 (예: 로그, 주석, API 응답 필드에 `source: "ai" | "rule"` 등).

---

## 데이터 포맷 및 흐름

세 브랜치 간 데이터는 아래 흐름으로 오간다. voice와 vital이 각자 결과를 만들어 dashboard로 보내고, dashboard에서 발생한 승인 행위는 다시 vital로 돌아간다.

```
feature/voice ──(통화 요약 JSON)──────────→ feature/dashboard
feature/vital ──(바이탈 JSON)──────────────→ feature/dashboard
feature/vital ──(병원 매칭 결과 JSON)──────→ feature/dashboard
feature/dashboard ──(승인 액션 JSON)───────→ feature/vital
feature/voice(환자 정보) + feature/info(병원 정보) → feature/hub(규칙 기반 매칭) → feature/dashboard(통합 결과)
```

아래 포맷은 voice를 제외하고는 아직 약식이다. vital은 실제 구급차 바이탈 기기 스펙이 확정되지 않아 우선 가정한 형태이며, 확정되는 대로 갱신한다.

### 1. feature/voice → feature/dashboard : 통화 요약

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

바이탈 필드는 포함하지 않는다. 바이탈은 feature/vital이 별도 스키마로 관리한다.

### 2. feature/vital → feature/dashboard : 바이탈 (약식)

```json
{
  "vitals": {
    "bp_systolic": 90,
    "bp_diastolic": 60,
    "pulse": 102,
    "spo2": 92,
    "gcs": 13,
    "temperature": 36.4,
    "resp_rate": 24
  },
  "timestamp": "2026-07-28T14:33:10Z",
  "source": "rule"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `vitals.bp_systolic` / `bp_diastolic` | number | 수축기/이완기 혈압 (mmHg) |
| `vitals.pulse` | number | 맥박 (bpm) |
| `vitals.spo2` | number | 산소포화도 (%) |
| `vitals.gcs` | number | 의식 수준 (GCS, 3~15) |
| `vitals.temperature` | number | 체온 (℃) |
| `vitals.resp_rate` | number | 호흡수 (회/분) |
| `timestamp` | string (ISO 8601) | 측정 시각 |
| `source` | `"rule"` | 센서 직결, AI 미사용을 나타내는 고정값 |

### 3. feature/vital → feature/dashboard : 존 기반 병원 매칭 결과 (약식)

```json
{
  "zone_active": [1, 2],
  "hospitals": [
    {
      "hospital_id": "C",
      "name": "C병원",
      "distance_km": 2.1,
      "status": "confirmed",
      "eta_min": 6
    },
    {
      "hospital_id": "D",
      "name": "D병원",
      "distance_km": 2.6,
      "status": "rejected"
    }
  ],
  "source": "rule"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `zone_active` | number[] | 현재 활성화된 존 번호 목록 |
| `hospitals[].hospital_id` | string | 병원 식별자 |
| `hospitals[].name` | string | 병원명 |
| `hospitals[].distance_km` | number | GPS 기준 거리 |
| `hospitals[].status` | `"pending"` \| `"approved"` \| `"rejected"` \| `"confirmed"` | 병원 응답 상태 |
| `hospitals[].eta_min` | number | 도착 예상 시간(분), 확정 병원만 필요 |
| `source` | `"rule"` | 규칙 기반 매칭 결과임을 나타내는 고정값 |

### 4. feature/dashboard → feature/vital : 승인 액션 (약식)

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

- 입력 데이터는 음성 중심이다: 구급대원 브리핑, 환자·보호자 진술, 바이탈 데이터. 영상은 다루지 않는다
- STT 모델: Whisper 또는 Qwen3-ASR (스트리밍 지원)
- 실시간 음성 필터링 처리: STT 결과를 문장/발화 턴 단위로 분리 → 의료 관련 여부 분류(경량 분류기 또는 KM-BERT) → 관련 문장만 sLLM(Llama3 Korean 8B)에 전달해 SBAR 형태로 구조화
- 잡담·인사말·통화 연결 관련 발화는 필터링 대상이며, 필터링된 문장도 원본 로그에는 남겨두고 "요약 제외" 표시만 한다 (완전 삭제 금지 — 사후 검증 및 audit trail 때문)
- 출력 포맷은 위 "데이터 포맷 및 흐름 > 1. feature/voice → feature/dashboard" 참고
- 개인정보(이름, 주민등록번호, 주소)는 AI 처리 대상에서 제외

## feature/info 담당자 참고사항

> **브랜치 이름 변경 안내**: 이 브랜치는 기존 `feature/vital`에서 이름이
> 변경되었습니다. 바이탈 수집과 병원 매칭 로직 중 어디까지를 이 브랜치가
> 계속 담당할지, 아니면 신설된 `feature/hub`로 옮길지는 아직 팀 내부에서
> **역할 분담 확정 필요** 상태입니다.

- 바이탈 데이터는 AI 처리 없이 센서값을 그대로 전달 (규칙 기반)
- 병원 매칭은 AI가 아닌 규칙 기반 적합도 엔진으로 구현: hv1(전문의 보유)/hvec(병상 현황)/hv2(중증 질환별 수용 가능 여부) API를 대조해 점수 산출
- 존(Zone) 로직: 구급차 GPS 기준 반경으로 존을 나누고, 존 내 병원 중 명시적 거절 비율이 일정 기준을 넘으면 다음 존까지 자동 확장 (시간 기반 타임아웃이 아닌 거절 비율 기반)
- 승인 프로세스: 병원의 "승인"은 후보 등록일 뿐이며, 구급대원의 "이송 승인"이 최종 확정이다. 이동 중에도 새 병원이 승인하면 재선택 가능해야 한다
- 바이탈 실시간 전송은 이송 승인이 확정된 병원 한 곳에만 이루어져야 하며, 병원 전환 시 기존 전송은 즉시 중단한다
- 출력 포맷은 위 "데이터 포맷 및 흐름 > 2, 3" 참고. dashboard로부터 승인 액션(4번 포맷)을 수신하는 처리도 구현해야 한다

## feature/hub 담당자 참고사항

- 입력은 두 가지: feature/voice가 보내는 환자 정보 JSON(부상 상태, 예상 병명, 중증도)과 feature/info가 보내는 병원 정보 JSON(위치, 병상, 전문성)
- 처리는 규칙 기반 스코어링만 사용 (AI 미사용, source: "rule")
  - 1차: GPS 기준 거리·존(Zone) 분류
  - 2차: voice의 예상 병명·중증도와 info의 병원 전문성(specialties)을 결합한 가중합 스코어링으로 재정렬
- 존 확장은 시간 기반이 아닌 명시적 거절 비율 기준
- 출력은 feature/dashboard로 전송하는 통합 매칭 결과 JSON (feature/hub README.md의 "입출력 데이터 포맷" 참고)
- dashboard가 보내는 hospital_approve / hospital_reject / final_approval 액션을 수신해 상태를 관리하고, 실시간 바이탈 스트리밍이 final_approval이 확정된 병원 한 곳에만 가도록 전환 처리

## feature/dashboard 담당자 참고사항

- 구급차 대시보드와 병원 대시보드는 유사한 레이아웃을 공유하되, 승인 버튼 종류만 다르다 (병원: 병원 승인/불가, 구급차: 이송 승인)
- 각 정보 패널에는 출처 표시가 필요하다: AI 처리된 정보(통화 요약 등)와 규칙 기반/센서 직결 정보(바이탈, 병원 리스트, 지도)를 시각적으로 구분해서 보여준다
- Override 구조를 UI로 드러낼 것: AI가 생성한 요약은 전송 전 구급대원이 확인·수정할 수 있어야 한다
- 실시간 갱신: WebSocket 기반, 완료된 정보부터 순차적으로 갱신 (전체 처리 완료까지 기다리지 않음)
- voice·vital로부터 수신하는 데이터와 vital로 송신하는 승인 액션은 위 "데이터 포맷 및 흐름" 참고

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
