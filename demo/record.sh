#!/usr/bin/env bash
# [demo 브랜치] 시연 영상 녹화 — 시나리오마다 시연용 hub를 새로 띄워(고정 스냅샷) 재생하고 mp4로 남긴다.
# ⚠ develop에 병합하지 않는다(demo 브랜치 규칙).
#
# 사용법:
#   ./demo/record.sh 01            시나리오 01 녹화 → demo/out/scenario_01.mp4
#   ./demo/record.sh 01 05 12      여러 개
#   ./demo/record.sh all           demo/scenarios/*.json 전부
#   ./demo/record.sh --play 01     녹화 없이 화면으로만 재생(확인용)
#
# 먼저 떠 있어야 하는 것: voice(대본 구조화 — ./voice/start-voice.sh, demo 브랜치 코드). 나머지는 이 스크립트가 띄운다:
#   시연용 hub(포트 DEMO_HUB_PORT=5101, 기록은 임시 폴더) · 시연용 대시보드(DEMO_DASH_PORT=3100, next dev)
# 실서버(start-all.sh)와 동시에 떠 있어도 서로 섞이지 않는다.
#
# 카카오 지도: 대시보드 지도는 카카오 콘솔에 등록된 주소에서만 뜬다. http://localhost:3100 을 JavaScript SDK 도메인에
# 등록하거나, 실서버를 끄고 DEMO_DASH_PORT=3000 으로 녹화한다.
#
# 환경변수: DEMO_VOICE(기본 http://127.0.0.1:6000) · HUB_PY(hub 파이썬) · DEMO_HEADLESS=1(창 없이)
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEMO="$ROOT/demo"
HUB_PORT="${DEMO_HUB_PORT:-5101}"
DASH_PORT="${DEMO_DASH_PORT:-3100}"
export DEMO_HUB="http://127.0.0.1:$HUB_PORT"
export DEMO_DASH="http://localhost:$DASH_PORT"
export DEMO_VOICE="${DEMO_VOICE:-http://127.0.0.1:6000}"
LOG_DIR="${LOG_DIR:-${TMPDIR:-/tmp}/goldenlink-demo-logs}"
mkdir -p "$LOG_DIR" "$DEMO/out"

case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) OS=windows; export PYTHONUTF8=1 ;; Darwin) OS=mac ;; *) OS=linux ;; esac

PLAY_ONLY=0
IDS=()
for a in "$@"; do
  case "$a" in
    --play) PLAY_ONLY=1 ;;
    -h|--help) sed -n '2,21p' "$0"; exit 0 ;;
    all) for f in "$DEMO"/scenarios/*.json; do IDS+=("$(basename "$f" .json)"); done ;;
    *) IDS+=("$a") ;;
  esac
done
[ ${#IDS[@]} -gt 0 ] || { sed -n '2,21p' "$0"; exit 1; }

# hub 파이썬 찾기(start-all.sh와 같은 규칙, 간단히)
if [ -z "${HUB_PY:-}" ]; then
  for base in "${CONDA_ENVS:-}" "$HOME/anaconda3/envs" "$HOME/miniconda3/envs" /opt/anaconda3/envs /opt/homebrew/anaconda3/envs \
              "$( [ "$OS" = windows ] && cygpath -u "${USERPROFILE:-}" 2>/dev/null)/anaconda3/envs"; do
    [ -n "$base" ] || continue
    for c in "$base/rookie_hub/python.exe" "$base/rookie_hub/bin/python"; do [ -x "$c" ] && HUB_PY="$c" && break 2; done
  done
fi
[ -n "${HUB_PY:-}" ] && [ -x "$HUB_PY" ] || { echo "❌ hub 파이썬(rookie_hub)을 못 찾았습니다. HUB_PY=<경로> 로 지정하세요"; exit 1; }

port_busy(){ if [ "$OS" = windows ]; then netstat -ano | grep -q ":$1 .*LISTENING"; else lsof -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; fi; }
wait_http(){ for _ in $(seq 1 "${3:-90}"); do curl -s -o /dev/null --max-time 3 "$1" && return 0; sleep 2; done; echo "❌ $2 응답 없음"; return 1; }
kill_tree(){ if [ "$OS" = windows ]; then taskkill //F //T //PID "$1" >/dev/null 2>&1; else kill "$1" 2>/dev/null; fi; }

# voice 확인 — demo 브랜치 코드라야 대본 입구(/demo/structure)가 있다
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 -X POST -H "Content-Type: application/json" -d '{}' "$DEMO_VOICE/demo/structure")
case "$code" in
  400) ;;
  503) echo "⏳ voice가 아직 모델을 올리는 중입니다. 잠시 뒤 다시 실행하세요"; exit 1 ;;
  404) echo "❌ $DEMO_VOICE 에 대본 입구가 없습니다 — demo 브랜치에서 voice를 다시 띄우세요"; exit 1 ;;
  *) echo "❌ voice($DEMO_VOICE)에 연결할 수 없습니다(응답 $code). ./voice/start-voice.sh 로 먼저 띄우세요"; exit 1 ;;
esac

# 시연용 대시보드(next dev) — 없으면 띄운다
DASH_PID=""
if ! port_busy "$DASH_PORT"; then
  echo "시연용 대시보드 시작 (포트 $DASH_PORT)..."
  (cd "$ROOT/dashboard" && NEXT_PUBLIC_DASHBOARD_WS_URL="ws://127.0.0.1:$HUB_PORT/ws/dashboard" NEXT_PUBLIC_HUB_HTTP_URL="$DEMO_HUB" \
    exec npx next dev -p "$DASH_PORT") > "$LOG_DIR/dashboard.log" 2>&1 &
  DASH_PID=$!
  wait_http "$DEMO_DASH/demo-stage.html" "시연용 대시보드" 120 || exit 1
  for u in map "ambulance?id=A0000001" "phone?id=A0000001" "hospital?id=_"; do curl -s -o /dev/null --max-time 180 "$DEMO_DASH/$u"; done  # 첫 컴파일 미리
fi
cleanup(){ [ -n "${HUB_PID:-}" ] && kill_tree "$HUB_PID"; [ -n "$DASH_PID" ] && kill_tree "$DASH_PID"; }
trap cleanup EXIT INT TERM

cd "$DEMO" && [ -d node_modules ] || npm install --silent
FFMPEG="$DEMO/node_modules/ffmpeg-static/ffmpeg$( [ "$OS" = windows ] && echo .exe)"

for id in "${IDS[@]}"; do
  echo "━━ 시나리오 $id ━━"
  port_busy "$HUB_PORT" && { echo "❌ 포트 $HUB_PORT 가 이미 쓰이고 있습니다"; exit 1; }
  "$HUB_PY" -u "$DEMO/run_hub.py" > "$LOG_DIR/hub_$id.log" 2>&1 &
  HUB_PID=$!
  wait_http "$DEMO_HUB/identity?role=hospital&id=_" "시연용 hub" 120 || exit 1
  "$HUB_PY" "$DEMO/snapshot.py" load "$DEMO_HUB" | tail -1
  if [ "$PLAY_ONLY" = 1 ]; then
    node "$DEMO/player/play.mjs" "$id" || echo "⚠ 시나리오 $id 재생 실패(로그: $LOG_DIR/hub_$id.log)"
  else
    if node "$DEMO/player/play.mjs" "$id" --record --out "$DEMO/out"; then
      "$FFMPEG" -v error -y -i "$DEMO/out/scenario_$id.webm" -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p -movflags +faststart "$DEMO/out/scenario_$id.mp4" \
        && rm -f "$DEMO/out/scenario_$id.webm" && echo "✅ $DEMO/out/scenario_$id.mp4"
    else
      echo "⚠ 시나리오 $id 녹화 실패(로그: $LOG_DIR/hub_$id.log)"
    fi
  fi
  kill_tree "$HUB_PID"; HUB_PID=""
  sleep 2
done
