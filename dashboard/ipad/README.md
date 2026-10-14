# 골든링크 아이패드 구급차 앱 (거미줄 3D · 정보 생존 모델)

**구급차에 싣는 대시보드**(2026-10-14). 웹 구급차 대시보드(`/ambulance`)와 같은 디자인(밝은 회색 바탕 · 흰 카드 · 상단바 ·
범례 · 병원 후보 가로 카드)이고, 지도 자리에는 spider 서버의 거미줄 3D를 WebView로 띄운다. 온디바이스 모델이 없어 아이폰 앱
(../iphone)보다 훨씬 가볍다 — 외부 패키지 0개, Xcode만 있으면 된다.

| 영역 | 내용 | 출처 |
|---|---|---|
| 상단바 | 골든링크 v2.0 · 구급대 이름 · 이송 상태(출동 대기 / 병원 선택 대기 / 이송 확정 · 병원) · 연결 · 수신 후 경과 · [정보 생존 모델] · 새로고침 · 설정 | hub `identity_info`·매칭 결과 |
| 왼쪽 — 현장 상태 | 출동 단계(대기·출동 중·현장·이송 중·병원 도착·재선택·복귀), 발생 위치 좌표, 확정 병원·도착까지 | hub `ambulance_phase/position` |
| 왼쪽 — 통화 요약 | (사고가 나면) 예상 병명·증상·중증도·KTAS·환자·의식·발생 시점·필요 진료과·활력징후, AI 요약/구급대원 확인, N차 통화, 통화 현황·실시간 자막 | hub `match_result.patientInfo`·`call_status`·`call_transcript` |
| 오른쪽 — 거미줄 3D | 이 구급차의 사건만: 환자 점, 존 안 병원으로 가는 줄(대기/승인/불가/확정), 이송 경로·구급차, 도착 고리, 거미줄 모델 제안(민트). 카메라가 출동 → 현장, 이송 → 현장~병원을 따라간다(손대면 멈춤) | spider `/spider/?mode=live&embed=1&apid=` |
| 아래 — 병원 후보 리스트 | **사고가 발생했을 때만 아래에서 올라온다.** 통화 전: 현장 후보(도착 시간순·첫 연락 추천). 통화 후: hub 순위 그대로 카드 — 상태(판단 대기/후보 등록/수용 불가·사유/이송 확정, 추천), 병상·AI 유효(도착 시)·전문의, 진료과 적합도·센터·수용 불가 신고·차단·이송 중·심평원 신뢰도·신고 신선도 칩, **정보 유효 지금 → 도착 시 막대와 이유 한 줄**(정보 나이·도착까지·병원 확인·1일 넘은 값·배후진료), [이송 승인]. 카드를 누르면 "왜 이 확률인가" 상세 | hub `match_result.hospitals[]`, `scene_candidates` |
| [정보 생존 모델] | 전체 화면 — 지금 이 환자의 후보 병원별 확률(초 단위 감쇠) + 라이브 채점 보드(그냥 믿을 때 vs 엔진 선별 vs 경고 값 유지율, 3석 이상 어긋남, 공통 충격, 시계열·예측 vs 실제·지역별·판명 피드) | hub `GET /verification/live` |

정보 유효 %는 hub가 보낸 생존곡선 파라미터(predictedSurvivalSec·bornAt·σ)로 앱이 초 단위로 감쇠시킨다 — `BedReliability.swift`,
웹 `lib/bedReliability.ts`·hub `bed_reliability.py`와 같은 식. 순위에는 쓰지 않는 설명용 확률(팀 원칙 그대로).
조작은 **[이송 승인] 하나**(구급대원 판단, 병원이 "후보 등록"한 병원에만 열림 — 웹 handleApprove와 같은 final_approval).
출동·현장 종료는 웹 구급차 대시보드·시연 콘솔에서 한다.

## 빌드 (맥 + Xcode, 아이패드 유선 연결)

```bash
brew install xcodegen            # 처음 한 번
./dashboard/ipad/setup.sh        # GoldenLinkPad.xcodeproj 생성(생성물이라 커밋 안 함). 서명 팀은 유지된다
open dashboard/ipad/GoldenLinkPad.xcodeproj
```

Xcode에서:
1. TARGETS `GoldenLinkPad` → **Signing & Capabilities** → Team(처음 한 번. 이후 `setup.sh`를 다시 돌려도 유지 — 지금 프로젝트나
   옆 아이폰 프로젝트의 팀을 읽어 다시 넣는다). Bundle Identifier가 겹치면 `com.goldenlink.pad` 뒤에 글자를 붙인다.
2. 상단 기기 선택에서 연결한 아이패드 → ▶ 실행.
3. "Update to recommended settings" 경고는 Perform Changes를 눌러도, 무시해도 된다(동작 영향 없음).
4. 명령줄 확인: `xcodebuild -project dashboard/ipad/GoldenLinkPad.xcodeproj -scheme GoldenLinkPad -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build`

요구: iPadOS 17 이상. 가로 전용.

## 아이패드에서 설정할 것

앱 오른쪽 위 ⚙︎ [설정]:
- **이 아이패드의 구급차** — `auto`(기본: 어떤 구급대든 출동하면 그 화면으로 자동 전환, 시연용) 또는 실제 차량 ID(`SEL0001`~).
- **hub 주소** — 기본 `https://app.rookie-goldenlink.xyz`(공개 모드, `./start-all.sh`). 같은 Wi-Fi 로컬이면 [빠른 설정 > 로컬 LAN]에
  맥 IP → `http://<맥 IP>:5001`(`./start-all.sh --local`).
- **spider 주소** — 비우면 자동(공개 도메인이면 같은 호스트, 로컬이면 `:2700`).
- [hub·spider·구급차 확인] → 모두 ✅ 면 [적용].

iOS 설정: 개발자 모드(첫 설치), VPN 및 기기 관리 > 개발자 앱 신뢰, 로컬 모드면 "로컬 네트워크" 허용, 자동 잠금 > 안 함.

## 지도 터치

두 손가락 확대·축소가 튀던 문제(한 번 벌리면 너무 많이 확대/축소)는 ① WKWebView의 페이지 확대와 지도(deck.gl) 확대가 동시에 걸리고
② deck.gl 관성이 손을 뗀 뒤에도 확대를 이어 가서였다. 앱은 웹뷰의 페이지 확대·스크롤을 끄고(`SpiderWebView.swift`), spider 페이지는
`user-scalable=no`·Safari gesture 이벤트 차단·터치 기기 관성 끔·확대 범위 5~16.5로 묶었다(`spider/web/app.js`). 한 손가락 끌기 =
이동, 두 손가락 = 확대·회전·기울이기.

## 문제 해결

- 지도 왼쪽 아래에 빨간 "JS 오류" 상자가 뜨면 그 문구를 그대로 알려 주세요(앱 WebView에선 개발자 도구가 없어 화면에 띄운다).
- 지도가 비면: 설정에서 spider 주소·연결 확인 → 새로고침. spider는 `start-all.sh`가 띄운다(`spider.log`).
- 정보 생존 모델이 비면: info의 거절 로그 수신구(5003)가 떠 있어야 한다. 첫 생성은 수십 초.

## 파일

| 파일 | 역할 |
|---|---|
| `project.yml` / `setup.sh` | XcodeGen 정의 · 프로젝트 생성(서명 팀 유지) |
| `GoldenLinkPad/GoldenLinkPadApp.swift` | 진입점 |
| `Settings.swift` | 구급차 ID·hub·spider 주소, 파생 URL |
| `HubMessages.swift` | 구급차 소켓 메시지 Codable(매칭 결과·현장 후보·통화·이동) · 표시 문구 |
| `HubSocket.swift` | WebSocket(identify, 재연결) — 아이폰 앱과 같은 규칙 |
| `AppModel.swift` | 상태 — 구급차 소켓 + auto면 감시 소켓으로 출동 구급대 따라가기, 이송 승인 전송 |
| `BedReliability.swift` | 생존곡선 감쇠 S(age) = 1 − Φ((ln age − ln m)/σ), 조건부 S(a)/S(u) |
| `LiveBoard.swift` | `/verification/live` JSON |
| `Theme.swift` | 웹 AD 팔레트·카드·알약·StatBox |
| `RootView.swift` | 상단바·범례·배치(병원 리스트는 사고 때만) · 지도 카드 |
| `AmbulanceViews.swift` | 현장 상태·통화 요약 카드 |
| `HospitalViews.swift` | 병원 후보 리스트(현장 후보·매칭 카드)·상세 시트 |
| `SurvivalModelView.swift` | 정보 생존 모델 전체 화면(Charts) |
| `SpiderWebView.swift` | WKWebView(spider) — 페이지 확대 끔, 새로고침·오류 화면 |
| `SettingsView.swift` | 설정·연결 확인 |
