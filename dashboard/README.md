# feature/dashboard — 구급차·병원·관제 실시간 대시보드

> **모노레포 안내**: 이 저장소는 `voice/`·`hub/`·`info/`·`dashboard/`를 한 저장소에 두고 브랜치마다 자기 폴더를 맡는다.
> `feature/dashboard`는 develop을 주기적으로 병합하므로 다른 폴더도 함께 보인다 — 정상이다. 이 브랜치가 고치는 건 `dashboard/`뿐이다.

## 담당자

- 이름: 김태우
- 역할: 리드 개발자

## 이 브랜치가 하는 일

구급대원·병원·관제가 보는 화면이다. 구급차 대시보드는 출동 상황, AI가 정리한 통화 요약(구급대원이 확인·수정), 후보 병원
목록과 이송 승인을 보여준다. 병원 대시보드는 들어온 수용 요청을 카드로 받아 승인·불가(사유)·도착 결과를 누른다. 관제 지도는
전체 병원·구급차와 요청 현황을 보여주며, 상단 ‘시연 조작’을 열면 같은 지도에서 시연을 진행할 수 있다.

**dashboard는 feature/hub와만 통신한다.** voice·info와 직접 연결하지 않고, 모든 데이터는 hub가 재가공한 WebSocket 메시지로 받는다.
순위는 hub가 정한 `hospitals[]` 순서를 그대로 쓴다(화면에서 다시 정렬하지 않음).

## 개발 환경

| 항목 | 내용 |
|---|---|
| 프레임워크 | Next.js 16 (App Router), React 19, TypeScript |
| 스타일 | Panda CSS(`styled-system/`, `npm install` 때 `panda codegen`으로 생성) + 컴포넌트별 인라인 디자인 토큰 |
| 실시간 통신 | 순수 WebSocket(`new WebSocket()`, socket.io 아님) — `src/hooks/use-dashboard-socket.ts` |
| 지도 | 카카오 지도 JavaScript SDK |
| 마이크 | 브라우저 PCM 캡처(16kHz 모노 16비트, `src/lib/pcm-capture.ts`) — https·localhost에서만 열림 |
| 모바일 앱 | `iphone/`(Swift), `android/`(Kotlin·Compose) — 통화 STT·구조화를 기기 안에서 돌리는 온디바이스 앱(각 폴더 README) |

## 실행 방법

```bash
cd dashboard
npm install                  # panda codegen 포함
npm run dev                  # http://localhost:3000
npm run build && npm start   # 배포 모드
npm run lint
```

보통은 저장소 루트의 `./start-all.sh`가 hub·info와 함께 띄운다(루트 README "실행 명령 정리").

`.env.local`:

| 변수 | 뜻 |
|---|---|
| `NEXT_PUBLIC_DASHBOARD_WS_URL` | hub WebSocket 주소(예: `ws://127.0.0.1:5001/ws/dashboard`). **없으면 목데이터 모드** — 상단바에 "○ 목데이터 모드" 배지 |
| `NEXT_PUBLIC_HUB_HTTP_URL` | hub HTTP 주소(예: `http://127.0.0.1:5001`). 접근 코드 사전 확인·경로·배후역량 조회 |
| `NEXT_PUBLIC_KAKAO_MAP_APP_KEY` | 카카오 지도 키. 없으면 지도 칸에 안내만 뜬다 |
| `NEXT_PUBLIC_LIDAR_VIEWER_URL` | (선택) 3D 뷰어 주소 — 있으면 병원 대시보드에 3D 버튼 |

## 화면

첫 페이지(`/`)에 접근 코드를 넣어 들어간다. 넘어가기 전에 hub `GET /identity`로 코드가 실제로 있는지 확인한다.

| 화면 | 주소 | 하는 일 |
|---|---|---|
| 구급차 대시보드 | `/ambulance?id=<apid>` (코드 `A-…`) | 출동 조작, 통화 요약 확인·수정, 현장 후보(첫 연락 추천), 후보 병원 목록·이송 승인, 이송 중 모니터링 |
| 휴대폰 전화 앱 | `/phone?id=<apid>` (코드 `P-…`) | 대원 휴대폰. 현장 도착 뒤 병원을 골라 통화만 한다(마이크 음성이 hub를 거쳐 voice STT 입력) |
| 병원 대시보드 | `/hospital?id=<hpid>` (코드 `H-…`) | 자기 병원이 후보인 **모든 사건**을 카드로. 승인·불가(사유)·이송 중 철회·도착 결과, 자기 정보 확인 |
| 관제 지도 | `/map` | 진행 중 사건·병원 응답·구급차 위치·존 범위 + 접을 수 있는 시연 조작 패널 |
| 사건 상황판 | `/case` | 사건 단위 모니터 지도 |
| 시연 콘솔 | `/control` | 시연 진행(이송 중 시나리오·대량사고 분배 등) |
| 신뢰도 검증 | `/verify` | 병상 정보 신뢰도 시연용 채점·라이브 보드(`?hpid=`면 그 병원 기록) |

## 통화 요약 확인·수정 (Override, 2026-10-13)

AI 통화 요약은 통화가 끝나자마자 후보 병원에 간다(순차 전화를 없애는 게 목적이라 기다리지 않는다). 대신 확인 상태를 화면에 드러낸다.

- **구급차 — 통화 요약 카드**(`components/ambulance/CallSummaryEditablePanel.tsx`): 요약이 맞으면 [확인] 한 번. 틀리면 [수정]에서
  예상 병명·증상·KTAS·필요 진료과·주 호소를 고쳐 [확인·전송]. 고친 칸만 `patient_override`로 hub에 보내고, hub 갱신본이 오면 화면이
  그것으로 맞춰진다(그 사이 "병원에 전송 중"). KTAS를 바꾸면 중증도가 따라 바뀌고, 이송 확정 전이면 hub가 다시 매칭해 후보 순서가 바뀔 수 있다.
- **병원 — 수용 요청 카드**(`components/hospital/RequestCard.tsx`): "AI 요약 · 구급대원 확인 전" 또는 "✓ 구급대원 확인 hh:mm" 칩.
  고친 칸이 있으면 AI 값 → 구급대원 값 상자(KTAS 상향이면 빨강). 병원 승인은 자동으로 풀리지 않는다 — 이 상자를 보고 다시 판단한다.
- 칩·상자는 `components/panels/PatientConfirmation.tsx` 공용. 구버전 hub(필드 없음)면 그리지 않는다. 목데이터 모드는 로컬로 흉내만 낸다.

## hub와 주고받는 메시지

형식의 정본은 CLAUDE.md "데이터 포맷 및 흐름"과 hub README "입출력 데이터 포맷"이다. 여기는 목록만 둔다.

**보냄**(같은 WebSocket): `identify`(연결 직후 자기소개) · 승인 액션(`hospital_approve`·`hospital_reject`(사유)·`final_approval`·
`arrival_accepted`·`arrival_refused`·`transport_withdraw`) · `call_signal`(통화 시작·종료·취소) · 마이크 PCM(바이너리) ·
`patient_override`(통화 요약 확인·수정) · `info_confirm`(병원 정보 확인) · `transport_vitals`(이송 중 활력징후) · 시뮬레이션 조작
(`dispatch`·`scene_end`·`sim_pause`·`sim_resume`·`sim_reset`·`sim_fast_forward`) · `zone_expand_now` · 대량사고(`mci_preview`·`mci_allocate`) ·
`voice_summary`(온디바이스 앱)

**받음**: `match_result`(통합 매칭 결과) · `identity_info` · `hospital_self_info` · `scene_candidates` · `ambulance_phase`·`ambulance_position` ·
`call_status`·`call_transcript` · `case_closed`·`case_sync` · `map_overview`·`case_overview`·`case_meta`·`case_history` ·
`transport_assessment`·`pre_alert` · `mci_plan`·`mci_allocated` · `scene_input_mode` · `action_refused`(일시정지·권한 없음 등).
모르는 `type`은 버리고, `type` 없는 메시지는 구 hub의 매칭 결과로 본다.

## 설계 메모 (왜 이렇게 했나)

- **상태는 사건 맵**: `matchResults: Record<caseId, HubMatchResult>`. 구급차는 자기 사건 하나, 병원은 자기 hpid가 후보인 모든 사건을 꺼낸다.
- **연결 직후 `identify`**: hub는 그 순간 연결된 소켓에만 매칭 결과를 보내서, 진행 중 사건이 있을 때 늦게 연 탭은 화면이 비었다(2026-08-11
  재현). 자기소개를 보내면 hub가 이름(`identity_info`)과 진행 중 사건(따라잡기, 평소와 같은 `match_result` 형식)을 돌려준다.
- **접근 코드 사전 확인은 첫 페이지에서**: 목적지 페이지가 열린 뒤 막는 대신, 라우팅 전에 `GET /identity`로 확인한다. hub가 꺼져 있으면
  확인 없이 통과시킨다(목적지의 `identify`가 이름 표시용으로 한 번 더 조회). dashboard는 Supabase에 직접 붙지 않는다.
- **병상 "미상"은 0이 아니다**: `bedCountUnknown`이면 "미상"으로 표시한다. 미상을 만실처럼 보이면 구급대원이 자리가 있을 수도 있는 병원을 스스로 뺀다.
- **AI와 규칙 구분**: AI 처리(통화 요약·자막·병상 신뢰도 확률)와 규칙 기반(병원 목록·순위·지도·존)을 칩과 범례로 나눠 보여준다.

## 폴더 구조

```
dashboard/
├── src/app/            화면(라우트): ambulance · phone · hospital · map · case · control · verify · api/demo
├── src/components/     ambulance · hospital · map · phone · panels(공용 상자) · verify · ui · layout
├── src/hooks/          use-dashboard-socket.ts(hub WebSocket 전부) · use-kakao-map-script.ts · use-elapsed-time.ts
├── src/lib/            mock-data · rejection(거절 사유 어휘) · distance · pcm-capture · control-map · monitor · route · geocode …
├── src/types/          dashboard.ts — hub 출력·입력 스키마의 TypeScript 대응
├── iphone/ · android/  온디바이스 통화 앱
└── public/             정적 파일(시연 영상 등)
```

## 알려진 제약사항

- WebSocket 인증이 없다. 접근 코드를 알면 누구나 그 화면에 들어간다(시연 범위).
- 브라우저 마이크는 https(도메인) 또는 localhost에서만 열린다.
- 통화 요약 확인·수정은 2026-10-13 hub와 함께 실서버(소켓 4개)와 헤드리스 화면 캡처로 확인했다. [수정] 편집 칸을 사람이 직접 눌러 보는 확인은 리뷰 때 한다.

## 관제 지도에서 시연 조작 (2026-11-01)

`/map` 상단의 **시연 조작**을 누르면 왼쪽 관제 목록 자리에 조작 패널이 열리고 지도는 계속 보인다.
**관제 목록으로**를 누르면 원래 목록으로 돌아간다. 패널을 접어도 입력·대량사고 대기열·시나리오 재생은 유지되며,
페이지를 새로고침하면 로컬 입력은 초기화된다. 지도 사건 선택과 패널의 구급대 선택은 서로 연동된다.
**고정 구급대 시연**은 역삼119안전센터 구급 1(SEL0111)에만 출동 사건을 부여한다. 강남역 흉통·역삼역 교통사고 두 상황을 하나씩 진행한다.

출동, 현장 확인(휴대폰 음성/개발 모드 가상 환자), 병원별·일괄 응답, 존 확장,
이송 중 상황·수용 철회, 도착 결과, 대량사고, 정지·재개·초기화·영상 모드는
`components/control/DemoConsole.tsx`를 기존 `/control`과 공유한다. 기존 콘솔 주소는 유지한다.
조작 패널은 별도 monitor 연결(`map-control`)로 기존 hub 메시지를 전송하며 백엔드 계약은 바꾸지 않았다.
조작을 한 번이라도 열면 지도 안에서만 도는 자동 가짜 사건은 해당 페이지를 새로고침할 때까지 중단한다.
좁은 화면(1100px 이하)에서는 조작 패널과 지도를 위아래로 배치한다.

검증: TypeScript, 변경 파일 ESLint, 분리한 WebSocket 테스트 연결에서 사건 선택·승인·거절 사유·정지/재개·이송 빨리감기·도착 처리·패널 재열기.
실제 hub의 기존 사건을 변경하지 않고 명령의 대상 사건을 검증했다. 지도 SDK가 검증 브라우저에서 로드되지 않아 지도 타일/마커의 실화면 최종 확인은 별도다.

이 변경 전의 커밋되지 않은 콘솔 수정까지 포함한 복구본과 안전한 복구 스크립트는
저장소 루트의 `.local-backups/goldenlink-before-map-console-20261101-040627/`에 보관한다.

### 고정 구급대 · 기기 접근 코드

- 구급대: **역삼119안전센터 구급 1 / SEL0111** (hub identity 등록 확인).
- 아이패드: 웹 첫 화면에서 **A-SEL0111** → `/ambulance?id=SEL0111`.
- 아이폰 네이티브 앱: 새 입장 화면에서 **P-SEL0111**. 서버에 등록된 구급대인지 확인한 뒤 고정 연결한다. 앱 업데이트 필요.
- 웹 전화 앱도 첫 화면에서 **P-SEL0111**로 접속할 수 있다.
- 기본 현장 확인·추가 통화는 전화. 개발 모드를 켜야 텍스트 상황 선택 탭이 보인다.
- 시연 상황: 강남역 흉통(62세 남성, 경색 의심), 역삼역 교통사고(35세 남성, 흉복부 외상).
- 발생 지점과 무관하게 SEL0111로만 출동한다. 등록 누락·연결 끊김·출동 시뮬레이션 꺼짐에는 부여 버튼이 잠긴다.
- 진행 중인 사건은 먼저 완료하거나 취소한 뒤 다음 상황을 부여한다. 한 구급대에 동시 두 사건을 만들지 않는다.
- 설정 파일: `src/lib/demo-unit.ts`. 기존 다중 구급대·대량사고 UI는 공통 콘솔 `singleUnit={false}`로만 사용한다.

브라우저 검증은 분리한 WebSocket 연결에서 고정 출동 대상·두 상황·전화/텍스트 모드 전환 및 아이패드 코드 라우팅을 확인했다.
이번 고정 구급대 변경 전 복구 지점은 `.local-backups/goldenlink-before-single-unit-20261101-042224/`이다.

현장 확인 대본은 최초 부여한 두 상황에 각각 하나씩 고정한다. 흉통은 심근경색 의심, 교통사고는 흉복부 다발성 외상 대본만 표시하며 개발 모드의 텍스트 전송도 같은 환자 정보를 쓴다. 현장 상황 재선택은 없고 새로고침 시 hub 신고/현장 좌표로 대본을 복원한다.
