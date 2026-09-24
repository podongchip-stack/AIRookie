import Foundation
import UIKit
import ARKit
import Combine
import simd

/// 한 번의 촬영을 하나의 Session으로 관리한다.
/// [START SESSION] -> ARKit + IMU 로깅 시작, [STOP SESSION] -> 메시 내보내기 + 파일 flush.
///
/// LiDAR 전환에서 바뀐 것과 그대로인 것:
/// - 바뀜: CameraManager(AVFoundation) -> ARCaptureManager(ARKit). 카메라를 동시 점유할 수
///         없으므로 덧붙이기가 아니라 교체다.
/// - 그대로: MotionManager(CoreMotion)는 ARSession과 공존 가능하므로 한 줄도 건드리지 않았다.
///         ARKit이 내부적으로 VIO를 돌리지만, 원시 IMU는 별도 검증 목적이 있어 계속 받는다.
/// - 그대로: 세션 폴더 구조와 업로드 프로토콜. 서버가 기존 스키마에 의존하기 때문이다.
///
/// graceful degradation (불변식 4번): 카메라가 실패해도 IMU는 기록되고, 메시가 비어도
/// 포즈/영상은 남고, 뎁스가 없어도 나머지는 전부 저장된다. 한 센서의 실패가 세션을 죽이지 않는다.
final class SessionManager: ObservableObject {

    // MARK: 기존 상태 (UI가 이미 쓰고 있으므로 유지)
    @Published var isRecording = false
    /// STOP을 누른 뒤 **저장이 끝날 때까지** true.
    ///
    /// 왜 별도 상태가 필요한가 (실제로 4개 세션을 망치고 나서 알아냄):
    ///   `isRecording`은 STOP 즉시 false가 되지만, 그 시점에 메시 병합(정점 수십만 개)과
    ///   depth.zip 압축은 **백그라운드에서 이제 막 시작**된다. metadata.json은 그 모든 게
    ///   끝난 뒤에야 쓰인다.
    ///   그런데 UPLOAD 버튼은 isRecording만 보고 있어서 STOP 직후 바로 눌렸고,
    ///   `sessionFiles()`는 **아직 존재하지 않는 metadata.json과 depth.zip을 빼고** 목록을
    ///   만들어 올렸다. 업로드는 "성공"했지만 세션은 해석 불가능한 상태가 됐다.
    ///   가장 나쁜 종류의 실패다 — 앱은 완료라고 말하는데 데이터가 불완전하다.
    @Published var isSaving = false
    @Published var currentSessionId: String?
    @Published var frameCount = 0
    @Published var gyroActive = false
    @Published var accelActive = false
    @Published var deviceMotionActive = false
    @Published var lastError: String?

    // MARK: LiDAR 관련 신규 상태
    @Published var lidarAvailable = false
    @Published var classificationSupported = false
    @Published var sceneDepthSupported = false
    @Published var trackingStateCode = 0
    @Published var trackingReasonCode = 0
    @Published var meshAnchorCount = 0
    @Published var depthFrameCount = 0
    @Published var poseRowCount = 0
    /// 추정 공간 크기 (m). LiDAR 전환의 핵심 성과 — 이게 "미터"라는 것이 이 프로젝트의 전부다.
    @Published var sceneExtent = SIMD3<Float>(repeating: 0)
    @Published var lastMeshSummary: String = ""
    // MARK: 촬영 옵션 — 앱을 껐다 켜도 유지된다
    //
    // ⚠️ 왜 UserDefaults에 저장하는가 (실제로 데이터를 잃고 나서 고침):
    //   예전에는 단순 기본값이라 **재빌드하거나 앱을 껐다 켤 때마다 매번 OFF로 되돌아갔다.**
    //   사용자는 켠 줄 알고 촬영했는데 뎁스가 저장/업로드되지 않아, 세션을 여러 번 다시
    //   찍어야 했다. 촬영은 되돌릴 수 없으므로 "설정이 조용히 초기화되는 것"은 데이터 손실이다.

    /// 뎁스 업로드 여부. 처음 기본값은 OFF — 뎁스는 수백 MB라 Wi-Fi 업로드가 오래 걸린다.
    /// 3D 뷰어에 필요한 것은 scene_mesh.ply 하나뿐이고, 뎁스는 오프라인 재융합/검증용이다.
    @Published var uploadDepth = SessionManager.pref("uploadDepth", default: false) {
        didSet { UserDefaults.standard.set(uploadDepth, forKey: "opt.uploadDepth") }
    }
    @Published var captureDepth = SessionManager.pref("captureDepth", default: true) {
        didSet { UserDefaults.standard.set(captureDepth, forKey: "opt.captureDepth") }
    }
    @Published var showMeshOverlay = SessionManager.pref("showMeshOverlay", default: true) {
        didSet { UserDefaults.standard.set(showMeshOverlay, forKey: "opt.showMeshOverlay") }
    }

    /// 저장된 값이 없으면 기본값을 쓴다. (UserDefaults.bool은 없을 때 false를 주므로
    /// 기본값이 true인 항목은 이렇게 존재 여부를 먼저 확인해야 한다.)
    private static func pref(_ key: String, default fallback: Bool) -> Bool {
        let full = "opt.\(key)"
        guard UserDefaults.standard.object(forKey: full) != nil else { return fallback }
        return UserDefaults.standard.bool(forKey: full)
    }

    /// 코칭이 띄운 경고를 **SessionManager가 다시 발행한다.**
    /// ScanCoach는 자기 자신이 ObservableObject지만, ContentView가 구독하는 것은
    /// SessionManager 하나뿐이다. 중계하지 않으면 경고가 떠도 테두리 색과 문구가
    /// 다시 그려지지 않는다 (햅틱만 울리고 화면은 그대로인 상태가 된다).
    @Published var coachAlert: ScanCoach.Alert?

    let arCaptureManager = ARCaptureManager()
    let motionManager = MotionManager()
    let coach: ScanCoach
    private var cancellables = Set<AnyCancellable>()

    private var sessionDirectory: URL?
    private var depthDirectory: URL?
    private var sessionStartWallClock: Date?
    private var imuLogger: CSVLogger?
    private var deviceMotionLogger: CSVLogger?
    private var meshResult: MeshExporter.Result?
    /// depth/ 를 묶은 zip. 업로드 토글이 켜졌을 때만 만들어진다.
    private var depthZipURL: URL?

    init() {
        coach = ScanCoach(session: arCaptureManager.session)
        lidarAvailable = ARCaptureManager.isLiDARCaptureAvailable
        classificationSupported = ARCaptureManager.supportsMeshWithClassification
        sceneDepthSupported = ARCaptureManager.supportsSceneDepth

        arCaptureManager.onStatsUpdate = { [weak self] stats in
            guard let self else { return }
            self.frameCount = stats.videoFrameCount
            self.poseRowCount = stats.poseRowCount
            self.depthFrameCount = stats.depthFrameCount
            self.meshAnchorCount = stats.meshAnchorCount
            self.trackingStateCode = stats.trackingStateCode
            self.trackingReasonCode = stats.trackingReasonCode
            self.sceneExtent = stats.sceneExtentMeters
        }

        // 코칭 경고 / 토글 상태를 이 객체의 변경으로 승격시켜 UI가 반응하게 한다.
        coach.$alert.receive(on: DispatchQueue.main)
            .sink { [weak self] in self?.coachAlert = $0 }
            .store(in: &cancellables)
        coach.objectWillChange.receive(on: DispatchQueue.main)
            .sink { [weak self] in self?.objectWillChange.send() }
            .store(in: &cancellables)
    }

    /// ARSession 실행. ARSCNView가 makeUIView에서 자기를 session.delegate로 잡기 때문에
    /// **뷰가 만들어진 뒤**(ContentView의 .onAppear)에 불러야 한다.
    func startARSession() {
        guard ARCaptureManager.supportsWorldTracking else {
            lastError = "이 기기는 ARKit을 지원하지 않습니다. LiDAR 캡처 불가."
            return
        }
        arCaptureManager.configureAndRun()
        if !lidarAvailable {
            lastError = "이 기기는 LiDAR 미지원입니다 — 포즈/영상은 기록되지만 뎁스·메시는 없습니다."
        }
        coach.tooCloseEnabled = arCaptureManager.sceneDepthActive
        coach.start(logger: nil)   // 녹화 시작 시 로거를 붙여 다시 start한다
    }

    private func documentsDirectory() -> URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
    }

    /// 세션 id를 만든다: `session_20260917v1_iPhone15Pro`
    ///
    /// 구성: `session_` + 날짜(YYYYMMDD, **기기 현지 시각**) + `v` + 그날의 순번 + `_` + 기종
    ///
    /// 왜 기종을 붙이는가:
    ///   두 대로 동시에 찍으면 폴더 이름만 봐서는 어느 기기 것인지 알 수 없다. 병합 결과를
    ///   해석할 때 "어느 쪽 메시가 성글었나"를 추적하려면 이름에 기종이 있어야 한다.
    ///
    /// 왜 현지 시각인가:
    ///   사람이 "오늘 찍은 것"을 찾을 때 쓰는 날짜는 현지 날짜다. (UTC를 쓰면 오전에 찍은
    ///   세션이 전날 날짜로 저장되어 혼란스럽다.) 정확한 촬영 시각은 metadata.json의
    ///   `session_start_wallclock_iso8601`(UTC)에 그대로 남으므로 정보 손실은 없다.
    ///
    /// ⚠️ 순번 충돌 주의:
    ///   순번은 "오늘 몇 번째 스캔인가"이므로 **기기마다 독립적으로** 센다. 서로 다른 두 기기의
    ///   v1은 다른 스캔이지만, 이름에 기종이 붙어 있어 구분된다.
    ///   앱을 재설치하거나 세션 폴더를 지우면 순번이 되돌아가 **서버의 기존 폴더를 덮어쓸 수**
    ///   있다. 그래서 폴더 스캔 결과와 UserDefaults에 저장된 마지막 번호 중 **큰 값**을 쓴다
    ///   (폴더를 지워도 번호는 되돌아가지 않는다).
    private func nextSessionId() -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyyMMdd"
        formatter.locale = Locale(identifier: "en_US_POSIX")   // 사용자 달력 설정에 영향받지 않게
        formatter.timeZone = TimeZone.current
        let day = formatter.string(from: Date())
        let prefix = "session_\(day)v"

        // 1) 기기에 남아 있는 오늘 세션 폴더에서 최대 번호를 찾는다
        var maxVersion = 0
        let names = (try? FileManager.default.contentsOfDirectory(
            atPath: documentsDirectory().path)) ?? []
        for name in names where name.hasPrefix(prefix) {
            let digits = name.dropFirst(prefix.count).prefix { $0.isNumber }
            maxVersion = max(maxVersion, Int(digits) ?? 0)
        }

        // 2) 폴더를 지웠어도 번호가 되돌아가지 않도록 마지막 번호를 기억해 둔다
        let key = "lastSessionVersion.\(day)"
        maxVersion = max(maxVersion, UserDefaults.standard.integer(forKey: key))

        let version = maxVersion + 1
        UserDefaults.standard.set(version, forKey: key)
        return "\(prefix)\(version)_\(DeviceInfo.slug)"
    }

    // MARK: - 세션 시작

    func startSession() {
        let sessionId = nextSessionId()
        let dir = documentsDirectory().appendingPathComponent(sessionId, isDirectory: true)

        do {
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        } catch {
            lastError = "세션 폴더 생성 실패: \(error.localizedDescription)"
            return
        }
        sessionDirectory = dir
        currentSessionId = sessionId
        sessionStartWallClock = Date()
        meshResult = nil
        depthZipURL = nil
        lastMeshSummary = ""

        // depth/ 폴더는 뎁스를 실제로 찍을 때만 만든다 (빈 폴더가 업로드 목록에 끼지 않게).
        var depthDir: URL?
        var depthIndexLogger: CSVLogger?
        if captureDepth && arCaptureManager.sceneDepthActive {
            let d = dir.appendingPathComponent("depth", isDirectory: true)
            if (try? FileManager.default.createDirectory(at: d, withIntermediateDirectories: true)) != nil {
                depthDir = d
                // 파일명 정렬에 의존하지 않도록 인덱스를 남긴다. 중간에 프레임이 빠져도 안전하다.
                depthIndexLogger = CSVLogger(fileURL: d.appendingPathComponent("index.csv"),
                                             header: ARCaptureManager.depthIndexCSVHeader)
            }
        }
        depthDirectory = depthDir

        // ARKit 캡처: 실패해도 IMU는 계속 간다.
        let frameLogger = CSVLogger(fileURL: dir.appendingPathComponent("video_frames.csv"),
                                    header: "frame_index,timestamp")
        let poseLogger = CSVLogger(fileURL: dir.appendingPathComponent("arkit_pose.csv"),
                                   header: ARCaptureManager.poseCSVHeader)
        arCaptureManager.depthCaptureEnabled = captureDepth
        arCaptureManager.startRecording(videoURL: dir.appendingPathComponent("video.mov"),
                                        frameLogger: frameLogger,
                                        poseLogger: poseLogger,
                                        depthDirectory: depthDir,
                                        depthIndexLogger: depthIndexLogger)

        // IMU: ARKit 성공 여부와 무관하게 독립적으로 시작 (기존 구조 유지)
        imuLogger = CSVLogger(fileURL: dir.appendingPathComponent("imu.csv"),
                              header: "timestamp,type,x,y,z")
        deviceMotionLogger = CSVLogger(fileURL: dir.appendingPathComponent("device_motion.csv"),
                                       header: "timestamp,qx,qy,qz,qw,roll,pitch,yaw")
        if let imuLogger {
            motionManager.start(imuLogger: imuLogger, deviceMotionLogger: deviceMotionLogger)
        }
        gyroActive = motionManager.isGyroAvailable
        accelActive = motionManager.isAccelerometerAvailable
        deviceMotionActive = motionManager.isDeviceMotionAvailable

        // 코칭: 이제부터 실제 촬영이므로 로거를 붙이고 활성화한다.
        coach.stop()
        coach.tooCloseEnabled = arCaptureManager.sceneDepthActive
        coach.start(logger: CSVLogger(fileURL: dir.appendingPathComponent("coaching.csv"),
                                      header: ScanCoach.coachingCSVHeader))
        coach.setActive(true)

        // 10~30분짜리 스캔 도중 자동 잠금이 세션을 끊으면 안 된다.
        UIApplication.shared.isIdleTimerDisabled = true
        isRecording = true
    }

    // MARK: - 세션 종료

    /// 정지 순서가 중요하다: IMU/코칭을 먼저 멈추고 -> 영상 마무리 -> 메시 내보내기 -> metadata.
    /// metadata를 마지막에 쓰는 이유는 메시 통계(정점 수, 클래스별 면 개수)가 들어가야 하기 때문이다.
    func stopSession(completion: @escaping (URL?) -> Void) {
        isRecording = false
        isSaving = true
        UIApplication.shared.isIdleTimerDisabled = false
        motionManager.stop()
        coach.setActive(false)
        coach.stop()

        // 메시 스냅샷은 ARSession을 멈추기 **전에** 떠야 한다.
        // delegateQueue 위에서 복사한다 — 메인에서 직접 읽으면 ARKit의 앵커 갱신과 경합한다.
        let anchors = arCaptureManager.snapshotMeshAnchors()

        arCaptureManager.stopRecording { [weak self] in
            guard let self, let dir = self.sessionDirectory else {
                DispatchQueue.main.async { self?.isSaving = false; completion(nil) }
                return
            }
            self.imuLogger?.close()
            self.deviceMotionLogger?.close()

            // 메시 병합은 정점 수십만 개가 될 수 있어 몇 초 걸린다. 반드시 백그라운드에서.
            DispatchQueue.global(qos: .userInitiated).async {
                var result: MeshExporter.Result?
                var meshError: String?
                if anchors.isEmpty {
                    meshError = "메시 앵커가 0개입니다 (LiDAR 미지원이거나 스캔 시간이 너무 짧음)."
                } else {
                    do {
                        result = try MeshExporter.export(
                            anchors: anchors,
                            plyURL: dir.appendingPathComponent("scene_mesh.ply"),
                            classBinURL: dir.appendingPathComponent("scene_mesh_faces_class.bin"))
                    } catch {
                        meshError = "메시 내보내기 실패 (나머지 파일은 정상): \(error.localizedDescription)"
                    }
                }

                // 뎁스 zip은 업로드 토글이 켜진 경우에만 만든다 (수백 MB짜리 작업).
                var zipURL: URL?
                if self.uploadDepth, let depthDir = self.depthDirectory,
                   self.arCaptureManager.depthFrameCount > 0 {
                    zipURL = Self.makeZip(of: depthDir, named: "depth.zip", in: dir)
                }

                DispatchQueue.main.async {
                    self.meshResult = result
                    self.depthZipURL = zipURL
                    if let meshError { self.lastError = meshError }
                    if let result {
                        let size = result.boundsMax - result.boundsMin
                        self.lastMeshSummary = String(
                            format: "%d vertices / %d faces / %.1f×%.1f×%.1f m",
                            result.vertexCount, result.faceCount,
                            Double(size.x), Double(size.y), Double(size.z))
                    }
                    self.writeMetadata(to: dir, mesh: result)
                    // 모든 파일이 디스크에 있는 지금에야 업로드가 가능해진다.
                    self.isSaving = false
                    completion(dir)
                }
            }
        }
    }

    /// 폴더를 zip 하나로 묶는다. 서드파티 라이브러리 없이 Foundation만으로 가능하다 —
    /// NSFileCoordinator의 .forUploading 옵션이 디렉터리를 zip으로 만들어 준다
    /// (iOS가 파일 공유 시 쓰는 바로 그 경로다).
    /// 뎁스 파일이 수백 개일 때 파일당 1회 HTTP 요청은 비현실적이라 이 방식을 쓴다.
    private static func makeZip(of directory: URL, named name: String, in destinationDir: URL) -> URL? {
        let destination = destinationDir.appendingPathComponent(name)
        try? FileManager.default.removeItem(at: destination)
        var coordError: NSError?
        var result: URL?
        NSFileCoordinator().coordinate(readingItemAt: directory,
                                       options: [.forUploading],
                                       error: &coordError) { zippedURL in
            do {
                try FileManager.default.copyItem(at: zippedURL, to: destination)
                result = destination
            } catch {
                result = nil
            }
        }
        return result
    }

    // MARK: - metadata.json

    /// 불변식 2번: 단위 변환을 한 곳에서만 하고 **반드시 여기에 명시한다.**
    /// 불변식 1번: timestamp를 보정하지 않는다. 보정이 구조적으로 불가피한 영상 PTS만
    ///            video_pts_epoch로 오프셋을 그대로 내보낸다.
    private func writeMetadata(to dir: URL, mesh: MeshExporter.Result?) {
        let device = UIDevice.current
        let ar = arCaptureManager

        var metadata: [String: Any] = [
            "session_id": currentSessionId ?? "",
            "capture_mode": "lidar_arkit",
            "schema_version": 2,

            // --- 서버가 파이프라인을 분기하는 근거 ---
            // ⚠ 서버는 이 값을 보고 COLMAP/OpenMVS 재구성을 **건너뛰어야 한다.**
            //   LiDAR 세션은 이미 미터 단위 메시를 들고 오므로 SfM/MVS를 돌릴 이유가 없다.
            "reconstruction_required": false,
            "primary_model_file": mesh != nil ? "scene_mesh.ply" : NSNull(),

            // START SESSION을 누른 순간의 카메라 기준 자세 (ARKit world 좌표계).
            // 두 대 병합에서 초기 정렬값으로 쓴다 — 같은 자리에서 START를 누르면
            // 두 좌표계 관계가 이 값들의 차이로 거의 그대로 나온다.
            "session_start_pose_translation": ar.startPoseTranslation.map { [$0.x, $0.y, $0.z] } ?? NSNull(),
            "session_start_pose_quaternion": ar.startPoseQuaternion.map { [$0.x, $0.y, $0.z, $0.w] } ?? NSNull(),
            "session_start_pose_yaw_rad": ar.startPoseYaw.map { Double($0) } ?? NSNull(),
            "session_start_pose_note":
                "ARKit world 원점은 앱 화면이 뜬 자리이지 START를 누른 자리가 아니다. "
                + "이 값은 START 시점의 카메라 포즈(camera-to-world)이며, 두 기기가 같은 자리에서 "
                + "START를 눌렀다면 각자의 이 값으로 두 좌표계를 정렬할 수 있다. "
                + "yaw만 쓰는 이유는 중력 정렬로 roll/pitch가 이미 일치하기 때문이다.",
            "session_id_format": "session_<YYYYMMDD(기기 현지 날짜)>v<그날의 순번>_<기종>",
            "session_id_timezone": TimeZone.current.identifier,
            "session_start_wallclock_iso8601":
                sessionStartWallClock.map { ISO8601DateFormatter().string(from: $0) } ?? "",

            // --- 시계 ---
            "timestamp_source": "monotonic system uptime (CACurrentMediaTime 기준). wall-clock 아님.",
            "arkit_timestamp_type": "ARFrame.timestamp (seconds) — 보정 없이 원본 그대로 기록",
            "imu_timestamp_type": "CMGyroData/CMAccelerometerData/CMDeviceMotion .timestamp (seconds)",
            "clock_note": "arkit_pose.csv / video_frames.csv / coaching.csv / depth/index.csv 는 전부 "
                + "동일한 ARFrame.timestamp 값을 쓰므로 근사 매칭 없이 정확히 조인된다. "
                + "imu.csv도 같은 uptime 시계이나 센서 지연은 측정 대상이지 보정 대상이 아니다.",
            // 원본 timestamp = (video.mov의 PTS 초) + video_pts_epoch. 정확히 성립한다.
            "video_pts_epoch": ar.videoPTSEpoch,
            "video_pts_note": "AVAssetWriter는 0 기준 상대 PTS만 받으므로 첫 프레임 timestamp를 뺐다. "
                + "원본 복원: original_timestamp = pts_seconds + video_pts_epoch",

            // --- 단위 ---
            "accelerometer_unit": "m/s^2 (CoreMotion 원시값은 g 단위, x\(MotionManager.gravityConstant) 변환 후 기록. MotionManager에서만 변환)",
            "gyroscope_unit": "rad/s (CoreMotion 기본 단위, 변환 없음)",
            "arkit_pose_unit": "meters (ARKit 원본, 변환 없음)",
            "depth_unit": "meters (ARKit 원본, 변환 없음)",
            "mesh_unit": "meters (ARKit 원본, 변환 없음)",

            // --- 좌표계 (docs/coordinate_system.md 참고) ---
            "coordinate_system": "ARKit world: right-handed, Y-up (gravity-aligned), meters",
            "coordinate_origin": "세션 시작 시점의 기기 포즈",
            "pose_convention": "camera-to-world. (tx,ty,tz)=카메라 위치, (qx,qy,qz,qw)=카메라->월드 회전",
            "camera_look_direction": "카메라는 자신의 -Z 방향을 본다 (ARKit 규약)",
            "colmap_conversion_applied": false,
            "colmap_conversion_note": "앱에서 COLMAP 좌표계로 변환하지 않았다. 변환은 Mac 쪽에서 한다.",

            // --- 기기 능력 (Phase 1) ---
            "lidar_available": ARCaptureManager.isLiDARCaptureAvailable,
            "world_tracking_supported": ARCaptureManager.supportsWorldTracking,
            "scene_reconstruction_supported": ARCaptureManager.supportsMesh,
            "scene_reconstruction_classification_supported": ARCaptureManager.supportsMeshWithClassification,
            "scene_depth_supported": ARCaptureManager.supportsSceneDepth,
            "scene_reconstruction_active": ar.meshActive,
            "classification_active": ar.classificationActive,
            "scene_depth_active": ar.sceneDepthActive,
            "smoothed_scene_depth_supported": ARCaptureManager.supportsSmoothedSceneDepth,
            "smoothed_scene_depth_active": ar.smoothedSceneDepthActive,
            "depth_files_note": "depth_*.bin/conf_*.bin = 원시 sceneDepth, "
                + "sdepth_*.bin/sconf_*.bin = 시간 평활 smoothedSceneDepth. "
                + "같은 프레임의 두 버전이므로 직접 비교할 수 있다.",

            // --- 실제 선택된 값 (요청값이 아니라 런타임 확인값, 불변식 6번) ---
            "video_format_selected": ar.videoFormatDescription,
            "video_frame_width": ar.frameWidth,
            "video_frame_height": ar.frameHeight,
            "video_nominal_fps": ar.nominalFrameRate,
            "video_orientation": "native landscape — camera.intrinsics와 픽셀 단위로 정합. "
                + "회전 transform을 붙이지 않았다 (붙이면 intrinsics가 조용히 어긋난다).",
            "video_saved_hz_requested": ar.videoSaveHz,
            "video_saved_hz_measured": ar.measuredVideoHz,

            // --- 뎁스 ---
            "depth_width": ar.depthWidth,
            "depth_height": ar.depthHeight,
            "depth_format": "raw little-endian Float32, row-major, tightly packed (행 패딩 제거됨)",
            "depth_confidence_format": "raw UInt8, row-major (0=low, 1=medium, 2=high)",
            "depth_saved_hz_requested": ar.depthSaveHz,
            "depth_saved_hz_measured": ar.measuredDepthHz,   // 설정값이 아니라 실측값
            "depth_frame_count": ar.depthFrameCount,
            "depth_uploaded": uploadDepth,
            "depth_note": "뎁스는 3D 뷰어에 필요 없다 (뷰어가 그리는 것은 scene_mesh.ply). "
                + "오프라인 재융합/검증용 자산이며 기본적으로 기기에만 남는다.",

            // --- 카운트 ---
            "video_frame_count": ar.videoFrameCount,
            "pose_row_count": ar.poseRowCount,
            "gyro_sample_count": motionManager.gyroSampleCount,
            "accel_sample_count": motionManager.accelSampleCount,
            "device_motion_sample_count": motionManager.deviceMotionSampleCount,
            "coaching_event_count": coach.eventCount,

            // --- CSV legend ---
            "tracking_state_legend": ARCaptureManager.trackingStateLegend,
            "tracking_reason_legend": ARCaptureManager.trackingReasonLegend,
            "arkit_pose_columns": ARCaptureManager.poseCSVHeader,
            "arkit_pose_frame_index_note":
                "frame_index는 video.mov의 프레임 번호. -1이면 이 포즈에 대응하는 영상 프레임이 없다 "
                + "(포즈는 매 프레임, 영상은 video_saved_hz로 솎아 기록하기 때문).",

            // --- 기기 ---
            // UIDevice.current.model은 모든 아이폰에서 "iPhone"만 주므로 기종 구분이 안 된다.
            // 실제 기종은 DeviceInfo(uname 기반)에서 가져온다.
            "device": DeviceInfo.marketingName,          // 예: "iPhone 15 Pro"
            "device_identifier": DeviceInfo.identifier,  // 예: "iPhone16,1"
            "device_class": device.model,                // "iPhone" / "iPad" (기존 필드 의미 유지)
            "device_name": device.name,
            "ios_version": device.systemVersion,
            // 표 기준 LiDAR 탑재 여부. 실제 판단은 lidar_available(ARKit 런타임 질의)이며,
            // 둘이 다르면 표가 낡았다는 뜻이다.
            "device_has_lidar_by_model_table": DeviceInfo.hasLiDARByModelTable,
            "gyro_available": gyroActive,
            "accelerometer_available": accelActive,
            "device_motion_available": deviceMotionActive,
        ]

        // --- 메시 통계 ---
        if let mesh {
            metadata["mesh_vertex_count"] = mesh.vertexCount
            metadata["mesh_face_count"] = mesh.faceCount
            metadata["mesh_anchor_count"] = mesh.anchorCount
            metadata["mesh_has_classification"] = mesh.hasClassification
            metadata["mesh_class_face_counts"] = mesh.classFaceCounts
            metadata["mesh_bounds_min"] = [mesh.boundsMin.x, mesh.boundsMin.y, mesh.boundsMin.z]
            metadata["mesh_bounds_max"] = [mesh.boundsMax.x, mesh.boundsMax.y, mesh.boundsMax.z]
            let size = mesh.boundsMax - mesh.boundsMin
            metadata["mesh_extent_meters"] = [size.x, size.y, size.z]
            metadata["mesh_format"] = "PLY binary_little_endian 1.0. "
                + "정점: x,y,z,nx,ny,nz,red,green,blue / 면: vertex_indices + classification(uchar)"
            metadata["mesh_classification_legend"] =
                Dictionary(uniqueKeysWithValues:
                    MeshExporter.classPalette.enumerated().map { ($0.element.name, $0.offset) })
            metadata["mesh_classification_sidecar"] = "scene_mesh_faces_class.bin"
            metadata["mesh_classification_sidecar_note"] =
                "면당 UInt8 1바이트, PLY의 면 순서와 동일. Open3D는 PLY의 커스텀 면 property를 "
                + "조용히 버리므로 기계가 읽어야 하는 정답 라벨은 이 파일 쪽이다. "
                + "PLY의 정점 색은 같은 분류를 눈으로 보기 위한 시각화이며, 면->정점 전파 과정에서 "
                + "경계 정점은 인접 클래스 중 하나로 임의 결정된다."
        } else {
            metadata["mesh_vertex_count"] = 0
            metadata["mesh_face_count"] = 0
        }

        let url = dir.appendingPathComponent("metadata.json")
        if let data = try? JSONSerialization.data(withJSONObject: metadata,
                                                  options: [.prettyPrinted, .sortedKeys]) {
            try? data.write(to: url)
        }
    }

    // MARK: - 업로드 대상

    /// 서버로 올릴 파일 목록.
    /// ⚠ 서버의 ALLOWED_FILENAMES 화이트리스트에 없는 파일명은 400으로 거부된다.
    ///   새 파일(scene_mesh.ply, scene_mesh_faces_class.bin, coaching.csv, depth.zip)은
    ///   서버 수정이 필요하다. docs/server_changes.md 참고.
    ///   임의로 기존 화이트리스트 이름에 맞춰 우회하지 않았다.
    func sessionFiles() -> [URL] {
        guard let dir = sessionDirectory else { return [] }
        var names = [
            "video.mov",
            "video_frames.csv",
            "imu.csv",
            "device_motion.csv",
            "arkit_pose.csv",
            "coaching.csv",
            "scene_mesh.ply",
            "scene_mesh_faces_class.bin",
            "metadata.json",
        ]
        // ⚠️ depth.zip은 **가장 마지막**에 둔다 (metadata.json 뒤).
        //
        //   이유: depth.zip은 수십~수백 MB로 가장 실패하기 쉬운 파일인데, 예전에는
        //   metadata.json 바로 앞에 있었다. 그래서 뎁스가 실패하거나 멈추면 metadata.json이
        //   영영 안 올라가고 **세션 전체가 해석 불가능**해졌다 (실제로 4번 연속 그렇게 됐다).
        //
        //   metadata.json이 먼저 올라가면, 뎁스가 어떻게 되든 그 세션은 뷰어에서 열리고
        //   분석도 된다. 뎁스는 "있으면 좋은" 부가 데이터이므로 이 순서가 맞다.
        //   (서버의 /session/stop은 업로드가 다 끝난 뒤 앱이 한 번 부르므로 순서와 무관하다.)
        if uploadDepth, depthZipURL != nil { names.append("depth.zip") }

        return names
            .map { dir.appendingPathComponent($0) }
            .filter { FileManager.default.fileExists(atPath: $0.path) }
    }

    /// 업로드하기 전에 "이 세션이 완전한가"를 확인한다.
    ///
    /// isSaving 가드가 이미 막고 있지만, 이건 **두 번째 방어선**이다. 불완전한 세션을
    /// 올려서 "성공"이라고 말하는 것이 이 앱에서 겪은 가장 나쁜 실패였다 —
    /// 앱은 완료라 하고 서버에는 해석 불가능한 폴더가 남았다.
    /// 없으면 안 되는 파일이 빠졌으면 아예 올리지 않고 이유를 말한다.
    func missingRequiredFiles() -> [String] {
        guard let dir = sessionDirectory else { return ["세션 폴더"] }
        // metadata.json이 없으면 서버도 뷰어도 그 세션을 해석할 수 없다.
        // scene_mesh.ply가 없으면 3D 모델 자체가 없는 것이다(LiDAR 미지원 기기는 예외).
        var required = ["metadata.json"]
        if lidarAvailable { required.append("scene_mesh.ply") }
        return required.filter { !FileManager.default.fileExists(
            atPath: dir.appendingPathComponent($0).path) }
    }

    /// 업로드할 총 바이트. UI에서 "이거 올리면 얼마나 걸리는지"를 미리 보여주기 위한 것.
    func sessionUploadSize() -> Int64 {
        sessionFiles().reduce(Int64(0)) { total, url in
            let size = (try? FileManager.default.attributesOfItem(atPath: url.path)[.size]) as? Int64
            return total + (size ?? 0)
        }
    }
}

