#!/usr/bin/env bash
# 아이패드 구급차 앱 빌드 준비: XcodeGen으로 프로젝트를 만든다. 외부 패키지·모델 없음.
#   ./dashboard/ipad/setup.sh          (저장소 어디서 실행해도 된다)
#
# Xcode에서 고른 서명 팀(DEVELOPMENT_TEAM)은 생성물(.xcodeproj)에만 있어서 다시 만들면 지워진다 — 그래서 만들기 전에
# 지금 프로젝트(없으면 옆의 아이폰 프로젝트)의 팀을 읽어 두었다가 새 프로젝트에 다시 넣는다. 팀 ID는 커밋하지 않는다.
set -euo pipefail
cd "$(dirname "$0")"
if ! command -v xcodegen >/dev/null; then
  echo "xcodegen 설치: brew install xcodegen"; exit 1
fi
team_of(){ [ -f "$1" ] && grep -o 'DEVELOPMENT_TEAM = [A-Z0-9]\{10\};' "$1" | head -1 | sed 's/.*= \(.*\);/\1/' || true; }
TEAM="${DEVELOPMENT_TEAM:-$(team_of GoldenLinkPad.xcodeproj/project.pbxproj)}"
[ -z "$TEAM" ] && TEAM="$(team_of ../iphone/GoldenLinkPhone.xcodeproj/project.pbxproj)"
xcodegen generate
if [ -n "$TEAM" ]; then
  sed -i '' "s/DEVELOPMENT_TEAM = \"\";/DEVELOPMENT_TEAM = $TEAM;/g" GoldenLinkPad.xcodeproj/project.pbxproj
  echo "서명 팀 유지: $TEAM"
else
  echo "서명 팀 없음 — Xcode > Signing & Capabilities에서 Team을 고르세요"
fi
echo "완료: open dashboard/ipad/GoldenLinkPad.xcodeproj"
