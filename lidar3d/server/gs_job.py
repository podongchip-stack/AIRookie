"""3DGS 자동 처리 작업 큐.

업로드가 끝나면 사람별 3DGS까지 자동으로 만든다:
  적응형 융합 -> COLMAP 내보내기 -> GPU 업로드 -> 학습 -> 크롭 -> 다운로드

세 가지 원칙:

  ① **선택적 단계다.** LIDAR_GPU_HOST가 없거나 GPU가 죽어도 업로드·메시·사람 검출은
     정상 동작해야 한다. 3DGS는 있으면 좋은 것이지 없으면 안 되는 것이 아니다.
     (대회 GPU 서버는 2026-11-05에 회수된다 — 그때 이 경로는 반드시 죽는다.)

  ② **한 번에 하나만 돌린다.** GPU가 하나뿐이라 두 세션이 동시에 학습하면
     메모리와 시간이 경합한다. 큐로 순차 처리한다.

  ③ **진행 상황을 파일로 남긴다.** 학습이 17분까지 걸리므로, 뷰어가 "없음"과
     "만드는 중"을 구분하지 못하면 사용자는 고장으로 오해한다.

SSH 키는 이 코드에 넣지 않는다. ~/.ssh/config의 Host 별칭(IdentityFile 포함)을 쓴다.
"""
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SCRIPTS = BASE_DIR.parent / "scripts"

# ─────────────────────────────────────────────────────────────────────────────
# 설정 — 전부 환경변수. 호스트가 없으면 3DGS 단계를 통째로 건너뛴다.
# ─────────────────────────────────────────────────────────────────────────────
GPU_HOST = os.environ.get("LIDAR_GPU_HOST", "").strip()
GPU_ITERS = int(os.environ.get("LIDAR_GPU_ITERS", "30000"))
GPU_FACTOR = int(os.environ.get("LIDAR_GPU_FACTOR", "2"))
GPU_REMOTE_DATA = os.environ.get("LIDAR_GPU_DATA", "data")
GPU_REMOTE_OUT = os.environ.get("LIDAR_GPU_OUT", "out")
GPU_PYTHON = os.environ.get("LIDAR_GPU_PYTHON", "~/gs-env/bin/activate")

STATUS_FILE = "gs_status.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_status(session_path: Path, **fields) -> None:
    """상태를 세션 폴더에 기록한다. 뷰어가 이 파일을 폴링한다."""
    path = session_path / STATUS_FILE
    try:
        cur = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        cur = {}
    cur.update(fields)
    cur["updated_at"] = _now()
    try:
        path.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:                       # 상태 기록 실패가 작업을 죽이면 안 된다
        print(f"  [GS] 상태 기록 실패: {e}")


def _run(cmd: list, timeout: int = 3600) -> tuple[bool, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           cwd=str(BASE_DIR.parent))
        out = (p.stdout or "") + (p.stderr or "")
        return p.returncode == 0, out
    except subprocess.TimeoutExpired:
        return False, f"시간 초과 ({timeout}초)"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _ssh(remote_cmd: str, timeout: int = 3600) -> tuple[bool, str]:
    return _run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
                 GPU_HOST, remote_cmd], timeout)


# ─────────────────────────────────────────────────────────────────────────────
# 파이프라인
# ─────────────────────────────────────────────────────────────────────────────
def _need_fusion(sp: Path) -> bool:
    return not (sp / "persons.json").exists()


def _stage_fusion(sp: Path, sid: str) -> tuple[bool, str]:
    """적응형 융합. 사람별 경계상자(persons.json)가 있어야 3DGS를 자를 수 있다."""
    if not _need_fusion(sp):
        return True, "이미 있음"
    if not (sp / "depth").is_dir():
        return False, "뎁스가 없어 사람 분리를 할 수 없습니다 (앱의 '뎁스도 업로드'를 켜세요)"
    write_status(sp, stage="fusion", progress=5, message="사람 검출·융합 중…")
    ok, log = _run(["python3", str(SCRIPTS / "stage1_masks.py"), str(sp), "person"], 3600)
    if not ok:
        return False, f"1단계(YOLO) 실패: {log[-300:]}"
    # window=0 — 시간창을 주면 첫 사람이 보인 뒤 N초만 남아 대부분이 잘린다.
    ok, log = _run(["python3", str(SCRIPTS / "stage2_fuse.py"), str(sp), "0.04", "0.01", "0.0"], 3600)
    if not ok:
        return False, f"2단계(융합) 실패: {log[-300:]}"
    return True, log[-300:]


def _stage_export(sp: Path, work: Path) -> tuple[bool, str]:
    write_status(sp, stage="export", progress=15, message="COLMAP 포맷으로 내보내는 중…")
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    return _run(["python3", str(SCRIPTS / "export_colmap.py"), str(sp), "-o", str(work)], 3600)


def _stage_upload(sp: Path, work: Path, sid: str) -> tuple[bool, str]:
    write_status(sp, stage="upload", progress=25, message="GPU 서버로 전송 중…")
    ok, log = _ssh(f"mkdir -p {GPU_REMOTE_DATA}/{sid}", 60)
    if not ok:
        return False, f"GPU 서버 접속 실패: {log[-200:]}"
    ok, log = _run(["rsync", "-az", "--partial", f"{work}/",
                    f"{GPU_HOST}:{GPU_REMOTE_DATA}/{sid}/"], 3600)
    if not ok:
        return False, f"전송 실패: {log[-200:]}"
    # persons.json은 크롭에 필요하다 (COLMAP 내보내기에는 없다).
    return _run(["scp", "-q", str(sp / "persons.json"),
                 f"{GPU_HOST}:{GPU_REMOTE_DATA}/{sid}/persons.json"], 300)


def _stage_train(sp: Path, sid: str) -> tuple[bool, str]:
    """원격 학습. 진행률을 폴링해 상태 파일에 반영한다."""
    write_status(sp, stage="train", progress=30, message="3DGS 학습 시작…")
    # 이전 시도에서 이미 학습이 끝났으면(우리 쪽만 실패로 기록된 경우 포함) 다시 돌리지 않는다.
    ok, out = _ssh(f"test -f {GPU_REMOTE_OUT}/{sid}/point_cloud.ply && echo exists", 60)
    if ok and "exists" in out:
        return True, "이미 학습된 결과가 있어 건너뜁니다"
    log_remote = f"~/train_{sid}.log"
    # ⚠️ 표준 입출력을 **모두** 끊어야 ssh가 바로 돌아온다.
    #   nohup과 `&`만으로는 부족하다. 원격 프로세스가 ssh 채널의 stdout/stderr를 물고 있으면
    #   ssh는 그 스트림이 닫힐 때까지 기다린다 — 학습이 끝날 때까지(17분) 붙잡혀 있다가
    #   타임아웃으로 "시작 실패"가 된다. 실제로는 학습이 정상 실행 중인데도.
    #   (`< /dev/null`과 `2>&1`로 로그 파일에 묶고, setsid로 세션까지 분리한다.)
    cmd = (f"source {GPU_PYTHON} && export TORCH_CUDA_ARCH_LIST=8.0 CUDA_HOME=/usr && "
           f"setsid nohup python ~/train_3dgs.py {GPU_REMOTE_DATA}/{sid} "
           f"-o {GPU_REMOTE_OUT}/{sid} --iters {GPU_ITERS} --factor {GPU_FACTOR} "
           f"--save-every 0 > {log_remote} 2>&1 < /dev/null & "
           f"disown; echo started")
    ok, log = _ssh(cmd, 60)
    if not ok or "started" not in log:
        return False, f"학습 시작 실패: {log[-200:]}"

    # 진행률 폴링. pgrep으로 살았는지 보는 방식은 쓰지 않는다 —
    # 패턴이 폴링 명령 자신을 잡아 영원히 도는 사고가 실제로 있었다.
    # 대신 로그의 마지막 스텝이 멈췄는지로 판단한다.
    step_re = re.compile(r"step\s+(\d+)/(\d+)")
    last_step, stale = -1, 0
    deadline = time.time() + 3 * 3600
    while time.time() < deadline:
        time.sleep(20)
        ok, out = _ssh(f"tail -3 {log_remote}", 60)
        if not ok:
            stale += 1
            if stale > 10:
                return False, "GPU 서버와 연결이 끊겼습니다"
            continue
        stale = 0
        if "학습 완료" in out or "저장:" in out:
            return True, out[-300:]
        if "Error" in out or "Traceback" in out:
            return False, f"학습 오류: {out[-300:]}"
        m = None
        for m in step_re.finditer(out):
            pass
        if m:
            step, total = int(m.group(1)), int(m.group(2))
            if step != last_step:
                last_step = step
                write_status(sp, stage="train", progress=30 + int(55 * step / max(total, 1)),
                             message=f"3DGS 학습 중… {step:,}/{total:,}")
    return False, "학습 시간 초과 (3시간)"


def _stage_crop_download(sp: Path, sid: str) -> tuple[bool, str]:
    write_status(sp, stage="crop", progress=88, message="사람별로 잘라내는 중…")
    ok, log = _ssh(f"source {GPU_PYTHON} && python ~/crop_3dgs.py "
                   f"{GPU_REMOTE_OUT}/{sid}/point_cloud.ply {GPU_REMOTE_DATA}/{sid}", 900)
    if not ok:
        return False, f"크롭 실패: {log[-300:]}"
    write_status(sp, stage="download", progress=94, message="결과를 내려받는 중…")
    ok, log2 = _run(["rsync", "-az",
                     f"{GPU_HOST}:{GPU_REMOTE_DATA}/{sid}/gs_person_*.ply",
                     f"{GPU_HOST}:{GPU_REMOTE_DATA}/{sid}/gs_persons.json",
                     str(sp) + "/"], 3600)
    return (ok, log + log2)


def process(session_path: Path, session_id: str) -> None:
    """한 세션의 전체 파이프라인. 예외를 밖으로 내보내지 않는다."""
    work = Path("/tmp") / f"gs_{session_id}"
    try:
        write_status(session_path, state="running", stage="fusion", progress=0,
                     message="시작…", error=None)
        for fn, args in ((_stage_fusion, (session_path, session_id)),
                         (_stage_export, (session_path, work)),
                         (_stage_upload, (session_path, work, session_id)),
                         (_stage_train, (session_path, session_id)),
                         (_stage_crop_download, (session_path, session_id))):
            ok, log = fn(*args)
            if not ok:
                print(f"  [GS] {session_id} 실패: {log[:400]}")
                write_status(session_path, state="failed", progress=0,
                             message="3DGS 생성 실패", error=log[-400:])
                return
        n = 0
        gj = session_path / "gs_persons.json"
        if gj.exists():
            try:
                n = len(json.loads(gj.read_text(encoding="utf-8")).get("persons", []))
            except Exception:
                pass
        write_status(session_path, state="done", stage="done", progress=100,
                     message=f"3DGS 준비 완료 — 사람 {n}명", persons=n, error=None)
        print(f"  [GS] {session_id} 완료 — 사람 {n}명")
    except Exception as e:                        # 작업 스레드가 죽으면 큐 전체가 멈춘다
        print(f"  [GS] {session_id} 예외: {type(e).__name__}: {e}")
        write_status(session_path, state="failed", message="3DGS 생성 중 오류",
                     error=f"{type(e).__name__}: {e}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────────
# 큐 — GPU가 하나뿐이라 한 번에 하나씩만 돌린다
# ─────────────────────────────────────────────────────────────────────────────
_q: "queue.Queue[tuple[Path, str]]" = queue.Queue()
_worker: threading.Thread | None = None
_lock = threading.Lock()


def _loop() -> None:
    while True:
        sp, sid = _q.get()
        try:
            process(sp, sid)
        finally:
            _q.task_done()


def enqueue(session_path: Path, session_id: str) -> dict:
    """업로드 완료 후 호출. GPU 설정이 없으면 조용히 건너뛰되 이유는 남긴다."""
    if not GPU_HOST:
        write_status(session_path, state="skipped", progress=0,
                     message="3DGS 미설정 (LIDAR_GPU_HOST 없음)",
                     error=None)
        return {"queued": False, "reason": "LIDAR_GPU_HOST 미설정"}

    global _worker
    with _lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_loop, daemon=True, name="gs-worker")
            _worker.start()
    ahead = _q.qsize()
    write_status(session_path, state="queued", progress=0,
                 message=f"대기 중… (앞에 {ahead}건)" if ahead else "대기 중…",
                 error=None)
    _q.put((session_path, session_id))
    print(f"  [GS] {session_id} 큐 등록 (대기 {ahead}건, iters={GPU_ITERS}, factor={GPU_FACTOR})")
    return {"queued": True, "ahead": ahead}
