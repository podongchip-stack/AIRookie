# Claude Code 프롬프트 — LiDAR 기반 3D 캡처 앱

아래 전체를 Claude Code에 붙여넣으세요.
`docs/` 참조가 필요하면 `CAM/documents/0917v2_1905_iOS앱 코드 컨텍스트.md`를 같이 넣으면 좋습니다.

---

## 붙여넣을 프롬프트 (여기서부터)

이 저장소는 **응급현장 3D 인식 시스템**의 iOS 캡처 앱을 LiDAR 기반으로 전환하는 작업 공간이다.

### 배경 — 지금까지 한 것과 왜 바꾸는가

기존 시스템은 iPhone으로 영상만 찍어 Mac 서버로 보내고, 서버가 COLMAP(SfM) + OpenMVS(MVS)로
photogrammetry 3D 재구성을 하는 구조였다. 실측으로 확인된 한계가 두 가지다.

1. **절대 스케일이 없다.** monocular SfM이라 결과 좌표가 "실제 미터"가 아니라 임의 스케일의
   상대 좌표다. 응급현장에서 "문까지 2m"를 말할 수 없다.
2. **재구성이 느리고 불안정하다.** 부스 시연 조건(120프레임)에서 A100 GPU 서버로도 123초가
   걸리고, 촬영이 조금만 빨라도 등록률이 20%대로 떨어져 파편화된다.

iPhone Pro의 **LiDAR 스캐너**는 이 둘을 동시에 해결한다. ARKit이 미터 단위 뎁스와 카메라
포즈를 실시간으로 주므로, 서버 재구성 없이 기기에서 바로 3D가 나온다.

### 참고할 오픈소스 — CedarScan

구현 패턴은 `Tupham16/CedarScan`(iPhone LiDAR 방 스캔 앱, MIT 계열 오픈소스)을 주요 레퍼런스로
삼는다. 단, **코드를 가져다 쓰는 것이 아니라 세 가지 설계 패턴만 차용한다.**

1. **라이브 스캔 코칭** — 스캔 중 화면 테두리 색상·햅틱·음성으로 "너무 빠르게 이동",
   "너무 빠르게 회전", "조명 부족", "너무 가까움", "트래킹 손실"을 실시간 안내한다.
   기존 photogrammetry 경로에서 촬영이 조금만 빨라도 등록률이 20%대로 떨어졌던 문제를
   **촬영 단계에서 사전 차단**하는 장치다. 구조대원은 화면을 계속 볼 수 없으므로 햅틱을 우선한다.
2. **라이브 메시 오버레이** — 지금까지 스캔된 메시를 카메라 화면 위에 실시간으로 덧그려,
   무엇이 캡처됐고 무엇이 비었는지 촬영 중에 바로 보이게 한다.
3. **워크스루 영상 + 카메라 트랙 동시 기록** — 메시와 별개로 무음 영상과 카메라 궤적을
   같이 남긴다. 이는 기존 `video.mov` + `arkit_pose.csv` 조합과 이미 같은 구조이므로
   현재 설계를 그대로 유지하면 된다.

**차용하지 않는 것**: CedarScan은 Apple `RoomPlan`을 사용해 벽·문·창문·가구를 자동 검출한다.
RoomPlan은 실내 "방" 구조 추출에 특화돼 있어, 차량 전복·야외·붕괴 공간처럼 방 형태가 아닌
응급현장에서는 신뢰하기 어렵다. 따라서 본 프로젝트는 RoomPlan이 아니라
`sceneReconstruction = .meshWithClassification` 기반 임의 형상 메시를 유지한다.

### 현재 코드베이스

`iphone/EmergencyCapture/` 에 기존 앱 소스 7개가 있다 (SwiftUI, 약 758줄).

| 파일 | 역할 |
|---|---|
| `EmergencyCaptureApp.swift` | 앱 진입점 |
| `ContentView.swift` | 단일 화면 UI (프리뷰, 상태 7줄, 서버 IP/Port, START/STOP/UPLOAD) |
| `CameraManager.swift` | AVCaptureVideoDataOutput으로 raw 프레임 수신 + AVAssetWriter로 video.mov |
| `MotionManager.swift` | CoreMotion gyro/accel/deviceMotion 100Hz 수집 |
| `SessionManager.swift` | 세션 생명주기, metadata.json 작성 |
| `NetworkManager.swift` | Mac 서버 통신 (health / start / upload / stop) |
| `DataLogger.swift` | NSLock 기반 스레드 안전 CSV writer |

기존 세션 출력 (Mac 서버와 하위 파이프라인이 이 스키마에 의존한다):
```
session_YYYYMMDDTHHMMSSZ/
├── video.mov            # H.264
├── video_frames.csv     # frame_index,timestamp
├── imu.csv              # timestamp,type,x,y,z   (type = gyro | accel)
├── device_motion.csv    # timestamp,qx,qy,qz,qw,roll,pitch,yaw
└── metadata.json
```

서버 프로토콜: `POST /session/start` → 파일마다 `POST /session/upload` (multipart) →
`POST /session/stop`. 마지막 stop 호출이 서버의 3D 파이프라인을 자동 트리거한다.

### 목표

iPhone Pro의 LiDAR를 사용해 **미터 단위 3D 데이터를 기기에서 직접 수집**하도록 앱을 전환한다.
기존 세션 폴더 구조와 서버 업로드 프로토콜은 **최대한 그대로 유지**해서, Mac 서버와
하위 스크립트를 크게 고치지 않고도 새 데이터를 받을 수 있게 한다.

### 반드시 먼저 이해할 구조적 제약

**`ARSession`과 `AVCaptureSession`은 카메라를 동시에 점유할 수 없다.**
따라서 `CameraManager.swift`는 "유지하면서 LiDAR를 덧붙이는" 대상이 아니라 **교체** 대상이다.
ARKit이 주는 `ARFrame.capturedImage`를 AVAssetWriter에 넣으면 `video.mov`는 계속 만들 수 있으므로,
출력 계약은 유지하면서 내부 구현만 ARKit으로 바꾸는 방향으로 간다.

반면 **CoreMotion(`MotionManager`)은 ARSession과 동시에 동작해도 된다.** 그대로 유지한다.
(ARKit이 내부적으로 VIO를 하지만, 원시 IMU는 별도 검증·기록 목적이 있으므로 계속 받는다.)

### 작업 단계

#### Phase 1 — 기기 능력 확인 및 안전한 분기
- `ARWorldTrackingConfiguration.supportsSceneReconstruction(.mesh)` 와
  `supportsFrameSemantics(.sceneDepth)` 를 런타임에 확인한다.
- LiDAR가 없는 기기에서는 **크래시하지 말고** 기존 AVFoundation 경로로 폴백하거나,
  최소한 UI에 "이 기기는 LiDAR 미지원"을 명확히 표시한다.
- 확인 결과를 `metadata.json`에 기록한다 (`lidar_available`, `scene_reconstruction_supported` 등).

#### Phase 2 — ARKit 캡처로 전환 (`ARCaptureManager.swift` 신규)
`ARSession` + `ARWorldTrackingConfiguration`을 구성하고 프레임마다 다음을 수집한다.

| 데이터 | ARKit 소스 | 저장 |
|---|---|---|
| RGB 프레임 | `frame.capturedImage` | `video.mov` (AVAssetWriter, 기존과 동일) |
| 카메라 포즈 | `frame.camera.transform` (4x4, **미터**) | `arkit_pose.csv` |
| 카메라 intrinsics | `frame.camera.intrinsics` (3x3) | `arkit_pose.csv` 또는 metadata |
| 트래킹 상태 | `frame.camera.trackingState` | `arkit_pose.csv` |
| 뎁스맵 | `frame.sceneDepth?.depthMap` (Float32, 미터) | `depth/depth_%06d.bin` |
| 뎁스 신뢰도 | `frame.sceneDepth?.confidenceMap` (UInt8) | `depth/conf_%06d.bin` |

`arkit_pose.csv` 스키마 제안 (확정 전 나에게 확인받을 것):
```csv
timestamp,tx,ty,tz,qx,qy,qz,qw,tracking_state,fx,fy,cx,cy
```

**`arkit_pose.csv`는 서버 `ALLOWED_FILENAMES`에 이미 등록되어 있다.** 파일명을 그대로 쓸 것.

주의 — 데이터 용량: 뎁스맵은 256x192 Float32 = 프레임당 약 192KB다. 60fps로 전부 저장하면
40초에 460MB가 된다. **저장 주기를 설정 가능하게(기본 10Hz 정도) 만들고, 실제 저장 Hz를
metadata에 기록**할 것. 매 프레임 저장은 기본값으로 하지 말 것.

#### Phase 3 — Scene Reconstruction 메시 (`.meshWithClassification`)
`configuration.sceneReconstruction = .meshWithClassification` 을 켜고 `ARMeshAnchor`를 수집한다.

이게 이 프로젝트에 특히 중요한 이유: `ARMeshClassification`에 **door, wall, floor, ceiling,
table, seat, window** 분류가 포함된다. 기존 YOLO는 COCO 80클래스를 쓰는데 거기엔 door가 없어서
"문이 어디 있는지"를 영영 알 수 없었다. LiDAR 메시 분류가 이 공백을 그대로 메운다.

- 세션 종료 시 모든 `ARMeshAnchor`의 vertices / faces / normals / classification을 병합해
  **`scene_mesh.ply` 또는 `scene_mesh.obj`로 내보낸다.**
- 분류 라벨은 face별 또는 vertex별로 보존한다 (PLY라면 커스텀 속성, OBJ라면 별도 sidecar JSON).
- 이 파일 하나만 있어도 Mac에서 Open3D로 바로 열어 시연할 수 있어야 한다.

#### Phase 3 — Scene Reconstruction 메시 (`.meshWithClassification`)

※ CedarScan은 RoomPlan을 쓰지만, 위 배경에서 설명한 이유로 본 프로젝트는 RoomPlan을 쓰지 않는다.
   단, CedarScan이 메시를 `model.obj` + `model.mtl` + 카메라 트랙 JSON으로 묶어 내보내는
   패키징 방식은 참고할 것.

#### Phase 4 — 업로드 경로 연결
- `SessionManager.sessionFiles()`에 새 파일들을 추가한다.
- ⚠️ **서버 `ALLOWED_FILENAMES` 화이트리스트에 없는 파일명은 400으로 거부된다.**
  `scene_mesh.ply`, `depth/*.bin` 등 새 파일을 올리려면 **서버(`server/app.py`) 수정이 필요하다.**
  이 저장소에는 서버 코드가 없으므로, **필요한 서버 변경 사항을 별도 목록으로 정리해서 보고할 것.**
  임의로 파일명을 기존 화이트리스트에 맞춰 우회하지 말 것.
- 뎁스 프레임이 수백 개면 파일당 1회 HTTP 요청은 비효율적이다.
  `depth/`를 zip 하나로 묶어 올리는 방안을 제안하되, **구현 전에 나에게 확인받을 것.**

#### Phase 5 — UI 갱신 및 스캔 품질 코칭

`ContentView`에 다음 상태를 추가한다: LiDAR 지원 여부, ARKit 트래킹 상태(normal/limited/
notAvailable + 사유), 수집된 메시 앵커 수, 저장된 뎁스 프레임 수, 추정 공간 크기.
기존 상태 표시 행들은 유지한다.

추가로 CedarScan의 코칭 패턴을 적용한다.

- **햅틱 우선**: 구조대원은 화면을 계속 주시할 수 없다. 트래킹 품질 저하 시
  화면 표시보다 햅틱(`UIImpactFeedbackGenerator`)을 우선 트리거한다.
- **화면 테두리 경고**: 트래킹 상태가 `.limited`로 떨어지면 프리뷰 테두리 색을 바꾼다.
  `ARCamera.TrackingState.Reason`(`.excessiveMotion`, `.insufficientFeatures`,
  `.initializing`, `.relocalizing`)별로 사유를 구분해 표시한다.
- **라이브 메시 오버레이**: `ARSCNView`의 `.showSceneUnderstanding` 디버그 옵션 또는
  `ARMeshAnchor` 기반 커스텀 렌더링으로, 캡처된 영역을 촬영 중에 화면에 표시한다.
  기본값은 켜짐으로 하되 토글 가능하게 한다.
- **코칭 이벤트 로깅**: 발생한 코칭 경고를 `coaching.csv`(timestamp, event_type, detail)로
  기록한다. 사후에 "어느 구간에서 촬영이 불안정했는지"를 메시 품질과 대조할 수 있게 하기 위함이다.
  ⚠️ 이 파일도 서버 `ALLOWED_FILENAMES` 추가 대상이므로 Phase 4 보고 목록에 포함할 것.

### 지켜야 할 불변식 (어기면 하위 파이프라인이 조용히 망가진다)

1. **timestamp를 임의로 보정하지 않는다.** `ARFrame.timestamp`, `CMSampleBuffer.presentationTimeStamp`,
   CoreMotion `.timestamp`를 **있는 그대로** 기록한다. 셋이 안 맞아 보여도 코드에 오프셋 상수를
   박지 않는다. 오차는 측정해서 보고할 대상이지 숨길 대상이 아니다.
2. **단위 변환은 한 곳에서만 하고 반드시 metadata에 명시한다.** accel은 g → m/s²(×9.80665)를
   `MotionManager`에서만 하고 있다. gyro는 rad/s 원본 그대로다. ARKit 뎁스/포즈는 이미 미터다.
   변환을 추가하면 어디서 했는지 metadata.json에 기록할 것.
3. **로컬 저장이 항상 우선이다.** 네트워크가 끊겨도 촬영 데이터는 남아야 한다.
4. **한 센서의 실패가 다른 센서를 죽이지 않는다.** 기존 코드의 graceful degradation 구조를 유지할 것.
5. **`NetworkManager`의 `isUploading` 가드를 제거하지 말 것.** 과거에 UPLOAD 버튼 연타로
   `/session/stop`이 두 번 호출되어 서버 파이프라인이 중복 실행되고 서로 파일을 지우며
   양쪽 다 실패한 사고가 있었다. 불필요해 보여도 남겨둘 것.
6. **지원하지 않는 카메라 포맷/설정을 강제하지 않는다.** 런타임에 확인하고, 실제 선택된 값을 기록한다.

### 좌표계 — 반드시 문서화할 것

ARKit world 좌표계와 COLMAP 좌표계는 **컨벤션이 다르다.**
- ARKit: 오른손 좌표계, y축이 중력 반대(위), 카메라는 -z 방향을 본다
- COLMAP: `X_cam = R @ X_world + t`, y축 아래

**앱 안에서 임의로 변환하지 말고, ARKit 원본 그대로 기록**한 뒤 좌표계 규약을
`metadata.json`과 별도 문서에 명확히 남길 것. 변환은 Mac 쪽에서 한다.

### 작업 방식

- **API 이름과 시그니처는 프롬프트를 믿지 말고 설치된 iOS SDK 기준으로 검증할 것.**
  내가 위에 적은 API명(`sceneDepth`, `ARMeshClassification` 등)은 기억에 기반한 것이라
  실제 SDK와 다를 수 있다.
- 이 저장소에는 `.xcodeproj`가 없다. Swift 소스만 있고,
  `xcrun --sdk iphoneos swiftc -typecheck *.swift` (arm64-apple-ios16.0) 로 타입체크 검증해왔다.
  같은 방식으로 검증하고, LiDAR/ARKit에 필요한 최소 iOS 버전을 확인해 보고할 것.
- Info.plist에 추가로 필요한 키가 있으면 목록으로 정리할 것
  (기존: `NSCameraUsageDescription`, `NSMotionUsageDescription`, `NSLocalNetworkUsageDescription`,
  `NSAppTransportSecurity > NSAllowsArbitraryLoads`).
- **실기기 없이 컴파일 검증만 가능하다면 그렇다고 명시할 것.** 되지 않은 것을 됐다고 하지 말 것.
- 각 파일 상단에 기존 코드와 같은 밀도로 한국어 주석을 달 것 — 무엇을 왜 그렇게 했는지,
  실패 시 무엇을 확인해야 하는지까지.

### 먼저 할 일

구현을 시작하기 전에:
1. `iphone/EmergencyCapture/` 의 7개 파일을 전부 읽고 현재 구조를 파악할 것.
2. **Phase 1~5 중 어디까지를 한 번에 할지, 그리고 위 스키마 제안(`arkit_pose.csv` 컬럼,
   뎁스 저장 형식/주기, 메시 내보내기 포맷)에 대한 의견을 먼저 나에게 제시할 것.**
   바로 코드를 쓰지 말고 계획부터 확인받을 것.
3. 기존 파일 중 무엇을 교체하고 무엇을 유지할지 명확히 구분해서 보고할 것.
4. CedarScan 저장소(`Tupham16/CedarScan`)를 확인할 수 있다면 코칭 로직과 메시 오버레이
   구현 방식을 살펴보고, 우리 구조에 적용 가능한 부분과 그렇지 않은 부분을 구분해 보고할 것.
   저장소 접근이 불가하면 그렇다고 명시하고, ARKit 표준 API만으로 동일 기능을 구현하는
   방안을 제시할 것.

## 프롬프트 끝
