#!/usr/bin/env bash
# 골든링크 전체 실행 — hub + info + dashboard + Cloudflare 터널을 한 번에 띄운다 (lidar3d는 --lidar로만).
#
# 도메인 하나(rookie-goldenlink.xyz)를 Cloudflare named 터널 하나로 나눠 쓴다:
#
#   https://app.rookie-goldenlink.xyz     /ws/dashboard, /identity, /route, /geocode, /verification → hub (127.0.0.1:5001)
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
#   ./start-all.sh --skip-build       dashboard 빌드 생략 (직전과 같은 모드로 띄울 때만!)
#   ./start-all.sh --no-info          info(병원 정보 주기 전송)·E-Gen 스냅샷 수집·거절 로그 수신구 생략
#   ./start-all.sh --no-snapshot      E-Gen 스냅샷 수집(20분 주기, 병상 신뢰도 모델의 관측 기록)만 생략
#   ./start-all.sh --no-sim-dispatch  구급차 출동 시뮬레이션(가짜 GPS) 끄기 — 기본은 켬: 실제 구급차 GPS 수신
#                                     경로가 아직 없어 구급차 화면의 [이동] 버튼으로 위치를 만든다
#   ./start-all.sh --lidar            lidar3d(3D 뷰어·아이폰 앱 업로드 서버)도 함께 — 병원 대시보드에 3D 버튼이 생긴다
#                                     (기본은 끔: 3D는 당분간 시연에서 뺀다. 끄면 버튼도 자동으로 숨겨진다)
#
# voice는 구급차 노트북마다 따로 뜨므로 여기서 띄우지 않는다(voice/app.py, HUB_BASE_URL로 이 hub를 가리킴).
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
LOG_DIR="${LOG_DIR:-/tmp/goldenlink-logs}"

MODE=public; BUILD=1; RUN_INFO=1; RUN_SNAPSHOT=1; RUN_LIDAR=0; SIM_DISPATCH=1
for a in "$@"; do
  case "$a" in
    --local)      MODE=local ;;
    --skip-build) BUILD=0 ;;
    --no-info)    RUN_INFO=0 ;;
    --no-snapshot) RUN_SNAPSHOT=0 ;;
    --sim-dispatch) SIM_DISPATCH=1 ;;  # 예전 옵션 — 이제 기본값이라 없어도 된다
    --no-sim-dispatch) SIM_DISPATCH=0 ;;
    --lidar)      RUN_LIDAR=1 ;;
    --no-lidar)   RUN_LIDAR=0 ;;  # 예전 옵션 — 이제 기본값이라 없어도 된다
    --setup-dns)
      [ -n "$CF_BIN" ] || { echo "❌ cloudflared가 없습니다: $CF_INSTALL"; exit 1; }
      echo "터널 '$TUNNEL_NAME'에 $APP_HOST 를 연결합니다 (Cloudflare DNS에 CNAME 생성)..."
      cf tunnel route dns "$TUNNEL_NAME" "$APP_HOST"
      exit $? ;;
    -h|--help) sed -n '2,34p' "$0"; exit 0 ;;
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
  echo "모두 종료했습니다."
}
trap cleanup EXIT INT TERM

need(){ [ -x "$1" ] || { echo "❌ $2 파이썬이 없습니다: $1 (환경변수 $3 로 경로 지정 가능, 감지된 OS: $OS)"; exit 1; }; }

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

# ── 1. hub ──
# 포트를 이 스크립트가 정하려고 app.py의 __main__ 대신 직접 띄운다. debug는 끈다 — 디버그 모드가
# 외부에 닿으면 원격 코드 실행 위험이 있다. 0.0.0.0은 유지한다: 구급차 노트북의 voice가 LAN으로 붙어야 한다.
need "$HUB_PY" hub HUB_PY
echo "hub 시작 (포트 $HUB_PORT, 임베딩 모델 로드에 시간이 걸릴 수 있음)..."
# start_background(): 60초 재계산·상태 저장/복구·방치 사건 정리(와 출동 시뮬레이션) 루프. 예전엔
# app.app.run()만 불러서 이 루프들이 start-all로 띄운 실서버에서는 한 번도 돌지 않았다(2026-10-01 수정).
(cd hub && HUB_SIM_DISPATCH="$SIM_DISPATCH" exec "$HUB_PY" -u -c \
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
  # E-Gen은 과거 이력을 주지 않아서, 병상 신뢰도 모델(reliability/)과 중증신고 신선도가 쓰는
  # 관측 기록은 직접 찍어 쌓아야 한다. Windows에선 작업 스케줄러(snapshot_nationwide.bat)로
  # 돌리던 것을 여기서 같이 띄운다 — 전국 1회 호출 × 20분 = 하루 약 145회(서울만 받을 때와 같음).
  # 거절 로그 수신구(포트 5003). hub가 병원 거절·도착 후 수용 불가·무응답을 그때 화면에 보였던 병상 수·
  # 신뢰도 확률과 함께 보낸다 — 신뢰도 모델의 정답(G2 라벨) 재료라 안 띄우면 그 기간 로그는 영영 사라진다
  # (소급 생성 불가). 예전엔 따로 켜야 해서 실제로는 버려지고 있었다(2026-10-01 기본 실행).
  echo "거절 로그 수신구 시작 (포트 5003)..."
  (cd info/Hospital_inform/info && PYTHONIOENCODING=utf-8 exec "$INFO_PY" -u -m hospital_score.ingest) \
      > "$LOG_DIR/rejection.log" 2>&1 &
  PIDS+=("$!")
  if [ "$RUN_SNAPSHOT" = 1 ]; then
    echo "E-Gen 스냅샷 수집 시작 (전국, 20분 주기)..."
    (cd info/Hospital_inform && PYTHONIOENCODING=utf-8 exec "$INFO_PY" -u info/snapshot.py --stage1 "" \
        --interval 1200 --dir info/data/snapshots_nationwide) > "$LOG_DIR/snapshot.log" 2>&1 &
    PIDS+=("$!")
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

# ── 4. dashboard ──
# NEXT_PUBLIC_* 값은 빌드할 때 코드에 박힌다. 그래서 모드(공개/로컬)가 바뀌면 반드시 다시 빌드해야 한다.
# 여기서 넘기는 환경변수가 dashboard/.env.local 보다 우선한다.
export NEXT_PUBLIC_DASHBOARD_WS_URL="$WS_URL"
export NEXT_PUBLIC_HUB_HTTP_URL="$HUB_HTTP_URL"
export NEXT_PUBLIC_LIDAR_VIEWER_URL="$VIEWER_URL"

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
    echo "    path: ^/(ws/dashboard|identity|route|geocode|verification)"
    echo "    service: http://127.0.0.1:$HUB_PORT"
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
if [ "$RUN_LIDAR" = 1 ]; then
  echo "  🧊 3D 뷰어         $VIEWER_URL"
  echo "     (병원 대시보드 상단의 [3D 현장 뷰어] 버튼으로도 열림)"
  [ "$MODE" = public ] && echo "  📱 아이폰 앱        Server: https://$LIDAR_HOST   Token: $LIDAR_TOKEN"
fi
cat <<BANNER

  voice(구급차 노트북)는 HUB_BASE_URL=http://<이 장비의 LAN IP>:$HUB_PORT 로 따로 실행하세요.
  로그: $LOG_DIR/{hub,info,snapshot,rejection,lidar3d,dashboard,cloudflared}.log
  Ctrl-C 로 전부 종료합니다.
==============================================================

BANNER
wait "$HUB_PID"
