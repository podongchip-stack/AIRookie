#!/usr/bin/env bash
# 공개 시연용 실행 — 서버 + Cloudflare Tunnel을 한 번에 띄운다.
#
# 왜 필요한가: 시연장에서는 아이폰이 셀룰러, 맥이 행사장 Wi-Fi라 서로 다른 망에 있다.
# 사설 IP(192.168.x.x)로는 닿지 않으므로 공개 HTTPS 주소가 필요하다.
#
# 같은 Wi-Fi에서 쓸 때는 이 스크립트 대신 그냥 `python server/app.py`를 쓰면 된다.
set -uo pipefail
cd "$(dirname "$0")/.."

PY="${PY:-/opt/anaconda3/envs/labs/bin/python}"
PORT="${PORT:-8000}"
TOKEN_FILE=".lidar_token"

# 토큰은 파일에 보관한다. 재시작할 때마다 바뀌면 폰에서 매번 다시 쳐야 한다.
if [ -n "${LIDAR_TOKEN:-}" ]; then
  TOKEN="$LIDAR_TOKEN"
elif [ -f "$TOKEN_FILE" ]; then
  TOKEN="$(cat "$TOKEN_FILE")"
else
  TOKEN="$("$PY" -c 'import secrets;print(secrets.token_urlsafe(18))')"
  echo "$TOKEN" > "$TOKEN_FILE"
  chmod 600 "$TOKEN_FILE"
  echo "새 토큰을 만들어 $TOKEN_FILE 에 저장했습니다 (git에 올리지 마세요)."
fi

command -v cloudflared >/dev/null || { echo "❌ cloudflared가 없습니다: brew install cloudflared"; exit 1; }

cleanup(){ echo; echo "정리 중..."; kill ${SRV:-} ${CF:-} 2>/dev/null; wait 2>/dev/null; }
trap cleanup EXIT INT TERM

echo "서버 시작 (포트 $PORT)..."
LIDAR_TOKEN="$TOKEN" "$PY" -m uvicorn server.app:app --host 127.0.0.1 --port "$PORT" \
  > /tmp/lidar_server.log 2>&1 &
SRV=$!

# 서버가 뜨기 전에 터널을 열면 502가 난다. 준비될 때까지 기다린다.
for i in $(seq 1 30); do
  curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/health?token=$TOKEN" && break
  kill -0 $SRV 2>/dev/null || { echo "❌ 서버가 죽었습니다:"; tail -20 /tmp/lidar_server.log; exit 1; }
  sleep 1
done

# 터널은 두 가지 모드가 있다.
#
#   named  — 주소가 고정된다. Cloudflare 계정에 **도메인이 등록돼 있어야** 한다
#            (DNS에 CNAME을 꽂아야 하므로). 시연 중 서버를 재시작해도 주소가 안 바뀐다.
#            준비:  cloudflared tunnel login
#                   cloudflared tunnel create lidar
#                   cloudflared tunnel route dns lidar lidar.<도메인>
#            실행:  TUNNEL_NAME=lidar TUNNEL_HOSTNAME=lidar.<도메인> ./server/serve_public.sh
#
#   quick  — 도메인이 필요 없지만 **재시작할 때마다 주소가 바뀐다** (기본값).
#
# 설정은 .lidar_tunnel 파일에 적어두고 매번 타이핑하지 않는다.
#   TUNNEL_NAME=lidar
#   TUNNEL_HOSTNAME=lidar.rookie-goldenlink.xyz
# 우선순위: 환경변수 > .lidar_tunnel 파일 > quick 터널
TUNNEL_CONF=".lidar_tunnel"
if [ -f "$TUNNEL_CONF" ]; then
  # shellcheck disable=SC1090
  . "$TUNNEL_CONF"
fi
TUNNEL_NAME="${TUNNEL_NAME:-}"
TUNNEL_HOSTNAME="${TUNNEL_HOSTNAME:-}"

# --quick 을 주면 설정 파일이 있어도 임시 터널을 쓴다.
# (named 터널이 말썽일 때 원인을 가르기 위한 우회로)
for a in "$@"; do
  if [ "$a" = "--quick" ]; then TUNNEL_NAME=""; TUNNEL_HOSTNAME=""; fi
done

if [ -n "$TUNNEL_NAME" ]; then
  if [ -z "$TUNNEL_HOSTNAME" ]; then
    echo "❌ TUNNEL_NAME을 줬으면 TUNNEL_HOSTNAME도 필요합니다 (예: lidar.내도메인.com)."
    echo "   그 호스트명이 'cloudflared tunnel route dns' 로 등록돼 있어야 합니다."
    exit 1
  fi
  echo "named 터널 '$TUNNEL_NAME' 실행 중..."
  cloudflared tunnel --no-autoupdate run \
    --url "http://127.0.0.1:$PORT" "$TUNNEL_NAME" > /tmp/cloudflared.log 2>&1 &
  CF=$!
  URL="https://$TUNNEL_HOSTNAME"
  MODE="named (주소 고정)"
  # 주소는 우리가 아는 값이지만, 연결이 실제로 섰는지는 확인해야 한다.
  for i in $(seq 1 45); do
    grep -q "Registered tunnel connection" /tmp/cloudflared.log && break
    kill -0 $CF 2>/dev/null || { echo "❌ 터널이 죽었습니다:"; tail -20 /tmp/cloudflared.log; exit 1; }
    sleep 1
  done
  grep -q "Registered tunnel connection" /tmp/cloudflared.log \
    || { echo "❌ 터널이 연결되지 않았습니다:"; tail -20 /tmp/cloudflared.log; exit 1; }
else
  echo "quick 터널 여는 중..."
  cloudflared tunnel --url "http://127.0.0.1:$PORT" --no-autoupdate > /tmp/cloudflared.log 2>&1 &
  CF=$!
  MODE="quick (재시작하면 주소 바뀜)"
  URL=""
  for i in $(seq 1 45); do
    URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/cloudflared.log | head -1)
    [ -n "$URL" ] && break
    kill -0 $CF 2>/dev/null || { echo "❌ 터널이 죽었습니다:"; tail -20 /tmp/cloudflared.log; exit 1; }
    sleep 1
  done
  [ -z "$URL" ] && { echo "❌ 터널 주소를 얻지 못했습니다:"; tail -20 /tmp/cloudflared.log; exit 1; }
fi

cat <<BANNER

==============================================================
  공개 시연 모드 — 아이폰이 셀룰러여도 접속됩니다
==============================================================

  📱 아이폰 앱에 입력
       Server : $URL
       Token  : $TOKEN
       (Port 칸은 https 주소를 넣으면 자동으로 비활성화됩니다)

  🖥  뷰어 (심사위원에게 공유할 주소)
       $URL/viewer/?token=$TOKEN

  🔒 토큰 없는 요청은 401로 거부됩니다.
  🔗 터널 모드: $MODE
      토큰은 $TOKEN_FILE 에 저장돼 있어 재시작해도 유지됩니다.

  Ctrl-C 로 서버와 터널을 함께 종료합니다.
==============================================================

BANNER
wait $SRV
