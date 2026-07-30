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
| 구급차 대시보드 | | feature/hub (voice·info 결합 결과) |
| 병원 대시보드 | | feature/hub (voice·info 결합 결과) |

## 연동하는 데이터 (약식)

> **dashboard는 feature/hub와만 직접 통신한다.** feature/voice·feature/info와는
> 직접 연결하지 않으며, voice의 의료 정보·예상 병명과 info의 병원 정보는 모두
> feature/hub가 재가공한 통합 결과로만 받는다 (자세한 설명은 CLAUDE.md "데이터
> 포맷 및 흐름" 참고). 환자 바이탈 정보는 더 이상 사용하지 않기로 결정되어 관련
> 스키마를 제거했다. 아래 스키마는 모두 가안이며 팀 리뷰 후 확정 예정.

**hub로부터 수신** — 통합 매칭 결과 (의료 정보·예상 병명·병원 정보·병원 리스트 포함. 자세한 필드 설명은 feature/hub README 참고)
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
`feature/hub`로 확정됨 — dashboard는 feature/hub와만 직접 통신하기 때문)
```json
{
  "action": "final_approval",
  "hospital_id": "",
  "actor": "paramedic",
  "timestamp": "..."
}
```

## AI 처리 여부 표시 규칙

> 대시보드는 AI 처리 정보와 규칙 기반 정보를 시각적으로 구분해서 보여줘야 한다 (CLAUDE.md 참고).
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
