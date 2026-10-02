#!/usr/bin/env bash
# 구급차 voice(마이크) 서버 실행 — macOS·Linux·Windows(Git Bash) 공통 (2026-10-03).
#
# 사용법:
#   ./voice/start-voice.sh A0000001                 역삼 구급대 (포트는 아래 표에서 자동)
#   ./voice/start-voice.sh A0000004 6004            표에 없는 구급차는 포트를 직접 준다
#   HUB_BASE_URL=http://192.168.0.3:5001 ./voice/start-voice.sh A0000001
#                                                   hub가 다른 장비일 때(환자 정보 전송 주소도 같이 맞춘다)
#
# 환경변수(전부 선택):
#   VOICE_PY      voice 파이썬 경로. 없으면 conda 환경(rookie_voice → AIRookieProject → rookie 순)에서 찾는다
#   CONDA_ENVS    conda envs 폴더. 자동 탐지가 틀릴 때만
#   VOICE_DEVICE  auto(기본) | cuda | mps | cpu — GPU가 없으면 auto가 cpu를 고른다(느림)
#   HUB_BASE_URL  hub 주소(기본 http://127.0.0.1:5001). HUB_VOICE_SUMMARY_URL을 따로 안 주면 이 주소의 /voice/summary
#
# Windows는 Git Bash에서 실행한다. 콘솔 인코딩(cp949) 문제는 voice 코드(console.py)와 여기서 둘 다 막는다.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

APID="${1:-${VOICE_APID:-}}"
if [ -z "$APID" ] || [ "$APID" = "-h" ] || [ "$APID" = "--help" ]; then
  sed -n '2,18p' "$0"; exit 1
fi

# 구급차 레지스트리(hub가 info에서 받는 AmbulanceInfo.voicePort)와 맞춘 포트. 레지스트리가 바뀌면 여기도 고치거나
# 두 번째 인자로 준다 — 포트가 다르면 hub가 통화 시작·종료 신호를 엉뚱한 곳으로 보내 마이크가 안 켜진다.
default_port(){
  case "$1" in
    A0000001) echo 6001 ;;  # 역삼 구급대
    A0000002) echo 6002 ;;  # 성산 구급대
    A0000003) echo 6003 ;;  # 회현 구급대
    *) echo "" ;;
  esac
}
PORT="${2:-${VOICE_PORT:-$(default_port "$APID")}}"
[ -n "$PORT" ] || { echo "❌ $APID 의 voice 포트를 모릅니다. 두 번째 인자로 주세요: ./voice/start-voice.sh $APID <포트>"; exit 1; }

case "$(uname -s)" in
  Darwin)               OS=mac ;;
  MINGW*|MSYS*|CYGWIN*) OS=windows ;;
  *)                    OS=linux ;;
esac
if [ "$OS" = windows ]; then
  export PYTHONUTF8="${PYTHONUTF8:-1}"
  # Windows는 관리자·개발자 모드가 아니면 심볼릭 링크를 못 만든다. huggingface_hub는 이를 폴더별로 한 번 시험하는데,
  # 시험이 끝나기 전에 "가능"으로 먼저 적어 두는 탓에 여러 파일을 동시에 받는 모델(MF_BERT)에서 다른 다운로드가 링크를
  # 만들려다 WinError 1314로 죽는다(2026-10-03 실제로 겪음). 링크 대신 파일 복사로 받게 한다(디스크만 조금 더 씀).
  export HF_HUB_DISABLE_SYMLINKS="${HF_HUB_DISABLE_SYMLINKS:-1}"
  export HF_HUB_DISABLE_SYMLINKS_WARNING="${HF_HUB_DISABLE_SYMLINKS_WARNING:-1}"
fi

# conda envs 폴더 찾기(start-all.sh와 같은 규칙)
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
}
env_py(){ if [ "$OS" = windows ]; then echo "$1/$2/python.exe"; else echo "$1/$2/bin/python"; fi; }

if [ -z "${VOICE_PY:-}" ]; then
  ENVS="${CONDA_ENVS:-$(find_conda_envs)}"
  # rookie_voice: Windows 안내 기준 / AIRookieProject: 팀 voice 장비 / rookie: voice README 예시
  for name in rookie_voice AIRookieProject rookie; do
    cand="$(env_py "$ENVS" "$name")"
    [ -x "$cand" ] && { VOICE_PY="$cand"; break; }
  done
fi
if [ -z "${VOICE_PY:-}" ] || [ ! -x "$VOICE_PY" ]; then
  echo "❌ voice 파이썬을 찾지 못했습니다 (감지된 OS: $OS). 가상환경부터 만드세요:"
  echo "   conda create -n rookie_voice python=3.11 -y"
  echo "   <그 환경의 python> -m pip install torch==2.11.0      # NVIDIA GPU면 --index-url https://download.pytorch.org/whl/cu128"
  echo "   <그 환경의 python> -m pip install -r voice/requirements.txt"
  echo "   이미 있다면 VOICE_PY=<파이썬 경로> 로 지정하세요."
  exit 1
fi

export VOICE_APID="$APID" VOICE_PORT="$PORT" VOICE_DEVICE="${VOICE_DEVICE:-auto}"
export HUB_BASE_URL="${HUB_BASE_URL:-http://127.0.0.1:5001}"
# hub 주소만 바꾸고 이걸 안 바꾸면 환자 정보가 voice 자기 자신(127.0.0.1)으로 가서 사라진다 — 같이 맞춘다.
export HUB_VOICE_SUMMARY_URL="${HUB_VOICE_SUMMARY_URL:-${HUB_BASE_URL%/}/voice/summary}"

echo "voice 서버 시작 — 구급차 $VOICE_APID · 포트 $VOICE_PORT · 장치 $VOICE_DEVICE · hub $HUB_BASE_URL"
echo "  파이썬: $VOICE_PY"
echo "  처음 실행이면 모델(약 3GB)을 내려받습니다. '[통신] hub 자가등록 완료'가 뜨면 준비된 것입니다. 끄려면 Ctrl-C."
cd "$ROOT" && exec "$VOICE_PY" -u app.py
