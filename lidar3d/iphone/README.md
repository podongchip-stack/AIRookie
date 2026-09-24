# LiDAR_Space3D (iOS 앱)

iPhone Pro의 **LiDAR 스캐너**로 응급현장의 **미터 단위 3D 데이터를 기기에서 직접 수집**한다.
서버 재구성(COLMAP/OpenMVS) 없이 기기에서 바로 3D 메시가 나온다.

## 왜 바꿨는가

기존 photogrammetry 경로에는 실측으로 확인된 한계가 둘 있었다.

1. **절대 스케일이 없다.** monocular SfM이라 결과가 임의 스케일의 상대 좌표였다.
   "문까지 2m"를 말할 수 없었다.
2. **느리고 불안정하다.** 120프레임 기준 A100 서버로도 123초, 촬영이 조금만 빨라도
   등록률이 20%대로 떨어져 파편화됐다.

ARKit은 미터 단위 뎁스와 카메라 포즈를 실시간으로 준다. 둘 다 해결된다.
덤으로 `ARMeshClassification`이 **door / wall / floor / ceiling / table / seat / window**를
준다 — 기존 YOLO는 COCO 80클래스라 door가 없어서 영영 알 수 없던 정보다.

## ⚠️ 검증 상태 — 정직하게

- ✅ **컴파일(타입체크) 검증 완료.** iOS SDK 26.5, 에러 0 / 경고 0.

  ⚠️ **반드시 아래 플래그를 함께 주고 검사할 것.** 그냥 `swiftc -typecheck *.swift`만 돌리면
  파일 10개를 한 모듈로 묶어 검사하기 때문에, 한 파일의 `import`가 다른 파일의 누락을
  가려버려 **Xcode에서만 터지는 에러**를 놓친다 (실제로 `ScanCoach.swift`의
  `import Combine` 누락을 이 방식으로 놓쳤다).

  ```bash
  cd iphone/LiDAR_Space3D
  xcrun --sdk iphoneos swiftc -typecheck -target arm64-apple-ios26.5 \
    -swift-version 5 \
    -enable-upcoming-feature MemberImportVisibility \
    -enable-experimental-feature UnspecifiedMeansMainActorIsolated \
    *.swift
  ```

  두 플래그는 Xcode 26이 새 프로젝트에 기본으로 켜는 것이다
  (`SWIFT_UPCOMING_FEATURE_MEMBER_IMPORT_VISIBILITY`, `SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor`).

- ❌ **실기기 실행/테스트는 못 했습니다** (이 환경에 물리 iPhone이 없음).
  아래는 전부 실기기에서 직접 확인해야 하며, 됐다고 말할 수 없습니다:
  - 실제 LiDAR 동작, 메시 품질, 분류 정확도
  - 뎁스 해상도 (256×192는 문서 기반 추정값, 실제 값은 `metadata.json`에 기록됨)
  - 실제 달성 저장 Hz (기기가 뜨거우면 ARKit이 조용히 60→30fps로 떨어진다)
  - 햅틱 타이밍, 코칭 임계값의 현장 적합성
  - **ARSCNView가 `session.delegate`를 잡는 문제** (아래 "알려진 위험" 참고)

## ⚠️ 파일 사본이 두 벌이다

Xcode에 "Copy items if needed"로 드래그했다면 `LiDAR_Space3D.xcodeproj` 옆 폴더에
**사본**이 생긴다. 이 저장소를 고쳐도 **빌드되는 것은 사본**이므로 반영되지 않는다.

```bash
# 저장소 -> Xcode 프로젝트로 동기화
cp iphone/LiDAR_Space3D/*.swift \
   "../LiDAR_Space3D/LiDAR_Space3D/"
```

(근본 해결은 Xcode에서 사본을 지우고 이 저장소 폴더를 참조로 추가하는 것이지만,
 동기화 그룹 방식이라 경로가 저장소 밖이면 설정이 번거롭다. 우선은 위 복사로 충분하다.)

## 최소 iOS 버전

| 기능 | 최소 iOS |
|---|---|
| `sceneReconstruction` / `ARMeshAnchor` | 13.4 |
| `sceneDepth` / `ARDepthData` | 14.0 |
| `captureHighResolutionFrame` | 16.0 |

**현재 타깃 16.0이 전부 커버한다. 버전을 올릴 필요 없다.**

## 파일 구성

| 파일 | 역할 | 상태 |
|---|---|---|
| `LiDAR_Space3DApp.swift` | 앱 진입점 (`@main`) | 이름만 변경 |
| `ContentView.swift` | 단일 화면 UI + 코칭 표시 | 대폭 수정 |
| `ARCaptureManager.swift` | **ARSession + 포즈/영상/뎁스 기록** | 🆕 신규 |
| `MeshExporter.swift` | ARMeshAnchor 병합 → PLY + 분류 사이드카 | 🆕 신규 |
| `ScanCoach.swift` | 실시간 스캔 코칭 + `coaching.csv` | 🆕 신규 |
| `ARPreviewView.swift` | ARSCNView 프리뷰 + 분류색 메시 오버레이 | 🆕 신규 |
| `SessionManager.swift` | 세션 생명주기, `metadata.json` | 수정 |
| `MotionManager.swift` | CoreMotion gyro/accel 100Hz | **그대로 (한 줄도 안 건드림)** |
| `NetworkManager.swift` | 서버 통신 | 그대로 |
| `DataLogger.swift` | 스레드 안전 CSV writer | 그대로 |
| ~~`CameraManager.swift`~~ | AVFoundation 카메라 | ❌ **삭제됨** |

### `CameraManager.swift`를 왜 지웠나

`ARSession`과 `AVCaptureSession`은 **카메라 하드웨어를 동시에 점유할 수 없다.** 둘을 같이
켜면 나중에 켠 쪽이 조용히 프레임을 못 받거나 세션이 중단된다. 그래서 "유지하면서 LiDAR를
덧붙이는" 것이 불가능하고 교체가 유일한 선택이었다.
`ARFrame.capturedImage`를 AVAssetWriter에 넣으면 `video.mov`는 계속 만들 수 있으므로,
**출력 파일 계약은 그대로 두고 내부 구현만 ARKit으로** 바꿨다.

반면 **CoreMotion은 ARSession과 공존 가능**하므로 `MotionManager`는 그대로 뒀다.
(ARKit이 내부적으로 VIO를 돌리지만, 원시 IMU는 별도 검증 목적이 있어 계속 받는다.)

## 세션 출력

```
session_YYYYMMDDTHHMMSSZ/
├── video.mov                     # H.264, 네이티브 landscape (회전 transform 없음 — 아래 참고)
├── video_frames.csv              # frame_index,timestamp            [기존 스키마 유지]
├── imu.csv                       # timestamp,type,x,y,z             [기존 스키마 유지]
├── device_motion.csv             # timestamp,qx,qy,qz,qw,roll,pitch,yaw [기존 스키마 유지]
├── arkit_pose.csv                # 🆕 카메라 포즈 + intrinsics + 트래킹 상태
├── coaching.csv                  # 🆕 timestamp,event_type,detail
├── scene_mesh.ply                # 🆕 3D 모델 본체 (binary LE, 분류색 포함)
├── scene_mesh_faces_class.bin    # 🆕 면별 분류 라벨 (UInt8)
├── depth/                        # 🆕 뎁스 프레임 (기본 10Hz, 업로드는 기본 OFF)
│   ├── index.csv
│   ├── depth_%06d.bin            # little-endian Float32, 미터
│   └── conf_%06d.bin             # UInt8 (0=low 1=med 2=high)
└── metadata.json                 # 대폭 확장
```

정확한 스키마와 좌표계 규약: **`docs/coordinate_system.md`**

## 알려진 위험 (실기기에서 반드시 확인할 것)

### 1. ARSCNView와 `session.delegate` 경합 🔴

`ARSCNView`는 `makeUIView` 시점에 **자기 자신을 `session.delegate`로 설정**한다.
우리는 데이터 기록을 위해 그 delegate를 가져와야 한다.

대응: `SessionManager.startARSession()`을 **뷰가 만들어진 뒤**(`ContentView.onAppear`)에 부른다.
ARSCNView는 delegate가 아니라 자체 렌더 루프에서 `session.currentFrame`을 읽어 배경을
그리므로 카메라 화면은 계속 나온다 — **이론상으로는.** 참조로 삼은 CedarScan이 같은 방식으로
출시되어 있지만, **실기기에서 카메라 배경이 정상 표시되는지 직접 확인해야 한다.**
화면이 검게 나오면 이 부분이 원인이다.

### 2. 영상 해상도가 1920×1080 → 1920×1440으로 바뀐다 🟡

ARKit은 `ARVideoFormat` 중에서만 고를 수 있고, LiDAR 기기 기본값은 보통 4:3이다.
서버의 `04_extract_frames.py` 등이 16:9/1080p를 가정하면 여기서 깨진다.
→ `docs/server_changes.md` 6번

### 3. `video.mov`에 회전 transform이 없다 🟡 (의도적)

`fx,fy,cx,cy`는 **회전 전 landscape 원본 픽셀 좌표계** 기준값이다. 영상만 세로로 돌리면
프레임은 세로인데 intrinsics는 가로 기준이 되어 **에러 없이 조용히 틀린 재투영**이 나온다.
LiDAR로 얻은 절대 스케일이 거기서 죽는다. 그래서 회전을 붙이지 않았다.
화면 프리뷰는 ARSCNView가 알아서 세로로 보여주므로 촬영자 경험은 그대로다.

### 4. 뎁스 용량 🟡

256×192 Float32 = 프레임당 약 192KB. 60fps 전량 저장 시 40초에 460MB.
→ 기본 10Hz로 제한하고, **업로드는 기본 OFF**로 뒀다.
3D 뷰어가 그리는 것은 `scene_mesh.ply` 하나이고 뎁스는 오프라인 검증용 자산이다.
실제 달성 Hz는 설정값이 아니라 **실측값**이 `metadata.json`에 기록된다.

## Info.plist

| 키 | 상태 |
|---|---|
| `NSCameraUsageDescription` | 기존 — 그대로 (ARKit도 이걸 쓴다) |
| `NSMotionUsageDescription` | 기존 — 그대로 |
| `NSLocalNetworkUsageDescription` | 기존 — 그대로 |
| `NSAppTransportSecurity > NSAllowsArbitraryLoads` | 기존 — 그대로 |
| **ARKit 전용 신규 키** | **없음** |

### ⚠️ `UIRequiredDeviceCapabilities`에 `arkit`을 넣지 말 것

넣으면 비LiDAR 기기에 **설치 자체가 차단**되어, 앱이 LiDAR 없이도 안 죽게 만들어 둔
graceful fallback과 정면으로 충돌한다.

### 💡 추가 권장

```xml
<key>UIFileSharingEnabled</key><true/>
<key>LSSupportsOpeningDocumentsInPlace</key><true/>
```

네트워크가 죽었을 때 Finder로 세션 폴더를 직접 빼낼 수 있다.
"로컬 저장이 항상 우선"이라는 원칙의 실질적인 보험이다.

## 프로젝트 생성 (`.xcodeproj`가 없는 이유)

pbxproj 포맷을 손으로 만들면 깨진 프로젝트가 될 위험이 높아서 생성하지 않았다.
Xcode에서 새로 만드는 게 표준이고 3분이면 된다.

1. Xcode → **File > New > Project** → **iOS > App**
2. Product Name **`LiDAR_Space3D`**, Interface **SwiftUI**, Language **Swift**
3. ⚠️ Xcode가 자동 생성한 **`ContentView.swift`와 `LiDAR_Space3DApp.swift`를 먼저 삭제**
   (Move to Trash). 안 지우고 드래그하면 `@main`이 두 개, `ContentView`가 두 개가 되어
   빌드가 깨진다.
4. 이 폴더의 `.swift` **10개 전부**를 프로젝트 네비게이터로 드래그 (Copy items if needed 체크).
   `README.md`는 넣지 않는다.
5. 위 Info.plist 키 추가 (`UIFileSharingEnabled` 포함 — 없으면 파인더로 파일을 못 꺼낸다)
6. **실제 iPhone Pro(LiDAR 탑재)를 USB로 연결** — 시뮬레이터는 ARKit이 없어 의미 있는 테스트 불가
