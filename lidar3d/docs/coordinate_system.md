# 좌표계 규약 (LiDAR 캡처)

> **핵심 원칙: 앱은 좌표를 변환하지 않는다.** ARKit 원본을 그대로 기록하고,
> COLMAP 등 다른 규약으로의 변환은 전부 Mac 쪽에서 한다.
> 변환을 앱에 넣으면 "어느 단계에서 한 번 변환됐는지"를 아무도 추적할 수 없게 되고,
> 두 번 변환되거나 아예 안 된 데이터가 에러 없이 섞인다.

## 1. ARKit world 좌표계

| 항목 | 값 |
|---|---|
| 손 방향 | **오른손 좌표계** |
| Y축 | **중력 반대 방향(위)** — ARKit이 가속도계로 정렬한다 |
| 원점 | **세션 시작 시점의 기기 포즈** (절대 위치가 아니다) |
| 단위 | **미터** |
| 카메라 시선 | 카메라는 자신의 **-Z** 방향을 본다 |

X/Z축의 방향은 세션 시작 시 기기가 향하던 방향에 따라 정해진다. 즉 **세션마다 다르다.**
여러 세션을 합치려면 별도의 정합(registration)이 필요하다 — 좌표값이 같다고 같은 장소가 아니다.

## 2. `arkit_pose.csv`

```
frame_index,timestamp,tx,ty,tz,qx,qy,qz,qw,tracking_state,tracking_state_reason,fx,fy,cx,cy
```

| 컬럼 | 의미 |
|---|---|
| `frame_index` | `video.mov`의 프레임 번호. **-1이면 이 포즈에 대응하는 영상 프레임이 없다** (포즈는 매 프레임, 영상은 `video_saved_hz`로 솎아 기록하기 때문) |
| `timestamp` | `ARFrame.timestamp` **원본**. 보정 없음 |
| `tx,ty,tz` | 카메라 위치 (미터). `camera.transform.columns.3` |
| `qx,qy,qz,qw` | **camera-to-world** 회전 쿼터니언. `simd_quatf` 순서 그대로 |
| `tracking_state` | 0=notAvailable 1=limited 2=normal |
| `tracking_state_reason` | 0=none 1=initializing 2=excessiveMotion 3=insufficientFeatures 4=relocalizing |
| `fx,fy,cx,cy` | `camera.intrinsics`. **네이티브 landscape 픽셀 좌표계 기준** |

### ⚠ 가장 틀리기 쉬운 지점: 변환의 방향

ARKit의 `camera.transform`은 **camera-to-world**다. COLMAP이 쓰는 것은 **world-to-camera**다.

```
ARKit : X_world = R · X_cam + t         (R = quat(qx,qy,qz,qw), t = (tx,ty,tz))
COLMAP: X_cam   = R_c · X_world + t_c
```

따라서 변환은 단순한 부호 뒤집기가 아니라 **역변환**이다:

```python
R_c = R.T
t_c = -R.T @ t
```

여기에 더해 축 규약이 다르다 (ARKit은 Y-up/-Z-forward, COLMAP은 Y-down/+Z-forward):

```python
import numpy as np
from scipy.spatial.transform import Rotation

FLIP = np.diag([1, -1, -1])        # ARKit(Y-up, -Z fwd) -> COLMAP(Y-down, +Z fwd)

def arkit_to_colmap(tx, ty, tz, qx, qy, qz, qw):
    R = Rotation.from_quat([qx, qy, qz, qw]).as_matrix()   # camera-to-world
    t = np.array([tx, ty, tz])
    R_cam = FLIP @ R.T                                     # world-to-camera
    t_cam = -R_cam @ t
    return R_cam, t_cam
```

> `scipy`의 `from_quat`은 `[x, y, z, w]` 순서다. CSV 컬럼 순서와 같으므로 그대로 넣으면 된다.
> `w`를 앞에 두는 라이브러리(예: `pyquaternion`)에 그대로 넣으면 **조용히 틀린 회전**이 나온다.

## 3. 영상과 intrinsics의 정합

**`video.mov`에는 회전 transform을 붙이지 않았다.** 기존 AVFoundation 경로는 세로로 들고 찍는
경험을 맞추려고 90° 회전 메타데이터를 붙였지만, LiDAR 경로에서는 의도적으로 뺐다.

이유: `fx,fy,cx,cy`는 **회전 전 landscape 원본 픽셀 좌표계** 기준값이다. 영상만 세로로 돌리면
Mac에서 뽑은 프레임은 세로인데 intrinsics는 가로 기준이 되어, 아무 에러 없이 **조용히 틀린
재투영**이 나온다. LiDAR로 얻은 절대 스케일의 의미가 바로 여기서 죽는다.

→ `video.mov`의 프레임은 `metadata.json`의 `video_frame_width × video_frame_height`와
   픽셀 단위로 정확히 일치하며, intrinsics를 그대로 적용하면 된다.
   화면 프리뷰는 ARSCNView가 알아서 세로로 보여주므로 촬영자의 경험은 달라지지 않는다.

## 4. 시계(clock)

모든 timestamp는 **단조 증가하는 시스템 uptime** (`CACurrentMediaTime()`과 같은 시계)이다.
wall-clock이 아니므로 기기를 재부팅하면 0부터 다시 시작한다.
세션의 wall-clock 시작 시각은 `metadata.json`의 `session_start_wallclock_iso8601`에 있다.

| 파일 | 시계 |
|---|---|
| `arkit_pose.csv` | `ARFrame.timestamp` |
| `video_frames.csv` | `ARFrame.timestamp` (같은 값) |
| `coaching.csv` | `ARFrame.timestamp` (같은 값) |
| `depth/index.csv` | `ARFrame.timestamp` (같은 값) |
| `imu.csv`, `device_motion.csv` | CoreMotion `.timestamp` (같은 uptime 시계, 다른 센서) |

위 네 개는 **같은 `ARFrame` 객체에서 읽은 동일한 double 값**이다. 근사 매칭 없이
정확한 동등 조인(`==`)이 성립한다.

### 영상 PTS만은 예외 — 그리고 그 오프셋을 명시한다

`AVAssetWriter`는 0 기준 상대 PTS만 받으므로 첫 프레임의 timestamp를 빼는 것이 구조적으로
불가피하다. 뺀 값을 숨기지 않고 `metadata.json`의 `video_pts_epoch`로 내보낸다:

```
original_timestamp = pts_seconds + video_pts_epoch     # 정확히 성립
```

CSV에는 항상 원본 timestamp가 들어간다. 오차는 측정해서 보고할 대상이지 숨길 대상이 아니다.

## 5. 메시 (`scene_mesh.ply`)

- 좌표는 **ARKit world**, 미터. 위 1절과 동일.
- `ARMeshGeometry`의 원본 좌표는 **앵커 로컬**이지만, 내보낼 때 `anchor.transform`을 곱해
  월드로 변환한 뒤 저장한다. 파일 안의 값은 이미 월드 좌표다.
- 면 감김(winding)은 ARKit 기본인 **반시계(CCW)**.
- 정점 색은 면 분류를 눈으로 보기 위한 **시각화**다. 기계가 읽어야 하는 정답 라벨은
  `scene_mesh_faces_class.bin` (면당 UInt8 1바이트, PLY의 면 순서와 동일).
  이유: Open3D와 three.js PLYLoader 모두 PLY 면의 커스텀 property를 **조용히 버린다.**

```python
import open3d as o3d, numpy as np, json
mesh = o3d.io.read_triangle_mesh("scene_mesh.ply")     # 정점 색은 살아서 온다
cls  = np.fromfile("scene_mesh_faces_class.bin", dtype=np.uint8)
meta = json.load(open("metadata.json"))
legend = meta["mesh_classification_legend"]            # {"door": 7, ...}

tris = np.asarray(mesh.triangles)
door_tris = tris[cls[:len(tris)] == legend["door"]]    # 문에 해당하는 삼각형만
print("문 면 개수:", len(door_tris))
print("공간 크기(m):", meta["mesh_extent_meters"])
```

## 6. 뎁스 (`depth/`)

- `depth_%06d.bin`: little-endian **Float32**, row-major, **tightly packed**(행 패딩 제거됨), 미터.
- `conf_%06d.bin`: **UInt8** (0=low, 1=medium, 2=high).
- 크기는 `metadata.json`의 `depth_width × depth_height` (보통 256×192).
- `depth/index.csv`가 `depth_index,timestamp,video_frame_index,depth_file,conf_file`를 들고 있다.
  **파일명 정렬 순서에 의존하지 말 것** — 중간 프레임이 빠질 수 있다.

```python
import numpy as np, json
meta = json.load(open("metadata.json"))
w, h = meta["depth_width"], meta["depth_height"]
d = np.fromfile("depth/depth_000000.bin", dtype="<f4").reshape(h, w)   # 미터
```

뎁스맵(256×192)과 RGB 프레임(예: 1920×1440)은 **같은 4:3 종횡비**라 스케일만 맞추면 되지만,
정확한 대응이 필요하면 intrinsics를 뎁스 해상도에 맞게 스케일해야 한다
(`fx * 256/1920` 등). 뎁스 자체에는 별도 intrinsics가 제공되지 않는다.
