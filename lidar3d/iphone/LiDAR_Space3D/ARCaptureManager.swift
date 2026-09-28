import Foundation
import ARKit
import AVFoundation
import CoreVideo
import simd

/// ARKit(LiDAR) 기반 캡처의 심장. 기존 CameraManager(AVFoundation)를 **대체**한다.
///
/// 왜 교체인가 (덧붙이기가 아니라):
/// ARSession과 AVCaptureSession은 카메라 하드웨어를 동시에 점유할 수 없다. 둘을 같이 켜면
/// 나중에 켠 쪽이 조용히 프레임을 못 받거나 세션이 중단된다. 그래서 AVFoundation 경로를 버리고
/// ARKit이 주는 ARFrame.capturedImage를 AVAssetWriter에 직접 넣어 video.mov를 만든다.
/// 결과적으로 "출력 파일 계약은 그대로, 내부 구현만 ARKit"이 된다.
///
/// 한 콜백에서 포즈 + 영상 + 뎁스를 전부 처리하는 이유 (중요):
/// 세 가지를 각기 다른 타이머로 돌리면 "이 포즈가 저 영상 프레임의 포즈인가"를 float
/// timestamp 근사 매칭으로 풀어야 한다. 같은 콜백에서 같은 ARFrame 하나를 보고 전부 기록하면
/// frame_index가 **정확히** 일치한다. 근사 매칭은 조용히 한 프레임씩 밀리는 종류의 버그를 낳는다.
///
/// 실패 시 확인할 것:
/// - 영상이 0바이트  -> assetWriter.status / .error 로그, 그리고 Info.plist 카메라 권한
/// - 뎁스 파일이 안 생김 -> sceneDepthAvailable 플래그(비LiDAR 기기이거나 frameSemantics 미적용)
/// - 포즈 CSV만 있고 나머지가 없음 -> 정상적인 graceful degradation. metadata.json의 가용성 플래그 확인
final class ARCaptureManager: NSObject {

    // MARK: - 기기 능력 (Phase 1). 실행 전에 확인하고 metadata에 그대로 기록한다.

    /// .meshWithClassification (문/벽/바닥 분류 포함) 지원 여부. 사실상 LiDAR 탑재 여부와 같다.
    static var supportsMeshWithClassification: Bool {
        ARWorldTrackingConfiguration.supportsSceneReconstruction(.meshWithClassification)
    }
    /// 분류 없는 메시만 지원하는 경우(이론상). 위가 false여도 이게 true면 형상은 얻을 수 있다.
    static var supportsMesh: Bool {
        ARWorldTrackingConfiguration.supportsSceneReconstruction(.mesh)
    }
    /// 미터 단위 뎁스맵 제공 여부.
    static var supportsSceneDepth: Bool {
        ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth)
    }
    /// 시간적으로 평활화된 뎁스맵 제공 여부.
    ///
    /// 왜 둘 다 저장하는가 (실측으로 드러난 문제):
    ///   같은 방·같은 시각에 찍었는데 15 Pro(iOS 26.6.1)는 원시 sceneDepth의 신뢰도가
    ///   **"높음" 0.00%**, 12 Pro(iOS 26.2.1)는 80.29%였다. ARKit이 15 Pro의 뎁스를 전부
    ///   "믿을 수 없음"으로 판정해, 메시도 적게 만들고 품질도 낮았다.
    ///   smoothedSceneDepth는 여러 프레임을 누적해 만드므로 신뢰도 판정이 다를 수 있다.
    ///   **같은 스캔에서 둘 다 저장해야** 기기·촬영 조건 변수 없이 정확히 비교된다.
    static var supportsSmoothedSceneDepth: Bool {
        ARWorldTrackingConfiguration.supportsFrameSemantics(.smoothedSceneDepth)
    }
    /// ARKit world tracking 자체가 되는 기기인가 (A9 이상). 시뮬레이터/구형 기기에서 false.
    static var supportsWorldTracking: Bool {
        ARWorldTrackingConfiguration.isSupported
    }
    /// 이 앱이 의도한 "LiDAR 캡처"가 가능한가.
    static var isLiDARCaptureAvailable: Bool {
        supportsWorldTracking && supportsMesh && supportsSceneDepth
    }

    // MARK: - 설정 (전부 런타임 조정 가능. 하드코딩된 값을 강제하지 않는다.)

    /// 평활 뎁스(.smoothedSceneDepth)를 함께 받을지. **기본 false.**
    /// 켜면 15 Pro급 기기에서 메시 생성이 붕괴한다 (위 configureAndRun 주석 참고).
    /// 다시 실험할 일이 있을 때만 켠다.
    var enableSmoothedSceneDepth = false

    /// 뎁스맵 저장 주기(Hz). 뎁스맵은 프레임당 약 192KB라 60fps 전량 저장 시 40초에 460MB가 된다.
    /// 기본 10Hz. 0 이하이면 뎁스 저장을 끈다.
    var depthSaveHz: Double = 10.0
    /// video.mov에 넣을 프레임 주기(Hz). ARKit은 보통 60fps를 주지만 전량 인코딩은 낭비다.
    var videoSaveHz: Double = 15.0
    /// 뎁스 저장 자체를 끄는 스위치 (UI 토글).
    var depthCaptureEnabled: Bool = true

    // MARK: - 관측된 실제값 (추정이 아니라 측정값. metadata.json으로 나간다.)

    let session = ARSession()

    private(set) var isRecording = false
    private(set) var videoFrameCount = 0
    private(set) var poseRowCount = 0
    private(set) var depthFrameCount = 0
    /// 실제로 달성된 뎁스 저장 Hz. 설정값이 아니라 측정값이다 — 기기가 뜨거우면 ARKit이
    /// 조용히 60->30fps로 떨어뜨리므로 "설정 10Hz"를 그대로 믿으면 안 된다.
    private(set) var measuredDepthHz: Double = 0
    private(set) var measuredVideoHz: Double = 0
    /// ARKit이 실제로 고른 카메라 포맷. 1920x1080을 요청해도 LiDAR 기기는 4:3(1920x1440)을 준다.
    private(set) var videoFormatDescription: String = "unknown"
    private(set) var frameWidth: Int = 0
    private(set) var frameHeight: Int = 0
    private(set) var nominalFrameRate: Int = 0
    private(set) var depthWidth: Int = 0
    private(set) var depthHeight: Int = 0
    private(set) var sceneDepthActive = false
    private(set) var smoothedSceneDepthActive = false
    private(set) var meshActive = false
    private(set) var classificationActive = false
    /// 영상 PTS의 기준점. 원본 timestamp = (영상 PTS 초) + videoPTSEpoch 가 **정확히** 성립한다.
    /// AVAssetWriter는 0 기준 상대 PTS만 받으므로 리베이스가 불가피한데, 뺀 값을 숨기지 않고
    /// 여기에 담아 metadata.json으로 내보낸다 (불변식 1번: 오차는 숨기지 말고 기록한다).
    private(set) var videoPTSEpoch: Double = 0
    /// START SESSION을 누른 **그 순간의 카메라 포즈** (camera-to-world).
    ///
    /// 왜 필요한가 (두 대 병합의 핵심):
    ///   ARKit world 좌표계의 원점은 `session.run()`이 불린 자리 — 즉 **앱 화면이 뜬 자리**다.
    ///   START를 누른 자리가 아니다. 실측에서 두 폰이 각각 원점에서 4.5m / 7.0m 떨어진 곳에서
    ///   START를 눌렀고, 그래서 "같이 2m 이동"의 이점이 좌표계에 전혀 반영되지 않았다.
    ///
    ///   이 값을 남겨두면, 두 사람이 **같은 자리에서 START를 누르기만 해도** 맥 쪽 병합이
    ///   두 좌표계의 관계를 거의 정확히 알고 시작할 수 있다 (눈감고 전역 탐색하지 않아도 된다).
    ///
    /// ⚠️ 좌표를 앱에서 변환하지는 않는다. 기록은 ARKit 원본 그대로 두고, 이 기준 자세만
    ///    metadata.json에 따로 실어 보낸다 (변환은 맥에서 한다 — docs/coordinate_system.md).
    private(set) var startPoseTranslation: SIMD3<Float>?
    private(set) var startPoseQuaternion: SIMD4<Float>?
    /// START 시점 카메라가 바라본 **수평 방위**(라디안). 중력 정렬 덕분에 이 값 하나 + 위치면
    /// 두 좌표계 관계가 4자유도로 결정된다.
    private(set) var startPoseYaw: Float?

    private(set) var lastTrackingStateCode: Int = 0
    private(set) var lastTrackingReasonCode: Int = 0
    private(set) var lastError: String?

    /// 수집된 메시 앵커. 세션 종료 시 MeshExporter가 병합한다.
    /// ARFrame과 달리 ARAnchor는 붙잡고 있어도 프레임 풀을 고갈시키지 않으므로 보관해도 안전하다.
    private(set) var meshAnchors: [UUID: ARMeshAnchor] = [:]

    var onStatsUpdate: ((ARCaptureStats) -> Void)?

    // MARK: - 내부 상태

    /// ARKit 콜백을 메인 스레드에서 떼어낸다. 파일 쓰기와 H.264 인코딩이 UI를 막지 않도록.
    private let delegateQueue = DispatchQueue(label: "arcapture.delegate.queue")

    private var assetWriter: AVAssetWriter?
    private var assetWriterInput: AVAssetWriterInput?
    private var pixelBufferAdaptor: AVAssetWriterInputPixelBufferAdaptor?

    private var poseLogger: CSVLogger?
    private var frameLogger: CSVLogger?
    private var depthIndexLogger: CSVLogger?
    private var depthDirectory: URL?

    private var lastVideoWriteTime: TimeInterval = -1
    private var lastDepthWriteTime: TimeInterval = -1
    private var firstFrameTime: TimeInterval = -1
    private var lastFrameTime: TimeInterval = -1
    private var statsThrottle: TimeInterval = -1

    // MARK: - 세션 시작/정지

    /// ARSession 구성 후 실행. 지원하지 않는 기능은 **끄고 진행**하며 절대 크래시하지 않는다.
    ///
    /// 주의: ARSCNView는 makeUIView 시점에 자기 자신을 session.delegate로 설정한다. 따라서
    /// 이 메서드는 반드시 뷰가 만들어진 **뒤에**(ContentView의 .onAppear) 불러야 우리 delegate가
    /// 덮어써지지 않는다. delegate를 가져와도 ARSCNView의 카메라 배경 렌더링은 계속 동작한다
    /// (ARSCNView는 delegate가 아니라 자체 렌더 루프에서 session.currentFrame을 읽는다).
    func configureAndRun() {
        guard ARCaptureManager.supportsWorldTracking else {
            lastError = "이 기기는 ARKit World Tracking을 지원하지 않습니다 (시뮬레이터이거나 구형 기기)."
            return
        }
        let config = ARWorldTrackingConfiguration()

        // 씬 재구성: 분류 포함을 우선하고, 안 되면 분류 없는 메시로, 그것도 안 되면 끈다.
        // RoomPlan을 쓰지 않는 이유는 docs/coordinate_system.md 참고 — 차량 전복/붕괴 공간처럼
        // "방"이 아닌 현장에서는 벽/문 자동 검출을 신뢰할 수 없다.
        if ARCaptureManager.supportsMeshWithClassification {
            config.sceneReconstruction = .meshWithClassification
            meshActive = true
            classificationActive = true
        } else if ARCaptureManager.supportsMesh {
            config.sceneReconstruction = .mesh
            meshActive = true
            classificationActive = false
        } else {
            config.sceneReconstruction = []
            meshActive = false
            classificationActive = false
        }

        // 뎁스맵: 미터 단위 절대 스케일의 원천.
        if ARCaptureManager.supportsSceneDepth {
            config.frameSemantics.insert(.sceneDepth)
            sceneDepthActive = true
            // ⚠️ .smoothedSceneDepth는 **의도적으로 켜지 않는다** (2026-09-18 실측으로 철회).
            //
            //   기대: 평활 뎁스는 여러 프레임을 누적하므로 신뢰도 판정이 나을 것이다.
            //   실측: 원시/평활의 신뢰도 맵이 **소수점까지 완전히 동일**했다 (15 Pro 높음 0.00%,
            //         12 Pro 높음 73.56% — 양쪽 다 두 뎁스가 같은 값). 얻는 것이 없었다.
            //   대가: semantic을 하나 더 켜자 ARKit 부담이 늘어 **15 Pro의 메시 생성이 붕괴**했다
            //         (8,252 -> 134 정점/이동m, -98%). 12 Pro는 -8%로 견뎠다.
            //
            //   즉 "얻는 것 없이 이미 한계인 기기를 무너뜨리는" 변경이었다. 켜지 않는다.
            //   (지원 여부 조회 자체는 metadata 기록용으로 남겨둔다 — 비용이 없다.)
            if enableSmoothedSceneDepth, ARCaptureManager.supportsSmoothedSceneDepth {
                config.frameSemantics.insert(.smoothedSceneDepth)
                smoothedSceneDepthActive = true
            }
        } else {
            sceneDepthActive = false
        }

        // 조도 추정은 코칭(조명 부족 경고)에 필요하므로 기본값(true)을 그대로 둔다.
        config.isLightEstimationEnabled = true
        // 평면 검출은 켜지 않는다: 메시가 이미 형상을 주고, 평면 검출은 CPU만 더 먹는다.

        // 실제로 선택된 포맷을 읽어 기록한다. 없는 포맷을 강제하지 않는다 (불변식 6번).
        let format = config.videoFormat
        frameWidth = Int(format.imageResolution.width)
        frameHeight = Int(format.imageResolution.height)
        nominalFrameRate = format.framesPerSecond
        videoFormatDescription = "\(frameWidth)x\(frameHeight)@\(nominalFrameRate)"

        session.delegate = self
        session.delegateQueue = delegateQueue
        session.run(config, options: [.resetTracking, .removeExistingAnchors])
    }

    func pause() {
        session.pause()
    }

    // MARK: - 녹화

    /// 녹화 시작. 어느 한 출력이 실패해도 나머지는 계속 기록된다 (불변식 4번).
    /// - Parameters:
    ///   - videoURL: video.mov 경로
    ///   - frameLogger: video_frames.csv (frame_index,timestamp) — 기존 스키마 유지
    ///   - poseLogger: arkit_pose.csv
    ///   - depthDirectory: depth/ 폴더 (nil이면 뎁스 저장 안 함)
    ///   - depthIndexLogger: depth/index.csv
    func startRecording(videoURL: URL,
                        frameLogger: CSVLogger?,
                        poseLogger: CSVLogger?,
                        depthDirectory: URL?,
                        depthIndexLogger: CSVLogger?) {
        delegateQueue.sync {
            self.frameLogger = frameLogger
            self.poseLogger = poseLogger
            self.depthDirectory = depthDirectory
            self.depthIndexLogger = depthIndexLogger

            self.videoFrameCount = 0
            self.poseRowCount = 0
            self.depthFrameCount = 0
            self.lastVideoWriteTime = -1
            self.lastDepthWriteTime = -1
            self.firstFrameTime = -1
            self.lastFrameTime = -1
            self.videoPTSEpoch = 0
            self.startPoseTranslation = nil
            self.startPoseQuaternion = nil
            self.startPoseYaw = nil

            // AVAssetWriter 준비. 실패하면 영상만 포기하고 포즈/뎁스/메시는 계속 간다.
            do {
                let writer = try AVAssetWriter(outputURL: videoURL, fileType: .mov)
                let settings: [String: Any] = [
                    AVVideoCodecKey: AVVideoCodecType.h264,
                    AVVideoWidthKey: self.frameWidth,
                    AVVideoHeightKey: self.frameHeight,
                ]
                let input = AVAssetWriterInput(mediaType: .video, outputSettings: settings)
                input.expectsMediaDataInRealTime = true

                // 회전 transform을 **의도적으로 붙이지 않는다.** (기존 CameraManager는 90도 회전을 붙였다.)
                // frame.camera.intrinsics(fx,fy,cx,cy)는 회전 전 landscape 원본 픽셀 좌표계 기준값이다.
                // 영상만 세로로 돌려놓으면 Mac에서 뽑은 프레임은 세로인데 intrinsics는 가로 기준이 되어
                // **에러 없이 조용히 틀린 재투영**이 나온다. LiDAR로 얻은 절대 스케일이 여기서 죽는다.
                // 화면 프리뷰는 ARSCNView가 알아서 세로로 보여주므로 사람이 보는 것은 달라지지 않는다.
                // input.transform = ... (금지)

                // sourcePixelBufferAttributes를 nil로 둬서 ARKit이 준 YCbCr 버퍼를 변환 없이 그대로
                // 인코더에 넘긴다. CIContext로 RGB 변환을 거치면 프레임마다 풀해상도 리샘플이 들어가
                // 발열/프레임드랍의 주범이 된다.
                let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input,
                                                                    sourcePixelBufferAttributes: nil)
                guard writer.canAdd(input) else { throw ARCaptureError.cannotAddWriterInput }
                writer.add(input)
                guard writer.startWriting() else { throw ARCaptureError.writerFailed(writer.error) }
                writer.startSession(atSourceTime: .zero)

                self.assetWriter = writer
                self.assetWriterInput = input
                self.pixelBufferAdaptor = adaptor
            } catch {
                self.assetWriter = nil
                self.assetWriterInput = nil
                self.pixelBufferAdaptor = nil
                self.lastError = "영상 기록 시작 실패 (포즈/뎁스/메시는 계속 기록됨): \(error)"
            }

            self.isRecording = true
        }
    }

    /// 녹화 정지. AVAssetWriter의 finishWriting은 비동기라 완료 콜백을 기다린다.
    func stopRecording(completion: @escaping () -> Void) {
        delegateQueue.async {
            self.isRecording = false

            // 측정된 실제 Hz 확정 (설정값이 아니라 실측값).
            let span = self.lastFrameTime - self.firstFrameTime
            if span > 0 {
                self.measuredDepthHz = Double(self.depthFrameCount) / span
                self.measuredVideoHz = Double(self.videoFrameCount) / span
            }

            self.poseLogger?.close()
            self.frameLogger?.close()
            self.depthIndexLogger?.close()
            self.poseLogger = nil
            self.frameLogger = nil
            self.depthIndexLogger = nil

            guard let writer = self.assetWriter, let input = self.assetWriterInput else {
                self.assetWriter = nil
                self.assetWriterInput = nil
                self.pixelBufferAdaptor = nil
                completion()
                return
            }
            guard writer.status == .writing else {
                // 한 프레임도 못 썼거나 이미 실패한 상태 — 취소하고 나머지 파일은 살린다.
                writer.cancelWriting()
                self.assetWriter = nil
                self.assetWriterInput = nil
                self.pixelBufferAdaptor = nil
                completion()
                return
            }
            input.markAsFinished()
            writer.finishWriting {
                if writer.status != .completed {
                    self.lastError = "영상 마무리 실패: \(String(describing: writer.error))"
                }
                self.assetWriter = nil
                self.assetWriterInput = nil
                self.pixelBufferAdaptor = nil
                completion()
            }
        }
    }

    /// 메시 앵커를 **delegateQueue 위에서** 복사해 넘긴다.
    /// meshAnchors 딕셔너리는 ARSessionDelegate 콜백(= delegateQueue)에서만 쓰이는데,
    /// 세션 종료는 메인 스레드에서 일어난다. 메인에서 직접 읽으면 ARKit이 같은 순간에
    /// 딕셔너리를 수정하고 있을 수 있어 데이터 레이스가 된다 (Swift Dictionary는
    /// 동시 접근 시 크래시하거나 조용히 값이 깨진다).
    func snapshotMeshAnchors() -> [ARMeshAnchor] {
        delegateQueue.sync { Array(meshAnchors.values) }
    }

    enum ARCaptureError: Error {
        case cannotAddWriterInput
        case writerFailed(Error?)
    }
}

/// UI로 올려보내는 상태 묶음. @Published를 프레임마다 때리면 SwiftUI가 죽으므로
/// 여기 모아서 4Hz로만 올린다.
struct ARCaptureStats {
    var videoFrameCount: Int
    var poseRowCount: Int
    var depthFrameCount: Int
    var meshAnchorCount: Int
    var trackingStateCode: Int
    var trackingReasonCode: Int
    var sceneExtentMeters: SIMD3<Float>
}

// MARK: - ARSessionDelegate

extension ARCaptureManager: ARSessionDelegate {

    /// 매 프레임 호출 (보통 60Hz). 여기서 포즈 / 영상 / 뎁스를 **같은 ARFrame 하나로** 처리한다.
    /// delegateQueue(백그라운드 직렬 큐)에서 불리므로 UI를 막지 않는다.
    ///
    /// ⚠ ARFrame을 프로퍼티에 저장해서 붙잡으면 안 된다. ARKit의 프레임 풀이 고갈되어
    /// 세션이 통째로 멎는다. 아래는 전부 스칼라를 읽어 쓰고 바로 놓아준다.
    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        // timestamp는 ARFrame.timestamp 원본 그대로. 절대 보정하지 않는다 (불변식 1번).
        let t = frame.timestamp

        let camera = frame.camera
        let (stateCode, reasonCode) = ARCaptureManager.trackingCodes(camera.trackingState)
        lastTrackingStateCode = stateCode
        lastTrackingReasonCode = reasonCode

        // ⚠ 트래킹 상태와 메시 개수는 **녹화 중이 아니어도** 갱신해야 한다.
        //   여기에 `guard isRecording`을 걸면 START를 누르기 전까지 화면이 계속
        //   "NOT AVAILABLE"로 남아, 촬영자가 **트래킹이 잡혔는지 모르는 채로 START를 누르게 된다.**
        //   그러면 세션 앞부분이 통째로 못 쓰는 데이터가 된다 — 이 앱이 막으려던 바로 그 문제다.
        //   (파일 쓰기만 녹화 중으로 제한한다.)
        if isRecording {
            if firstFrameTime < 0 {
                firstFrameTime = t
                captureStartPose(camera.transform)
            }
            lastFrameTime = t
            writeOutputs(frame: frame, t: t, camera: camera,
                         stateCode: stateCode, reasonCode: reasonCode)
        }

        // --- 4) UI 갱신은 4Hz로 조인다 (녹화 여부와 무관) ---
        if statsThrottle < 0 || (t - statsThrottle) >= 0.25 {
            statsThrottle = t
            let stats = ARCaptureStats(
                videoFrameCount: videoFrameCount,
                poseRowCount: poseRowCount,
                depthFrameCount: depthFrameCount,
                meshAnchorCount: meshAnchors.count,
                trackingStateCode: stateCode,
                trackingReasonCode: reasonCode,
                sceneExtentMeters: sceneExtent()
            )
            DispatchQueue.main.async { [weak self] in self?.onStatsUpdate?(stats) }
        }
    }

    /// START 시점의 기준 자세를 기록한다. 첫 기록 프레임에서 한 번만 불린다.
    ///
    /// 회전에서 **yaw만** 뽑아두는 이유: ARKit이 두 기기 모두 중력으로 Y축을 맞추므로
    /// roll/pitch 차이는 물리적으로 0이어야 한다. 폰을 든 각도(기울기)까지 기준에 넣으면
    /// 오히려 두 좌표계 관계에 없는 기울기를 끌어들여 병합이 어긋난다.
    private func captureStartPose(_ transform: simd_float4x4) {
        let t = transform.columns.3
        guard t.x.isFinite, t.y.isFinite, t.z.isFinite else { return }
        startPoseTranslation = SIMD3(t.x, t.y, t.z)

        let rot = simd_float3x3(
            simd_normalize(SIMD3(transform.columns.0.x, transform.columns.0.y, transform.columns.0.z)),
            simd_normalize(SIMD3(transform.columns.1.x, transform.columns.1.y, transform.columns.1.z)),
            simd_normalize(SIMD3(transform.columns.2.x, transform.columns.2.y, transform.columns.2.z))
        )
        let q = simd_quatf(rot)
        startPoseQuaternion = SIMD4(q.vector.x, q.vector.y, q.vector.z, q.vector.w)

        // 카메라 전방은 -Z. 그 수평 성분의 방위각이 yaw다.
        let forwardX = -transform.columns.2.x
        let forwardZ = -transform.columns.2.z
        startPoseYaw = atan2(forwardX, forwardZ)
    }

    /// 녹화 중에만 도는 파일 쓰기 경로 (영상 / 포즈 / 뎁스).
    private func writeOutputs(frame: ARFrame, t: TimeInterval, camera: ARCamera,
                              stateCode: Int, reasonCode: Int) {
        // --- 1) 영상: 주기 게이트를 먼저 통과시켜야 frame_index를 확정할 수 있다 ---
        var writtenFrameIndex = -1
        let videoInterval = videoSaveHz > 0 ? 1.0 / videoSaveHz : .greatestFiniteMagnitude
        if lastVideoWriteTime < 0 || (t - lastVideoWriteTime) >= videoInterval {
            if let input = assetWriterInput, let adaptor = pixelBufferAdaptor,
               let writer = assetWriter, writer.status == .writing,
               input.isReadyForMoreMediaData {
                // 첫 프레임의 timestamp를 PTS 기준점으로 삼는다. 뺀 값은 videoPTSEpoch에 남겨
                // metadata로 내보내므로 원본 복원이 가능하다 (숨기는 게 아니라 명시하는 것).
                if videoFrameCount == 0 { videoPTSEpoch = t }
                let pts = CMTime(seconds: t - videoPTSEpoch, preferredTimescale: 600)
                if adaptor.append(frame.capturedImage, withPresentationTime: pts) {
                    writtenFrameIndex = videoFrameCount
                    // 기존 스키마 유지: frame_index,timestamp — timestamp는 원본 ARFrame.timestamp.
                    frameLogger?.write(String(format: "%d,%.6f\n", videoFrameCount, t))
                    videoFrameCount += 1
                    lastVideoWriteTime = t
                }
            }
        }

        // --- 2) 포즈: 매 프레임 전량 기록 (행당 ~120B, 60Hz라도 7KB/s에 불과) ---
        // transform은 camera-to-world. columns.3이 위치(미터), 좌상단 3x3이 회전.
        let T = camera.transform
        let tx = T.columns.3.x, ty = T.columns.3.y, tz = T.columns.3.z
        // 회전 3x3을 쿼터니언으로. 스케일이 섞이지 않도록 각 축을 정규화한 뒤 변환한다.
        let rot = simd_float3x3(
            simd_normalize(SIMD3(T.columns.0.x, T.columns.0.y, T.columns.0.z)),
            simd_normalize(SIMD3(T.columns.1.x, T.columns.1.y, T.columns.1.z)),
            simd_normalize(SIMD3(T.columns.2.x, T.columns.2.y, T.columns.2.z))
        )
        let q = simd_quatf(rot)
        let K = camera.intrinsics
        // 트래킹이 흔들릴 때 transform에 NaN/Inf가 들어올 수 있다. String(format:)이 "nan"을
        // 찍으면 pandas가 통째로 object 컬럼이 되어 하위 분석이 조용히 망가진다. 아예 건너뛴다.
        if tx.isFinite, ty.isFinite, tz.isFinite,
           q.vector.x.isFinite, q.vector.y.isFinite, q.vector.z.isFinite, q.vector.w.isFinite {
            poseLogger?.write(String(
                format: "%d,%.6f,%.6f,%.6f,%.6f,%.9f,%.9f,%.9f,%.9f,%d,%d,%.4f,%.4f,%.4f,%.4f\n",
                writtenFrameIndex, t,
                Double(tx), Double(ty), Double(tz),
                Double(q.vector.x), Double(q.vector.y), Double(q.vector.z), Double(q.vector.w),
                stateCode, reasonCode,
                Double(K.columns.0.x), Double(K.columns.1.y),
                Double(K.columns.2.x), Double(K.columns.2.y)
            ))
            poseRowCount += 1
        }

        // --- 3) 뎁스: 주기 게이트 ---
        if depthCaptureEnabled, depthSaveHz > 0, let depthDir = depthDirectory,
           let sceneDepth = frame.sceneDepth {
            let depthInterval = 1.0 / depthSaveHz
            if lastDepthWriteTime < 0 || (t - lastDepthWriteTime) >= depthInterval {
                if writeDepth(sceneDepth, smoothed: frame.smoothedSceneDepth,
                              to: depthDir, index: depthFrameCount, timestamp: t,
                              videoFrameIndex: writtenFrameIndex) {
                    depthFrameCount += 1
                    lastDepthWriteTime = t
                }
            }
        }
    }

    // MARK: 메시 앵커 수집

    func session(_ session: ARSession, didAdd anchors: [ARAnchor]) {
        for case let mesh as ARMeshAnchor in anchors { meshAnchors[mesh.identifier] = mesh }
    }

    func session(_ session: ARSession, didUpdate anchors: [ARAnchor]) {
        for case let mesh as ARMeshAnchor in anchors { meshAnchors[mesh.identifier] = mesh }
    }

    /// ARKit은 인접한 앵커를 합치면서 옛 앵커를 제거한다. 지우지 않으면 병합된 메시가
    /// 두 번 들어가 파일이 부풀고 표면이 겹쳐 보인다.
    func session(_ session: ARSession, didRemove anchors: [ARAnchor]) {
        for case let mesh as ARMeshAnchor in anchors { meshAnchors.removeValue(forKey: mesh.identifier) }
    }

    // MARK: 세션 사고 처리 — 한 쪽이 죽어도 나머지를 죽이지 않는다 (불변식 4번)

    func session(_ session: ARSession, didFailWithError error: Error) {
        lastError = "ARSession 실패: \(error.localizedDescription)"
    }

    func sessionWasInterrupted(_ session: ARSession) {
        lastError = "AR 세션 중단됨 (전화/잠금/앱 전환). 복귀를 기다립니다."
    }

    /// 중단에서 복귀. resetTracking을 하면 지금까지 모은 메시의 좌표계가 어긋나므로
    /// **절대 리셋하지 않는다.** ARKit의 자체 relocalization에 맡긴다.
    func sessionInterruptionEnded(_ session: ARSession) {
        lastError = nil
    }
}

// MARK: - 뎁스 파일 쓰기

private extension ARCaptureManager {

    /// depth_%06d.bin / conf_%06d.bin 저장 + index.csv 한 줄.
    ///
    /// 형식: little-endian Float32, row-major, **tightly packed**(패딩 제거).
    /// CVPixelBuffer의 bytesPerRow는 width*4보다 클 수 있어서(정렬 패딩) 통째로 복사하면
    /// Mac에서 numpy.reshape 했을 때 이미지가 비스듬히 밀린다. 반드시 행 단위로 복사한다.
    func writeDepth(_ depth: ARDepthData, smoothed: ARDepthData?, to dir: URL, index: Int,
                    timestamp: TimeInterval, videoFrameIndex: Int) -> Bool {
        let depthMap = depth.depthMap
        guard CVPixelBufferGetPixelFormatType(depthMap) == kCVPixelFormatType_DepthFloat32 else {
            return false
        }
        guard let depthData = ARCaptureManager.packedBytes(from: depthMap, bytesPerPixel: 4) else {
            return false
        }
        if depthWidth == 0 {
            depthWidth = CVPixelBufferGetWidth(depthMap)
            depthHeight = CVPixelBufferGetHeight(depthMap)
        }

        let depthName = String(format: "depth_%06d.bin", index)
        do {
            try depthData.write(to: dir.appendingPathComponent(depthName))
        } catch {
            lastError = "뎁스 저장 실패: \(error.localizedDescription)"
            return false
        }

        // 신뢰도는 UInt8 (0=low, 1=medium, 2=high). 없을 수도 있으므로 실패해도 뎁스는 살린다.
        var confName = ""
        if let confMap = depth.confidenceMap,
           CVPixelBufferGetPixelFormatType(confMap) == kCVPixelFormatType_OneComponent8,
           let confData = ARCaptureManager.packedBytes(from: confMap, bytesPerPixel: 1) {
            confName = String(format: "conf_%06d.bin", index)
            try? confData.write(to: dir.appendingPathComponent(confName))
        }

        // 평활 뎁스(있으면). 원시 뎁스와 **같은 프레임**이라 직접 비교가 가능하다.
        var sDepthName = "", sConfName = ""
        if let smoothed,
           CVPixelBufferGetPixelFormatType(smoothed.depthMap) == kCVPixelFormatType_DepthFloat32,
           let sData = ARCaptureManager.packedBytes(from: smoothed.depthMap, bytesPerPixel: 4) {
            sDepthName = String(format: "sdepth_%06d.bin", index)
            if (try? sData.write(to: dir.appendingPathComponent(sDepthName))) == nil {
                sDepthName = ""
            }
            if let sConf = smoothed.confidenceMap,
               CVPixelBufferGetPixelFormatType(sConf) == kCVPixelFormatType_OneComponent8,
               let sConfData = ARCaptureManager.packedBytes(from: sConf, bytesPerPixel: 1) {
                sConfName = String(format: "sconf_%06d.bin", index)
                if (try? sConfData.write(to: dir.appendingPathComponent(sConfName))) == nil {
                    sConfName = ""
                }
            }
        }

        // 파일명 정렬 순서에 의존하지 않게 인덱스를 남긴다. 중간에 프레임이 빠져도 안전하다.
        depthIndexLogger?.write(String(format: "%d,%.6f,%d,%@,%@,%@,%@\n",
                                        index, timestamp, videoFrameIndex,
                                        depthName, confName, sDepthName, sConfName))
        return true
    }

    /// CVPixelBuffer를 행 패딩 없이 촘촘한 Data로 복사한다.
    static func packedBytes(from buffer: CVPixelBuffer, bytesPerPixel: Int) -> Data? {
        CVPixelBufferLockBaseAddress(buffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddress(buffer) else { return nil }
        let width = CVPixelBufferGetWidth(buffer)
        let height = CVPixelBufferGetHeight(buffer)
        let srcStride = CVPixelBufferGetBytesPerRow(buffer)
        let dstStride = width * bytesPerPixel

        if srcStride == dstStride {
            return Data(bytes: base, count: dstStride * height)   // 패딩 없음 — 통째로 복사
        }
        var out = Data(capacity: dstStride * height)
        for row in 0..<height {
            out.append(Data(bytes: base.advanced(by: row * srcStride), count: dstStride))
        }
        return out
    }

    /// 지금까지 수집된 메시의 월드 바운딩 박스 크기(미터). UI에 "추정 공간 크기"로 보여준다.
    /// 앵커의 transform 원점만 쓰는 근사치다 — 정확한 값은 최종 PLY에서 계산된다.
    func sceneExtent() -> SIMD3<Float> {
        guard !meshAnchors.isEmpty else { return .zero }
        var lo = SIMD3<Float>(repeating: .greatestFiniteMagnitude)
        var hi = SIMD3<Float>(repeating: -.greatestFiniteMagnitude)
        for anchor in meshAnchors.values {
            let c = anchor.transform.columns.3
            let p = SIMD3(c.x, c.y, c.z)
            guard p.x.isFinite, p.y.isFinite, p.z.isFinite else { continue }
            lo = simd_min(lo, p); hi = simd_max(hi, p)
        }
        guard lo.x <= hi.x else { return .zero }
        return hi - lo
    }
}

// MARK: - 트래킹 상태 코드

extension ARCaptureManager {
    /// CSV에는 문자열 대신 정수 코드를 쓴다 (pandas 파싱이 쉽고 오타가 없다).
    /// legend는 metadata.json의 tracking_state_legend / tracking_reason_legend에 나간다.
    /// state: 0=notAvailable 1=limited 2=normal
    /// reason: 0=none 1=initializing 2=excessiveMotion 3=insufficientFeatures 4=relocalizing
    static func trackingCodes(_ state: ARCamera.TrackingState) -> (Int, Int) {
        switch state {
        case .notAvailable: return (0, 0)
        case .normal:       return (2, 0)
        case .limited(let reason):
            switch reason {
            case .initializing:          return (1, 1)
            case .excessiveMotion:       return (1, 2)
            case .insufficientFeatures:  return (1, 3)
            case .relocalizing:          return (1, 4)
            @unknown default:            return (1, 0)
            }
        }
    }

    static let trackingStateLegend: [String: Int] =
        ["notAvailable": 0, "limited": 1, "normal": 2]
    static let trackingReasonLegend: [String: Int] =
        ["none": 0, "initializing": 1, "excessiveMotion": 2,
         "insufficientFeatures": 3, "relocalizing": 4]

    static let poseCSVHeader =
        "frame_index,timestamp,tx,ty,tz,qx,qy,qz,qw,tracking_state,tracking_state_reason,fx,fy,cx,cy"
    /// 열을 **뒤에 덧붙였다** — 기존 분석 코드(DictReader 기반)는 그대로 동작한다.
    static let depthIndexCSVHeader =
        "depth_index,timestamp,video_frame_index,depth_file,conf_file,smooth_depth_file,smooth_conf_file"
}
