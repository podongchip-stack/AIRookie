# 골든링크 갤럭시 앱 (온디바이스 STT·MF_BERT)

아이폰 앱(`dashboard/iphone`)과 같은 앱을 안드로이드로 옮겼다. 흐름은 웹 전화 앱(`/phone`)과 같다:
출동 → 현장 도착 → 병원 목록 → 병원 골라 통화 → [취소]/[전송] → 후보 병원 전체 전달.
음성 인식(Qwen3-ASR)과 구조화(MF_BERT)를 **휴대폰 안에서** 돌리고, hub에는 지금 voice가 보내는 것과 **같은 통화 요약 JSON**만
WebSocket(`type: "voice_summary"`)으로 보낸다. 그래서 공개 도메인에서도 된다. 대상은 갤럭시 S24(8GB)급이다.

## 모델은 서버와 같다

- **같은 가중치**: 서버 voice가 받는 Hub 저장소·커밋 그대로다(`voice/weights.py`).
  - ASR: `Qwen/Qwen3-ASR-0.6B-hf`에 LoRA `Playedwell03/qwen3-asr-0.6b-119ko-tiny`를 fp32로 합쳤다.
  - MF_BERT: `podongchip/MF_BERT@f1d3e1d`.
  - 변환 결과 파일(`Models/asr_tokens.json`·`mf_bert_meta.json`)에 출처를 기록한다.
- **같은 정밀도**: 양자화·fp16 변환은 하지 않는다. 둘 다 **fp32**다. 서버가 CPU에서 도는 정밀도와 같다. 서버 GPU는 bf16이다.
- **같은 처리 순서**:
  - 그래프 밖 계산을 서버 코드에서 그대로 옮겼다: 멜 스펙트로그램, 프롬프트, 그리디 생성, 바이트 BPE 풀기, 반복 정리, 512토큰 조각, decode·parse 규칙.
  - 발화 자르기(무음 감지·5초 분할)도 같다.
- **대조 결과** (2026-10-05, PC):

| 대조 | 결과 |
|---|---|
| MF_BERT ONNX vs 서버 PyTorch | 5/5 summary 완전 일치. 1,242토큰 긴 통화 포함, 로짓 최대 오차 1.8e-5 |
| **앱 Kotlin 코드**로 돌린 MF_BERT vs 서버 | 5/5 완전 일치 (`OnDeviceE2ETest`) |
| ASR ONNX vs 서버 (실제 통화 녹음 16건, 5초 구간 177개) | **177/177 문장 완전 일치**. 영어로 녹음된 통화 1건 포함 |
| **앱 Kotlin 코드**로 돌린 ASR vs 서버 | 6/6 완전 일치 (`OnDeviceE2ETest`) — Kotlin 멜·프롬프트·KV 캐시 그리디·토큰 풀기 |
| 앱 Kotlin 코어 로직 vs Python 원본 | 13개 테스트 통과. 아이폰과 같은 정답 파일을 쓴다: 토크나이저 오프셋, 조각, decode 무작위 60건, parse, 발화 자르기 |

> 휴대폰의 onnxruntime-android(1.30.0)는 PC 대조와 **같은 버전**이다. CPU 커널이 ARM용이라 부동소수 끝자리는 다를 수 있다.
> 기기에서 서버와 같은 문장이 나오는지는 실기기에서 다시 확인한다(아래 "기기 확인").

## 폴더

| 경로 | 내용 |
|---|---|
| `convert/` | PC Python — 모델 변환(`convert_*.py`)과 서버 대조(`check_*.py`). `qwen3_asr_split.py`가 그래프 분할과 앱이 옮길 기준 계산이다 |
| `core/` | 순수 Kotlin(JVM). 토크나이저·조각·decode·parse·발화 자르기·멜·토큰 풀기·hub 메시지·**onnxruntime 실행 코드**. PC에서 `./gradlew :core:test`로 Python 원본·서버와 대조한다 |
| `app/` | 안드로이드 앱(Compose). 화면·hub 연결·마이크·통화 처리. 모델 실행은 `core`의 코드를 그대로 쓴다 |
| `Models/` | 변환 결과(약 4.6GB, 커밋 안 함) |
| `fixtures/` | 대조용 정답(실제 통화 녹음 조각이 들어 있어 커밋 안 함). `check_*.py --fixtures`가 만든다 |

### 아이폰 코드 대응

| 안드로이드 | 아이폰 |
|---|---|
| `core/.../WordPieceTokenizer.kt` | `GoldenLinkCore/WordPieceTokenizer.swift`, `Chunking.swift` |
| `core/.../Decode.kt`, `Parse.kt`, `resources/labels.json` | `Decode.swift`, `Parse.swift`, `Resources/labels.json`(같은 파일) |
| `core/.../Utterance.kt` | `UtteranceSegmenter.swift`, `CallSummary.swift` |
| `core/.../HubMessages.kt` | `HubMessages.swift` |
| `core/.../AsrCore.kt`, `OnnxRunners.kt` | `OnDeviceASR.swift`(speech-swift), `MFBertRunner.swift` |
| `app/.../PhoneModel.kt`, `CallSession.kt` | `PhoneModel.swift`, `CallSession.swift` |
| `app/.../Platform.kt` | `HubSocket.swift`, `MicCapture.swift`, `Settings.swift` |
| `app/.../ui/Screens.kt` | `Views.swift`(같은 색·카드·화면 순서) |

---

## 순서 요약

```bash
cd dashboard/android
./setup-tools.sh                                       # 1. 빌드 도구(JDK 17·Android SDK) — 한 번만, Android Studio 불필요
conda create -n goldenlink-android --clone rookie_voice -y && \
  conda run -n goldenlink-android pip install onnx onnxruntime onnxscript   # 2. 변환용 Python 환경
python convert/convert_mf_bert.py && python convert/check_mf_bert.py --fixtures          # 3. MF_BERT 변환·대조
python convert/convert_qwen3_asr.py && python convert/check_qwen3_asr.py --fixtures ../../data/voice_data/origin_data/*.wav   # 4. ASR
./build-apk.sh                                         # 5. 테스트 + APK (GoldenLink.apk)
./push-models.sh --install                             # 6. 휴대폰에 APK 설치 + 모델 넣기(USB)
```

Python 명령은 `conda activate goldenlink-android` 뒤 저장소 루트나 `dashboard/android`에서 돌린다. 경로는 스크립트가 알아서 찾는다.
Windows는 `PYTHONUTF8=1 HF_HUB_DISABLE_SYMLINKS=1`을 켠다.

## 1. 빌드 도구

`./setup-tools.sh`는 `~/.goldenlink-android`에 JDK 17과 Android SDK(platform 35, build-tools 35, adb)를 받는다. 약 1.5GB다.
Android Studio를 쓰고 싶으면 이 폴더(`dashboard/android`)를 그대로 열면 된다. 같은 Gradle 프로젝트다.

## 2~4. 모델 변환·대조 (PC, 한 번만)

- 가중치는 첫 실행 때 HF 캐시로 받는다. ASR 베이스 약 1.8GB, MF_BERT 약 1.4GB다.
- 변환은 각각 몇 분 걸린다. RAM은 16GB면 된다.
- `check_qwen3_asr.py`는 두 단계로 돈다.
  1. 서버 경로로 정답을 만들어 `fixtures/asr_server_cache.json`에 저장한다. 중간에 끊겨도 이어서 받는다.
  2. 서버 모델을 내린 뒤 ONNX를 돌려 대조한다.
  - 두 모델을 동시에 올리면 fp32 두 벌이라 16GB PC에서 스왑이 나서 수십 배 느려진다. 그래서 단계를 나눴다.
- `--torch`는 ONNX로 내보내기 전에 PyTorch 래퍼만으로 대조한다. 그래프 분할을 고칠 때 쓴다.
- 대조가 다 맞아야 다음 단계로 간다. 하나라도 다르면 원인을 찾는다(정밀도를 낮추거나 규칙을 바꿔서 맞추지 않는다).

> ⚠ **멜은 특징 추출기 기본값이 아니라 서버 경로와 같아야 한다.** 서버는 `processor.apply_chat_template`로 특징을 만들고,
> 이때 특징 추출기는 `padding="longest"`로 돈다. 즉 30초로 채우지 않는다. 그 결과 오디오 끝 반사, 유효 프레임 수(내림), 채움 칸(0)이 달라진다.
> 처음에 기본값(30초 채움)을 옮겼더니 68구간 중 6구간에서 문장 끝 글자·쉼표·언어가 달라졌다(91%).
> 원인을 찾아 맞춘 뒤 177/177 일치했다. 다른 그래프·디코딩 코드는 처음부터 서버와 로짓 3e-5 이내로 같았다.

### 그래프 분할 (convert/qwen3_asr_split.py)

| 그래프 | 입력 → 출력 |
|---|---|
| `asr_audio_encoder.onnx` | 멜 조각 `(C,1,128,100)` + 유효 위치 + 창 마스크 → 오디오 임베딩 `(T,1024)`. 합성곱 3층 + 트랜스포머 18층 + 프로젝터 |
| `asr_decoder.onnx` | 토큰 + 오디오 임베딩 + KV 캐시 → 마지막 로짓 + 새 KV. Qwen3 28층. lm_head는 임베딩 표와 공유한다(원본과 같다) |
| `mf_bert_encoder.onnx` | 512토큰 조각 → 마지막 4층 은닉 상태 |
| `mf_bert_heads.onnx` | 이어 붙인 은닉 상태 → 헤드 16개 로짓 |

- transformers의 forward에서 추적이 안 되는 부분만 입력으로 바꿨다.
  - nonzero로 고르는 유효 위치 → `valid_index`
  - 창별 어텐션 → 블록 대각 마스크
  - DynamicCache → 텐서
- 계산식은 같다.
- 가중치는 `<이름>.onnx.data` 한 파일로 따로 둔다. 휴대폰이 불러올 때 메모리가 두 배로 뛰지 않게 하려는 것이다.

## 5~6. 빌드와 설치

1. 휴대폰 설정:
   - 설정 → 휴대전화 정보 → 소프트웨어 정보 → **빌드번호를 7번** 누른다(개발자 옵션 켜짐).
   - 개발자 옵션 → **USB 디버깅**을 켠다.
2. PC와 USB-C 케이블로 연결하고, 휴대폰의 "이 컴퓨터 허용"을 누른다.
3. `./build-apk.sh`로 `GoldenLink.apk`를 만든다. 테스트가 같이 돈다. APK는 약 73MB이고 모델은 들어 있지 않다.
4. `./push-models.sh --install`로 설치하고 모델 4.6GB를 넣는다.
   - 모델은 `/sdcard/Android/data/xyz.goldenlink.phone/files/models/`에 들어간다.
   - USB 3 기준 수 분 걸린다.
   - 이미 같은 크기로 있는 파일은 건너뛴다. 다시 넣을 때 빠르다.
   - USB가 아니라 APK만 옮겨 설치했다면, 모델은 adb로만 넣을 수 있다. Android 11부터 다른 앱이 `Android/data`에 쓰지 못한다.
5. 앱을 열면 오른쪽 위 ⚙︎에서 설정한다.
   - hub: 공개 도메인 `https://app.rookie-goldenlink.xyz`(기본값) 또는 로컬 `http://<PC IP>:5001`
   - 구급차 ID: `auto`(출동하는 구급차를 자동으로 따라감) 또는 `SEL0001`
   - 하단에 "온디바이스 음성 인식·구조화"가 뜨면 모델이 올라간 것이다. 모델이 없으면 조용히 서버 음성 인식으로 동작한다(웹 전화 앱과 같다).

## 기기 확인 (실기기에서 할 일)

| 확인 | 방법 |
|---|---|
| 서버와 같은 문장·요약 | 앱이 남긴 녹음을 서버 voice로도 처리해 비교한다. 앱은 통화마다 앱 전용 폴더의 `calls/<caseId>/`에 `call.wav`·`transcript.txt`·`call_summary.json`을 남긴다. `adb pull /sdcard/Android/data/xyz.goldenlink.phone/files/calls`로 꺼낸다. `model_used`에는 `-android`가 붙는다 |
| 메모리 | 모델 두 개를 fp32로 올리면 약 4.6GB다. S24(8GB)에서 앱이 죽지 않는지 본다. 죽으면 MF_BERT를 [전송] 때 올렸다가 내리도록 바꾼다(`ModelStore`) |
| 속도 | 발화당 인식 시간과 [전송]부터 hub 도착까지의 시간을 잰다. PC(CPU, fp32)에서는 3~5초 구간 하나에 3~8초가 걸렸다(실시간보다 느림). 통화 중엔 발화를 줄 세워 인식하므로, 휴대폰이 더 느리면 [전송] 뒤 남은 인식이 길어진다 |
| 화면 꺼짐 | 통화 중엔 화면을 켜 둔다. 녹음은 포그라운드 서비스(마이크)로 이어진다 |

## 한계

- 통화는 **연출**이다. 병원과 실제 음성으로 연결되지는 않는다(웹·아이폰과 같다). 앱 안 통화 화면에서 대원 목소리를 녹음한다.
- 화자 분리가 없다.
- WebSocket 인증이 없다(현재 시스템과 같다).
- 모델 4.6GB를 fp32로 쓰므로 8GB 미만 기기는 대상이 아니다.
