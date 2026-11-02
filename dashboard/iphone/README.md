# 골든링크 아이폰 앱 (온디바이스 STT·MF_BERT)

웹 전화 앱(`/phone`)과 같은 흐름(출동 → 현장 도착 → 병원 목록 → 병원 골라 통화 → 종료 → 후보 병원 전체 전달)을
네이티브 앱으로 옮겼다. 음성 인식(Qwen3-ASR)과 구조화(MF_BERT)를 **아이폰 안에서** 돌리고, hub에는 지금 voice가
보내는 것과 **같은 통화 요약 JSON**만 보낸다. 모델은 양자화·fp16 변환 없이 원본
정밀도(ASR bf16, MF_BERT fp32)로 쓴다. 대상: iPhone 15 Pro(iOS 18+), 개발 맥 + Xcode.

**2026-10-05 통화 흐름 변경**: 통화는 **[취소]**와 **[전송]**으로 끝난다. 통화 중 인식 결과는 이 화면 자막에만 쓰고 기기 밖으로
보내지 않으며, **[전송]을 눌러야** 남은 인식·구조화를 마쳐 요약을 보낸다([취소]는 아무것도 보내지 않음). 요약은 hub
WebSocket(`type: "voice_summary"`)으로 보내서 **공개 도메인에서도 된다**(예전 `/voice/summary` HTTP는 터널이 막아 404였다).
현장 첫 통화 뒤에도 환자 상태가 바뀌면 **추가 통화**(현장: 다른 병원 / 이송 중: 목적지 병원)를 할 수 있고, 새 요약은 hub가
환자 정보에 덧붙인다. 시연 일시정지 중엔 통화를 시작·전송하지 않고 "현재 시연 일시정지 중입니다." 안내를 띄운다.
통화 전송 후에는 인식·구조화 처리 상태를 보여주고, 이번 통화의 새 요약이 hub에 반영되면 확인 버튼 없이
환자 정보 탭으로 자동 전환한다(첫 통화·추가 통화 모두). 병원 응답·주기 갱신만으로 전환하지 않도록 통화 회차를 대조한다.
인식 실패·무음·시간 초과 시에는 성공으로 넘기지 않고 `다시 통화하기`를 표시한다.

앱은 hub에 "구급차 탭(role=ambulance)"으로 붙고, voice 역할을 겸한다(hub는 이 연결로 온 `voice_summary`를 `/voice/summary`와 같게 처리한다).

## 2026-11-01 지도·환자 정보·처치 연동

- 현장 확인에서 Pre-KTAS 또는 통화할 병원을 선택하면 내 구급차와 선택 병원이 함께 보이도록 한 번 배율을 맞춘다. 탭을 다시 열거나 위치만 갱신되는 경우에는 수동 배율을 유지한다.
- 통화 지도 오른쪽 위 **내 위치**는 현재 배율을 유지하며 내 구급차를 중앙으로 옮긴다. 지도 중심·배율은 탭 전환 후에도 유지한다.
- 출동이 시작되면 통화 지도로 전환하고 구급대 센터·사고 현장·도로 전체를 한 번 자동 배율한다. 센터 좌표는 hub의 `base`를 사용하므로 구급차가 이동해도 출발지가 유지된다.
- 이송 승인 후 hub가 **이송 중** 단계를 보내면 통화 탭으로 자동 전환한다. 사고 현장·목적지 병원·도로 경로 전체에 여백을 둬 한 번 자동 확대/축소하고, 이후 수동 배율은 유지한다. 목적지를 다시 선택해 이송을 시작할 때도 다시 맞춘다.
- 전달 후 실제 매칭 후보 병원을 노드로 표시하고, 구급차에서 각 병원으로 점이 이동한다. 회차별 한 번 재생하며 동작 줄이기 설정에서는 생략한다.
- 출동·병원 이송·기지 복귀 경로는 hub의 `ambulance_phase.path`(카카오 도로 좌표)를 사용한다. `ambulance_position`이 path를 생략해도 이전 경로를 유지한다. 이동 위치도 hub가 같은 경로로 계산한다.
- 상황 종료 후 복귀는 기지 핀·도로 경로·기지까지 ETA를 표시하고 전체 경로에 배율을 맞춘다. 구급차는 hub의 ETA/배속으로 남은 도로 경로를 연속 재생한다. 탭 재진입 때 지나온 구간을 다시 재생하지 않는다. 자동 추적 모드도 복귀 중인 구급대를 계속 따라간다.
- 기지 복귀 시연 시간은 기본 30초(`HUB_SIM_RETURN_SEC`). 현장 종료와 환자 수용 완료 모두 같은 복귀 경로를 사용하며, 도착한 뒤에 대기 상태로 바뀐다.
  도로 경로를 받으려면 hub의 `KAKAO_REST_API_KEY` 설정과 API 연결이 필요하다. hub가 직선 대체 경로만 보내면 지도에 도로 안내 불가를 표시한다.
- 통화 요약 하단의 **확인 / 수정** 버튼을 같은 폭으로 배치했다. 수정 시트 내부 스크롤은 껐으며 기본 시트의 아래로 밀어 닫기는 유지한다.
- 추가 정보 초안은 사건별 앱 상태에 보관하므로 탭 전환으로 지워지지 않는다(앱 종료 후 복원은 아님). 입력창 밖을 누르면 키보드가 닫힌다.
- 인계확인서 수정 화면 상단 버튼에 여백을 추가했다. 처치 내용은 기도·호흡·순환·약물·고정·기타 칸으로 자동 분류하며 거부·실패 같은 원문 표시도 보존한다.
- 이송 탭 목록은 병원이 수용 승인한 곳과 이송 확정 병원만 보여 준다. 승인 전에는 응답 대기 안내를 표시한다.

최신 서버 voice(2026-10-29 처치판)의 `patients[].treat_categories` 28범주는 hub `voice_treatments.py`가 기존 `patientInfo.treatment`로 변환한다.
환자 상태도 같이 변환하며, 여러 환자의 처치가 한 인계확인서에 섞이지 않도록 현재 단일 환자 사건에서는 다중 환자 입력을 거절한다.
**iPhone 번들 안의 기존 Core ML 모델은 교체하지 않았다.** 온디바이스 모델의 기존 v2 `treatments[]`도 계속 자동 입력된다.
새 처치판의 추출 결과를 사용하려면 해당 버전 서버 voice를 실행하고 앱 설정에서 서버 음성 인식 모드를 사용해야 한다.
hub 변경은 서버 재시작 후 적용된다.

검증: Swift 코어 테스트(기존 Python 대조 포함), hub 새 처치 형식·환자 정보 전달 테스트 및 기존 환자 수정/출동 흐름 검사,
Xcode `generic/platform=iOS`, `CODE_SIGNING_ALLOWED=NO` 빌드. 화면 제스처·지도 애니메이션·마이크 동작은 실제 iPhone에서 최종 확인한다.

## 서버 기록 동기화

기록 탭은 hub의 영구 보관소와 변경 순번으로 동기화한다. 새 설치에서도 같은 구급차의 과거 사건을 내려받고,
기존 기기에만 있던 기록은 최초 연결 때 서버로 이관한다. 승인→거절처럼 응답이 바뀐 과정은 사건의 ‘더보기 · 전체 병원 응답 이력’에서 확인한다.
연결이 끊겨도 받은 기록은 기기에서 조회할 수 있다. 인계확인서 수정은 재연결 때 재전송하며 충돌 시 기록 탭에서 선택한다.

최초 한 번 운영자가 `python hub/record_archive.py grant SEL0001`로 키를 발급하고, 앱 설정에 **고정 구급차 ID와 기록 동기화 키**를 넣는다.
새 기기마다 같은 구급차 ID에 대한 별도 키를 발급할 수 있다. 서버 저장소·키 폐기·초기 이관 범위는 [기록 동기화 가이드](../../hub/RECORD_SYNC.md)를 참고한다.
hub 재시작 및 최신 iPhone 앱 설치 후 적용된다. 기록 탭 상단에 동기화 상태를 표시한다.

## 폴더

| 경로 | 내용 |
|---|---|
| `GoldenLinkPhone/` | 앱 소스(SwiftUI). 화면·hub 연결·마이크·통화 처리·모델 실행 |
| `GoldenLinkCore/` | 모델·화면과 무관한 순수 로직 Swift 패키지 — WordPiece 토크나이저, 512토큰 조각 나누기, decode(v2 17필드), parse(활력징후·나이·발생 시점 규칙), 무음 감지 발화 자르기, hub 메시지, 통화 요약 JSON. **맥에서 `swift test`로 Python 원본과 대조된다** |
| `convert/` | 맥 Python 스크립트 — 모델 변환(Core ML·MLX), 대조, 정답 픽스처 생성 |
| `patches/speech-swift-float-decoder.patch` | speech-swift(Qwen3-ASR MLX Swift 포팅)는 디코더가 4/8비트 양자화로 고정돼 있다 → bf16 그대로 쓰도록 바꾸는 패치 |
| `project.yml` | Xcode 프로젝트 정의(XcodeGen). `.xcodeproj`는 이걸로 만든다(커밋 안 함) |
| `setup.sh` | speech-swift 받기 + 패치 + `.xcodeproj` 생성 |
| `Models/`, `Vendor/` | 변환한 모델·받은 패키지(커밋 안 함, `.gitignore`) |

### 코드 대응표

| Swift | 원본(Python/TS) |
|---|---|
| `GoldenLinkCore/WordPieceTokenizer.swift` | KLUE 토크나이저(`tokenizer.json`) — 오프셋까지 |
| `GoldenLinkCore/Chunking.swift` | `voice/MF_BERT/chunking.py` |
| `GoldenLinkCore/Decode.swift`, `Parse.swift`, `Resources/labels.json` | `decode.py`, `parse.py`, `labels.py`(스크립트로 뽑음) |
| `GoldenLinkCore/UtteranceSegmenter.swift` | `voice/live_transcriber.py`, `asr.py`의 `split_chunks` |
| `GoldenLinkCore/CallSummary.swift` | `voice/transcribe.py` `build_call_summary_message` |
| `GoldenLinkCore/HubMessages.swift` | `hub/schema.py`, `dashboard/src/types/dashboard.ts` |
| `GoldenLinkPhone/HubSocket.swift` | `use-dashboard-socket.ts`(재연결·identify), `voice/app.py`의 hub 전송 |
| `GoldenLinkPhone/PhoneModel.swift`, `Views.swift` | `app/phone/page.tsx`(자동 전환), `PhoneCallView.tsx` |
| `GoldenLinkPhone/CallSession.swift` | `voice/app.py` + `live_transcriber.py`(통화 중 발화 인식 → 종료 후 구조화·전송, 원본 보존) |
| `GoldenLinkPhone/MicCapture.swift` | `lib/pcm-capture.ts`(16kHz 모노) |
| `GoldenLinkPhone/MFBertRunner.swift` | `voice/MF_BERT/__init__.py` (Core ML 두 모델) |
| `GoldenLinkPhone/OnDeviceASR.swift` | `voice/asr.py` (speech-swift) |

---

## 빌드 순서 요약

```bash
# 저장소 루트에서
conda create -n goldenlink-ios --clone rookie_voice -y && conda activate goldenlink-ios && pip install coremltools   # 1
python dashboard/iphone/convert/convert_mf_bert.py && python dashboard/iphone/convert/check_mf_bert.py           # 2-1
python dashboard/iphone/convert/merge_qwen3_asr.py <통화 wav 몇 개>                                                 # 2-2
brew install xcodegen && ./dashboard/iphone/setup.sh                                                                # 4
open dashboard/iphone/GoldenLinkPhone.xcodeproj                                                                     # 5 (서명 팀 고르고 ▶)
```

모델 없이도 빌드된다(2번을 건너뛰면 앱이 "서버 STT 모드"로 웹 전화 앱처럼 동작). 화면·hub 흐름(P2)을 먼저
확인하고 모델을 넣는 순서를 권한다.

---

## 1. 맥 Python 환경

voice 환경(`rookie_voice`: torch 2.11, transformers 5.17, peft)을 복제해 `coremltools`만 더한다. voice 환경을
직접 건드리지 않으려고 복제한다.

```bash
conda create -n goldenlink-ios --clone rookie_voice -y
conda activate goldenlink-ios
pip install coremltools
```

## 2. 모델 변환 (맥, 한 번만)

출력은 전부 `dashboard/iphone/Models/`로 간다. 가중치는 voice와 같은 Hugging Face 저장소·커밋에서 받는다
(`voice/weights.py` — MF_BERT `podongchip/MF_BERT@f1d3e1d…`, ASR 어댑터 `Playedwell03/qwen3-asr-0.6b-119ko-tiny`).

### 2-1. MF_BERT → Core ML (fp32)

```bash
python dashboard/iphone/convert/convert_mf_bert.py   # MFBertEncoder.mlpackage, MFBertHeads.mlpackage, tokenizer.json
python dashboard/iphone/convert/check_mf_bert.py     # PyTorch와 summary 완전 일치 확인 (P0 통과 기준)
python dashboard/iphone/convert/check_mf_bert.py voice/data/어딘가/*.txt   # 실제 통화 텍스트로도
```

- 두 모델로 나눈 이유: 긴 통화는 512토큰 조각마다 인코더를 돌린 뒤 이어 붙이는데, 이 이어 붙이기가 통화 길이에
  따라 가변이라 앱(Swift)이 맡는다. 나눈 실행이 원본 forward와 같은지는 `python dashboard/iphone/convert/mf_bert_split.py`
  (가중치 불필요, 무작위 가중치)로 확인된다 — 확인함: 조각 1개 오차 0, 조각 여러 개 3e-5(원본의 패딩 배치 차이).
- `compute_precision=FLOAT32`라 정밀도가 그대로다. 앱은 CPU+GPU로 돈다(Neural Engine은 fp32 미지원).

### 2-2. Qwen3-ASR → 합친 bf16 (MLX)

```bash
python dashboard/iphone/convert/merge_qwen3_asr.py                 # 합치기만
python dashboard/iphone/convert/merge_qwen3_asr.py a.wav b.wav     # + 합치기 전후 같은 문장인지, 정답(asr_reference.json) 저장
```

- LoRA를 베이스에 합치고, 키 이름을 speech-swift가 읽는 형식으로 바꿔 `Models/Qwen3ASR-119ko-bf16/`에 저장한다
  (bf16 그대로, 약 1.6GB). 이 폴더가 앱 번들에 폴더째 들어간다.
- 정답은 맥 CPU bf16으로 낸다. 학습·검증 기준은 CUDA bf16이라, 서버(CUDA) 결과와 최종 대조는 P5에서 한다.

## 3. 코어 로직 검사 (선택, 수 초)

```bash
python dashboard/iphone/convert/make_fixtures.py     # Python 원본으로 정답 생성(이미 커밋돼 있음)
cd dashboard/iphone/GoldenLinkCore && swift test
```

토크나이저(오프셋 포함)·조각 나누기·decode(무작위 로짓 60건)·parse·발화 자르기가 Python과 같은지 본다.
`voice/MF_BERT/`가 바뀌면(재학습·규칙 수정) `export_labels.py`와 `make_fixtures.py`를 다시 돌리고 테스트한다.

## 4. Xcode 프로젝트 만들기

```bash
brew install xcodegen
xcodebuild -downloadComponent MetalToolchain   # 약 840MB, 한 번만 — 없으면 MLX 셰이더 컴파일에서 빌드 실패
./dashboard/iphone/setup.sh
```

speech-swift를 `Vendor/`에 받아(커밋 `1f54e56` 고정) 패치를 적용하고 `GoldenLinkPhone.xcodeproj`를 만든다.
`project.yml`을 고쳤으면 `cd dashboard/iphone && xcodegen generate`를 다시 돌린다. `Models/`는 폴더째 번들에 들어가므로
모델을 새로 넣으면 다시 빌드만 하면 된다. Core ML 모델(.mlpackage)은 앱이 **첫 실행 때 기기에서 컴파일**해 캐시한다
(그때만 수십 초 걸릴 수 있다).

## 5. Xcode에서 빌드·설치 (iPhone 15 Pro)

1. 아이폰: 설정 → 개인정보 보호 및 보안 → **개발자 모드** 켜기(재부팅). 맥과 케이블 연결, "이 컴퓨터 신뢰".
2. `open dashboard/iphone/GoldenLinkPhone.xcodeproj`
3. 왼쪽에서 프로젝트 → 타깃 **GoldenLinkPhone** → **Signing & Capabilities**
   - Team: 내 Apple ID(Xcode → Settings → Accounts에서 추가)
   - Bundle Identifier: 겹치지 않게 바꾼다(예: `com.<이름>.goldenlink`)
   - **Increased Memory Limit**이 목록에 있는지 확인(entitlements에 들어 있음). 무료 계정에서 서명이 막히면 아래 "문제 해결"
4. 상단 기기 선택에서 내 아이폰 → ▶ (Cmd+R). 처음엔 패키지 받기·MLX 컴파일로 수 분 걸린다.
   **"Validate plug-in 'CudaBuild'" / 매크로 신뢰 오류가 나면** 이슈 내비게이터에서 해당 항목 → **Trust & Enable**
   (mlx-swift·swift-syntax 패키지의 빌드 플러그인·매크로 — Xcode가 처음 한 번 사용자 승인을 받는다).
5. 아이폰에서 "신뢰할 수 없는 개발자" 경고가 뜨면: 설정 → 일반 → VPN 및 기기 관리 → 내 Apple ID → 신뢰
6. 무료 Apple ID는 7일마다 다시 설치해야 한다. 팀 배포·TestFlight는 유료(연 $99)

> 시뮬레이터는 마이크·MLX(Metal) 때문에 시연용으로 쓸 수 없다. 화면 확인 정도만 된다. 실제 기기로 한다.

명령줄 빌드(서명 없이 컴파일만 확인):
```bash
cd dashboard/iphone
xcodebuild -project GoldenLinkPhone.xcodeproj -scheme GoldenLinkPhone -destination 'generic/platform=iOS' \
  -skipPackagePluginValidation -skipMacroValidation CODE_SIGNING_ALLOWED=NO build
```

## 6. hub 띄우고 앱 연결 (로컬 모드)

```bash
./start-all.sh --local        # 맥에서. voice는 띄우지 않는다(아래 주의)
ipconfig getifaddr en0        # 맥 IP 확인 → 예: 192.168.0.10
```

앱 오른쪽 위 ⚙︎ → hub `http://192.168.0.10:5001`, 구급차 ID `auto`(출동하는 구급차 자동 추적, 웹 P-AUTO) 또는
`SEL0001` → 적용. 처음 연결할 때 "로컬 네트워크" 권한 팝업에서 허용. 아이폰과 맥이 **같은 Wi-Fi**여야 한다.

### ⚠ 팀 결정이 필요한 두 가지 (가이드 §5)

- **공개 도메인으로는 `/voice/*`가 막혀 있다.** `start-all.sh` 터널 규칙이 `ws/dashboard|identity|route|geocode|verification`만
  hub로 보낸다(인증 없는 요약 주입 방지). 그래서 온디바이스 모드는 지금 **로컬 모드에서만** 끝까지 된다. 공개 도메인에서
  쓰려면 hub에 인증을 붙여 터널을 열거나, 요약·자막을 WebSocket 메시지로 보내도록 hub를 고쳐야 한다(hub 담당자).
- **중앙 voice가 떠 있으면 섞인다.** hub는 `call_started`를 등록된 voice로 중계한다. 앱은 음성을 안 보내므로 중앙 voice는
  빈 통화를 열었다 닫는다. **온디바이스 시험 중엔 `./voice/start-voice.sh`를 실행하지 않는다.** 운영에서 웹 휴대폰과 섞으려면
  `CallSignal`에 "온디바이스" 표시를 추가해 중계를 건너뛰게 해야 한다(hub 담당자).

## 7. 시연·검증 체크리스트

| 단계 | 확인 |
|---|---|
| P2 | 앱 상단 "연결됨", 이름 표시(`identity_info`). 구급차 대시보드 [이동] → "현장 출동 중" → 현장 도착 → 병원 목록·"첫 연락 추천" 배지 |
| P2 | 병원 탭 → "연결 중" → 통화 중. 병원 대시보드 "📞 통화 중", 관제 지도 📞 |
| P3 | 통화 전송 → "환자 정보를 구조화하는 중…" → 확인 버튼 없이 환자 정보 탭으로 자동 전환 |
| P4 | 통화 중 말이 끊길 때마다 앱·구급차 대시보드에 자막(`call_transcript`) |
| P5 | hub 로그 `/voice/summary` 202, 두 대시보드에 매칭 결과. 같은 녹음(앱이 남긴 wav)을 서버 voice로도 처리해 요약 비교 (`model_used`에 `-ios`) |
| P5 | Xcode → Debug Navigator(메모리 최대치), 발화당 인식 시간, 종료→hub 도착 시간, 화면 꺼진 상태에서 녹음 유지 |

**원본 보존**: 앱은 통화마다 `Documents/calls/<caseId>/`에 `call.wav`·`transcript.txt`·`call_summary.json`을 잠금 시
암호화(`completeFileProtection`)로 남긴다. 꺼내려면 Xcode → Window → Devices and Simulators → 앱 → Download Container.

**서버 STT 모드**(⚙︎에서 "기기 안에서 음성 인식·구조화" 끔, 또는 모델이 번들에 없을 때): 웹 전화 앱과 똑같이 16kHz PCM을
hub WebSocket으로 보내 중앙 voice가 처리한다. 이때는 `./voice/start-voice.sh`가 떠 있어야 한다.

## 문제 해결

| 증상 | 해결 |
|---|---|
| 앱 하단이 "서버 음성 인식" | `Models/`에 변환 결과가 다 들어가지 않았다(MF_BERT 3개 + Qwen 폴더). 2번 → Xcode에서 다시 빌드 |
| 서명 오류 "increased-memory-limit" | 무료 계정에서 막히면 `GoldenLinkPhone/GoldenLinkPhone.entitlements`에서 그 키를 지우고 빌드(메모리 부족으로 꺼질 수 있음 — 그땐 `ModelStore`에서 MF_BERT를 통화 종료 뒤에 올리도록 바꾼다) |
| 연결 안 됨(빨간 점) | 같은 Wi-Fi인지, hub 주소에 `http://`·포트 5001, 맥 방화벽, 아이폰 설정 → 앱 → 로컬 네트워크 허용 |
| 전송 후 "전달되지 않았습니다" | hub와 연결이 끊겼거나(위쪽 연결 표시) 인식된 말이 없었다 → [확인 · 다시 걸기] |
| 말을 해도 자막이 안 나옴 | 무음 기준이 높다 → ⚙︎에서 RMS를 낮춘다. 말하는 중에 자꾸 끊기면 "발화 끝"을 늘린다 |
| 패키지 해석 실패 | `Vendor/speech-swift`가 없음 → `./setup.sh` |
| MLX 컴파일 중 Metal 오류 | Xcode → Settings → Components에서 Metal Toolchain 설치 |

## 확인한 것 / 아직 모르는 것

- **확인함(맥)**: Swift 코어 로직이 Python 원본과 일치(`swift test` 11개 — 토크나이저 13문장 오프셋까지, 조각 나누기 4가지,
  decode 무작위 60건, parse 58건, 발화 자르기 300건). MF_BERT 인코더/헤드 분할 = 원본 forward(무작위 가중치).
  추적 그래프가 다른 길이에서도 같은 값. speech-swift 0.6B 구조(오디오 인코더 896/14/18층)가 우리 모델과 같고 프롬프트도 서버와 같은 형태.
- **아직 안 함**: 실제 가중치로 Core ML 변환·대조(2-1), ASR 합치기·아이폰 인식 대조(2-2, P1), 아이폰 실행 속도·메모리·발열.
  speech-swift의 멜 특징 추출은 Swift 재구현이라 서버와 수치가 조금 다를 수 있다 — 다른 문장은 목록화해 voice 담당자 판단을 받는다(가이드 §7-3).
- **한계**: iOS는 서드파티 앱의 셀룰러 통화 녹음을 막는다 → 웹과 같이 "앱 안 통화 화면 = 대원 목소리 녹음" 연출이다. 화자 분리 없음.
  WebSocket 인증 없음(현재 시스템과 동일).

## 구급대 접근 코드로 입장

앱 첫 실행/업데이트 후 접근 코드 입장 화면이 뜬다. **P-SEL0111**을 입력하면 hub `/identity`에서
역삼119안전센터 구급 1 등록 여부를 확인하고 해당 구급대에 고정 연결한다. 아이패드는 웹 첫 화면에서 **A-SEL0111**을 쓴다.
기존 auto 설정이 있더라도 처음 한 번 코드를 입력해야 한다. 앱 재실행 시 입력한 코드로 연결한다.
설정의 ‘접근 코드 변경’으로 다른 구급대 코드를 입력할 수 있다. 서버 주소는 입장 화면의 ‘서버 연결 설정’에서 바꾼다.
등록되지 않은 코드나 서버 확인 실패 시 입장하지 않고 오류를 표시한다. 과거 기록 조회에 필요한 기록 동기화 키는 기존과 같다.

## 기기 간 수동 수정 동기화

같은 구급대의 아이폰·아이패드에서 인계확인서를 저장하면 수정한 칸만 hub에 보관하고 다른 기기에 즉시 반영한다.
외상 도해에서 적용한 부위·외상 유무·처치도 공유한다. 환자 요약/추가 정보는 기존 hub 재전송 결과로 양쪽에 반영된다.
서로 다른 칸은 병합하고 같은 칸의 충돌은 **서버 값 사용 / 내 수정으로 다시 저장**으로 선택한다.
상태와 전송 대기 건수를 화면에 표시하며, 인계확인서·도해 수정 대기열은 재실행/재연결 후에도 보존한다.
현재 사건 공유에는 기록 동기화 키가 필요 없으며 과거 기록 조회 권한은 그대로다.
서식을 열어 둔 상태에서도 직접 손대지 않은 칸은 상대 기기의 수정값을 따라간다.

**hub 재시작과 양쪽 앱 최신 빌드 설치가 필요하다.** 공통 소스는 `../shared/CaseEditSync.swift`이므로
project.yml 변경 후 `xcodegen generate`로 Xcode 프로젝트를 갱신한다. 상세 계약·오프라인 범위는 `../../hub/RECORD_SYNC.md` 참고.

## 카카오맵 iOS SDK (2026-11-01)

통화 지도는 애플 MapKit 대신 공식 KakaoMapsSDK 2.12.19를 사용한다.
구급차·사건 현장·선택 병원 핀, hub의 도로 경로, Pre-KTAS 선택 자동 배율, 내 위치, 탭 전환 시 카메라 유지,
후보 병원 전달 애니메이션을 카카오맵으로 표시한다. 하단 전화 카드 높이는 SDK 지도 여백으로 반영한다.
백그라운드에서는 엔진을 멈추고 통화 탭이 해제되면 리소스를 정리한다.

카카오 디벨로퍼스에서 **실제 빌드 번들 ID(com.goldenlink.phone)**를 등록하고 카카오맵 사용 설정을 확인한다.
네이티브 앱 키가 필요하며 JavaScript/REST API 키로 대체하지 않는다. 등록만으로 앱 코드가 바뀌지는 않는다.

키 설정 방법은 둘 중 하나다.

1. `Config/Kakao.local.xcconfig.example`을 `Config/Kakao.local.xcconfig`로 복사하고 네이티브 앱 키를 입력한 뒤 빌드.
   로컬 파일은 git에서 제외한다. 실제 값은 Info.plist의 빌드 설정 치환으로 앱에 들어간다.
2. 설치한 앱의 설정에서 **카카오맵 네이티브 앱 키**를 입력하고 적용. 이 기기에 저장한 값이 있으면 번들 설정보다 우선한다.

SDK는 project.yml의 SPM 의존성이다. `xcodegen generate`로 갱신한 .xcodeproj에서 패키지를 받아 빌드한다.
키 누락·인증 실패 시 애플 지도로 우회하지 않고 원인을 표시한다.
검증: 아이폰 코드서명 없는 iOS 빌드. 실제 타일/인증·지도 조작은 유효한 네이티브 앱 키가 설정된 기기에서 최종 확인해야 한다.

### 통화 지도 노드 모양·크기

모든 통화 단계에서 병원·구급대 모두 같은 사각 박스 안의 십자가로 표시한다. 병원은 기존 남색, 구급대는 기존 주황색이다.
센터는 차고 형태, 현장은 느낌표 마름모로 구분한다. 기존 상태 색과 병원 선택 동작은 유지한다.
줌 15 기준 아이콘 크기는 병원 21pt·구급차 28pt다.
SDK PerLevelPoiStyle로 줌에 따라 확대·축소하며 병원은 기본 크기의 0.6~1.35배, 구급차는 0.75~1.35배(최소 21pt)로 제한한다.
일반 핀은 zOrder 5000, 구급차는 별도 `ambulance-foreground` 레이어(zOrder 10000, competitionType .none)에 표시해
지도 기본 장소 아이콘·지명과 병원 핀보다 앞에 보이도록 한다.
스타일은 지도 생성 때만 등록하며 줌 동작마다 이미지를 새로 만들지 않는다. 이름표는 읽을 수 있도록 9~12 크기를 유지한다.

병원 응답 단계의 통화 지도에는 관제 지도와 같은 보라색(`#7B4DFF`) 점선 원과 옅은 영역으로 구급차 중심 활성 존을 표시한다.
그 안에서 구급차를 중심으로 3개의 동심원 펄스가 바깥으로 퍼지며 점차 사라지는 동작을 반복한다.
범위는 match_result.zoneActive와 hub/geo.py의 존 폭 5km 규칙을 따른다. 예전 메시지에 존 정보가 없으면 Zone 1이다.
존 진입·확장 때 범위가 보이도록 배율을 맞추며, 일반 응답 갱신과 펄스 프레임에서는 카메라를 움직이지 않는다.
존이 확장되면 바깥 원과 기존 안쪽 원을 함께 표시한다. 별도의 좌측 상단 정보 전달 안내 블록은 두지 않는다.
병원은 실제 위치에 일반 십자가 아이콘으로 표시한다.
통화 종료 후 전달 병원 수와 지도 병원은 hub가 음성 KTAS·spider 역량 규칙으로 고른 실제 전달 목록을 사용한다.
같은 WebSocket 결과를 아이패드에도 보내므로 기기별로 다시 필터링하지 않는다. 상한 존까지 적합한 병원이 없으면
0곳 전달 성공으로 표시하지 않고 조건에 맞는 병원이 없다는 안내를 띄운다. 역량 규칙은 임상 검증 전 시연 기준이다.
이송 시작·추가 통화 화면에서는 효과를 해제한다. 동작 줄이기·시연 일시정지 시에는 존·병원 노드를 정적으로 유지하며,
백그라운드와 지도 해제 시 반복 작업을 중단한다.

### 통화 전 Pre-KTAS 병원 선택

hub의 현장 후보 `supportedKtas`(일반 질환 조건, 기존 spider 규칙: 등급·응급의학과 전문의 수·시간대)를 이용한다.
선택한 Pre-KTAS의 hub 추천 순서를 사용한다(이동시간·경증 센터 보존·동시 사건 부하).
KTAS 변경 시 수동 선택을 초기화한다. 적합도 정보가 없거나 적합 후보가 없으면 자동 선택과 전화 버튼을 비활성화한다.
이는 실제 수용 보장이 아닌 임상 검증 전 적합도 규칙이다. hub 재시작과 iPhone 새 빌드를 함께 적용해야 한다.


통화 전 추천은 이제 `first_call_request`로 hub에 요청한다. 로컬 거리순 자동 선택 대신
hub의 KTAS·이동시간·센터 보존·동시 사건 부하 추천을 표시한다. 「미응답 · 다음 병원」은
현재 녹음을 취소하고 미응답을 기록한 뒤 다음 후보를 요청한다. 미응답 이력 메뉴에서
수동 재시도할 수 있다. 현재 시연 통화는 미응답 자동 감지가 없어 사용자가 판단한다.


### 전화 연결 대기와 수용 판단 분리

iPhone 전화 요청은 `call_connection`(operation=request, caseId, hospitalId, requestId,
timestamp)으로 전송한다. hub는 ringing을 방송하고 이때는 voice·마이크를 시작하지 않는다.
관제 상단 「전화 응답」(answer) 이후 calling으로 바뀌어 녹음을 시작한다. 「전화 미응답」
(no_answer)은 녹음 없이 요청을 종료하고 다음 후보를 추천한다. iPhone에서도 연결 대기 중
「미응답 · 다음 병원」이나 「취소」를 선택할 수 있다. 연결 이후에는 미응답 버튼이 없다.
요청 ID로 취소 후 늦은 응답·중복 응답을 무시하고, 요청 기기 소켓이 끊기면 대기를 취소한다.
관제의 병원 승인 pending 표시는 「수용 판단 대기」로 구분한다.
새 흐름은 hub·관제·iPhone을 함께 업데이트해야 한다. 실제 전화망 수신 감지가 아닌 시연 제어다.

현장 통화 화면은 Pre-KTAS 선택 버튼만 표시한다. 등급을 선택하면 병원 목록 시트가
자동으로 열리고(같은 등급 재선택도 가능), 각 병원 오른쪽 「전화」 버튼으로 요청한다.
병원 정보 행 자체를 눌러서는 전화하지 않는다. 미응답 이력은 해당 목록 안에서 표시한다.

## Android 기능 반영 (2026-11-03)

Android `3f153b16`까지의 앱 동작과 대조해 다음 차이를 반영했다. 기존 iOS Core ML/MLX 음성 인식과 서버 음성 인식 선택은 유지한다.

| 영역 | iPhone 반영 내용 |
|---|---|
| 출동·이송·복귀 지도 | 진행 방향이 위로 오는 내비 시점, 경로 위 추정 주행·GPS 보정, 속도에 따른 연속 배율, 경로 전체 보기 전환 |
| 내비 안내 | 경로에서 계산한 다음 회전·거리·남은 거리·hub ETA 기준 도착 시각. 새 이동 구간은 지도 준비 전 로딩으로 가린다 |
| 지도 배치 | 상태바·헤더 뒤까지 지도, 위·아래 덮개를 뺀 영역에서 구급차를 아래쪽에 배치. 탭을 벗어나면 지도와 반복 애니메이션을 숨기고 멈춘다 |
| 병원 이송 | 접고 펼치는 목적지 병원 통화 시트, 재선택 시 자동 펼침, 병원 도착 안내와 병원 핀 표시(겹치는 구급차·현장 핀 제거) |
| 외상 처치 | voice/hub의 28범주 어휘. 부위별 처치 선택(규칙 기반·전문의 검토 전 초안), 다른 기기·예전 값도 부위에 맞지 않으면 전달·서식에서 제외 |
| 문구·전송 | 환자 요약·수정·외상·기록에 Pre-KTAS 표시. 소켓에서 종료·취소 신호를 보낼 수 없으면 통화를 유지하고, 외상 처치 전송 실패 시 ‘보냄’ 표시를 하지 않는다 |

기존 통화 요약 분배 연출·승인 병원 이송·거절 제외 재전화·환자 수정·인계확인서·기록·현재 사건 수정 동기화는 유지한다.
WebSocket `send` 결과는 송신 가능 여부이며 서버 수신 확인 응답을 뜻하지 않는다.

검증: Swift 코어 테스트 28개(새 경로/카메라/부위 처치 테스트 4개 포함), Xcode `generic/platform=iOS`, `CODE_SIGNING_ALLOWED=NO` 빌드.
실기기에서 카카오맵 회전·안전 영역·시트 드래그·마이크 통화와 구간 전환을 최종 확인한다. 서명·기기 설치는 별도다.

## 첫 전화 병원 선택 (2026-11-03 수정)

첫 전화 전에 Pre-KTAS를 수동 선택하지 않고 hub 추천 병원 목록에서 선택한다. `first_call_request`에는 `ktas`를 보내지 않는다. 이 흐름은 최신 develop의 hub가 필요하며, 등급을 필수로 요구하던 구형 hub와는 호환되지 않는다. 통화 후 환자 정보의 Pre-KTAS 표시·수정은 유지한다.
