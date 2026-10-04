# 골든링크 아이폰 앱 (온디바이스 STT·MF_BERT)

웹 전화 앱(`/phone`)과 같은 흐름(출동 → 현장 도착 → 병원 목록 → 병원 골라 통화 → 종료 → 후보 병원 전체 전달)을
네이티브 앱으로 옮겼다. 음성 인식(Qwen3-ASR)과 구조화(MF_BERT)를 **아이폰 안에서** 돌리고, hub에는 지금 voice가
보내는 것과 **같은 JSON**(`/voice/utterance`, `/voice/summary`)만 보낸다. 모델은 양자화·fp16 변환 없이 원본
정밀도(ASR bf16, MF_BERT fp32)로 쓴다. 대상: iPhone 15 Pro(iOS 18+), 개발 맥 + Xcode.

hub·dashboard 코드는 바꾸지 않았다. 앱은 hub에 "구급차 탭(role=ambulance)"으로 붙고, voice 역할을 겸한다.

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
| P3 | 통화 종료 → "환자 정보를 구조화하는 중…" → "후보 병원 N곳에 전달됐습니다" |
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
| 앱 하단 "온디바이스 모델 없음" | `Models/`에 변환 결과가 없다. 2번 → Xcode에서 다시 빌드 |
| 서명 오류 "increased-memory-limit" | 무료 계정에서 막히면 `GoldenLinkPhone/GoldenLinkPhone.entitlements`에서 그 키를 지우고 빌드(메모리 부족으로 꺼질 수 있음 — 그땐 `ModelStore`에서 MF_BERT를 통화 종료 뒤에 올리도록 바꾼다) |
| 연결 안 됨(빨간 점) | 같은 Wi-Fi인지, hub 주소에 `http://`·포트 5001, 맥 방화벽, 아이폰 설정 → 앱 → 로컬 네트워크 허용 |
| 종료 후 "hub가 /voice/summary를 받지 않음(404)" | 공개 도메인 주소를 넣었다 → 로컬 모드 주소로 |
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
