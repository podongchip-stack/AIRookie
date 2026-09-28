# 서버 변경 요청 목록 (Mac `server/app.py`)

> 이 저장소에는 서버 코드가 없어서 **직접 고치지 않았습니다.**
> 파일명을 기존 화이트리스트에 맞춰 우회하지도 않았습니다 (그렇게 하면 서버가 잘못된 스키마로
> 파일을 해석하게 되고, 문제가 훨씬 나중에 엉뚱한 곳에서 터집니다).
> 아래는 새 데이터를 받기 위해 서버에 필요한 변경 전부입니다.

우선순위: 🔴 없으면 동작 안 함 / 🟡 없으면 일부 기능 손실 / 🟢 개선

---

## 🔴 1. `ALLOWED_FILENAMES` 화이트리스트 추가

화이트리스트에 없는 파일명은 400으로 거부됩니다. 다음을 추가해야 합니다:

| 파일명 | 내용 | 대략 크기 |
|---|---|---|
| `scene_mesh.ply` | **3D 모델 본체.** 뷰어가 그리는 것이 이 파일입니다 | 5~60 MB |
| `scene_mesh_faces_class.bin` | 면별 분류 라벨 (UInt8 × 면 개수) | 0.1~1 MB |
| `coaching.csv` | 스캔 품질 경고 로그 | < 50 KB |
| `depth.zip` | 뎁스 프레임 묶음 (**업로드 기본 OFF**) | 50~500 MB |

`arkit_pose.csv`는 이미 등록되어 있습니다 — 그대로 씁니다.

---

## 🔴 2. `/session/stop`에서 파이프라인 분기

**이게 빠지면 LiDAR 세션에도 COLMAP/OpenMVS가 돌아갑니다.** 무의미할 뿐 아니라(이미 미터 단위
메시가 있음), 123초를 낭비하고 실패할 가능성이 높습니다 (LiDAR 세션은 촬영 프레임 수가 적음).

`metadata.json`에 판단 근거를 넣어 두었습니다:

```json
{
  "capture_mode": "lidar_arkit",
  "reconstruction_required": false,
  "primary_model_file": "scene_mesh.ply",
  "schema_version": 2
}
```

```python
meta = json.load(open(session_dir / "metadata.json"))
if meta.get("reconstruction_required", True):
    run_colmap_pipeline(session_dir)      # 기존 photogrammetry 경로
else:
    register_mesh(session_dir, meta["primary_model_file"])   # 메시만 등록하고 끝
```

기존 세션에는 이 키가 없으므로 `.get(..., True)` 기본값이 **예전 동작을 그대로 유지**합니다.

---

## 🔴 3. 업로드 바디 크기 제한

`scene_mesh.ply`가 수십 MB입니다. FastAPI 자체에는 기본 제한이 없지만, 앞단에 nginx 등이
있으면 `client_max_body_size`(기본 1MB)에서 **413**으로 잘립니다.
uvicorn 직접 구동이면 대개 문제없지만 확인이 필요합니다.

---

## 🟡 4. 하위 디렉터리 경로 — zip으로 회피했습니다

`depth/depth_000001.bin`에는 `/`가 들어가는데, 현재 화이트리스트는 *파일명* 기준이라
경로가 들어오면 거부되거나 (더 나쁘게) 경로 순회 취약점이 됩니다.

**앱 쪽에서 `depth.zip` 하나로 묶어 올리도록 만들어서 이 문제를 피했습니다.**
(`NSFileCoordinator`의 `.forUploading` 옵션 — 서드파티 라이브러리 없이 Foundation만으로
디렉터리를 zip으로 만듭니다.) 파일 수백 개에 대해 파일당 1회 HTTP 요청은 비현실적이라
어차피 zip이 맞는 선택이었습니다.

서버에서 압축을 푼다면 **zip 폭탄과 경로 순회를 반드시 방어하세요**:

```python
import zipfile
with zipfile.ZipFile(path) as z:
    for info in z.infolist():
        name = info.filename
        if name.startswith("/") or ".." in name.split("/"):
            raise ValueError(f"unsafe path in zip: {name}")
    z.extractall(dest)
```

---

## 🟡 5. 3D 뷰어용 엔드포인트 3개 (신규)

`server/viewer/index.html`을 만들어 두었습니다. 브라우저에서 메시를 회전/확대하고,
분류별로 켜고 끄고, **두 점을 클릭해 미터 단위 거리를 재는** 뷰어입니다.
동작하려면 엔드포인트 3개가 필요합니다:

```python
@app.get("/viewer")
def viewer():
    return FileResponse("server/viewer/index.html")

@app.get("/sessions")
def sessions():
    # 최신순 정렬을 권장합니다 (뷰어는 첫 항목을 자동으로 엽니다)
    return [
        {"session_id": d.name, "has_mesh": (d / "scene_mesh.ply").exists()}
        for d in sorted(SESSIONS_ROOT.iterdir(), reverse=True) if d.is_dir()
    ]

@app.get("/session/{session_id}/file/{filename}")
def session_file(session_id: str, filename: str):
    # ⚠ session_id와 filename 모두 사용자 입력입니다. 경로 순회를 반드시 막으세요.
    if not re.fullmatch(r"session_[0-9A-Za-z]+", session_id):
        raise HTTPException(400)
    if filename not in ALLOWED_FILENAMES:
        raise HTTPException(400)
    path = (SESSIONS_ROOT / session_id / filename).resolve()
    if not path.is_relative_to(SESSIONS_ROOT.resolve()) or not path.exists():
        raise HTTPException(404)
    return FileResponse(path)
```

**엔드포인트가 없어도 뷰어는 쓸 수 있습니다** — `.ply` 파일을 창에 드래그&드롭하거나
"파일 열기"를 누르면 바로 열립니다. 서버 작업 전에 먼저 확인해 보세요.

---

## 🟡 6. 영상 해상도/종횡비 가정 확인

ARKit은 카메라 포맷을 자유롭게 고를 수 없고 `ARVideoFormat` 중에서만 고릅니다.
LiDAR 기기의 기본값은 대개 **1920×1440 (4:3)** 이라, 기존 1920×1080 (16:9)에서 바뀝니다.

- `04_extract_frames.py` 등이 16:9나 1080p를 가정하고 있는지 확인이 필요합니다.
- 실제 선택된 값은 `metadata.json`의 `video_frame_width` / `video_frame_height` /
  `video_format_selected`에 기록되므로, **하드코딩 대신 이 값을 읽도록** 바꾸는 것을 권장합니다.
- 또한 **회전 transform이 붙어 있지 않습니다** (네이티브 landscape).
  이유는 `docs/coordinate_system.md` 3절 참고 — intrinsics 정합을 위한 의도적 결정입니다.
  기존 코드가 세로 영상을 가정하고 있다면 여기서 차이가 납니다.

---

## 🟢 7. YOLO 경로와의 관계 (선택)

기존 YOLO는 COCO 80클래스라 **door가 없어서** "문이 어디인지"를 알 수 없었습니다.
이제 `scene_mesh_faces_class.bin`이 door/window/wall/floor/ceiling/table/seat를 줍니다.
두 소스를 합치면 (YOLO=사람·사물, 메시=구조물) 서로의 빈 곳을 메웁니다.
이번 변경에 필수는 아니지만, 원래 목표였던 "문까지 2m"는 이제 메시만으로 답이 나옵니다.

---

## 요약 체크리스트

- [ ] 🔴 `ALLOWED_FILENAMES`에 4개 추가
- [ ] 🔴 `/session/stop`에서 `reconstruction_required` 분기
- [ ] 🔴 업로드 바디 크기 제한 확인 (수십 MB)
- [ ] 🟡 `depth.zip` 처리 시 zip 폭탄/경로 순회 방어
- [ ] 🟡 뷰어 엔드포인트 3개 (`/viewer`, `/sessions`, `/session/{id}/file/{name}`)
- [ ] 🟡 영상 해상도 하드코딩 제거 → `metadata.json`에서 읽기
