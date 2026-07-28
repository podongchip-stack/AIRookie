# feature/dashboard — 기능 요약 한 줄

<!-- 예: feature/dashboard — 구급차·병원 실시간 대시보드 -->

## 담당자

- 이름: 김태우
- 역할: 리드 개발자

## 이 브랜치가 하는 일

<!-- 구급차 대시보드 / 병원 대시보드가 각각 무엇을 보여주는지 2~3문장 -->

## 개발 환경 / 언어

- 언어:
- 프레임워크: (예: React)
- 스타일링:
- 상태 관리:
- 실시간 통신 방식: (예: WebSocket)

## 화면 구성

| 화면 | 설명 | 관련 브랜치 데이터 |
|---|---|---|
| 구급차 대시보드 | | feature/voice, feature/vital |
| 병원 대시보드 | | feature/voice, feature/vital |

## 연동하는 데이터

## 연동하는 데이터 (약식)

> vital 브랜치의 실제 기기 스펙 확정 전까지는 아래 약식 포맷 기준으로 화면을 구성한다.

**voice로부터 수신** — 통화 요약 (자세한 필드 설명은 feature/voice README 참고)
```json
{
  "transcript": { "raw_text": "...", "filtered_text": "...", "language": "ko", "timestamp": "...", "duration_sec": 0 },
  "summary": { "patient": "...", "mechanism": "...", "symptoms": [], "treatment": [], "severity_tag": "high" },
  "source": "ai",
  "model_used": { "stt": "...", "llm": "..." }
}
```

**vital로부터 수신** — 바이탈 (자세한 필드 설명은 feature/vital README 참고)
```json
{
  "vitals": { "bp_systolic": 0, "bp_diastolic": 0, "pulse": 0, "spo2": 0, "gcs": 0, "temperature": 0, "resp_rate": 0 },
  "timestamp": "...",
  "source": "rule"
}
```

**vital로부터 수신** — 병원 매칭 결과 (자세한 필드 설명은 feature/vital README 참고)
```json
{
  "zone_active": [],
  "hospitals": [{ "hospital_id": "", "name": "", "distance_km": 0, "status": "pending", "eta_min": 0 }],
  "source": "rule"
}
```

**vital로 송신** — 승인 액션 (구급대원/병원이 대시보드에서 버튼을 눌렀을 때)
```json
{
  "action": "final_approval",
  "hospital_id": "",
  "actor": "paramedic",
  "timestamp": "..."
}
```

## AI 처리 여부 표시 규칙

> 대시보드는 AI 처리 정보와 규칙 기반/센서 직결 정보를 시각적으로 구분해서 보여줘야 한다 (CLAUDE.md 참고).
- [ ] AI 처리 항목에 배지/표시 적용함
- [ ] 규칙 기반 항목에 배지/표시 적용함

## 실행 방법

```bash

```

## 폴더 구조

```

```

## 알려진 제약사항 / TODO

-

## 추가사항
