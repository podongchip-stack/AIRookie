#!/usr/bin/env bash
# 아이패드 관제 앱 빌드 준비: XcodeGen으로 프로젝트를 만든다. 외부 패키지·모델 없음.
#   ./dashboard/ipad/setup.sh          (저장소 어디서 실행해도 된다)
set -euo pipefail
cd "$(dirname "$0")"
if ! command -v xcodegen >/dev/null; then
  echo "xcodegen 설치: brew install xcodegen"; exit 1
fi
xcodegen generate
echo "완료: open dashboard/ipad/GoldenLinkPad.xcodeproj"
