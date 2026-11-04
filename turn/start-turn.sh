#!/usr/bin/env bash
# start-all.sh가 생성한 설정을 받아 foreground 실행한다. 개별 실행은 README 참고.
set -euo pipefail
CONF=${1:?coturn 설정 파일 경로가 필요합니다}
TURN_BIN=${TURN_BIN:-$(command -v turnserver || true)}
if [ -z "$TURN_BIN" ] || [ ! -x "$TURN_BIN" ]; then
  echo 'coturn이 없습니다. macOS: brew install coturn / Ubuntu: sudo apt install coturn'
  echo 'TURN_BIN으로 turnserver 실행 파일의 절대 경로를 지정할 수 있습니다.'
  exit 1
fi
exec "$TURN_BIN" -c "$CONF" --pidfile=
