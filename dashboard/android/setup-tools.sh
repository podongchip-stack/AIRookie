#!/usr/bin/env bash
# 빌드 도구(JDK 17 + Android SDK 명령줄 도구 + platform 35·build-tools·adb)를 ~/.goldenlink-android에 받는다.
# Android Studio·관리자 권한 없이 폴더 하나에 푼다(약 1.5GB). Windows(Git Bash)·macOS·Linux 공통. 한 번만 하면 된다.
set -euo pipefail
TOOLS="${GOLDENLINK_ANDROID_TOOLS:-$HOME/.goldenlink-android}"
mkdir -p "$TOOLS" && cd "$TOOLS"
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) os=windows; ctools=win; ext=zip ;;
  Darwin) os=mac; ctools=mac; ext=tar.gz ;;
  *) os=linux; ctools=linux; ext=tar.gz ;;
esac
arch=x64; [ "$(uname -m)" = "arm64" ] || [ "$(uname -m)" = "aarch64" ] && arch=aarch64

if ! ls -d jdk-17* >/dev/null 2>&1; then
  echo "JDK 17 받는 중…"
  curl -sL -o "jdk.$ext" "https://api.adoptium.net/v3/binary/latest/17/ga/$os/$arch/jdk/hotspot/normal/eclipse"
  if [ "$ext" = zip ]; then unzip -q "jdk.$ext"; else tar xzf "jdk.$ext"; fi
  rm "jdk.$ext"
fi
JDK="$(ls -d jdk-17* | head -1)"
[ -d "$JDK/Contents/Home" ] && JDK="$JDK/Contents/Home"  # macOS
export JAVA_HOME="$TOOLS/$JDK"

if [ ! -d sdk/cmdline-tools/latest ]; then
  echo "Android SDK 명령줄 도구 받는 중…"
  curl -sL -o cmdline.zip "https://dl.google.com/android/repository/commandlinetools-${ctools}-11076708_latest.zip"
  mkdir -p sdk/cmdline-tools && unzip -q cmdline.zip -d sdk/cmdline-tools && mv sdk/cmdline-tools/cmdline-tools sdk/cmdline-tools/latest
  rm cmdline.zip
fi
SDKMANAGER=sdk/cmdline-tools/latest/bin/sdkmanager; [ "$os" = windows ] && SDKMANAGER="$SDKMANAGER.bat"
yes | "$SDKMANAGER" --sdk_root="$TOOLS/sdk" --licenses >/dev/null 2>&1 || true
"$SDKMANAGER" --sdk_root="$TOOLS/sdk" "platform-tools" "platforms;android-35" "build-tools;35.0.0" >/dev/null
echo "완료: $TOOLS (JAVA_HOME=$JAVA_HOME)"
