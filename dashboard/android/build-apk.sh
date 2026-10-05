#!/usr/bin/env bash
# APK 빌드 — Android Studio 없이 명령줄로. JDK 17·Android SDK 위치는 환경변수(JAVA_HOME·ANDROID_HOME)나 아래 기본 폴더
# (setup-tools.sh가 받아 두는 곳)를 쓴다. 결과: dashboard/android/GoldenLink.apk
set -euo pipefail
cd "$(dirname "$0")"
TOOLS="${GOLDENLINK_ANDROID_TOOLS:-$HOME/.goldenlink-android}"
if [ -z "${JAVA_HOME:-}" ]; then JAVA_HOME="$(ls -d "$TOOLS"/jdk-17* 2>/dev/null | head -1)"; export JAVA_HOME; fi
SDK="${ANDROID_HOME:-$TOOLS/sdk}"
[ -f local.properties ] || echo "sdk.dir=$(cd "$SDK" && pwd -W 2>/dev/null || pwd)" | sed 's#\#/#g' > local.properties
GRADLEW=./gradlew; [ -f gradlew.bat ] && [ "${OS:-}" = "Windows_NT" ] && GRADLEW=./gradlew.bat
$GRADLEW :core:test :app:assembleRelease --console=plain
cp app/build/outputs/apk/release/app-release.apk GoldenLink.apk
echo "완료: $(pwd)/GoldenLink.apk ($(du -h GoldenLink.apk | cut -f1))"
