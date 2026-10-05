#!/usr/bin/env bash
# 변환한 모델(Models/, 약 4.6GB)을 USB로 연결한 갤럭시의 앱 전용 폴더에 넣는다. APK에는 모델을 넣지 않는다(크기).
#   ./push-models.sh            # 모델 넣기(이미 같은 크기로 있는 파일은 건너뜀)
#   ./push-models.sh --install  # APK 설치까지
# 필요: 휴대폰 개발자 옵션 → USB 디버깅 켜기, PC와 연결 후 "이 컴퓨터 허용"
set -euo pipefail
export MSYS_NO_PATHCONV=1  # Windows Git Bash가 /sdcard 같은 기기 경로를 C:/Program Files/Git/... 로 바꾸지 않게
cd "$(dirname "$0")"
TOOLS="${GOLDENLINK_ANDROID_TOOLS:-$HOME/.goldenlink-android}"
ADB="$(command -v adb || true)"
[ -n "$ADB" ] || ADB="${ANDROID_HOME:-$TOOLS/sdk}/platform-tools/adb"
PKG=xyz.goldenlink.phone
DEST=/sdcard/Android/data/$PKG/files/models

"$ADB" get-state >/dev/null || { echo "휴대폰이 연결되지 않았습니다 — USB 디버깅을 켜고 '이 컴퓨터 허용'을 누르세요"; exit 1; }
if [ "${1:-}" = "--install" ]; then
  "$ADB" install -r GoldenLink.apk
fi
"$ADB" shell mkdir -p "$DEST"
for f in Models/*; do
  name=$(basename "$f")
  [ -d "$f" ] && continue
  local_size=$(stat -c %s "$f" 2>/dev/null || stat -f %z "$f")
  remote_size=$("$ADB" shell "stat -c %s $DEST/$name 2>/dev/null" | tr -d '\r' || true)
  if [ "$local_size" = "$remote_size" ]; then echo "같음: $name"; continue; fi
  echo "넣는 중: $name ($((local_size / 1048576))MB)"
  "$ADB" push "$f" "$DEST/$name"
done
echo "완료 — 앱을 다시 열면 하단에 '온디바이스 음성 인식·구조화'가 뜹니다"
