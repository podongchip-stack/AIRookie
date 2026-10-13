# Lab_DH — 양자화 구조화 모델이 iPhone 12 Pro에 올라가는지 보는 실험 앱

기존 `GoldenLinkPhone`과 독립이다. 서버(hub) 연결 없이 앱 안에서 **음성인식 → 구조화**까지 돌려 결과를 화면에 보는 것이 목표.
대상 모델: `small-MF_BERT` 양자화본(인코더 4bit `MatMulNBits` + 디코더 fp32, 질문별 선택지 점수 방식 — 생성형 아님).

## 진행 단계

| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | 프로젝트 뼈대 + 모델 로드·메모리 확인 (ONNX Runtime iOS가 `MatMulNBits`를 지원하는지) | 코드 작성 완료, **맥 빌드 미확인** |
| 2 | 텍스트 입력 → 구조화 결과 표시 (`runtime.py` 이식), 모델 자동 다운로드 | 예정 |
| 3 | 마이크 → Qwen3-ASR → 구조화 | 예정 |
| 4 | 단계별 시간·메모리 표시 | 예정 |

## 1단계 실행 (맥)

```bash
brew install xcodegen
cd dashboard/iphone/Lab_DH && xcodegen generate && open LabDH.xcodeproj
```

Xcode에서 Signing 팀을 고르고(번들 ID가 겹치면 바꾼다) iPhone 12 Pro를 선택해 ▶.
모델은 이 단계에서만 수동으로 넣는다: Finder → iPhone → 파일 → LabDH에 `encoder.onnx`, `decoder.onnx`, `decoder.onnx.data`
(`small-MF_BERT/2026-10-12_014124/high_score/hqq/`)를 `small_mf` 폴더째 복사. 앱에서 [모델 로드 확인].

## 읽는 법

- 로드·실행 성공 + 메모리 줄 → 올라간다. 남은 메모리가 충분한지도 같이 본다.
- 인코더 로드에서 실패하고 `MatMulNBits`·`NOT_IMPLEMENTED` 류 메시지가 나오면 → ONNX Runtime iOS 빌드에 그 커널이 없다는 뜻이다(이 경우 알려 주면 대안을 정한다).

## 알아 둘 점

- ONNX Runtime SPM 래퍼의 최신 태그가 `1.19.2`라 그 버전에 고정했다(Android 앱의 1.30.0보다 낮다).
- `increased-memory-limit` entitlement가 무료 Apple ID 서명에서 막히면 `LabApp/LabDH.entitlements`에서 그 키를 지운다.
