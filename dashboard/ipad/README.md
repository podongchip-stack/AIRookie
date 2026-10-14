# 골든링크 관제 아이패드 앱 (거미줄 3D · 정보 생존 모델)

hub WebSocket에 관제 지도와 같은 역할(`role: "monitor"`)로 붙어 **실제 사건**을 보여 주는 보기 전용 앱(2026-10-14).
가운데는 spider 서버의 거미줄 3D(`/spider/?mode=live&embed=1`)를 WebView로 띄우고, 양옆은 네이티브(SwiftUI)다.
온디바이스 모델이 없어 아이폰 앱(../iphone)보다 훨씬 가볍다 — 외부 패키지 0개, Xcode만 있으면 된다.

| 화면 | 내용 | 출처 |
|---|---|---|
| 왼쪽 — 사건·환자 | 진행 중 사건 목록 → 선택 사건의 **환자 정보**(KTAS·예상 병명·주 호소·필요 진료과·나이/성별·구급대원 확인 여부)·**발생 위치**(좌표 + MapKit 미니 지도: 현장·후보 병원 응답 색·구급차·이송 경로)·진행 과정 | hub `case_meta`·`case_overview`·`ambulance_*` |
| 가운데 — 거미줄 3D | spider 실시간 모드: 환자 점, 존 안 병원으로 가는 줄(대기/승인/불가/확정 색), 이송 경로와 구급차, 도착 고리, 거미줄 모델 제안(민트) | spider 서버(WebView) |
| 오른쪽 — 병원 수용 여부·정보 유효성 | hub 순위 그대로 병원마다 **수용 상태**(판단 대기/승인/불가(사유)/확정), 응급실 가용/정원·포화·이동시간·순위 점수, **정보 유효 % (지금 · 도착 시)** + 1일 넘은 값·중증 신고 신선도·심평원 대조 신뢰도·내림 이유 칩. 탭하면 **왜 그런가** 상세(정보 나이·모델 예측 수명·도착까지·병원 확인·신고·심평원 근거·순위 근거·E-Gen 공지) | hub `case_overview.hospitals[]` 설명 필드(2026-10-14) |
| 탭 [정보 생존 모델] | 라이브 채점 보드 — 그냥 믿을 때 vs 엔진 선별 vs 경고 값 유지율, 3석 이상 어긋남, 공통 충격 감지, 시계열 그래프(Swift Charts), 예측 vs 실제, 지역별, 판명 피드 + **지금 사건 병원별 확률**(초 단위 감쇠) | hub `GET /verification/live`(info 수신구 5003 중계) |

정보 유효 %는 hub가 보낸 생존곡선 파라미터(predictedSurvivalSec·bornAt·σ)로 앱이 초 단위로 감쇠시킨다 — `BedReliability.swift`,
dashboard `lib/bedReliability.ts`·hub `bed_reliability.py`와 같은 식. 순위에는 쓰지 않는 설명용 확률(팀 원칙 그대로).

## 빌드 (맥 + Xcode, 아이패드 유선 연결)

```bash
brew install xcodegen            # 처음 한 번
./dashboard/ipad/setup.sh        # GoldenLinkPad.xcodeproj 생성(생성물이라 커밋 안 함)
open dashboard/ipad/GoldenLinkPad.xcodeproj
```

Xcode에서:
1. 왼쪽 프로젝트 → TARGETS `GoldenLinkPad` → **Signing & Capabilities** → Team에 내 Apple ID 선택. Bundle Identifier가 겹치면
   `com.goldenlink.pad` 뒤에 아무 글자나 붙인다(무료 개인 계정도 됨).
2. 상단 기기 선택에서 연결한 아이패드 고르기(처음이면 아이패드에서 "이 컴퓨터를 신뢰" → 개발자 모드 켜기: 설정 > 개인정보 보호 및 보안 > 개발자 모드 → 재시동).
3. ▶ 실행. 처음 설치 뒤 아이패드 설정 > 일반 > VPN 및 기기 관리에서 내 Apple ID 개발자 앱 **신뢰**를 눌러야 열린다.
4. 명령줄로만 확인하려면: `xcodebuild -project dashboard/ipad/GoldenLinkPad.xcodeproj -scheme GoldenLinkPad -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build`

요구: iPadOS 17 이상. 가로 전용(폭 1,000pt 미만의 창이면 위 거미줄 · 아래 2단으로 바뀐다).

## 아이패드에서 설정할 것

앱 오른쪽 위 [설정]:
- **hub 주소** — 기본 `https://app.rookie-goldenlink.xyz`(공개 모드, `./start-all.sh`). 같은 Wi-Fi 로컬 시연이면
  `http://<맥 IP>:5001`(`./start-all.sh --local`). [빠른 설정]의 두 버튼이 이 둘을 채운다.
- **spider 주소** — 비워 두면 자동: 공개 도메인이면 hub와 같은 호스트(터널이 `/spider/`를 spider로 보냄), 로컬 `…:5001`이면
  같은 IP의 `:2700`.
- [hub·spider 연결 확인] → 둘 다 ✅ 이면 [적용]. 소켓을 다시 붙이고 WebView를 다시 연다.
- 마지막 탭·주소는 기기에 저장된다(UserDefaults).

아이패드 쪽 iOS 설정:
- 설정 > 개발자 모드 켜기(첫 설치 때), 설정 > 일반 > VPN 및 기기 관리 > 개발자 앱 신뢰.
- 로컬 모드: 앱 첫 실행 때 "로컬 네트워크" 접근 허용 팝업 → 허용(설정 > 개인정보 보호 > 로컬 네트워크에서 다시 켤 수 있음).
- 화면 자동 잠금 끄기(설정 > 디스플레이 및 밝기 > 자동 잠금 > 안 함) — 시연 중 꺼지지 않게.
- 가로로 들기(세로로 들면 가로 화면이 회전돼 보인다). 홈 화면 회전 잠금이 켜져 있어도 앱은 가로로 뜬다.

## 서버 쪽 준비

- `./start-all.sh`: hub·info(거절 로그 수신구 5003 — 정보 생존 모델 보드)·spider(2700)·dashboard·터널이 다 뜬다.
  정보 생존 모델 탭의 첫 생성은 수십 초(48시간 × 416곳 재생) 걸리고 이후 20분 캐시. 수신구가 안 떠 있으면 탭에 안내가 뜬다.
- 사건은 평소대로 만든다: 구급차 대시보드 [이동] → 현장 도착 → 휴대폰 전화 앱 통화 → 병원 대시보드 승인/불가 → 이송 승인.
  이 앱은 그 과정을 받아 그릴 뿐 아무것도 보내지 않는다.

## 파일

| 파일 | 역할 |
|---|---|
| `project.yml` / `setup.sh` | XcodeGen 정의 · 프로젝트 생성 |
| `GoldenLinkPad/GoldenLinkPadApp.swift` | 진입점 |
| `Settings.swift` | hub·spider 주소, 파생 URL(ws·spider·verification/live) |
| `HubMessages.swift` | hub 메시지 Codable(관제 스키마 + 설명 필드) · 표시 문구 |
| `HubSocket.swift` | WebSocket(identify monitor, 재연결) — 아이폰 앱과 같은 규칙 |
| `AppModel.swift` | 상태(사건·구급차·병원 좌표·라이브 보드·1초 시계) |
| `BedReliability.swift` | 생존곡선 감쇠 S(age) = 1 − Φ((ln age − ln m)/σ), 조건부 S(a)/S(u) |
| `LiveBoard.swift` | `/verification/live` JSON |
| `RootView.swift` | 상단바·탭·3단/2단 배치 |
| `CaseViews.swift` | 사건 목록·환자 카드·미니 지도·진행 과정 |
| `HospitalViews.swift` | 병원 목록(수용 상태·유효성)·상세 시트("왜 이 확률인가") |
| `SurvivalModelView.swift` | 정보 생존 모델 전체 화면(Charts) |
| `SpiderWebView.swift` | WKWebView(spider), 새로고침·오류 화면 |
| `SettingsView.swift` | 설정·연결 확인 |

## 한계·다음

- 보기 전용. 승인·이송 승인은 넣지 않았다(병원·구급차 대시보드의 역할).
- 거미줄 3D는 서버 페이지라 네트워크가 끊기면 가운데만 비고 양옆은 마지막 값으로 남는다(재연결은 자동).
- spider가 hub 데이터로 직접 계산하게 바뀌면(엔진 hub 이관) WebView 주소만 그대로 두면 된다.
