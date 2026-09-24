# LiDAR_Space3D 서버

아이폰이 보낸 LiDAR 세션을 **이 폴더 아래 `sessions/`** 에 저장하고, 브라우저에서 3D로 보여준다.

`CAM/server/app.py`(기존 photogrammetry 서버)와 **완전히 별개**다.
기존 서버는 `/session/stop`에서 COLMAP+OpenMVS를 자동 실행하는데, LiDAR 세션은 이미
미터 단위 메시를 들고 오므로 그걸 돌리면 시간만 버리고 실패한다. 여기서는 재구성을 하지 않는다.

## 실행

실행 방법이 **두 가지**다. 아이폰과 맥이 같은 망에 있는지로 갈린다.

### 1) 같은 Wi-Fi (평소 개발용)

```bash
cd server
python3 app.py
```

띄우면 아이폰에 입력할 주소가 그대로 출력된다:

```
  📱 아이폰 앱에 입력:   Server = http://192.168.0.7:8000
  🖥  브라우저에서 3D:    http://192.168.0.7:8000/viewer/
```

### 2) 서로 다른 망 (시연용)

시연장에서는 아이폰이 셀룰러, 맥이 행사장 Wi-Fi라 **사설 IP로는 닿지 않는다.**
Cloudflare Tunnel로 공개 HTTPS 주소를 받는다:

```bash
./server/serve_public.sh          # 서버 + 터널을 함께 띄우고 Ctrl-C로 함께 종료
```

```
  📱 아이폰 앱에 입력
       Server : https://xxxx-xxxx.trycloudflare.com
       Token  : (자동 생성, .lidar_token 에 저장)
  🖥  뷰어 : https://xxxx-xxxx.trycloudflare.com/viewer/?token=...
```

사전 준비: `brew install cloudflared`

> ⚠️ 기본값인 quick tunnel은 **주소가 재시작할 때마다 바뀐다.** 토큰은 `.lidar_token`에
> 저장돼 유지된다. 이 파일은 `.gitignore`에 들어 있다 — **저장소에 올리지 말 것.**

### 주소를 고정하려면 (named tunnel)

Cloudflare 계정에 **도메인이 등록돼 있어야 한다.** DNS에 CNAME을 꽂는 방식이라
계정만으로는 안 되고, `*.trycloudflare.com`은 임시 전용이라 고정할 수 없다.

```bash
cloudflared tunnel login                              # 브라우저에서 도메인 선택
cloudflared tunnel create lidar                       # UUID + 자격증명 발급
cloudflared tunnel route dns lidar lidar.<도메인>      # CNAME 자동 생성

TUNNEL_NAME=lidar TUNNEL_HOSTNAME=lidar.<도메인> ./server/serve_public.sh
```

고정 주소가 실제로 필요한 경우는 두 가지다.
① 발표자료에 주소를 미리 박아야 할 때 ② **시연 중 서버를 재시작해도 주소가 유지돼야 할 때**.
②는 사고가 났을 때 실제로 중요하다.

> ⚠️ 도메인이 생겨도 **Cloudflare Access(Zero Trust 인증)를 앱 업로드 경로에 붙이면 안 된다.**
> Access는 브라우저 SSO 로그인을 요구해서 아이폰 앱의 `URLSession` 요청이 전부 막힌다.
> 앱에는 우리가 넣은 공유 토큰이 맞는 방식이다. 뷰어 경로에만 씌우는 건 가능하다.

### 인증

`LIDAR_TOKEN` 환경변수가 있으면 토큰을 요구하고, 없으면 인증 없이 동작한다
(같은 Wi-Fi 전용이던 기존 방식과 호환). **공개 URL로 열 때는 반드시 설정해야 한다.**
안 그러면 주소를 아는 누구나 업로드·삭제·후처리 실행이 가능하다.

토큰은 세 가지로 받는다. 쿼리 파라미터를 지원하는 이유가 중요한데, 뷰어의
`<img src=...>`와 3DGS 로더는 **요청 헤더를 붙일 수 없기** 때문이다.

| 방법 | 쓰는 곳 |
|---|---|
| `Authorization: Bearer <토큰>` | 아이폰 앱 |
| `X-API-Key: <토큰>` | 스크립트/curl |
| `?token=<토큰>` | 뷰어 (이미지·3DGS 파일 로드) |

`/viewer` 정적 페이지만 토큰 없이 열린다. 페이지 자체에는 데이터가 없고,
데이터 요청은 전부 401로 막힌다.

> `--host 0.0.0.0`으로 떠 있어야 아이폰에서 붙는다 (`app.py`가 알아서 그렇게 띄운다).
> 직접 uvicorn을 쓸 거면 `python3 -m uvicorn app:app --host 0.0.0.0 --port 8000`.
> 기본값 `127.0.0.1`로 띄우면 맥 안에서만 되고 **아이폰에서는 절대 안 붙는다.**

필요 패키지: `fastapi`, `uvicorn`, `python-multipart` (이 맥에는 이미 설치돼 있음)

## 큰 파일 업로드 (분할 전송)

Cloudflare 무료 플랜은 **요청 본문 100MB**가 상한이다. `video.mov`가 132MB까지 나오는데
통째로 보내면 **Cloudflare 단계에서 잘려 서버에 요청이 도달조차 하지 않는다**
(앱에는 "The request timed out"으로만 보이고, 서버 로그에는 아무것도 안 남는다).

그래서 50MB가 넘는 파일은 앱이 20MB씩 조각내 보내고 서버가 합친다.

| 엔드포인트 | 역할 |
|---|---|
| `POST /session/upload/chunk` | 조각 하나 저장 (`session_id`, `filename`, `chunk_index`, `chunk_count`, `file`) |
| `POST /session/upload/complete` | 순서대로 합치고 크기 대조 (`chunk_count`, `total_size`) |

**전송만 조각낸다.** 서버가 원래 이름으로 다시 합치므로 세션 폴더 구조도,
`video.mov`의 `frame_index`와 `arkit_pose.csv`의 대응도 바뀌지 않는다. 기존 스크립트는 그대로다.

- 조각은 `<세션>/.chunks/<파일명>/NNNN.part` 에 쌓이고, 합친 뒤 지워진다.
- 합치기는 임시 파일에 먼저 하고 **크기가 맞아야** 제자리로 옮긴다. 중간에 실패해도
  깨진 파일이 정상 파일인 척 남지 않는다.
- 조각이 빠지면 400으로 **어느 조각이 없는지** 알려준다.
- `/session/start` 는 이전 시도의 조각 찌꺼기를 지운다 (옛 조각이 섞이면 크기 검사는
  통과하는데 내용이 깨진 파일이 만들어질 수 있다). 그래서 **재시도는 처음부터** 다시 보낸다.

50MB 이하 파일은 기존 `POST /session/upload` 를 그대로 쓴다.

## 전체 흐름

```
아이폰                          이 서버                        브라우저
  │                               │                              │
  │ [CONNECT]  GET /health ──────>│                              │
  │ [START SESSION] (로컬 촬영)    │                              │
  │ [STOP SESSION]  (메시 생성)    │                              │
  │ [UPLOAD]                      │                              │
  │   POST /session/start ───────>│ sessions/session_xxx/ 생성    │
  │   POST /session/upload  x N ─>│ 파일 저장 (화이트리스트 검사)    │
  │   POST /session/stop ────────>│ 메시 요약 출력                 │
  │                               │<──── GET /sessions ──────────│
  │                               │<──── GET /session/…/scene_mesh.ply
  │                               │      3D 렌더 + 거리 측정 ────>│
```

## 엔드포인트

| | |
|---|---|
| `GET /health` | 아이폰 [CONNECT] 버튼 |
| `POST /session/start` | `session_id` (form) |
| `POST /session/upload` | `session_id` + `file` (multipart) |
| `POST /session/stop` | 업로드 완료 신호. 메시 요약을 콘솔에 출력 |
| `GET /sessions` | 뷰어의 세션 목록 (최신순) |
| `GET /session/{id}/file/{name}` | 파일 원본 |
| `GET /session/{id}` | 세션 상세 (파일 목록 + metadata) |
| `GET /viewer/` | 3D 뷰어 |
| `GET /` | `/viewer/`로 리다이렉트 |

## 저장 위치

```
server/
├── app.py
├── sessions/
│   └── session_20260917T203000Z/
│       ├── scene_mesh.ply              ← 뷰어가 그리는 3D 모델
│       ├── scene_mesh_faces_class.bin  ← 면별 분류(문/벽/바닥…)
│       ├── arkit_pose.csv
│       ├── video.mov
│       ├── video_frames.csv
│       ├── imu.csv
│       ├── device_motion.csv
│       ├── coaching.csv
│       ├── metadata.json
│       └── depth/                      ← depth.zip을 받으면 자동 해제
└── viewer/
```

경로는 **`app.py` 파일 기준**이라 어디서 실행하든 같은 곳에 저장된다.

## 업로드 허용 파일명

화이트리스트에 없으면 **400으로 거부**한다 (`app.py`의 `ALLOWED_FILENAMES`).

```
video.mov  video_frames.csv  imu.csv  device_motion.csv  metadata.json
arkit_pose.csv  coaching.csv  scene_mesh.ply  scene_mesh_faces_class.bin  depth.zip
```

## 안 될 때

| 증상 | 확인 |
|---|---|
| 아이폰에서 연결 실패 | 같은 Wi-Fi인지 / 맥 방화벽이 python을 막는지 (시스템 설정 > 네트워크 > 방화벽) |
| 연결은 되는데 **401** | 토큰 불일치. 앱의 Token 칸과 서버 배너의 값을 비교 |
| `address already in use` | 서버가 이미 떠 있다. `lsof -nP -iTCP:8000 -sTCP:LISTEN` 로 확인 후 정리 |
| 터널 주소가 안 나옴 | `tail /tmp/cloudflared.log` — 행사장 방화벽이 아웃바운드 443을 막는 경우는 드물다 |
| 업로드 400 | 화이트리스트에 없는 파일명. 서버 콘솔에 파일명이 찍힌다 |
| 뷰어에 세션이 안 보임 | `scene_mesh.ply`가 없는 세션은 목록에 나오지만 열리지 않는다 |
| IP가 바뀜 | Wi-Fi를 옮기거나 공유기를 재부팅하면 바뀐다. 서버를 다시 띄우면 새 IP가 출력된다 |

## 보안

로컬 네트워크 전용이다. 인증이 없고 ATS 예외(HTTP 평문)를 쓰므로 **공용 Wi-Fi나 인터넷에
노출하지 말 것.** 세션 id와 파일명은 사용자 입력으로 취급해 경로 순회를 막고 있고
(`SESSION_ID_RE` + `resolve()` 검사), `depth.zip`은 zip 폭탄·경로 순회를 검사한 뒤 푼다.
