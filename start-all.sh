#!/usr/bin/env bash
# 골든링크 전체 실행 — hub + info + dashboard + Cloudflare 터널 + TURN(설정 시)을 띄운다 (lidar3d는 --lidar로만).
#
# 도메인 하나(rookie-goldenlink.xyz)를 Cloudflare named 터널 하나로 나눠 쓴다:
#
#   https://app.rookie-goldenlink.xyz     /ws/dashboard, /identity, /route, /geocode, /verification, /rejection-stats, /case-archive, /hospital-backup → hub (127.0.0.1:5001)
#                                         /spider/*                  → spider 거미줄 3D (127.0.0.1:2700, spider/ 폴더가 있을 때만)
#                                         그 밖의 모든 경로           → dashboard (127.0.0.1:3000)
#   https://lidar.rookie-goldenlink.xyz   전체                        → lidar3d   (127.0.0.1:8000)
#
# 대시보드 페이지와 hub가 같은 호스트(app.*)라 브라우저 입장에서 동일 출처가 된다(CORS 불필요).
# hub의 나머지 경로(/info/*, /voice/*)는 터널 규칙에 없어서 인터넷에서는 404다 — info·voice는
# 지금처럼 LAN/로컬로 hub에 붙는다. lidar.* 는 아이폰 앱이 이미 쓰는 주소라 그대로 둔다.
#
# 처음 한 번만:
#   ./start-all.sh --setup-dns        app.* 호스트를 터널에 DNS로 연결 (Cloudflare에 CNAME 생성)
#
# 실행:
#   ./start-all.sh                    공개 모드 (도메인 주소로 접속)
#   ./start-all.sh --local            터널 없이 로컬 주소로만 (같은 Wi-Fi 시연·개발용)
#   ./start-all.sh --hotspot          아이폰 핫스팟의 Mac + 별도 모바일 데이터의 Android: 공개 터널 + STUN 직접 통화
#   ./start-all.sh --skip-build       dashboard 빌드 생략 (직전과 같은 모드로 띄울 때만!)
#   ./start-all.sh --no-info          info(병원 정보 주기 전송)·E-Gen 스냅샷 동기화·거절 로그 수신구 생략
#   ./start-all.sh --no-snapshot      E-Gen 스냅샷 동기화(클라우드 수집분 내려받기)만 생략
#   ./start-all.sh --no-sim-dispatch  구급차 출동 시뮬레이션(가짜 GPS) 끄기 — 기본은 켬: 실제 구급차 GPS 수신
#                                     경로가 아직 없어 구급차 화면의 [이동] 버튼으로 위치를 만든다
#   ./start-all.sh --dashboard-call   구급차 대시보드에도 [통화 시작] 버튼(마이크 파형) — 기본은 끔: 통화는 대원 휴대폰
#                                     전화 앱(첫 페이지 P-<구급차ID>)으로만 하고, 대시보드엔 통화 현황·자막만 보인다.
#                                     --no-sim-dispatch면 휴대폰 앱을 쓸 수 없어 자동으로 켠다
#   ./start-all.sh --lidar            lidar3d(3D 뷰어·아이폰 앱 업로드 서버)도 함께 — 병원 대시보드에 3D 버튼이 생긴다
#                                     (기본은 끔: 3D는 당분간 시연에서 뺀다. 끄면 버튼도 자동으로 숨겨진다)
#   ./start-all.sh --no-spider        spider 거미줄 3D 서버 생략 — 기본은 spider/ 폴더가 있으면 켬(/spider/ 로 열린다,
#                                     아이패드 앱이 이 주소를 WebView로 띄운다). 계산은 서버가 하고 화면은 그리기만 한다
#   ./start-all.sh --turn             TURN 설정 필수로 실행 (turn/.env, coturn 필요). 설정이 있으면 기본 실행
#   ./start-all.sh --no-turn          TURN 생략 (STUN만, 다른 모바일 데이터망 통화 보장 안 됨)
#
# voice는 여기서 띄우지 않는다 — 따로 ./voice/start-voice.sh(인자 없이 = 중앙 voice 1대, 휴대폰·대시보드 브라우저 음성을
# hub 경유로 받음. 구급차 번호를 주면 그 장비 마이크 전용). HUB_BASE_URL로 이 hub를 가리킨다.
# Ctrl-C 한 번으로 띄운 것 전부를 함께 끈다. 로그는 $LOG_DIR 아래에 서버별로 남는다.
#
# macOS·Linux·Windows(Git Bash) 어디서든 같은 명령으로 돈다 — OS를 보고 conda 환경의 파이썬 위치
# (bin/python ↔ python.exe), 포트 검사 도구(lsof ↔ netstat), 종료 방식을 고른다. Windows는 반드시
# Git Bash에서 실행할 것(PowerShell·cmd에서는 bash 스크립트가 안 돈다). 자동 탐지가 틀리면
# CONDA_ENVS(envs 폴더) 또는 HUB_PY/INFO_PY/LIDAR_PY(파이썬 경로)로 직접 지정한다.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

case "$(uname -s)" in
  Darwin)               OS=mac ;;
  MINGW*|MSYS*|CYGWIN*) OS=windows ;;
  *)                    OS=linux ;;
esac

# Windows 기본 인코딩(cp949)으로는 로그의 이모지 등을 못 써서 파이썬이 죽을 수 있다.
[ "$OS" = windows ] && export PYTHONUTF8="${PYTHONUTF8:-1}"

# conda envs 폴더 찾기: CONDA_ENVS 지정값 → 흔한 설치 위치 → `conda info --base`.
# 맥은 예전 기본값(/opt/anaconda3/envs)을 맨 앞에 둬서 동작이 그대로다.
find_conda_envs(){
  local c base
  local cands=(/opt/anaconda3/envs /opt/miniconda3/envs /opt/homebrew/anaconda3/envs
               "$HOME/anaconda3/envs" "$HOME/miniconda3/envs" "$HOME/miniforge3/envs")
  if [ "$OS" = windows ] && [ -n "${USERPROFILE:-}" ]; then
    local up; up="$(cygpath -u "$USERPROFILE" 2>/dev/null || echo "$USERPROFILE")"
    cands+=("$up/anaconda3/envs" "$up/miniconda3/envs" "$up/miniforge3/envs"
            /c/ProgramData/anaconda3/envs /c/ProgramData/miniconda3/envs)
  fi
  for c in "${cands[@]}"; do [ -d "$c" ] && { echo "$c"; return; }; done
  if command -v conda >/dev/null 2>&1; then
    base="$(conda info --base 2>/dev/null | tr -d '\r')"
    [ "$OS" = windows ] && base="$(cygpath -u "$base" 2>/dev/null || echo "$base")"
    [ -n "$base" ] && [ -d "$base/envs" ] && { echo "$base/envs"; return; }
  fi
  echo /opt/anaconda3/envs  # 못 찾으면 예전 기본값 — 아래 need()가 경로와 함께 알려준다
}
CONDA_ENVS="${CONDA_ENVS:-$(find_conda_envs)}"
# conda 환경의 파이썬: 맥·리눅스는 <env>/bin/python, Windows는 <env>/python.exe
env_py(){ if [ "$OS" = windows ]; then echo "$CONDA_ENVS/$1/python.exe"; else echo "$CONDA_ENVS/$1/bin/python"; fi; }
HUB_PY="${HUB_PY:-$(env_py rookie_hub)}"
INFO_PY="${INFO_PY:-$(env_py rookie_info)}"
LIDAR_PY="${LIDAR_PY:-$(env_py labs)}"
SPIDER_PY="${SPIDER_PY:-$INFO_PY}"   # spider 엔진은 numpy·scipy·flask뿐이라 info 환경을 그대로 쓴다

case "$OS" in
  mac)     CF_INSTALL="brew install cloudflared" ;;
  windows) CF_INSTALL="winget install Cloudflare.cloudflared" ;;
  *)       CF_INSTALL="https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/" ;;
esac

# cloudflared 실행 파일과 인증 폴더(.cloudflared: cert.pem + <터널ID>.json) 찾기.
# Windows: winget 설치 직후엔 이미 열려 있던 터미널의 PATH에 안 잡혀서 기본 설치 위치도 본다.
# 또 cloudflared는 HOME 기준으로 .cloudflared를 찾는데, 다른 프로그램이 Windows 사용자
# 환경변수 HOME을 사용자 폴더가 아닌 곳으로 바꿔 둔 장비가 있다(실제로 겪음). 그럴 땐
# HOME 전체를 건드리지 않고 cloudflared를 부를 때만 사용자 폴더(USERPROFILE)를 보게 한다.
CF_BIN="$(command -v cloudflared 2>/dev/null || true)"
if [ -z "$CF_BIN" ] && [ "$OS" = windows ]; then
  for c in "/c/Program Files (x86)/cloudflared/cloudflared.exe" "/c/Program Files/cloudflared/cloudflared.exe"; do
    [ -x "$c" ] && { CF_BIN="$c"; break; }
  done
fi
CF_HOME="$HOME"
if [ "$OS" = windows ] && [ ! -d "$HOME/.cloudflared" ] && [ -n "${USERPROFILE:-}" ]; then
  UP_DIR="$(cygpath -u "$USERPROFILE" 2>/dev/null || echo "$USERPROFILE")"
  [ -d "$UP_DIR/.cloudflared" ] && CF_HOME="$UP_DIR"
fi
cf(){ HOME="$CF_HOME" "$CF_BIN" "$@"; }

TUNNEL_NAME="${TUNNEL_NAME:-lidar}"
APP_HOST="${APP_HOST:-app.rookie-goldenlink.xyz}"
LIDAR_HOST="${LIDAR_HOST:-lidar.rookie-goldenlink.xyz}"

HUB_PORT=5001          # dashboard·info·voice가 모두 이 포트를 기본값으로 알고 있다
DASH_PORT="${DASH_PORT:-3000}"
LIDAR_PORT="${LIDAR_PORT:-8000}"
SPIDER_PORT="${SPIDER_PORT:-2700}"   # 2700: spider 전용 — 2700 spider · 3000 dashboard · 5000대 hub/info · 8000 lidar3d 순. 5000·7000은 macOS AirPlay 수신기가 잡고 있어 피했다
LOG_DIR="${LOG_DIR:-/tmp/goldenlink-logs}"

MODE=public; BUILD=1; RUN_INFO=1; RUN_SNAPSHOT=1; RUN_LIDAR=0; SIM_DISPATCH=1; DASHBOARD_CALL=0
RUN_TURN=auto
RUN_SPIDER=0; [ -f spider/serve.py ] && RUN_SPIDER=1   # spider/ 가 없는 체크아웃(옛 develop·다른 브랜치)에서는 조용히 건너뛴다
for a in "$@"; do
  case "$a" in
    --local)      MODE=local ;;
    --hotspot)    MODE=public; RUN_TURN=0 ;;
    --skip-build) BUILD=0 ;;
    --no-info)    RUN_INFO=0 ;;
    --no-snapshot) RUN_SNAPSHOT=0 ;;
    --sim-dispatch) SIM_DISPATCH=1 ;;  # 예전 옵션 — 이제 기본값이라 없어도 된다
    --no-sim-dispatch) SIM_DISPATCH=0 ;;
    --dashboard-call) DASHBOARD_CALL=1 ;;
    --lidar)      RUN_LIDAR=1 ;;
    --no-lidar)   RUN_LIDAR=0 ;;  # 예전 옵션 — 이제 기본값이라 없어도 된다
    --spider)     RUN_SPIDER=1 ;;
    --no-spider)  RUN_SPIDER=0 ;;
    --turn)       RUN_TURN=1 ;;
    --no-turn)    RUN_TURN=0 ;;
    --setup-dns)
      [ -n "$CF_BIN" ] || { echo "❌ cloudflared가 없습니다: $CF_INSTALL"; exit 1; }
      echo "터널 '$TUNNEL_NAME'에 $APP_HOST 를 연결합니다 (Cloudflare DNS에 CNAME 생성)..."
      cf tunnel route dns "$TUNNEL_NAME" "$APP_HOST"
      exit $? ;;
    -h|--help) sed -n '2,/^set -uo pipefail/{ /^set -uo pipefail/d; p; }' "$0"; exit 0 ;;
    *) echo "❌ 알 수 없는 옵션: $a (도움말: --help)"; exit 1 ;;
  esac
done

mkdir -p "$LOG_DIR"
PIDS=()
cleanup(){
  echo; echo "정리 중..."
  for p in "${PIDS[@]:-}"; do
    [ -n "$p" ] || continue
    # Windows: Git Bash의 kill은 그 프로세스만 끄므로, npx → node처럼 자식을 띄우는 것까지
    # 확실히 끄려고 Windows 프로세스 트리째 먼저 끈다.
    if [ "$OS" = windows ] && [ -r "/proc/$p/winpid" ]; then
      taskkill //F //T //PID "$(cat "/proc/$p/winpid")" >/dev/null 2>&1
    fi
    kill "$p" 2>/dev/null
  done
  wait 2>/dev/null
  [ -z "${TURN_CONF:-}" ] || rm -f -- "$TURN_CONF"
  echo "모두 종료했습니다."
}
trap cleanup EXIT INT TERM

need(){ [ -x "$1" ] || { echo "❌ $2 파이썬이 없습니다: $1 (환경변수 $3 로 경로 지정 가능, 감지된 OS: $OS)"; exit 1; }; }

# TURN은 HTTP Cloudflare 터널을 통과하지 않는다. 이 장비의 포트 전달 또는 별도 공인 서버 필요.
# 환경 파일은 로컬 신뢰 설정이며 비밀값을 포함한다(.gitignore의 .env 규칙으로 제외).
TURN_ENV_FILE="${TURN_ENV_FILE:-$ROOT/turn/.env}"
if [ "$RUN_TURN" != 0 ] && [ -f "$TURN_ENV_FILE" ]; then
  set -a
  source "$TURN_ENV_FILE" || exit 1
  set +a
fi
if [ "$RUN_TURN" = auto ]; then
  RUN_TURN=0
  [ -n "${TURN_HOST:-}${HUB_TURN_URLS:-}" ] && RUN_TURN=1
fi
if [ -z "${TURN_MODE:-}" ]; then
  TURN_MODE=local
  [ -n "${HUB_TURN_URLS:-}" ] && [ -z "${TURN_HOST:-}" ] && TURN_MODE=external
fi
if [ "$RUN_TURN" = 1 ]; then
  need "$HUB_PY" hub HUB_PY
  case "$TURN_MODE" in
    local)
      TURN_BIN="${TURN_BIN:-$(command -v turnserver 2>/dev/null || true)}"
      [ -x "$TURN_BIN" ] || { echo '❌ coturn 필요: macOS는 brew install coturn, Ubuntu는 sudo apt install coturn (또는 TURN_MODE=external)'; exit 1; }
      export TURN_BIN
      # mktemp로 실행별 설정을 분리하며 비밀값은 인자나 로그에 출력하지 않는다.
      TURN_CONF=$(mktemp "$LOG_DIR/turn.XXXXXX") || exit 1
      HUB_TURN_URLS=$("$HUB_PY" "$ROOT/turn/configure.py" "$TURN_CONF") || exit 1
      ;;
    external)
      [ -n "${HUB_TURN_URLS:-}" ] && [ -n "${HUB_TURN_SECRET:-}" ] \
        || { echo '❌ 외부 TURN: HUB_TURN_URLS와 HUB_TURN_SECRET을 지정하세요'; exit 1; }
      ;;
    *) echo '❌ TURN_MODE는 local 또는 external이어야 합니다'; exit 1 ;;
  esac
  export HUB_TURN_URLS HUB_TURN_SECRET
else
  unset HUB_TURN_URLS HUB_TURN_SECRET
  echo '⚠️  TURN 꺼짐: 서로 다른 모바일 데이터망 통화는 아직 보장되지 않습니다 (turn/.env 설정 후 --turn).'
fi

# 띄우기 전에 포트가 비어 있는지 먼저 본다. 다른 프로그램이 이미 그 포트를 쓰고 있으면 우리
# 서버는 바로 죽는데, 아래 wait_http는 그 다른 프로그램의 응답을 "준비 완료"로 착각한다
# (실제로 3000번을 다른 프로젝트 백엔드가 쓰고 있어서 겪었다).
# lsof가 없는 Windows(Git Bash)는 netstat, lsof 없는 리눅스는 ss로 본다. 도구가 하나도 없으면
# 예전처럼 검사 없이 넘어간다.
port_owner(){  # 포트 → "프로그램 (pid N)" 또는 빈 값
  if [ "$OS" = windows ]; then
    local pid name
    pid=$(netstat -ano -p TCP 2>/dev/null | tr -d '\r' \
          | awk -v p=":$1" '$4=="LISTENING" && substr($2, length($2)-length(p)+1)==p {print $5; exit}')
    [ -z "$pid" ] && return 0
    name=$(tasklist //FI "PID eq $pid" //FO CSV //NH 2>/dev/null | tr -d '\r' | head -1 | cut -d'"' -f2)
    echo "${name:-?} (pid $pid)"
  elif command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | awk 'NR==2{print $1" (pid "$2")"}'
  elif command -v ss >/dev/null 2>&1; then
    ss -ltnpH "sport = :$1" 2>/dev/null | head -1 | sed -n 's/.*users:(("\([^"]*\)",pid=\([0-9]*\).*/\1 (pid \2)/p'
  fi
}
port_free(){  # 이름, 포트, 바꿀 때 쓸 환경변수
  local owner
  owner=$(port_owner "$2")
  [ -z "$owner" ] && return 0
  echo "❌ $1 포트 $2 를 이미 $owner 가 쓰고 있습니다."
  [ -n "$3" ] && echo "   그 프로그램을 끄거나 다른 포트로 실행하세요: $3=<다른 포트> ./start-all.sh"
  exit 1
}
port_free hub "$HUB_PORT" ""
[ "$RUN_INFO" = 1 ] && port_free "거절 로그 수신구" 5003 ""
port_free dashboard "$DASH_PORT" DASH_PORT
[ "$RUN_LIDAR" = 1 ] && port_free lidar3d "$LIDAR_PORT" LIDAR_PORT
[ "$RUN_SPIDER" = 1 ] && port_free spider "$SPIDER_PORT" SPIDER_PORT
[ "$RUN_TURN" = 1 ] && [ "$TURN_MODE" = local ] && port_free TURN "${TURN_PORT:-3478}" TURN_PORT

# 포트가 응답할 때까지 기다린다. 먼저 뜬 서버 없이 다음 단계로 가면 연결 실패(502 등)가 난다.
wait_http(){  # 이름, URL, pid, 로그, 최대초
  local name=$1 url=$2 pid=$3 log=$4 max=${5:-60}
  for _ in $(seq 1 "$max"); do
    curl -s -o /dev/null -m 2 "$url" && { echo "  ✅ $name 준비 완료"; return 0; }
    kill -0 "$pid" 2>/dev/null || { echo "❌ $name 가 죽었습니다:"; tail -20 "$log"; exit 1; }
    sleep 1
  done
  echo "❌ $name 가 ${max}초 안에 응답하지 않습니다:"; tail -20 "$log"; exit 1
}

# ── lidar3d 토큰 (serve_public.sh와 같은 파일을 공유한다 — 아이폰 앱에 입력한 값 유지) ──
LIDAR_TOKEN=""
if [ "$RUN_LIDAR" = 1 ]; then
  need "$LIDAR_PY" lidar3d LIDAR_PY
  TOKEN_FILE="lidar3d/.lidar_token"
  if [ -n "${LIDAR_TOKEN_OVERRIDE:-}" ]; then
    LIDAR_TOKEN="$LIDAR_TOKEN_OVERRIDE"
  elif [ -f "$TOKEN_FILE" ]; then
    LIDAR_TOKEN="$(cat "$TOKEN_FILE")"
  else
    LIDAR_TOKEN="$("$LIDAR_PY" -c 'import secrets;print(secrets.token_urlsafe(18))')"
    echo "$LIDAR_TOKEN" > "$TOKEN_FILE"; chmod 600 "$TOKEN_FILE"
    echo "새 lidar3d 토큰을 $TOKEN_FILE 에 저장했습니다 (git에 올리지 마세요)."
  fi
fi

# ── 모드별 주소 ──
if [ "$MODE" = public ]; then
  [ -n "$CF_BIN" ] || { echo "❌ cloudflared가 없습니다: $CF_INSTALL (또는 --local)"; exit 1; }
  DASH_URL="https://$APP_HOST"
  WS_URL="wss://$APP_HOST/ws/dashboard"      # https 페이지에서는 ws:// 가 차단된다
  HUB_HTTP_URL="https://$APP_HOST"
  VIEWER_BASE="https://$LIDAR_HOST"
  DASH_BIND=127.0.0.1                        # 공개 모드에선 터널로만 들어오게
else
  # 127.0.0.1이 아니라 localhost로 안내한다 — 카카오맵 키는 등록된 주소(http://localhost:3000)에서만 뜬다.
  DASH_URL="http://localhost:$DASH_PORT"
  WS_URL="ws://127.0.0.1:$HUB_PORT/ws/dashboard"
  HUB_HTTP_URL="http://127.0.0.1:$HUB_PORT"
  VIEWER_BASE="http://127.0.0.1:$LIDAR_PORT"
  DASH_BIND=0.0.0.0
fi
VIEWER_URL=""
[ "$RUN_LIDAR" = 1 ] && VIEWER_URL="$VIEWER_BASE/viewer/?token=$LIDAR_TOKEN"

# ── 0. TURN (음성 릴레이, hub는 통화 신호만 중계) ──
if [ "$RUN_TURN" = 1 ]; then
  if [ "$TURN_MODE" = local ]; then
    echo "TURN 시작 (UDP/TCP ${TURN_PORT:-3478}, 릴레이 UDP ${TURN_MIN_PORT:-49160}~${TURN_MAX_PORT:-49259})..."
    bash "$ROOT/turn/start-turn.sh" "$TURN_CONF" > "$LOG_DIR/turn.log" 2>&1 &
    TURN_PID=$!; PIDS+=("$TURN_PID")
    # 단순 생존만으로 성공 처리하지 않고 coturn 리스너가 열린 뒤 hub를 시작한다.
    "$HUB_PY" -c 'import socket, sys, time
for _ in range(50):
    try:
        with socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=.2):
            sys.exit(0)
    except OSError:
        time.sleep(.1)
sys.exit(1)' "${TURN_PORT:-3478}" \
      || { echo "❌ TURN 리스너 준비 실패. $LOG_DIR/turn.log 확인"; exit 1; }
    kill -0 "$TURN_PID" 2>/dev/null || { echo "❌ TURN 프로세스 종료. $LOG_DIR/turn.log 확인"; exit 1; }
    echo '  ✅ TURN 로컬 리스너 준비 완료 (외부망 중계 검증은 별도)'
  else
    echo '외부 TURN 사용 (원격 서버는 여기서 시작/종료하지 않습니다).'
  fi
fi

# ── 1. hub ──
# 포트를 이 스크립트가 정하려고 app.py의 __main__ 대신 직접 띄운다. debug는 끈다 — 디버그 모드가
# 외부에 닿으면 원격 코드 실행 위험이 있다. 0.0.0.0은 유지한다: 구급차 노트북의 voice가 LAN으로 붙어야 한다.
need "$HUB_PY" hub HUB_PY
echo "hub 시작 (포트 $HUB_PORT, 임베딩 모델 로드에 시간이 걸릴 수 있음)..."
# start_background(): 60초 재계산·상태 저장/복구·방치 사건 정리(와 출동 시뮬레이션) 루프. 예전엔
# app.app.run()만 불러서 이 루프들이 start-all로 띄운 실서버에서는 한 번도 돌지 않았다(2026-10-01 수정).
# 휴대폰 전화 앱은 출동 시뮬레이션의 사건으로만 통화한다 — 시뮬레이션을 끄면 통화할 곳이 없어지므로 대시보드 통화를 켠다.
if [ "$SIM_DISPATCH" = 0 ] && [ "$DASHBOARD_CALL" = 0 ]; then
  DASHBOARD_CALL=1
  echo "  출동 시뮬레이션이 꺼져 휴대폰 전화 앱을 쓸 수 없어, 구급차 대시보드의 [통화 시작]을 켭니다"
fi
if [ "$DASHBOARD_CALL" = 1 ]; then echo "  통화: 구급차 대시보드 [통화 시작] + 휴대폰 전화 앱"; else echo "  통화: 휴대폰 전화 앱(P-<구급차ID>)으로만 — 대시보드 버튼은 --dashboard-call"; fi
(cd hub && HUB_SIM_DISPATCH="$SIM_DISPATCH" HUB_DASHBOARD_CALL="$DASHBOARD_CALL" exec "$HUB_PY" -u -c \
    "import app; app.start_background(); app.app.run(host='0.0.0.0', port=$HUB_PORT, debug=False)") \
  > "$LOG_DIR/hub.log" 2>&1 &
HUB_PID=$!; PIDS+=("$HUB_PID")
wait_http hub "http://127.0.0.1:$HUB_PORT/identity?role=hospital&id=_" "$HUB_PID" "$LOG_DIR/hub.log" 180

# ── 2. info (병원 정보를 hub로 주기 전송하는 상시 프로세스) ──
if [ "$RUN_INFO" = 1 ]; then
  need "$INFO_PY" info INFO_PY
  echo "info 시작 (병원 정보 → hub, 기본 30분 주기)..."
  "$INFO_PY" -u info/send_to_hub.py > "$LOG_DIR/info.log" 2>&1 &
  PIDS+=("$!")
  # 거절 로그 수신구(포트 5003). hub가 병원 거절·도착 후 수용 불가·무응답을 그때 화면에 보였던 병상 수·
  # 신뢰도 확률과 함께 보낸다 — 신뢰도 모델의 정답(G2 라벨) 재료라 안 띄우면 그 기간 로그는 영영 사라진다
  # (소급 생성 불가). 예전엔 따로 켜야 해서 실제로는 버려지고 있었다(2026-10-01 기본 실행).
  echo "거절 로그 수신구 시작 (포트 5003)..."
  (cd info/Hospital_inform/info && PYTHONIOENCODING=utf-8 exec "$INFO_PY" -u -m hospital_score.ingest) \
      > "$LOG_DIR/rejection.log" 2>&1 &
  PIDS+=("$!")
  # E-Gen 스냅샷은 2026-10-04부터 클라우드(Supabase Edge Function, pg_cron 5분 — 2026-10-10 20분에서 단축)가 수집한다
  # — 수집 장비(노트북)를 들고 이동해도 관측이 안 끊기게 하기 위한 이관. 여기서는 로컬 수집기
  # (info/snapshot.py) 대신 그 수집분을 내려받아 snapshots_nationwide/를 복원한다
  # (snapshot_cloud.py --sync — 신뢰도 보드·live_board가 읽는 건 여전히 로컬 파일이라 소비 코드 불변).
  # SNAPSHOT_SUPABASE_URL이 .env에 없으면 건너뛴다(fail-soft). SERVICE_KEY까지 있는 장비(과거
  # 로컬 수집분을 가진 노트북)는 완결된 날짜를 먼저 --seed로 올려 클라우드 아카이브를 메꾼다.
  if [ "$RUN_SNAPSHOT" = 1 ]; then
    INFO_ENV="info/Hospital_inform/.env"
    if grep -q '^SNAPSHOT_SUPABASE_URL=' "$INFO_ENV" 2>/dev/null; then
      echo "E-Gen 스냅샷 동기화 시작 (클라우드 → 로컬, 새 수집분이 생기면 바로 — 첫 실행은 과거분 전체라 오래 걸릴 수 있음)..."
      # --watch(2026-10-04): 클라우드 수집기가 올리는 것을 1분마다 확인해 생기면 바로 sync — 예전 20분 고정
      # 주기보다 그래프 반영이 빠르다. SERVICE_KEY 있는 장비의 --seed는 감시 안에서 20분마다 그대로 한다.
      (cd info/Hospital_inform/info && export PYTHONIOENCODING=utf-8 && \
          exec "$INFO_PY" -u snapshot_cloud.py --watch) > "$LOG_DIR/snapshot.log" 2>&1 &
      PIDS+=("$!")
    else
      echo "⚠️  $INFO_ENV 에 SNAPSHOT_SUPABASE_URL이 없어 스냅샷 동기화를 건너뜁니다 — 신뢰도 보드가 이 장비의 과거 수집분만 봅니다."
    fi
  fi
fi

# ── 3. lidar3d (3D 뷰어) ──
if [ "$RUN_LIDAR" = 1 ]; then
  echo "lidar3d 시작 (포트 $LIDAR_PORT)..."
  (cd lidar3d && LIDAR_TOKEN="$LIDAR_TOKEN" exec "$LIDAR_PY" -u -m uvicorn server.app:app \
      --host 0.0.0.0 --port "$LIDAR_PORT") > "$LOG_DIR/lidar3d.log" 2>&1 &
  LIDAR_PID=$!; PIDS+=("$LIDAR_PID")
  wait_http lidar3d "http://127.0.0.1:$LIDAR_PORT/health?token=$LIDAR_TOKEN" "$LIDAR_PID" "$LOG_DIR/lidar3d.log" 60
fi

# ── 3b. spider (거미줄 3D — 2026-10-14) ──
# 화면(spider/web)은 그리기만 하고 계산(줄 길이·충돌·재투척·도로 최단경로)은 이 파이썬 서버가 한다. 도로 그래프 25 MB를
# 브라우저가 내려받지 않아 아이패드 WebView에서도 가볍다. 경로 접두어 /spider 는 터널 규칙(아래 5)과 짝이다.
if [ "$RUN_SPIDER" = 1 ]; then
  need "$SPIDER_PY" spider SPIDER_PY
  echo "spider 시작 (포트 $SPIDER_PORT, 도로 그래프 로드에 몇 초)..."
  # SPIDER_HUB_WS_URL: 실시간 모드(/spider/?mode=live)가 붙을 hub 소켓 — 공개 모드는 터널 주소, 로컬은 127.0.0.1:5001
  # SPIDER_HUB_HTTP_URL: 거미줄 제안이 hub와 같은 병원 재료로 계산하도록 spider 서버가 가져가는 hub /hospital-features(같은 맥이라 로컬)
  # (아이패드가 LAN으로 열면 화면이 127.0.0.1을 자기 접속 호스트로 바꿔 쓴다)
  (cd spider && MSYS_NO_PATHCONV=1 SPIDER_PREFIX=/spider SPIDER_HUB_WS_URL="$WS_URL" SPIDER_HUB_HTTP_URL="http://127.0.0.1:$HUB_PORT" exec "$SPIDER_PY" -u serve.py --host 0.0.0.0 --port "$SPIDER_PORT") \
      > "$LOG_DIR/spider.log" 2>&1 &
  SPIDER_PID=$!; PIDS+=("$SPIDER_PID")
  wait_http spider "http://127.0.0.1:$SPIDER_PORT/spider/api/health" "$SPIDER_PID" "$LOG_DIR/spider.log" 120
fi

# ── 4. dashboard ──
# NEXT_PUBLIC_* 값은 빌드할 때 코드에 박힌다. 그래서 모드(공개/로컬)가 바뀌면 반드시 다시 빌드해야 한다.
# 여기서 넘기는 환경변수가 dashboard/.env.local 보다 우선한다.
export NEXT_PUBLIC_DASHBOARD_WS_URL="$WS_URL"
export NEXT_PUBLIC_HUB_HTTP_URL="$HUB_HTTP_URL"
export NEXT_PUBLIC_LIDAR_VIEWER_URL="$VIEWER_URL"
# 서버측(Next 라우트 핸들러) 전용 — 공개 모드에선 NEXT_PUBLIC_HUB_HTTP_URL이 터널 도메인인데
# 터널은 /voice/* 를 hub로 안 넘기므로(의도적), Next→hub 서버간 호출은 루프백으로 직접 간다.
# NEXT_PUBLIC_이 아니라 빌드에 안 박히고 next start가 실행 시점에 읽는다.
export HUB_INTERNAL_HTTP_URL="http://127.0.0.1:$HUB_PORT"

# 카카오맵 키는 접속 주소마다 따로 발급돼 있다(콘솔의 JavaScript SDK 도메인). 로컬 모드는
# .env.local의 NEXT_PUBLIC_KAKAO_MAP_APP_KEY(localhost용)를 그대로 쓰고, 도메인 모드는
# 같은 파일의 KAKAO_MAP_APP_KEY_PUBLIC(app.* 용)을 넣는다. 없으면 경고만 하고 진행한다
# (지도만 안 뜨고 매칭·승인은 정상 동작).
if [ "$MODE" = public ]; then
  KAKAO_PUBLIC="$(grep -E '^KAKAO_MAP_APP_KEY_PUBLIC=' dashboard/.env.local 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"' ')"
  if [ -n "$KAKAO_PUBLIC" ]; then
    export NEXT_PUBLIC_KAKAO_MAP_APP_KEY="$KAKAO_PUBLIC"
  else
    echo "⚠️  dashboard/.env.local에 KAKAO_MAP_APP_KEY_PUBLIC이 없어 $APP_HOST 에서 지도가 안 뜰 수 있습니다."
  fi
fi
if [ "$BUILD" = 1 ]; then
  echo "dashboard 빌드 중 ($MODE 모드 주소로)..."
  (cd dashboard && npm run build) > "$LOG_DIR/dashboard-build.log" 2>&1 \
    || { echo "❌ dashboard 빌드 실패:"; tail -30 "$LOG_DIR/dashboard-build.log"; exit 1; }
fi
echo "dashboard 시작 (포트 $DASH_PORT)..."
(cd dashboard && exec npx next start -p "$DASH_PORT" -H "$DASH_BIND") > "$LOG_DIR/dashboard.log" 2>&1 &
DASH_PID=$!; PIDS+=("$DASH_PID")
wait_http dashboard "http://127.0.0.1:$DASH_PORT/" "$DASH_PID" "$LOG_DIR/dashboard.log" 60

# ── 5. Cloudflare 터널 (공개 모드만) ──
if [ "$MODE" = public ]; then
  TUNNEL_CONF="$LOG_DIR/cloudflared.yml"
  {
    echo "# start-all.sh가 실행할 때마다 새로 쓴다 — 직접 고치지 말고 스크립트를 고칠 것"
    echo "ingress:"
    echo "  - hostname: $APP_HOST"
    echo "    path: ^/(ws/dashboard|identity|route|geocode|verification|rejection-stats|case-archive|hospital-backup)"
    echo "    service: http://127.0.0.1:$HUB_PORT"
    if [ "$RUN_SPIDER" = 1 ]; then
      echo "  - hostname: $APP_HOST"
      echo "    path: ^/spider(/|$)"
      echo "    service: http://127.0.0.1:$SPIDER_PORT"
    fi
    echo "  - hostname: $APP_HOST"
    echo "    service: http://127.0.0.1:$DASH_PORT"
    if [ "$RUN_LIDAR" = 1 ]; then
      echo "  - hostname: $LIDAR_HOST"
      echo "    service: http://127.0.0.1:$LIDAR_PORT"
    fi
    echo "  - service: http_status:404"
  } > "$TUNNEL_CONF"
  cf tunnel --config "$TUNNEL_CONF" ingress validate >/dev/null 2>&1 \
    || { echo "❌ 터널 설정이 잘못됐습니다:"; cf tunnel --config "$TUNNEL_CONF" ingress validate; exit 1; }
  echo "Cloudflare 터널 '$TUNNEL_NAME' 연결 중..."
  (HOME="$CF_HOME" exec "$CF_BIN" tunnel --no-autoupdate --config "$TUNNEL_CONF" run "$TUNNEL_NAME") > "$LOG_DIR/cloudflared.log" 2>&1 &
  CF_PID=$!; PIDS+=("$CF_PID")
  for _ in $(seq 1 45); do
    grep -q "Registered tunnel connection" "$LOG_DIR/cloudflared.log" && break
    kill -0 "$CF_PID" 2>/dev/null || { echo "❌ 터널이 죽었습니다:"; tail -20 "$LOG_DIR/cloudflared.log"; exit 1; }
    sleep 1
  done
  grep -q "Registered tunnel connection" "$LOG_DIR/cloudflared.log" \
    || { echo "❌ 터널이 연결되지 않았습니다:"; tail -20 "$LOG_DIR/cloudflared.log"; exit 1; }
  echo "  ✅ 터널 연결 완료"
fi

cat <<BANNER

==============================================================
  골든링크 실행 중 ($MODE 모드)
==============================================================
  🗺️ 관제 지도       $DASH_URL/map   (보기 전용 — 병원 이름 옆 H-<hpid>가 병원 접근 코드)
  🏥 병원 대시보드    $DASH_URL/hospital?id=<병원 hpid>
  🚑 구급차 대시보드  $DASH_URL/ambulance?id=<구급차 apid>
  🔑 코드 입력 화면   $DASH_URL/   (병원 H-<hpid>, 구급차 A-<apid>)
BANNER
if [ "$RUN_SPIDER" = 1 ]; then
  if [ "$MODE" = public ]; then echo "  🕸️ 거미줄 3D       $DASH_URL/spider/   (아이패드 앱 WebView 주소)"; else echo "  🕸️ 거미줄 3D       http://127.0.0.1:$SPIDER_PORT/spider/   (LAN: http://<이 장비 IP>:$SPIDER_PORT/spider/)"; fi
fi
if [ "$RUN_LIDAR" = 1 ]; then
  echo "  🧊 3D 뷰어         $VIEWER_URL"
  echo "     (병원 대시보드 상단의 [3D 현장 뷰어] 버튼으로도 열림)"
  [ "$MODE" = public ] && echo "  📱 아이폰 앱        Server: https://$LIDAR_HOST   Token: $LIDAR_TOKEN"
fi
cat <<BANNER

  voice(구급차 노트북)는 HUB_BASE_URL=http://<이 장비의 LAN IP>:$HUB_PORT 로 따로 실행하세요.
  로그: $LOG_DIR/{turn,hub,info,snapshot,rejection,lidar3d,spider,dashboard,cloudflared}.log
  Ctrl-C 로 전부 종료합니다.
==============================================================

BANNER
wait "$HUB_PID"
