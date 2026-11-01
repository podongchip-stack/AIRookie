---
name: run-demo
description: hub + dashboard만 가볍게 띄워 시연 상태(가짜 병원 3곳·구급차 1대·이송 확정 사건)를 만들고, 이송 중 모니터링(2.5단계) 시나리오까지 눈으로 확인한다. voice·info 없이 UI/hub 로직 확인용 — 풀 스택은 start-all.sh.
---

# 시연 기동 (hub + dashboard, voice·info 없이)

2026-10-04 Windows(PowerShell)에서 콜드 스타트로 검증한 절차다. voice(GPU)·info(E-Gen API)
없이 hub와 dashboard만으로 "통화 요약 → 동시 전달 → 승인 → 이송 확정 → 이송 중 모니터링"
전 구간을 재현한다. 가짜 voice 요약은 HTTP로 직접 쏜다.

## 0. 함정 먼저 — 이것 때문에 각각 한 번씩 실패했다

1. **포트 5001 이중 바인딩**: 이전 hub가 `127.0.0.1:5001`로 떠 있으면, 새 hub가
   `0.0.0.0:5001`로 **에러 없이 같이 떠서** localhost 요청을 이전(구버전) hub가 받는다.
   새 엔드포인트가 404면 십중팔구 이것이다. 기동 전 반드시 확인:
   ```powershell
   netstat -ano | Select-String ":5001.*LISTENING"   # 두 줄이면 PID 찾아 taskkill /PID <pid> /F
   ```
2. **IPv6 함정**: hub는 IPv4(0.0.0.0)만 바인딩한다. 파이썬 WS 클라이언트·env의 주소는
   `localhost`가 아니라 **`127.0.0.1`** 로 쓴다(localhost가 ::1로 풀리면 연결 거부).
3. **next dev는 .env.local을 시작 시점에 읽는다**: 파일을 만들거나 바꿨는데 이미 dev 서버가
   떠 있으면 재시작(단, Next 16은 변경을 감지해 자동 리로드하기도 한다 — 로그에
   `Reload env: .env.local`이 떴는지 확인). 이미 떠 있는 dev 서버가 있으면 새로 띄울 때
   "Another next dev server is already running" + PID를 알려주므로 그걸 kill.

## 1. hub 기동 (conda `rookie_info` 파이썬)

시연 승인·판정이 **실제 의사결정 로그(해시 체인)를 오염시키지 않도록** 경로를 분리한다.

```powershell
cd C:\Dev\AIRookie\hub
$env:HUB_DASHBOARD_CALL="1"        # 구급차 탭에 [통화 시작] 버튼 (기본은 휴대폰 앱 전용)
$demo="$env:TEMP\goldenlink-demo"  # 아무 임시 폴더
$env:HUB_STATE_PATH="$demo\hub_state.json"
$env:HUB_DECISION_LOG_PATH="$demo\hub_decisions.jsonl"
$env:HOSPITAL_REJECTION_LOG_DIR="$demo\rejections"
& C:\Users\user\anaconda3\envs\rookie_info\python.exe app.py
```

뜨면 `GET http://127.0.0.1:5001/identity?role=ambulance&id=A0000001`이 200으로 답한다.
(출동 시뮬레이션까지 원하면 `$env:HUB_SIM_DISPATCH="1"` — 단, 그 경우 통화는 현장 도착
뒤에만 열리므로 아래 시드 스크립트의 call_signal이 거부된다. 이 스킬의 시드는 sim 끈 상태 기준.)

## 2. dashboard 기동

`dashboard/.env.local` (gitignore됨 — 없으면 목데이터 모드로 뜬다):

```
NEXT_PUBLIC_DASHBOARD_WS_URL=ws://127.0.0.1:5001/ws/dashboard
NEXT_PUBLIC_HUB_HTTP_URL=http://127.0.0.1:5001
NEXT_PUBLIC_KAKAO_MAP_APP_KEY=<카카오 JS 키 — 없으면 지도 칸만 안내문, 나머지는 정상>
```

```powershell
cd C:\Dev\AIRookie\dashboard
npm run dev        # http://localhost:3000
```

## 3. 시연 데이터 주입 (이 폴더의 seed_demo.py)

가짜 병원 3곳(H001~H003)·구급 1호차 등록 → 통화 신호로 사건-구급차 바인딩 →
가짜 voice 요약(v1 6필드, 경색 의심·중증) → H002(권역센터) 승인 → 이송 확정까지 자동.

```powershell
& C:\Users\user\anaconda3\envs\rookie_info\python.exe C:\Dev\AIRookie\.Codex\skills\run-demo\seed_demo.py
# 마지막 줄 "이송 확정: OK"가 나와야 한다
```

> 병상 신뢰도("AI · 도착 시 유효 N%" 칩·첫 연락 추천)는 두 시드 모두 **데모용 가상값**으로
> 채운다(2026-10-04) — info의 reliability 엔진 없이 띄우는 환경이라 실모델 값이 없고, 빼면
> 첫 후보 리스트에 신뢰도 수치가 아예 안 뜬다. modelTag가 `demo-가상값`(또는
> `…+demo-reseed`)이면 가짜다. 병상 미상 병원에는 안 붙인다(숫자가 없는데 "숫자의 유효
> 확률"은 성립 안 함 — 올바른 동작).

## 3.5 시연 시나리오 콘솔 — 사건 생성부터는 전부 이걸로 (2026-10-04)

**http://localhost:3000/control** (첫 페이지 [시연 통제 콘솔] 버튼). **위저드형** —
한 화면에 한 단계만 보여주고, hub 상태를 따라 자동으로 다음 화면으로 넘어간다
(출동 중·매칭 중은 중간 화면): ① 환자 발생(프리셋 지점 4곳·주소 검색·무작위 → 출동) →
② 신고 접수(환자 상태 카드 3종 — 누르면 내부적으로 통화 신호 + 요약 전송, 통화 버튼 없음) →
③ 병원 응답(**미응답 전부 승인/전부 불가 일괄 버튼** + 병원별 승인/불가/이송 확정 —
전부 불가는 거절 비율 존 확장 연출용) → ④ 이송 중 상황 부여(활력징후 시나리오 5종 +
판정 피드백) → ⑤ 도착 결과(수용 완료 → 자동으로 ① 복귀 / 수용 불가 → 재선택). 헤더에
[시연 정지/상황 재개]·[상황 취소]. ①과 ⑤의 도착 게이팅은 출동 시뮬레이션
(HUB_SIM_DISPATCH=1) 기준이고, sim이 꺼져 있으면 ①을 건너뛰고 ②부터 돈다.
병상 0이 확인된 병원은 hub 규칙대로 처음부터 "수용 불가"로 떠 있다.

실무 재현 두 가지(2026-10-04 추가):
- **가까운 구급대 자동 선정** — 시드가 구급대 3곳(회현·성산·역삼)을 등록하고, ①에서
  발생 지점을 고르면 기지가 가장 가까운 **대기 중** 구급차가 자동 선정된다(전부 바쁘면
  가장 가까운 순). 선정 주체는 콘솔(상황실 역할)이고 hub는 apid를 그대로 받는다.
- **예비 고지(pre_alert)** — 출동 순간 hub가 현장 존 안 후보 병원 전체에 "인근 사고
  발생 — 수용 요청 가능" **선 경고 모달**을 보낸다(병원엔 거리만, 현장 좌표는 안 보냄).
  실제 요청이 도착하면 모달 데이터는 자동으로 지워진다. 콘솔 출동 중 화면에 발송
  병원 수가 표시된다. 출동 시뮬레이션 모드 전용 — 실운영에선 119 신고 접수 이벤트 자리.
즉 **레지스트리 주입(위 seed 스크립트)만 돌려 두면 사건 생성부터는 콘솔 버튼만으로
풀 사이클이 돈다**(발생→신고→승인→확정→상황 부여→수용 완료→사건 종료, 실측 검증됨).
seed_demo.py는 "한 방에 확정 상태 만들기"용 지름길로 남는다. 가짜 환자 전송만 Next
서버 프록시(`/api/demo/voice` → hub `/voice/summary`)를 거친다(CORS).

시연 화면 구성(2026-10-04 추가):
- **구급대 대시보드 자동 전환**: `/ambulance?id=auto` — 특정 구급대에 고정하지 않고,
  상황이 발생해 어떤 구급대든 출동하면 그 구급대 화면으로 자동 로그인된다(시연용).
- **관제 지도 등급 색**: 병원 마커가 권역센터(자홍·중증)/지역센터(청록·중등증)/
  기관(남색·경증)으로 구분된다 — 분산 원칙("중증은 센터로, 경증은 기관으로")의 시각화.
- **사건 클릭 → 사건 전용 화면**: 관제 왼쪽 사건 카드를 클릭하면 지도가 그 사건 중심으로
  당겨지고, 왼쪽이 사건 상세(중증도·구급차 단계·존·병원 전체 상태·응답 기록)로 바뀐다.
  [← 전체 사건 보기]로 복귀. 사건이 끝나면 자동 복귀.

## 4. 화면 확인

- **구급차**: http://localhost:3000/ambulance?id=A0000001 — 이송 확정 상태라
  "이송 중 모니터링" 패널이 보인다. 시나리오 ▶ 버튼을 누르면 4초 간격으로 측정이 흘러가고
  기록→보류→전달 판정이 실시간 표시된다(같은 시나리오 = 항상 같은 결과).
- **병원**: http://localhost:3000/hospital?id=H002 — 시나리오 ②~④ 재생 중 카드 위에
  "🚑 이송 중 상태 변화" 배너(notify 이상만 옴).
- UI 없이 입력 구멍을 직접 치려면:
  ```powershell
  # record→hold→notify 전이 (시나리오 ②의 2·3걸음 수치)
  Invoke-RestMethod -Method Post -Uri http://127.0.0.1:5001/vitals -ContentType "application/json" -Body '{"caseId":"case-demo-transport","apid":"A0000001","demo":true,"scenario":"shock","observation":{"rr":20,"spo2":96,"sbp":100,"hr":115,"avpu":"A","measuredAt":"2026-01-01T00:00:00Z","source":"demo"}}'
  ```

## 5. 정리

- hub·dashboard는 포그라운드 프로세스 — Ctrl+C. 시연 상태는 전부 임시 폴더(1번)에만 남는다.
- 시드를 다시 돌리면 같은 caseId(`case-demo-transport`)로 사건이 재생성된다. hub를
  재시작하면 상태 파일(임시 경로)에서 복구되므로, 완전 초기화는 임시 폴더를 지우고 재시작.
- 스크린샷 자동화가 필요하면: `npx playwright screenshot --viewport-size="1600,1000" --full-page --wait-for-timeout=9000 "<URL>" out.png`
  (최초 1회 `npx playwright install chromium`. 판정 메시지는 따라잡기가 없어서, 페이지가
  열린 **뒤에** /vitals를 쏴야 화면에 잡힌다 — 브라우저 기동 몇 초를 감안해 10초쯤 늦출 것.)
