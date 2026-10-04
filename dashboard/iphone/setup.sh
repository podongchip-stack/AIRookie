#!/usr/bin/env bash
# 아이폰 앱 빌드 준비: speech-swift(Qwen3-ASR MLX 포팅)를 받아 float 디코더 패치를 적용하고, Xcode 프로젝트를 만든다.
#   ./dashboard/iphone/setup.sh          (저장소 어디서 실행해도 된다)
set -euo pipefail
cd "$(dirname "$0")"

SPEECH_SWIFT_REV=1f54e56cf137078ed681a03e0955e777f7314610  # 패치를 만든 커밋 — 올리면 패치가 안 맞을 수 있다

if [ ! -d Vendor/speech-swift/.git ]; then
  git clone https://github.com/soniqo/speech-swift Vendor/speech-swift
fi
git -C Vendor/speech-swift fetch --quiet origin "$SPEECH_SWIFT_REV" || true
git -C Vendor/speech-swift checkout --quiet "$SPEECH_SWIFT_REV"
if git -C Vendor/speech-swift apply --check ../../patches/speech-swift-float-decoder.patch 2>/dev/null; then
  git -C Vendor/speech-swift apply ../../patches/speech-swift-float-decoder.patch
  echo "speech-swift: float(bf16) 디코더 패치 적용"
else
  echo "speech-swift: 패치가 이미 적용돼 있거나 맞지 않음 — git -C Vendor/speech-swift diff 로 확인"
fi

if ! command -v xcodegen >/dev/null; then
  echo "xcodegen 설치: brew install xcodegen"; exit 1
fi
mkdir -p Models   # 폴더 참조 대상 — 모델이 아직 없어도 빌드되게
xcodegen generate
echo "완료: open dashboard/iphone/GoldenLinkPhone.xcodeproj"
