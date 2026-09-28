"""
LiDAR_Space3D — Mac 수신 서버

아이폰이 보낸 LiDAR 세션을 **이 파일이 있는 폴더 아래**(server/sessions/)에 저장하고,
브라우저에서 3D로 볼 수 있게 서빙한다.

CAM/server/app.py(기존 photogrammetry 서버)와 **완전히 별개**다. 이유:
기존 서버는 /session/stop에서 COLMAP+OpenMVS 재구성을 자동 실행하는데, LiDAR 세션은
이미 미터 단위 메시를 들고 오므로 그걸 돌리면 123초를 낭비하고 실패한다
(LiDAR 촬영은 프레임 수가 적어 SfM 등록이 잘 안 된다). 여기서는 재구성을 아예 하지 않는다.

실행:
    cd server
    python3 -m uvicorn app:app --host 0.0.0.0 --port 8000
    # 또는 그냥:  python3 app.py

--host 0.0.0.0 이 중요하다. 기본값(127.0.0.1)으로 띄우면 맥 안에서만 접속되고
**아이폰에서는 절대 안 붙는다.**

실패 시 확인할 것:
- 아이폰에서 연결 실패      -> 같은 Wi-Fi인지, 맥 방화벽이 python을 막는지
- 업로드가 400으로 거부됨   -> ALLOWED_FILENAMES에 없는 파일명. 아래 목록 확인
- 업로드가 413으로 잘림     -> 리버스 프록시의 body size 제한 (uvicorn 단독이면 무제한)
- 뷰어에 세션이 안 보임      -> scene_mesh.ply가 없는 세션은 목록에서 빠진다
"""

import hmac
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import webbrowser
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

# ─────────────────────────────────────────────────────────────────────────────
# 경로 — 전부 이 파일 기준. 어디서 실행하든 같은 곳에 저장된다.
# (cwd 기준으로 잡으면 "실행한 위치에 따라 데이터가 흩어지는" 사고가 난다.)
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
SESSIONS_ROOT = BASE_DIR / "sessions"
VIEWER_DIR = BASE_DIR / "viewer"
SCRIPTS = BASE_DIR.parent / "scripts"
MERGE_SCRIPT = SCRIPTS / "merge_sessions.py"
SESSIONS_ROOT.mkdir(parents=True, exist_ok=True)

# 업로드 허용 파일명. 화이트리스트에 없으면 400으로 거부한다.
# 아이폰의 SessionManager.sessionFiles()가 보내는 목록과 일치해야 한다.
ALLOWED_FILENAMES = {
    # 기존 스키마 (하위 파이프라인이 의존)
    "video.mov",
    "video_frames.csv",
    "imu.csv",
    "device_motion.csv",
    "metadata.json",
    # LiDAR 전환으로 추가된 것
    "arkit_pose.csv",              # 카메라 포즈 + intrinsics + 트래킹 상태
    "coaching.csv",                # 스캔 품질 경고 로그
    "scene_mesh.ply",              # ★ 3D 모델 본체 — 뷰어가 그리는 파일
    "scene_mesh_faces_class.bin",  # 면별 분류 라벨 (문/벽/바닥…)
    "depth.zip",                   # 뎁스 프레임 묶음 (아이폰에서 기본 OFF)
    # 맥에서 후처리로 만들어지는 것 (아이폰이 올리는 게 아니라 뷰어가 읽어간다).
    # 화이트리스트에 있어야 /session/{id}/file/objects_3d.json 이 200을 준다.
    "objects_3d.json",             # YOLO 객체 검출 + 3D 위치 (detect_stage1/2.py)
    "fused_mesh.ply",              # 직접 융합 결과 (scripts/fuse_depth.py)
    "fused_adaptive.ply",          # 적응형 해상도 융합 (배경 거침 + 객체 정밀)
    "fused_objects.ply",           # 적응형 융합의 객체 부분만
    "detections_2d.json",          # YOLO 2D 검출 중간 산출물 (scripts/detect_stage1.py)
    "persons.json",                # 사람별 분리 목록 (scripts/stage2_fuse.py)
    "photos.json",                 # 사람별 참조 사진 목록 (scripts/person_photos.py)
    "gs_persons.json",             # 사람별 3DGS 목록 (scripts/crop_3dgs.py)
    "gs_status.json",              # 3DGS 자동 생성 진행 상황 (server/gs_job.py)
    "detection_overlay.json",      # YOLO 검출 오버레이 (scripts/export_detection_overlay.py)
    "_progress.json",             # 후처리 진행 상황 (stage1/stage2가 쓰고 뷰어가 읽는다)
    # fused_person_NN(_colored).ply 는 PERSON_FILE_RE 로,
    # gs_person_NN.ply 는 GS_PERSON_RE 로 따로 허용한다
}


def allowed_filename(name: str) -> bool:
    return (name in ALLOWED_FILENAMES
            or bool(PERSON_FILE_RE.match(name))
            or bool(PERSON_PHOTO_RE.match(name))
            or bool(GS_PERSON_RE.match(name)))

# 경로 순회 방어. 세션 id는 아이폰이 만들지만 **사용자 입력으로 취급**한다.
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
# 사람별 메시는 개수가 가변이라 고정 화이트리스트로 못 적는다. 패턴으로 허용한다.
# (경로 성분이 들어갈 수 없는 좁은 패턴이라 순회 위험이 없다.)
# _confidence.bin = 마스크 일관성 신뢰도 사이드카 (stage2_fuse.py).
# 뷰어가 낮은 신뢰도를 흐리게 표시하는 데만 쓰며, 없으면 기존 표시로 돌아간다.
PERSON_FILE_RE = re.compile(r"^fused_person_\d{2}((_colored)?\.ply|_confidence\.bin)$")
# 사람별 참조 사진도 개수가 가변이라 패턴으로 허용한다.
PERSON_PHOTO_RE = re.compile(r"^person_\d{2}_photo_\d+\.jpg$")
# 사람별 3D 가우시안 스플랫(A100에서 학습 후 잘라온 것). 보기 전용이다.
GS_PERSON_RE = re.compile(r"^gs_person_\d{2}\.ply$")

MAX_ZIP_UNCOMPRESSED = 2 * 1024 * 1024 * 1024   # 2GB — zip 폭탄 방어

# 업로드가 끝날 때마다 브라우저 창을 새로 띄울 것인가.
#
# ⚠️ 기본 False인 이유: 촬영을 반복하면 **탭이 계속 쌓인다.** 시점을 맞춰 보던 중에
#    새 창이 튀어나와 작업을 끊기도 한다. 대신 뷰어가 주기적으로 세션 목록을 갱신하므로,
#    브라우저를 한 번만 열어두면 새 세션이 드롭다운에 저절로 나타난다.
AUTO_OPEN_VIEWER = False

# 로그가 즉시 보이도록 줄 단위 버퍼링. `python3 app.py`로 띄우든
# `uvicorn app:app`로 띄우든 동일하게 동작해야 한다 (경고가 묻히면 의미가 없다).
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

# 3DGS 자동 생성. import가 실패해도 서버는 정상 동작해야 한다 (선택적 기능).
try:
    from server import gs_job
except Exception as _e:                      # noqa: BLE001
    gs_job = None
    print(f"⚠ 3DGS 자동 생성 비활성 (모듈 로드 실패: {_e})")

app = FastAPI(title="LiDAR_Space3D Server")


# ─────────────────────────────────────────────────────────────────────────────
# 인증 — 공개 노출(Cloudflare Tunnel 등) 대비
#
# LIDAR_TOKEN 환경변수가 있으면 토큰을 요구한다. 없으면 인증 없이 동작한다
# (같은 Wi-Fi에서만 쓰던 기존 방식과 호환). 공개 URL로 열 때는 **반드시** 설정해야
# 한다. 안 그러면 URL을 아는 누구나 업로드·삭제·후처리 실행이 가능하다.
#
# 토큰은 세 가지 방법으로 받는다. 쿼리 파라미터를 지원하는 이유가 중요한데,
# 뷰어의 <img src=...> 와 3DGS 로더는 요청 헤더를 붙일 수 없기 때문이다.
#   1) Authorization: Bearer <토큰>
#   2) X-API-Key: <토큰>
#   3) ?token=<토큰>
# ─────────────────────────────────────────────────────────────────────────────
AUTH_TOKEN = os.environ.get("LIDAR_TOKEN", "").strip()

# 토큰 없이 통과시키는 경로. 뷰어 HTML 자체는 열어 둬야 브라우저가 페이지를 띄우고
# 그 다음에 ?token= 으로 데이터를 부를 수 있다. 페이지 자체에는 데이터가 없다.
AUTH_EXEMPT_PREFIXES = ("/viewer", "/docs", "/openapi.json", "/redoc", "/favicon.ico")
# 정확히 이 경로들만 면제. 루트는 뷰어로 보내주기만 하므로 노출되는 정보가 없다.
# (면제하지 않으면 주소창에 도메인만 친 사람이 한글 JSON 401을 보게 되는데,
#  글자가 깨진 것처럼 보여서 원인을 오해하기 딱 좋다.)
AUTH_EXEMPT_EXACT = ("/",)


def _token_from(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (request.headers.get("x-api-key")
            or request.query_params.get("token")
            or "").strip()


@app.middleware("http")
async def require_token(request: Request, call_next):
    path = request.url.path
    if (AUTH_TOKEN and path not in AUTH_EXEMPT_EXACT
            and not path.startswith(AUTH_EXEMPT_PREFIXES)):
        # compare_digest로 타이밍 공격을 막는다.
        if not hmac.compare_digest(_token_from(request), AUTH_TOKEN):
            # ensure_ascii 기본값이면 한글이 \uXXXX로 나가 브라우저에서 깨져 보인다.
            return JSONResponse(
                {"detail": "인증 토큰이 필요합니다. 앱의 Token 칸 또는 URL의 ?token= 을 확인하세요."},
                status_code=401,
                media_type="application/json; charset=utf-8")
    response = await call_next(request)

    # 뷰어 HTML/JS는 절대 캐시하지 않는다.
    # Cache-Control이 없으면 브라우저가 last-modified 기반 휴리스틱으로 멋대로 캐시해서,
    # 서버를 고쳐도 옛 코드가 계속 실행된다 (실제로 여러 번 겪었다).
    # no-cache는 "쓰지 마라"가 아니라 "매번 재검증하라"라서, 안 바뀌었으면 304로 싸게 끝난다.
    # 뷰어 코드와 **세션 데이터 파일** 모두 캐시하지 않는다.
    # 세션 파일은 후처리로 계속 바뀐다 (융합이 persons.json을 새로 쓰고, 학습이 끝나면
    # gs_persons.json이 생긴다). 브라우저가 옛 응답을 들고 있으면 새로고침해도
    # 갱신이 안 보인다 — 실제로 이 때문에 상태 표시가 안 바뀌는 것을 확인했다.
    # no-cache는 "쓰지 마라"가 아니라 "매번 재검증하라"라서, 안 바뀌었으면 304로 싸게 끝난다.
    path = request.url.path
    if path.startswith("/viewer") or "/file/" in path or path == "/sessions":
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


# ─────────────────────────────────────────────────────────────────────────────
# 내부 유틸
# ─────────────────────────────────────────────────────────────────────────────
def session_dir(session_id: str) -> Path:
    """세션 폴더 경로. 부적절한 id는 여기서 전부 막는다."""
    if not SESSION_ID_RE.match(session_id):
        raise HTTPException(400, f"잘못된 session_id: {session_id!r}")
    path = (SESSIONS_ROOT / session_id).resolve()
    # resolve() 후에도 루트 밖이면 거부 (심볼릭 링크 등)
    if not str(path).startswith(str(SESSIONS_ROOT.resolve())):
        raise HTTPException(400, "경로 순회 시도")
    return path


def read_metadata(path: Path) -> dict:
    try:
        return json.loads((path / "metadata.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
        n /= 1024.0
    return f"{n:.1f}TB"


def lan_ip() -> str:
    """아이폰에 입력할 IP. 외부로 패킷을 보내지 않고 라우팅 테이블만 조회한다."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


# ─────────────────────────────────────────────────────────────────────────────
# 아이폰 -> 서버 (NetworkManager.swift의 프로토콜과 1:1 대응)
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    """아이폰의 [CONNECT] 버튼이 부르는 곳. 200이면 연결 성공으로 표시된다."""
    # 인증을 켠 상태에서는 저장 경로를 노출하지 않는다 (공개 URL이므로).
    out = {"status": "ok", "server": "LiDAR_Space3D", "auth": bool(AUTH_TOKEN)}
    if not AUTH_TOKEN:
        out["sessions_root"] = str(SESSIONS_ROOT)
    return out


@app.post("/session/start")
def session_start(session_id: str = Form(...)):
    path = session_dir(session_id)

    # 세션 id가 "날짜+순번" 방식이라, 앱을 재설치하거나 폰의 세션 폴더를 지우면 순번이
    # 되돌아가 **기존 세션을 덮어쓸 수** 있다. (앱이 UserDefaults로 막고 있지만 완벽하지 않다.)
    # 업로드 재시도는 정상 동작이어야 하므로 거부하지는 않고, 눈에 띄게 경고한다.
    existing = [f.name for f in path.iterdir() if f.is_file()] if path.is_dir() else []
    path.mkdir(parents=True, exist_ok=True)
    print(f"\n[START] {session_id}")
    if existing:
        print(f"        ⚠️  이미 파일 {len(existing)}개가 있는 세션입니다 — 덮어씁니다.")
        print(f"        재업로드가 아니라면 폰의 세션 순번이 되돌아간 것입니다 "
              f"(앱 재설치/세션 삭제). 기존 데이터가 필요하면 지금 백업하세요.")
    # 이전 시도에서 남은 조각을 지운다. 남겨두면 다음 업로드에서 옛 조각이 섞여
    # 크기 검사는 통과하는데 내용이 깨진 파일이 만들어질 수 있다.
    stale = path / CHUNK_ROOT
    if stale.is_dir():
        shutil.rmtree(stale, ignore_errors=True)
        print("        이전 업로드의 조각 찌꺼기를 정리했습니다.")

    return {"status": "ok", "session_id": session_id, "existing_files": len(existing)}


# ─────────────────────────────────────────────────────────────────────────────
# 분할 업로드
#
# 왜 필요한가: Cloudflare 무료 플랜은 **요청 본문 100MB**가 상한이다.
# video.mov가 132MB까지 나오는데, 통째로 보내면 Cloudflare 단계에서 잘려
# 서버에는 요청이 도달조차 하지 않는다 (실제로 겪었다 — 로그에 upload 기록 없음).
#
# 설계 원칙: **전송만 조각낸다.** 서버는 조각을 원래 파일로 다시 합쳐서
# 기존과 똑같은 이름으로 저장한다. 세션 폴더 구조도, video.mov의 frame_index와
# arkit_pose.csv의 대응도 전혀 바뀌지 않으므로 기존 스크립트가 그대로 동작한다.
#
# 조각은 <세션>/.chunks/<파일명>/NNNN.part 로 쌓고, complete에서 순서대로 이어붙인다.
# ─────────────────────────────────────────────────────────────────────────────
CHUNK_ROOT = ".chunks"
MAX_CHUNK_BYTES = 64 * 1024 * 1024      # 조각 하나의 상한 (Cloudflare 100MB보다 충분히 아래)
MAX_ASSEMBLED_BYTES = 4 * 1024 * 1024 * 1024   # 합친 파일 상한 — 디스크 고갈 방어


def _chunk_dir(path: Path, name: str) -> Path:
    """조각 보관 폴더. name은 이미 basename + 화이트리스트 검증을 통과한 것이어야 한다."""
    return path / CHUNK_ROOT / name


def _checked_name(filename: str) -> str:
    name = os.path.basename(filename or "")
    if not allowed_filename(name):
        raise HTTPException(400, f"허용되지 않은 파일명: {name!r}")
    return name


@app.post("/session/upload/chunk")
async def session_upload_chunk(
    session_id: str = Form(...),
    filename: str = Form(...),
    chunk_index: int = Form(...),
    chunk_count: int = Form(...),
    file: UploadFile = File(...),
):
    """조각 하나를 받아 둔다. 같은 조각을 다시 보내면 덮어쓴다(재시도 안전)."""
    path = session_dir(session_id)
    if not path.is_dir():
        raise HTTPException(404, "session/start를 먼저 호출하세요")
    name = _checked_name(filename)

    if chunk_count < 1 or chunk_count > 10000:
        raise HTTPException(400, f"chunk_count 범위 오류: {chunk_count}")
    if not (0 <= chunk_index < chunk_count):
        raise HTTPException(400, f"chunk_index 범위 오류: {chunk_index}/{chunk_count}")

    cdir = _chunk_dir(path, name)
    cdir.mkdir(parents=True, exist_ok=True)
    part = cdir / f"{chunk_index:05d}.part"

    written = 0
    with part.open("wb") as out:
        while True:
            buf = await file.read(1024 * 1024)
            if not buf:
                break
            written += len(buf)
            if written > MAX_CHUNK_BYTES:
                out.close(); part.unlink(missing_ok=True)
                raise HTTPException(413, f"조각이 너무 큽니다 (>{human_size(MAX_CHUNK_BYTES)})")
            out.write(buf)

    have = len(list(cdir.glob("*.part")))
    print(f"  [CHUNK] {name:<24} {chunk_index + 1}/{chunk_count}  {human_size(written)}")
    return {"status": "ok", "filename": name, "chunk_index": chunk_index,
            "received_chunks": have, "chunk_count": chunk_count}


@app.post("/session/upload/complete")
def session_upload_complete(
    session_id: str = Form(...),
    filename: str = Form(...),
    chunk_count: int = Form(...),
    total_size: int = Form(...),
):
    """조각을 순서대로 이어붙여 원래 파일로 만든다. 크기가 안 맞으면 실패로 처리한다."""
    path = session_dir(session_id)
    if not path.is_dir():
        raise HTTPException(404, "session/start를 먼저 호출하세요")
    name = _checked_name(filename)
    cdir = _chunk_dir(path, name)
    if not cdir.is_dir():
        raise HTTPException(400, f"{name}: 받아둔 조각이 없습니다")

    # 빠진 조각을 **합치기 전에** 찾아낸다. 합친 뒤에 알면 이미 잘못된 파일이 생긴 뒤다.
    missing = [i for i in range(chunk_count) if not (cdir / f"{i:05d}.part").is_file()]
    if missing:
        raise HTTPException(400, f"{name}: 조각 {len(missing)}개 누락 "
                                 f"(예: {missing[:10]}) — 해당 조각만 다시 보내세요")
    if total_size > MAX_ASSEMBLED_BYTES:
        raise HTTPException(413, f"파일이 너무 큽니다: {human_size(total_size)}")

    # 임시 파일에 합친 뒤 검증에 성공해야 제자리로 옮긴다.
    # 곧바로 dest에 쓰면 중간에 실패했을 때 깨진 파일이 정상 파일처럼 남는다.
    tmp = cdir.parent / f".{name}.assembling"
    with tmp.open("wb") as out:
        for i in range(chunk_count):
            with (cdir / f"{i:05d}.part").open("rb") as src:
                shutil.copyfileobj(src, out, length=1024 * 1024)
    size = tmp.stat().st_size
    if size != total_size:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, f"{name}: 크기 불일치 (받음 {size}, 기대 {total_size})")

    dest = path / name
    tmp.replace(dest)
    shutil.rmtree(cdir, ignore_errors=True)
    # 파일별 폴더를 지운 뒤 .chunks 자체가 비면 그것도 치운다 (세션 폴더를 깔끔히 유지).
    try:
        cdir.parent.rmdir()
    except OSError:
        pass   # 다른 파일의 조각이 남아 있으면 그대로 둔다
    print(f"  [UP] {name:<30} {human_size(size)}  (조각 {chunk_count}개 합침)")

    if name == "depth.zip":
        try:
            extract_depth_zip(dest, path / "depth")
            print("       depth/ 압축 해제 완료")
        except Exception as e:
            print(f"       ⚠ depth 압축 해제 실패(원본 zip은 보존): {e}")

    return {"status": "ok", "filename": name, "size": size, "chunks": chunk_count}


@app.post("/session/upload")
async def session_upload(session_id: str = Form(...), file: UploadFile = File(...)):
    path = session_dir(session_id)
    if not path.is_dir():
        raise HTTPException(404, "session/start를 먼저 호출하세요")

    # 파일명은 basename만 취해 경로 성분을 제거한 뒤 화이트리스트와 대조한다.
    name = os.path.basename(file.filename or "")
    if name not in ALLOWED_FILENAMES:
        raise HTTPException(400, f"허용되지 않은 파일명: {name!r}")

    dest = path / name
    # 청크 복사 — scene_mesh.ply가 수십 MB라 통째로 메모리에 올리면 안 된다.
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out, length=1024 * 1024)
    size = dest.stat().st_size
    print(f"  [UP] {name:<30} {human_size(size)}")

    # depth.zip은 받은 즉시 풀어둔다 (나중에 분석할 때 편하도록).
    if name == "depth.zip":
        try:
            extract_depth_zip(dest, path / "depth")
            print("       depth/ 압축 해제 완료")
        except Exception as e:
            print(f"       ⚠ depth 압축 해제 실패(원본 zip은 보존): {e}")

    return {"status": "ok", "filename": name, "size": size}


def extract_depth_zip(zip_path: Path, dest: Path) -> None:
    """
    zip 폭탄과 경로 순회를 막으면서 푼다. 둘 다 실제로 악용되는 취약점이다.

    ⚠️ 이중 중첩 방지:
      아이폰의 NSFileCoordinator(.forUploading)는 폴더를 통째로 압축하므로 zip 안의 경로가
      "depth/depth_000000.bin" 처럼 폴더명으로 시작한다. 그대로 dest("…/depth")에 풀면
      "depth/depth/depth_000000.bin"이 되어 분석 스크립트가 파일을 못 찾는다.
      (실제로 그렇게 나오는 것을 확인하고 고쳤다.)
      모든 항목이 같은 최상위 폴더를 공유하면 그 한 겹을 벗겨낸다.
    """
    with zipfile.ZipFile(zip_path) as z:
        members = [i for i in z.infolist() if not i.is_dir()]
        total = 0
        for info in members:
            if info.filename.startswith("/") or ".." in Path(info.filename).parts:
                raise ValueError(f"안전하지 않은 경로: {info.filename}")
            total += info.file_size
            if total > MAX_ZIP_UNCOMPRESSED:
                raise ValueError("압축 해제 크기 한도 초과 (zip 폭탄 의심)")
        if not members:
            raise ValueError("zip이 비어 있습니다")

        # 공통 최상위 폴더가 있으면 한 겹 벗긴다
        tops = {Path(i.filename).parts[0] for i in members}
        strip = len(tops) == 1 and any(len(Path(i.filename).parts) > 1 for i in members)

        dest.mkdir(parents=True, exist_ok=True)
        for info in members:
            parts = Path(info.filename).parts
            rel = Path(*parts[1:]) if strip and len(parts) > 1 else Path(*parts)
            if not rel.name or rel.name.startswith("."):
                continue                      # __MACOSX 등 부산물 제외
            out = (dest / rel).resolve()
            if not str(out).startswith(str(dest.resolve())):
                raise ValueError(f"안전하지 않은 경로: {info.filename}")
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, out.open("wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)


@app.post("/session/stop")
def session_stop(session_id: str = Form(...)):
    """
    업로드 완료 신호. 아이폰이 마지막에 한 번 부른다.

    ⚠ 여기서 COLMAP/OpenMVS를 **돌리지 않는다.** metadata.json의
      reconstruction_required=false 가 그 근거다 (LiDAR 세션은 이미 미터 단위 메시가 있다).
      기존 세션처럼 이 키가 없으면 True로 읽혀 "재구성이 필요한 데이터"로 표시만 하고,
      실제 실행은 이 서버의 책임이 아니다.
    """
    path = session_dir(session_id)
    if not path.is_dir():
        raise HTTPException(404, "알 수 없는 session_id")

    meta = read_metadata(path)
    needs_recon = meta.get("reconstruction_required", True)
    mesh_file = path / "scene_mesh.ply"

    print(f"[STOP]  {session_id}")
    print(f"        capture_mode : {meta.get('capture_mode', '(없음 — 구버전 세션)')}")
    if meta.get("mesh_vertex_count"):
        extent = meta.get("mesh_extent_meters") or [0, 0, 0]
        print(f"        메시         : {meta['mesh_vertex_count']:,} vertices / "
              f"{meta.get('mesh_face_count', 0):,} faces")
        print(f"        공간 크기     : {extent[0]:.1f} x {extent[1]:.1f} x {extent[2]:.1f} m")
        counts = meta.get("mesh_class_face_counts") or {}
        if counts:
            print(f"        분류         : " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
        if counts.get("door"):
            print(f"        🚪 문 검출됨 ({counts['door']} faces)")
    if needs_recon:
        print("        ⚠ reconstruction_required=true — 이 서버는 재구성을 하지 않는다 "
              "(LiDAR 세션이 아닌 것으로 보임)")

    # 메시가 있으면 이 맥의 브라우저에 3D 뷰어를 띄운다.
    # 별도 스레드인 이유: webbrowser.open()이 드물게 수 초를 잡아먹는데, 그동안 아이폰의
    # /session/stop 요청이 타임아웃되면 앱에는 "업로드 실패"로 뜬다 — 실제로는 다 올라갔는데도.
    if AUTO_OPEN_VIEWER and mesh_file.exists():
        url = f"http://localhost:8000/viewer/?session={session_id}"
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
        print(f"        🖥  3D 뷰어를 엽니다: {url}")

    # 3DGS 자동 생성을 큐에 넣는다.
    # ⚠️ 여기서 기다리지 않는다. 학습이 17분까지 걸리는데 그동안 아이폰의 /session/stop이
    #    타임아웃되면 앱에는 "업로드 실패"로 뜬다 — 실제로는 다 올라갔는데도.
    #    실패하더라도 업로드는 성공으로 응답한다 (3DGS는 선택적 기능).
    gs = {"queued": False, "reason": "비활성"}
    if gs_job is not None and mesh_file.exists():
        try:
            gs = gs_job.enqueue(path, session_id)
        except Exception as e:                # noqa: BLE001
            print(f"        ⚠ 3DGS 큐 등록 실패(업로드에는 영향 없음): {e}")
            gs = {"queued": False, "reason": str(e)}

    return {
        "status": "ok",
        "session_id": session_id,
        "has_mesh": mesh_file.exists(),
        "reconstruction_required": needs_recon,
        "viewer_url": f"/viewer/?session={session_id}",
        "gs": gs,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 서버 -> 브라우저 (3D 뷰어)
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/sessions")
def list_sessions():
    """뷰어의 세션 드롭다운. 최신순으로 준다 (뷰어는 첫 항목을 자동으로 연다)."""
    out = []
    for d in sorted(SESSIONS_ROOT.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        meta = read_metadata(d)
        extent = meta.get("mesh_extent_meters")
        out.append({
            "session_id": d.name,
            "has_mesh": (d / "scene_mesh.ply").exists(),
            # 뷰어가 "있을 때만" 요청하도록 미리 알려준다.
            # 이게 없으면 YOLO를 안 돌린 세션마다 로그에 404가 쌓여, 진짜 문제가 묻힌다.
            "has_objects": (d / "objects_3d.json").exists(),
            # ⚠️ 주의점 1: 뎁스 없는 세션은 융합 버튼을 눌러도 실패한다.
            #    뷰어가 미리 비활성화할 수 있도록 여기서 알려준다.
            "has_depth": (d / "depth").is_dir()
                         and any(f.name.startswith("depth_") for f in (d / "depth").iterdir()),
            "has_fused": (d / "fused_mesh.ply").exists(),
            "has_adaptive": (d / "fused_adaptive.ply").exists(),
            "person_count": len(json.loads((d / "persons.json").read_text(encoding="utf-8"))
                                .get("persons", [])) if (d / "persons.json").exists() else 0,
            "vertex_count": meta.get("mesh_vertex_count", 0),
            "extent_meters": extent,
            "captured_at": meta.get("session_start_wallclock_iso8601", ""),
        })
    return out


@app.get("/session/{session_id}/file/{filename}")
def session_file(session_id: str, filename: str):
    """세션 파일 원본. 화이트리스트 + 경로 정규화로 이중 방어한다."""
    path = session_dir(session_id)
    name = os.path.basename(filename)
    if not allowed_filename(name):
        raise HTTPException(400, f"허용되지 않은 파일명: {name!r}")
    target = (path / name).resolve()
    if not str(target).startswith(str(path)) or not target.is_file():
        raise HTTPException(404, "파일 없음")
    return FileResponse(target)


@app.get("/session/{session_id}")
def session_detail(session_id: str):
    path = session_dir(session_id)
    if not path.is_dir():
        raise HTTPException(404, "알 수 없는 session_id")
    files = [
        {"name": f.name, "size": f.stat().st_size}
        for f in sorted(path.iterdir()) if f.is_file()
    ]
    return {"session_id": session_id, "files": files, "metadata": read_metadata(path)}


def run_script(script: Path, args: list, timeout: int = 1800):
    """
    후처리 스크립트를 **별도 프로세스**로 돌린다.

    왜 별도 프로세스인가:
      ① open3d/YOLO 연산이 CPU를 오래 점유하는데, 같은 프로세스에서 돌리면 그동안
         아이폰의 업로드 요청까지 막힌다 (촬영 중인 대원이 올리지 못하게 된다).
      ② torch(YOLO)와 open3d를 한 프로세스에서 import하면 이 환경에서 멈춘다 —
         적응형 융합을 두 단계로 나눈 이유이기도 하다.
    """
    proc = subprocess.run([sys.executable, str(script), *[str(a) for a in args]],
                          capture_output=True, text=True,
                          cwd=str(BASE_DIR.parent), timeout=timeout)
    return proc.returncode == 0, (proc.stdout + proc.stderr)


def require_depth(path: Path, session_id: str):
    """
    ⚠️ 주의점 1: 뎁스가 업로드된 세션에서만 직접 융합이 가능하다.
       뎁스 없이 실행하면 스크립트가 알 수 없는 오류로 죽는다. 먼저 막고 이유를 말한다.
    """
    dep = path / "depth"
    n = len([f for f in dep.iterdir() if f.name.startswith("depth_")]) if dep.is_dir() else 0
    if n == 0:
        raise HTTPException(400, f"{session_id}에 뎁스가 없습니다. "
                                 f"앱의 '뎁스도 업로드'를 켜고 다시 촬영·업로드하세요.")
    return n


@app.post("/fuse")
def fuse(session_id: str = Form(...), voxel: float = Form(0.02), maxd: float = Form(4.0)):
    """직접 융합 — ARKit 메시 대신 뎁스+포즈로 재구성한다 (신뢰도 불필요)."""
    path = session_dir(session_id)
    n = require_depth(path, session_id)
    print(f"\n[FUSE] {session_id} (뎁스 {n}프레임, 복셀 {voxel*100:.0f}cm)")
    ok, log = run_script(SCRIPTS / "fuse_depth.py",
                         [str(path), "--voxel", voxel, "--maxd", maxd, "--out", "fused_mesh.ply"])
    print(log)
    if not ok:
        raise HTTPException(500, f"융합 실패: {log[-400:]}")
    return {"status": "ok", "file": "fused_mesh.ply", "log": log}


@app.post("/fuse-adaptive")
def fuse_adaptive(session_id: str = Form(...), bg_voxel: float = Form(0.04),
                  obj_voxel: float = Form(0.01), window: float = Form(0.0),
                  classes: str = Form("person")):
    """
    적응형 해상도 융합 — 배경은 거칠게, 관심 객체는 정밀하게.

    ⚠️ 주의점 2: 두 단계를 순차 실행한다 (torch/open3d 충돌 회피).
       사용자에겐 버튼 하나로 보이지만, 실패하면 **어느 단계에서 실패했는지** 반드시 알린다.
       1단계 실패(YOLO)와 2단계 실패(융합)는 원인도 조치도 완전히 다르기 때문이다.
    """
    path = session_dir(session_id)
    n = require_depth(path, session_id)
    print(f"\n[ADAPTIVE] {session_id} (뎁스 {n}프레임, 배경 {bg_voxel*100:.0f}cm / "
          f"객체 {obj_voxel*100:.0f}cm, 클래스 {classes})")

    # 이전 실행의 찌꺼기가 남아 있으면 뷰어가 옛 진행률을 보여준다. 먼저 지운다.
    try: (path / "_progress.json").unlink()
    except FileNotFoundError: pass
    ok1, log1 = run_script(SCRIPTS / "stage1_masks.py", [str(path), classes])
    print(log1)
    if not ok1:
        raise HTTPException(500, {"stage": 1, "name": "객체 검출(YOLO)",
                                  "hint": "YOLO 모델 파일(yolov8n.pt)을 찾지 못했거나 "
                                          "video.mov가 없을 수 있습니다.",
                                  "log": log1[-400:]})

    # window(시간창)는 **0 = 제한 없음**이 기본이어야 한다.
    # "첫 사람이 보인 시각부터 N초"라서, 사람들이 촬영 내내 등장하면 대부분이 잘린다.
    # 실측(session_20260919v6): window 3.0 -> 객체 10프레임 / 사람 1명,
    #                           window 0.0 -> 객체 430프레임 / 사람 9명.
    # 움직임에 의한 겹침은 아래 사람별 크기 필터가 걸러낸다.
    ok2, log2 = run_script(SCRIPTS / "stage2_fuse.py",
                           [str(path), bg_voxel, obj_voxel, window])
    print(log2)
    if not ok2:
        raise HTTPException(500, {"stage": 2, "name": "융합(TSDF)",
                                  "hint": "뎁스 파일이나 포즈가 손상되었을 수 있습니다. "
                                          "1단계(객체 검출)는 성공했습니다.",
                                  "log": log2[-400:]})
    try: (path / "_progress.json").unlink()
    except FileNotFoundError: pass
    return {"status": "ok", "file": "fused_adaptive.ply",
            "stage1_log": log1, "stage2_log": log2}


@app.post("/detect")
def detect(session_id: str = Form(...), stride: int = Form(5), conf: float = Form(0.35),
           mesh: str = Form("scene_mesh.ply")):
    """
    YOLO 객체 검출 + 3D 위치. 뎁스가 없어도 메시만 있으면 동작한다.

    ⚠️ 적응형 융합과 같은 이유로 **2단계 순차 실행**이다.
       (구버전 detect_objects_3d.py는 open3d와 YOLO를 한 프로세스에서 import해
        CPU 0%로 무한 대기했다 — 실측 확인 후 분리.)
       실패 시 어느 단계인지 반드시 알린다.
    """
    path = session_dir(session_id)
    if not (path / mesh).exists():
        raise HTTPException(400, f"{session_id}에 {mesh}가 없습니다.")
    print(f"\n[DETECT] {session_id} (stride {stride}, conf {conf}, mesh {mesh})")

    ok1, log1 = run_script(SCRIPTS / "detect_stage1.py",
                           [str(path), "--stride", stride, "--conf", conf])
    print(log1)
    if not ok1:
        raise HTTPException(500, {"stage": 1, "name": "객체 검출(YOLO)",
                                  "hint": "video.mov가 없거나 YOLO 모델 파일을 찾지 못했습니다.",
                                  "log": log1[-400:]})

    ok2, log2 = run_script(SCRIPTS / "detect_stage2.py", [str(path), "--mesh", mesh])
    print(log2)
    if not ok2:
        raise HTTPException(500, {"stage": 2, "name": "3D 매핑",
                                  "hint": f"{mesh} 또는 arkit_pose.csv에 문제가 있을 수 있습니다. "
                                          f"1단계(객체 검출)는 성공했습니다.",
                                  "log": log2[-400:]})
    return {"status": "ok", "file": "objects_3d.json",
            "stage1_log": log1, "stage2_log": log2}


@app.post("/colorize")
def colorize(session_id: str = Form(...), stride: int = Form(2)):
    """
    분리된 사람 메시에 **영상의 실제 색**을 입힌다.

    한 번도 관측되지 않은 정점은 회색으로 남는다 — 안 본 것을 칠해 넣지 않는다는 원칙
    (documents/warning/0917v1_2148 3번).
    """
    path = session_dir(session_id)
    pj = path / "persons.json"
    if not pj.exists():
        raise HTTPException(400, f"{session_id}에 사람 분리 결과가 없습니다. "
                                 f"먼저 '적응형 융합'을 실행하세요.")
    persons = json.loads(pj.read_text(encoding="utf-8")).get("persons", [])
    if not persons:
        raise HTTPException(400, "분리된 사람이 없습니다. 사람이 가까이·여러 각도로 찍혔는지 확인하세요.")

    print(f"\n[COLORIZE] {session_id} — 사람 {len(persons)}명")
    done = []
    for p in persons:
        ok, log = run_script(SCRIPTS / "color_mesh.py", [str(path), p["file"], "--stride", stride])
        print(log)
        if not ok:
            raise HTTPException(500, f"{p['file']} 색 입히기 실패: {log[-300:]}")
        done.append(p["file"].replace(".ply", "_colored.ply"))

    # 참조 사진도 같이 뽑는다. 3D 옆에 실제 사진을 나란히 놓아야
    # "얼마나 더 사실적일 수 있는가"를 눈으로 판단할 수 있다.
    okp, logp = run_script(SCRIPTS / "person_photos.py", [str(path)])
    print(logp)
    return {"status": "ok", "files": done, "count": len(done),
            "photos": okp, "photo_log": logp if okp else None}


@app.post("/merge")
def merge(sessions: str = Form(...), voxel: float = Form(0.06)):
    """
    두 대(이상)의 아이폰 세션을 하나로 병합한다. 뷰어의 [병합] 버튼이 부른다.

    스크립트를 별도 프로세스로 돌리는 이유: open3d 정합은 CPU를 오래 점유하는데,
    같은 프로세스에서 돌리면 그동안 아이폰의 업로드 요청까지 막힌다.
    (촬영 중인 다른 대원이 올리지 못하는 상황을 만들면 안 된다.)

    ⚠️ 동기 호출이라 응답까지 수십 초 걸릴 수 있다. 뷰어는 그동안 진행 표시를 띄운다.
    """
    ids = [x.strip() for x in sessions.split(",") if x.strip()]
    if len(ids) < 2:
        raise HTTPException(400, "세션을 2개 이상 지정하세요")
    paths = []
    for sid in ids:
        p = session_dir(sid)                     # 경로 순회 검사 포함
        if not (p / "scene_mesh.ply").exists():
            raise HTTPException(400, f"{sid} 에 scene_mesh.ply 가 없습니다 "
                                     f"(LiDAR 미지원 기기로 찍었을 수 있습니다)")
        paths.append(str(p))
    if not MERGE_SCRIPT.exists():
        raise HTTPException(500, f"병합 스크립트를 찾을 수 없습니다: {MERGE_SCRIPT}")

    print(f"\n[MERGE] {' + '.join(ids)}")
    proc = subprocess.run(
        [sys.executable, str(MERGE_SCRIPT), *paths, "--voxel", str(voxel)],
        capture_output=True, text=True, cwd=str(BASE_DIR.parent), timeout=900)
    out = proc.stdout + proc.stderr
    print(out)

    # 병합 결과 폴더는 스크립트가 merged_<타임스탬프> 이름으로 만든다.
    created = None
    for line in out.splitlines():
        if "병합 완료:" in line:
            created = line.split("병합 완료:")[1].strip()
    ok = proc.returncode == 0 and created is not None
    # 한 세션도 못 붙였으면 기준 세션만 복사된 것이라 병합이라 부를 수 없다 — 정직하게 알린다
    merged_any = "✅ 병합됨" in out
    return {
        "status": "ok" if ok else "failed",
        "merged_session": created,
        "merged_any": merged_any,
        "log": out,
        "viewer_url": f"/viewer/?session={created}" if created else None,
    }


@app.get("/")
def root(request: Request):
    """뷰어로 보낸다. 토큰이 쿼리에 있으면 그대로 넘겨 한 번에 들어가지게 한다."""
    token = request.query_params.get("token", "")
    return RedirectResponse(f"/viewer/?token={token}" if token else "/viewer/")


# 뷰어를 정적 파일로 마운트한다. html=True 라서 /viewer/ 로 index.html이 뜨고,
# 같은 폴더의 sample_scene_mesh.ply 같은 상대 경로 참조도 그대로 동작한다.
if VIEWER_DIR.is_dir():
    app.mount("/viewer", StaticFiles(directory=str(VIEWER_DIR), html=True), name="viewer")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    # 로그를 파일로 리다이렉트해도 즉시 보이게 한다 (기본은 블록 버퍼링이라
    # 서버를 끄기 전까지 아무것도 안 보인다).
    ip = lan_ip()
    print("=" * 62)
    print("  LiDAR_Space3D 서버")
    print("=" * 62)
    print(f"  저장 위치   : {SESSIONS_ROOT}")
    print()
    q = f"?token={AUTH_TOKEN}" if AUTH_TOKEN else ""
    print(f"  📱 아이폰 앱에 입력:   Server = http://{ip}:8000")
    if AUTH_TOKEN:
        print(f"                        Token  = {AUTH_TOKEN}")
    print(f"  🖥  브라우저에서 3D:    http://{ip}:8000/viewer/{q}")
    print(f"                        http://localhost:8000/viewer/{q}")
    print()
    if AUTH_TOKEN:
        print("  🔒 인증 켜짐 — 토큰 없는 요청은 401로 거부됩니다.")
        print("     공개 URL(Cloudflare Tunnel 등)로 열어도 안전합니다.")
    else:
        print("  ⚠️  인증 꺼짐 — 같은 Wi-Fi 안에서만 쓰세요.")
        print("     공개 URL로 열려면 LIDAR_TOKEN 환경변수를 반드시 설정하세요:")
        print("       export LIDAR_TOKEN=$(python3 -c \'import secrets;print(secrets.token_urlsafe(24))\')")
    print("=" * 62)
    uvicorn.run(app, host="0.0.0.0", port=8000)
