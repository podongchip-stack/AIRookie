# 골든링크 리눅스 환경 구축·실행 가이드

> **Claude Code(Cursor)에게:** 이 문서를 위에서부터 순서대로 실행한다. 단계마다 **확인** 명령이 통과해야 다음 단계로 넘어간다.
> 실패하면 그 단계의 "자주 막히는 곳"을 먼저 보고, 그래도 안 되면 멈추고 사람에게 출력 내용을 보여 준다.
> **비밀 값은 절대 만들어 내거나 추측하지 않는다** — 4단계의 `.env` 키 값과 Cloudflare 인증 파일(`cert.pem`, `<터널ID>.json`)은 사람에게 받아 넣는다.
> 이 파일들은 커밋하지 않는다(`.env`는 이미 `.gitignore`에 있고, Cloudflare 파일은 저장소 밖 `~/.cloudflared/`에 둔다).

접속은 **Cloudflare로 산 도메인(`https://app.rookie-goldenlink.xyz`)** 으로 한다 — 휴대폰 마이크(실제 통화 음성)는 https에서만 열리고,
카카오 지도도 등록된 도메인에서만 뜨기 때문이다. 도메인 없이 이 장비에서만 볼 때는 `--local`(7단계 옵션 표)을 쓴다.

대상: Ubuntu 22.04/24.04 (x86_64). 다른 배포판은 `apt` 줄만 그 배포판 명령으로 바꾼다.
기준 브랜치: `develop` (`demo` 브랜치 작업을 `develop`·`main`에 병합하지 않는다 — CLAUDE.md 맨 위 규칙).

## 0. 전체 구성 한눈에

| 서비스 | 포트 | 파이썬 환경 | Python | 띄우는 방법 |
|---|---|---|---|---|
| hub (매칭·WebSocket) | 5001 | `rookie_hub` | 3.11 | `./start-all.sh`가 띄움 |
| info (병원 정보 주기 전송) + 거절 로그 수신구 + E-Gen 스냅샷 동기화 | 5003 | `rookie_info` | **3.12** | `./start-all.sh`가 띄움 |
| dashboard (Next.js) | 3000 | — (Node 20+) | — | `./start-all.sh`가 빌드·실행 |
| voice (STT·구조화, 중앙 모드) | 6000 | `rookie_voice` | 3.11 | **따로** `./voice/start-voice.sh` |
| lidar3d (선택, 3D 뷰어) | 8000 | `labs` | 3.11 | `./start-all.sh --lidar`일 때만 |
| Cloudflare 터널 | — | — | — | `./start-all.sh`가 띄움(공개 모드) |

인터넷 → `https://app.rookie-goldenlink.xyz` → Cloudflare 터널(`lidar`) → 이 장비:
`/ws/dashboard`·`/identity`·`/route`·`/geocode`·`/verification`은 hub(5001)로, 나머지는 dashboard(3000)로 간다.
info·voice는 터널을 거치지 않고 이 장비 안에서(127.0.0.1) hub에 붙는다.

> ⚠ **공개 모드는 한 번에 한 장비만 띄운다.** 같은 터널을 두 장비가 동시에 연결하면 Cloudflare가 요청을 두 장비에
> 나눠 보내서, 접속할 때마다 다른 hub에 붙어 화면 상태가 엉망이 된다. 다른 장비가 공개 모드로 떠 있으면 먼저 끄게 하고,
> 동시에 개발하려면 한쪽은 `--local`로 띄운다.

환경 이름은 스크립트가 그대로 찾으므로 **위 이름과 똑같이** 만든다(`start-all.sh`의 `env_py rookie_hub` 등).

## 1. 시스템 패키지

```bash
sudo apt update
sudo apt install -y git curl build-essential lsof iproute2 libportaudio2 libsndfile1
```

- `libportaudio2`: **voice 필수.** voice 서버가 시작할 때 마이크 라이브러리(`sounddevice`)를 불러오는데, 리눅스는 PortAudio를 시스템에서 따로 깔아야 한다(윈도우·맥은 내장). 없으면 중앙 모드여도 voice가 `PortAudio library not found`로 바로 죽는다.
- `lsof`/`iproute2`: `start-all.sh`가 포트 사용 여부를 검사할 때 쓴다.

**Node.js 20 이상** (Next.js 16 요구):

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
```

**Miniconda** (이미 있으면 건너뜀):

```bash
curl -fsSLo /tmp/miniconda.sh https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash /tmp/miniconda.sh -b -p "$HOME/miniconda3"
"$HOME/miniconda3/bin/conda" init bash && exec bash
```

**cloudflared** (Cloudflare 터널 클라이언트):

```bash
curl -fsSLo /tmp/cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i /tmp/cloudflared.deb
```

확인:
```bash
node -v             # v20 이상
conda -V
cloudflared --version
```

## 2. 저장소 받기

```bash
git clone https://github.com/podongchip-stack/AIRookie.git
cd AIRookie
git checkout develop
chmod +x start-all.sh voice/start-voice.sh pull-all.sh   # 실행 권한(보통 이미 있음)
```

이후 모든 명령은 저장소 루트(`AIRookie/`)에서 실행한다.

## 3. 파이썬 환경 만들기

### 3-1. hub (`rookie_hub`, Python 3.11)

```bash
conda create -n rookie_hub python=3.11 -y
# GPU 없는 장비면 CPU용 torch를 먼저 깐다(기본 설치는 GPU용이라 수 GB). GPU 장비면 이 줄은 건너뛴다.
conda run -n rookie_hub pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu
conda run -n rookie_hub pip install -r hub/requirements.txt
```

확인: `conda run -n rookie_hub python -c "import flask_sock, sentence_transformers, torch; print('hub ok', torch.__version__)"`

### 3-2. info (`rookie_info`, **Python 3.12**)

```bash
conda create -n rookie_info python=3.12 -y
conda run -n rookie_info pip install -r info/requirements.txt
```

- ⚠ `info/requirements.txt` 첫 줄 주석에 "3.11"이라고 적혀 있지만 **3.12로 만든다.** 고정된 `xgboost==3.4.1`·`numpy==2.5.1`·`scipy==1.18.0`이 3.12 이상에서만 설치된다(3.11이면 설치 실패).
- `sim/`(대량사고 시뮬레이션)도 이 환경을 쓴다.

확인: `conda run -n rookie_info python -c "import xgboost, scipy, supabase, dotenv; print('info ok')"`

### 3-3. voice (`rookie_voice`, Python 3.11)

torch를 **먼저 따로** 깐다(voice/requirements.txt 머리말 안내).

```bash
conda create -n rookie_voice python=3.11 -y
# NVIDIA GPU 장비:
conda run -n rookie_voice pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cu128
# GPU 없는 장비(느리지만 동작 — 대신 위 줄 말고 이 줄):
# conda run -n rookie_voice pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cpu
conda run -n rookie_voice pip install -r voice/requirements.txt
```

확인: `conda run -n rookie_voice python -c "import torch, transformers, sounddevice, soundfile, av; print('voice ok', torch.__version__, 'cuda', torch.cuda.is_available())"`

- 모델 가중치는 저장소에 없고, voice를 **처음 띄울 때** Hugging Face에서 자동으로 받는다(인터넷 필요, 수 GB). MF_BERT는 커밋 해시로 고정돼 있어 따로 할 일은 없다.


## 4. 비밀 파일 넣기 (Cloudflare 인증 + .env 키)

**전부 팀장(이승주)에게 직접 받는다.** 메신저 공개 채널·저장소에는 올리지 않는다.

### 4-1. Cloudflare 터널 인증 파일

받는 파일 두 개:
- `cert.pem` — Cloudflare 계정 인증서(터널 이름 `lidar`를 찾는 데 쓴다)
- `<터널ID>.json` — 터널 자격 증명. **받은 파일 이름(긴 ID)을 그대로 둔다** — cloudflared가 이 이름으로 찾는다

```bash
mkdir -p ~/.cloudflared
cp /받은/경로/cert.pem ~/.cloudflared/
cp /받은/경로/*.json  ~/.cloudflared/          # 파일 이름 바꾸지 않기
chmod 700 ~/.cloudflared && chmod 600 ~/.cloudflared/*
```

- `~/.cloudflared/`에는 **이 두 파일만** 둔다. `config.yml`은 만들지 않는다 — `start-all.sh`가 실행할 때마다 설정을 새로 써서 쓴다.
- DNS 연결(`./start-all.sh --setup-dns`)은 이미 해 둬서 **다시 하지 않는다.**

확인(터널 정보가 보이면 정상):
```bash
cloudflared tunnel info lidar
```

### 4-2. .env 키

아래는 키 이름만이다. 파일 위치·이름을 정확히 맞춘다.

| 파일 | 키 | 없으면 |
|---|---|---|
| `hub/.env` | `KAKAO_REST_API_KEY` | 카카오 내비 ETA·도로 거리·주소 검색이 안 됨(직선 거리로 대체) |
| `info/Hospital_inform/.env` | `EGEN_SERVICE_KEY` | **병원 정보가 안 들어옴 — 필수** |
| | `HIRA_SERVICE_KEY` | 심평원 근거(전문의 수 등) 빠짐 |
| | `AMBULANCE_SUPABASE_URL`, `AMBULANCE_SUPABASE_KEY` | **구급차 162대가 안 들어옴** — 콘솔에 "구급차가 없습니다" |
| | `SNAPSHOT_SUPABASE_URL`, `SNAPSHOT_SUPABASE_ANON_KEY` | E-Gen 스냅샷 동기화 생략(신뢰도 그래프가 이 장비 기록만 봄) |
| `dashboard/.env.local` | `NEXT_PUBLIC_KAKAO_MAP_APP_KEY` | 지도 안 뜸 |
| | `KAKAO_MAP_APP_KEY_PUBLIC` | **도메인 접속에서 지도 안 뜸 — 공개 모드 필수** |

- `dashboard/.env.local`의 `NEXT_PUBLIC_DASHBOARD_WS_URL`·`NEXT_PUBLIC_HUB_HTTP_URL`은 `start-all.sh`가 실행할 때 덮어쓰므로 없어도 된다.
- `SNAPSHOT_SUPABASE_SERVICE_KEY`·`SNAPSHOT_SUPABASE_DB_PASSWORD`, `info/ambulance_registry/.env`(service_role 키)는 **관리용이라 팀원 장비에는 넣지 않는다.**
- 카카오 지도 JavaScript 키는 카카오 개발자 콘솔에 **등록된 도메인에서만** 지도가 뜬다. `https://app.rookie-goldenlink.xyz`(공개 모드, `KAKAO_MAP_APP_KEY_PUBLIC`)와 `http://localhost:3000`(`--local`)이 등록돼 있다.

확인(키 이름만 출력, 값은 출력하지 않는다):
```bash
for f in hub/.env info/Hospital_inform/.env dashboard/.env.local; do echo "== $f"; cut -d= -f1 "$f" | grep -v '^#'; done
```

## 5. dashboard 패키지 설치

```bash
cd dashboard && npm ci && cd ..
```

확인: `ls dashboard/node_modules/.bin/next`

## 6. (처음 한 번) 심평원 캐시 만들기 — 권장

캐시가 없어도 서버는 돌지만 병원 신뢰도 판정에서 심평원 근거가 통째로 빠진다. `HIRA_SERVICE_KEY`가 있어야 한다.

```bash
cd info/Hospital_inform/info
conda run -n rookie_info python -m hospital_score.hira_files --fetch    # 전문병원 지정 (API 2회)
conda run -n rookie_info python -m hospital_score.hira --build-join     # 조인 + 전문의 수 (API 약 520회, 수 분)
cd ../../..
```

## 7. 서버 띄우기

터미널을 **두 개** 쓴다.

### 터미널 1 — hub + info + dashboard + Cloudflare 터널

```bash
./start-all.sh
```

- 옵션 없이 = **공개 모드**: 서버를 띄운 뒤 Cloudflare 터널을 연결해 `https://app.rookie-goldenlink.xyz`로 열린다. 마지막에 `✅ 터널 연결 완료`와 접속 주소 안내가 찍히면 끝.
- 첫 실행은 dashboard 빌드(수 분)와 hub 임베딩 모델 다운로드 때문에 오래 걸린다. dashboard는 **도메인 주소를 넣어 빌드**하므로 공개 모드와 `--local`을 오갈 때는 반드시 다시 빌드한다.
- 다시 띄울 때 코드가 안 바뀌었고 **직전과 같은 모드**면 `./start-all.sh --skip-build`로 빌드를 건너뛴다.
- 끌 때는 이 터미널에서 **Ctrl-C 한 번** — 띄운 서버와 터널이 전부 같이 꺼진다(다른 팀원이 공개 모드를 쓸 수 있게 끝나면 꼭 끈다).
- 로그: `/tmp/goldenlink-logs/`(`hub.log`·`info.log`·`rejection.log`·`snapshot.log`·`dashboard.log`·`dashboard-build.log`·`cloudflared.log`)

자주 쓰는 옵션(`./start-all.sh --help`에 전체 목록):

| 옵션 | 뜻 |
|---|---|
| `--local` | 터널 없이 이 장비에서만(`http://localhost:3000`). 다른 장비가 공개 모드로 떠 있을 때 개발용 |
| `--skip-build` | dashboard 빌드 생략(직전과 같은 모드일 때만) |
| `--no-info` | info·스냅샷 동기화·거절 로그 수신구 생략 |
| `--no-snapshot` | 스냅샷 동기화만 생략 |
| `--dashboard-call` | 구급차 대시보드에도 [통화 시작] 버튼 |
| `--no-sim-dispatch` | 출동 시뮬레이션 끄기(기본은 켬) |
| `--lidar` | lidar3d도 같이(3-4 환경 필요) — `https://lidar.rookie-goldenlink.xyz` |

확인:
```bash
curl -s "http://127.0.0.1:5001/identity?role=hospital&id=_"                       # hub — JSON이 오면 정상
curl -s -o /dev/null -w "%{http_code}
" https://app.rookie-goldenlink.xyz/          # 도메인 → dashboard — 200
curl -s "https://app.rookie-goldenlink.xyz/identity?role=hospital&id=_"             # 도메인 → hub — JSON
tail -n 5 /tmp/goldenlink-logs/info.log                                             # 병원 전송 로그가 찍히면 정상
```

### 터미널 2 — voice (중앙 모드)

```bash
./voice/start-voice.sh
```

- 인자 없이 = 중앙 voice 1대(포트 6000). 휴대폰·대시보드 브라우저 음성을 hub를 거쳐 받는다.
- hub가 다른 장비면: `HUB_BASE_URL=http://<hub장비IP>:5001 ./voice/start-voice.sh`
- GPU 강제/해제: `VOICE_DEVICE=cuda` 또는 `VOICE_DEVICE=cpu` (기본 auto)

확인: 터미널에 `모델 로딩 완료`와 `hub에 중앙 voice로 등록 완료`가 찍히면 정상(첫 실행은 모델 다운로드로 오래 걸림).

## 8. 접속 주소

어느 기기(PC·태블릿·휴대폰)에서든, 어느 네트워크에서든 같은 주소로 들어온다.

| 화면 | 주소 |
|---|---|
| 첫 페이지(접근 코드 입력) | https://app.rookie-goldenlink.xyz |
| 시연 시나리오 콘솔 | https://app.rookie-goldenlink.xyz/control |
| 관제 지도 | https://app.rookie-goldenlink.xyz/map |
| 구급차 대시보드(자동 전환) | https://app.rookie-goldenlink.xyz/ambulance?id=auto (또는 첫 페이지에 `A-<구급차ID>`) |
| 병원 대시보드 | 첫 페이지에 `H-<병원 hpid>` (hpid는 관제 지도 병원 이름 옆에 보임) |
| 대원 휴대폰 전화 앱 | 휴대폰에서 첫 페이지에 `P-AUTO` 또는 `P-<구급차ID>` — https라 마이크가 열려 실제 통화 음성이 STT로 간다 |
| 신뢰도 검증 | https://app.rookie-goldenlink.xyz/verify |
| 3D 뷰어(`--lidar`일 때) | 실행 끝에 찍히는 주소(`https://lidar.rookie-goldenlink.xyz/viewer/?token=...`) |

`--local`로 띄웠을 때는 위 주소의 `https://app.rookie-goldenlink.xyz`를 `http://localhost:3000`으로 바꾼다(이 장비에서만, 휴대폰 마이크 불가).

## 9. 자주 막히는 곳

| 증상 | 원인·해결 |
|---|---|
| `info` 설치 중 `xgboost==3.4.1` 못 찾음 | 환경이 3.11 — `rookie_info`를 **python=3.12**로 다시 만든다 |
| voice가 `PortAudio library not found`로 죽음 | `sudo apt install libportaudio2` |
| `❌ ... 파이썬이 없습니다`(need) | 환경 이름이 표와 다름, 또는 conda가 다른 위치 — `CONDA_ENVS=$HOME/miniconda3/envs ./start-all.sh` |
| `❌ cloudflared가 없습니다` | 1단계 cloudflared 설치를 빠뜨림 |
| `❌ 터널이 연결되지 않았습니다` / `cloudflared.log`에 인증 오류 | `~/.cloudflared/`에 `cert.pem`과 `<터널ID>.json`이 둘 다 있는지, json 이름을 바꾸지 않았는지 확인(`cloudflared tunnel info lidar`) |
| 도메인 접속이 될 때도 있고 안 될 때도 있음, 화면 상태가 들쭉날쭉 | **다른 장비도 공개 모드로 떠 있음** — 한 장비만 남기고 끈다 |
| 도메인에서 502/1033 오류 | 터널은 붙었는데 서버가 아직 안 떴거나 죽음 — `/tmp/goldenlink-logs/` 로그 확인 |
| 포트 사용 중 | 이전 실행이 남음 — `lsof -iTCP:5001 -sTCP:LISTEN`(3000·5003·6000도)으로 찾아 끈다 |
| 콘솔에 "구급차가 없습니다" | `AMBULANCE_SUPABASE_*` 키 없음, 또는 info가 아직 첫 전송 전(로그 확인) |
| 지도만 회색 | 공개 모드면 `KAKAO_MAP_APP_KEY_PUBLIC`, `--local`이면 `NEXT_PUBLIC_KAKAO_MAP_APP_KEY` 없음 — 넣고 다시 빌드(`--skip-build` 없이) |
| torch가 GPU를 못 잡음 | CPU용 torch가 깔림 — 3-3의 cu128 줄로 다시 설치 |
| `dashboard 빌드 실패` | `/tmp/goldenlink-logs/dashboard-build.log` 끝부분 확인. Node 20 미만이면 업그레이드 |

## 10. 최신 코드 받기

```bash
git pull                      # 지금 브랜치만
./pull-all.sh                 # 로컬 브랜치 전부를 한 번에(작업 디렉터리는 현재 브랜치만 바뀜)
```

코드가 바뀐 뒤에는 `--skip-build` 없이 다시 띄워 dashboard를 새로 빌드한다. 의존성 파일(`requirements.txt`·`package-lock.json`)이 바뀌었으면 3·5단계의 설치 줄을 다시 실행한다.

## 11. E-Gen 수집기와 데이터

### 11-1. 수집기는 클라우드에서 돈다 — 리눅스는 동기화만

- E-Gen 병상 스냅샷 수집은 2026-10-04부터 **Supabase(클라우드)에서 20분마다** 돈다. 이 장비에서 수집기를 따로 띄우지 않는다.
- 이 장비는 클라우드에 쌓인 원본을 내려받아 `info/Hospital_inform/info/data/snapshots_nationwide/<날짜>.jsonl`로 복원만 한다.
  `./start-all.sh`가 이 동기화를 자동으로 띄운다 — 1분마다 클라우드에 새 수집분이 생겼는지 보고, 생기면 바로 동기화해서 신뢰도 그래프가 20분 주기에 맞춰 따라온다.
- 필요한 키는 4-2의 `SNAPSHOT_SUPABASE_URL`·`SNAPSHOT_SUPABASE_ANON_KEY` 두 개뿐이다.
- 업로드용 `SNAPSHOT_SUPABASE_SERVICE_KEY`는 넣지 않는다. 이 키가 없으면 "하루가 끝난 날짜를 하루치 파일(`days/`)로 정리해 올리는 작업"만 안 할 뿐이고,
  수집·동기화·그래프는 그대로다(정리되지 않은 날짜는 20분 단위 원본에서 만들어서 처음 받을 때 조금 더 걸린다).

### 11-2. 첫 동기화 (약 1.5GB, 오래 걸림)

과거 전체(9월 초~)를 처음 한 번 내려받는다. 받는 동안에도 서버는 정상으로 뜨고, 받은 날짜만큼 신뢰도 그래프·병상 신뢰도가 채워진다.
두 번째 실행부터는 바뀐 날짜만 받는다.

```bash
tail -f /tmp/goldenlink-logs/snapshot.log          # 진행 확인 ("<날짜>: days/에서 복원" … "동기화 완료")
```

서버를 띄우기 전에 미리 받아 두려면:

```bash
cd info/Hospital_inform/info && conda run -n rookie_info python snapshot_cloud.py --sync && cd ../../..
```

### 11-3. 윈도우 서버에서 리눅스로 옮기기 (데이터 이전)

클라우드에 없는 데이터(약 100MB)는 직접 옮긴다. 스냅샷(11-1)은 옮기지 않는다 — 리눅스가 클라우드에서 받는다.

| 폴더 | 내용 |
|---|---|
| `hub/data/logs/` | 의사결정 로그(해시 체인 — 위변조 검증 기록) |
| `hub/data/state/` | hub 상태(병원·구급차 레지스트리, 지난 사건 기록) |
| `hub/data/live/`, `hub/data/sim/` | 실서버 매칭 결과 사본, 시뮬레이션 데이터 |
| `info/Hospital_inform/info/data/rejections/` | 거절 로그(정답 데이터 — 소급해서 다시 만들 수 없음) |
| `info/Hospital_inform/info/data/verification/` | 신뢰도 검증 화면 데이터 |
| `info/Hospital_inform/info/data/hira/` | 심평원 캐시(옮기면 6단계 생략 가능) |
| `data/voice_data/` | 통화 원본·STT 원문·요약 |

순서 — **같은 도메인은 한 장비만 연결해야 하므로(0단계 경고) 윈도우를 먼저 끈다.** 켜진 채 복사하면 로그·상태 파일이 중간에 잘릴 수도 있다.

1. 크롬 원격 데스크톱으로 윈도우에 접속해 `./start-all.sh` 터미널을 **Ctrl-C**로 끄고, voice 터미널도 끈다.
2. 윈도우 Git Bash, 저장소 루트에서 압축:
   ```bash
   tar -czf ~/goldenlink-data.tgz hub/data/logs hub/data/state hub/data/live hub/data/sim \
     info/Hospital_inform/info/data/rejections info/Hospital_inform/info/data/verification \
     info/Hospital_inform/info/data/hira data/voice_data
   ```
3. `goldenlink-data.tgz`(사용자 폴더)를 리눅스로 옮긴다 — 크롬 원격 데스크톱 파일 전송(세션 메뉴 → 파일 전송) 또는 구글 드라이브.
   **통화 원본(환자 음성·원문)이 들어 있으니** 공유 링크로 퍼지지 않게 하고, 옮긴 뒤 드라이브에서 지운다.
4. 리눅스 저장소 루트(`AIRookie/`)에서 푼다(경로가 그대로 들어 있어 제자리에 풀린다):
   ```bash
   tar -xzf ~/goldenlink-data.tgz
   ```
5. 리눅스에서 `./start-all.sh` — hub가 상태 파일을 읽어 지난 사건 기록·레지스트리를 이어받고, 의사결정 로그도 같은 파일에 이어 쌓여 해시 체인이 이어진다.
   진행 중이던 사건은 재시작 규칙대로 닫힌다(시뮬레이션 모드에선 재시작하면 구급차가 기지로 돌아가므로).

`hub/data/test/`는 테스트용이라 옮기지 않는다.
