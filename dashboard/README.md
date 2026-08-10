# feature/dashboard — 기능 요약 한 줄

<!-- 예: feature/dashboard — 구급차·병원 실시간 대시보드 -->

> **폴더 구조 안내(모노레포)**: 이 저장소는 `feature/voice`·`feature/hub`·
> `feature/info`·`feature/dashboard`가 하나의 저장소를 공유하며, 각 브랜치는
> 자기 작업 폴더(`voice/`·`hub/`·`info/`·`dashboard/`)만 갖는다. **지금 이
> 브랜치에는 `dashboard/` 폴더만 있고 `voice/`·`hub/`·`info/`는 없다.** 만약
> 작업 중 낯선 폴더가 보인다면 `develop`을 머지했거나 다른 브랜치를 체크아웃한
> 상태라는 뜻이니, 실수로 만들어진 게 아닌지 걱정하지 않아도 된다.

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
| 구급차 대시보드 (`/ambulance?id=<apid>`) | 구급차 1대 전용 화면. URL의 `?id=`(apid)로 자신을 식별하고, 통화 시작마다 새 `caseId`를 만들어 hub에 실어 보낸다. 사건은 항상 1개(자기 사건)만 표시 | feature/hub (voice·info 결합 결과) |
| 병원 대시보드 (`/hospital?id=<hpid>`) | 병원 1곳 전용 화면. `?id=`(hpid)가 후보로 걸린 **모든 사건**을 카드로 나열한다(다중 구급차가 동시에 같은 병원을 후보로 걸 수 있음) — 카드를 선택하면 그 사건 기준으로 지도가 갱신됨 | feature/hub (voice·info 결합 결과) |

## 연동하는 데이터 (약식)

> **dashboard는 feature/hub와만 직접 통신한다.** feature/voice·feature/info와는
> 직접 연결하지 않으며, voice의 의료 정보·예상 병명과 info의 병원 정보는 모두
> feature/hub가 재가공한 통합 결과로만 받는다 (자세한 설명은 CLAUDE.md "데이터
> 포맷 및 흐름" 참고). 환자 바이탈 정보는 더 이상 사용하지 않기로 결정되어 관련
> 스키마를 제거했다. 아래 스키마는 모두 가안이며 팀 리뷰 후 확정 예정.
>
> **다중 사건(multi-case) 지원 (2026-08-11)**: hub가 `caseId`(구급차 1건의 이송
> 이벤트 식별자)와 `apid`(구급차 식별자)를 도입하면서, dashboard의 상태도 사건
> 하나(`matchResult`)가 아니라 `matchResults: Record<caseId, HubMatchResult>` 맵으로
> 바뀌었다. 구급차 대시보드는 자신이 만든 `caseId` 하나만 맵에서 꺼내 쓰고, 병원
> 대시보드는 자기 hpid가 `hospitals[]`에 들어있는 모든 사건을 맵에서 걸러 리스트로
> 보여준다.

**hub로부터 수신** — 통합 매칭 결과 (의료 정보·예상 병명·병원 정보·병원 리스트 포함. 자세한 필드 설명은 feature/hub README 참고)
```json
{
  "caseId": "case-...",
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
  "caseId": "case-...",
  "action": "final_approval",
  "hospital_id": "",
  "actor": "paramedic",
  "timestamp": "..."
}
```

**송신** — 통화 시작/종료 신호 (구급차 대시보드 전용. `apid`는 URL `?id=`, `caseId`는
`call_started` 시점에 `crypto.randomUUID()`로 새로 생성)
```json
{
  "type": "call_signal",
  "signal": "call_started",
  "timestamp": "...",
  "apid": "A0000001",
  "caseId": "case-..."
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

- apid/hpid는 현재 URL 쿼리(`?id=`)만으로 구분하며, Supabase 구급차/병원
  레지스트리에 실제로 존재하는 값인지 서버 사이드로 검증하지 않는다 (오타나
  존재하지 않는 ID로 들어와도 화면은 그냥 "수신 대기 중"으로만 보임). 다음
  단계에서 Next.js Route Handler로 존재 여부를 확인하는 방안 검토 필요.
- 병원 대시보드의 다중 사건 카드 리스트·구급차 대시보드의 `caseId` 흐름은
  `tsc`/`eslint`/`next build`와 로컬 WebSocket smoke test로만 검증했고, 실제
  브라우저 인터랙션(다중 탭·다중 사건 동시 진행) 테스트는 아직 안 함.

## 추가사항
