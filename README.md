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
| 구급차 대시보드 | | feature/voice, feature/hub |
| 병원 대시보드 | | feature/voice, feature/hub |

## 연동하는 데이터 (약식)

> 환자 바이탈 정보는 더 이상 사용하지 않기로 결정되어 관련 스키마를 제거했다.
> 병원 매칭 결과는 `feature/hub` 신설에 따라 구 `feature/vital` 스키마를 대체했다.
> 아래 스키마는 모두 가안이며 팀 리뷰 후 확정 예정.

**voice로부터 수신** — 통화 요약 (자세한 필드 설명은 feature/voice README 참고)
```json
{
  "transcript": { "raw_text": "...", "filtered_text": "...", "language": "ko", "timestamp": "...", "duration_sec": 0 },
  "summary": { "patient": "...", "mechanism": "...", "symptoms": [], "treatment": [], "severity_tag": "high" },
  "source": "ai",
  "model_used": { "stt": "...", "llm": "..." }
}
```

**hub로부터 수신** — 통합 매칭 결과 (자세한 필드 설명은 feature/hub README 참고)
```json
{
  "patientInfo": {
    "injuryStatus": [],
    "expectedDiagnosis": "...",
    "severityTag": "high"
  },
  "zoneActive": [],
  "hospitals": [
    {
      "hospitalId": "",
      "name": "",
      "gps": { "lat": 0, "lng": 0 },
      "distanceKm": 0,
      "specialtyMatch": { "department": "", "score": 0 },
      "availableBedCount": 0,
      "status": "pending",
      "etaMin": 0
    }
  ],
  "source": "rule"
}
```

**송신** — 승인 액션 (구급대원/병원이 대시보드에서 버튼을 눌렀을 때. 수신처는
`feature/info`·`feature/hub` 간 논의 중 — 잠정 보류)
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
