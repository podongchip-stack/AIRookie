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

**송신** — 소켓 연결 직후 자기소개 (2026-08-11 신설, hub와의 "따라잡기" 문제 수정)
```json
{
  "type": "identify",
  "role": "hospital",
  "id": "S0000001"
}
```
> hub는 그동안 소켓 연결을 완전히 익명으로 취급해서, 매칭 결과를 그 순간
> 연결된 소켓에만 브로드캐스트했다. 그래서 진행 중인 사건이 있는 상태로
> 새 대시보드 탭이 뒤늦게 열리면, 그 탭은 이전 브로드캐스트를 놓쳐 화면에
> 아무것도 안 뜨는 문제가 있었다(2026-08-11 실제 재현됨 — 구급1호차·
> 서울대병원 탭이 연결된 상태에서 매칭이 끝난 뒤 한양대병원 탭을 새로
> 열면 그 사건이 안 보였음). `useDashboardSocket`이 소켓이 열리자마자
> 이 메시지를 자동으로 보내면, hub가 자기가 병원(hpid)인지 구급차
> (apid)인지 보고 두 가지를 순서대로 돌려준다: (1) 사건 유무와 무관한
> 즉시 신원 확인(아래 `identity_info`), (2) 관련된 진행 중인 사건
> 따라잡기 — 이건 평소 브로드캐스트와 같은 `HubMatchResult` 형식이라
> `onmessage`에서 별도 분기가 필요 없다(feature/hub README.md "입력
> 스키마 9" 참고).

**수신** — 신원 확인 응답 (2026-08-11 신설, "자기소개"에 대한 첫 응답)
```json
{
  "type": "identity_info",
  "role": "hospital",
  "id": "S0000001",
  "name": "서울대학교병원",
  "known": true
}
```
> `hospitals[].name`/`HubMatchResult.ambulanceName`은 둘 다 "그 병원/구급차가
> 실제 매칭 사건에 등장해야만" 이름이 왔다 — 통화 전에는 상단바에
> `병원 ID: S0000001`, `구급 A0000001호차` 같은 ID 폴백만 보였다. 이 응답은
> 사건 유무와 무관하게, hub가 이미 아는 병원/구급차 레지스트리에서 즉시
> 이름을 조회해 돌려준다. `useDashboardSocket`의 반환값 중
> `state.identity`(`{ name, known }`)에 저장되며, `matchResults`와는 완전히
> 분리된 상태다(feature/hub README.md "출력 스키마 6" 참고). `known`이
> `false`인 경우의 "존재하지 않는 접근 코드" 처리는 아래 "랜딩 페이지 사전
> 검증" 항목 참고 — 처음엔 이 소켓 응답을 받은 뒤(즉 `/hospital`,
> `/ambulance` 페이지가 열린 뒤) 전체 화면을 막는 방식이었는데, 2026-08-11에
> 랜딩 페이지에서 넘어가기 전에 미리 막는 방식으로 옮겼다(`/hospital`,
> `/ambulance` 페이지 자체엔 더 이상 이 차단이 없다 — 직접 URL로 들어온
> 경우엔 상단바 이름이 ID 폴백으로 남는 정도로만 티가 난다).

**랜딩 페이지 사전 검증** (2026-08-11 신설, `src/app/page.tsx`)

코드를 입력하고 "입장"을 누르면, `/hospital`·`/ambulance`로 라우팅하기 **전에**
hub의 `GET /identity`(HTTP, WebSocket 아님)로 그 hpid/apid가 실제로 존재하는지
먼저 확인한다. 존재하지 않으면 입력칸과 입장 버튼 사이에 빨간 글씨로
"존재하지 않는 코드입니다"를 띄우고 라우팅하지 않는다 — 예전엔 목적지
페이지로 넘어간 뒤 전체 화면이 "존재하지 않는 접근 코드입니다"로 막히는
방식이었다.

```
GET {NEXT_PUBLIC_HUB_HTTP_URL}/identity?role=hospital&id=S0000001
→ { "role": "hospital", "id": "S0000001", "name": "서울대학교병원", "known": true }
```

`NEXT_PUBLIC_HUB_HTTP_URL`(신규 환경변수, 예: `http://127.0.0.1:5001`)이
설정돼 있지 않거나 요청이 실패하면(hub가 안 떠 있는 개발 환경 등) 검증 없이
통과시킨다 — 그 경우엔 목적지 페이지의 WebSocket `identify`가 이름 표시
용도로 한 번 더 조회하므로 완전히 무방비는 아니다. dashboard(포트 3000)와
hub(포트 5001)는 다른 origin이라 브라우저 `fetch`가 CORS로 막히는데, hub의
`GET /identity`만 `Access-Control-Allow-Origin: *`을 붙여 이 요청을 허용한다
(feature/hub README.md "`GET /identity`" 참고).

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

- ~~apid/hpid는 URL 쿼리(`?id=`)만으로 구분하며, Supabase 구급차/병원
  레지스트리에 실제로 존재하는 값인지 서버 사이드로 검증하지 않는다~~ →
  **2026-08-11 해결.** dashboard가 Supabase에 직접 붙는 대신, hub가
  `identify`에 대한 응답(`identity_info`)으로 `known`을 알려주는 방식으로
  구현했다 — `known === false`면 `/hospital`, `/ambulance` 페이지가
  "존재하지 않는 접근 코드입니다" 화면으로 막는다. 이 결정 과정에서
  `dashboard/.env.local`의 `AMBULANCE_SUPABASE_URL`/`AMBULANCE_SUPABASE_KEY`
  (한 번도 실제로 쓰인 적 없었음)와 `package.json`의
  `@supabase/supabase-js` 의존성을 제거했다 — dashboard는 여전히
  feature/hub와만 직접 통신한다(CLAUDE.md 원칙 유지).
- 병원 대시보드의 다중 사건 카드 리스트·구급차 대시보드의 `caseId` 흐름,
  그리고 이번 `identity_info` 흐름은 `tsc`/`eslint`/`next build`와 로컬
  WebSocket smoke test로만 검증했고, 실제 브라우저 인터랙션(다중 탭·다중
  사건 동시 진행, 접근 불가 화면 실제 렌더링 등) 테스트는 아직 안 함 — 이
  환경엔 브라우저 도구가 없어 직접 확인이 어려웠다.

## 추가사항
