import SwiftUI
import ARKit
import AVFoundation

/// 단일 화면 UI. 기존 상태 표시 행과 START/STOP/UPLOAD 흐름은 유지하고,
/// LiDAR 상태 + 스캔 코칭을 얹었다.
///
/// 코칭 UI의 우선순위 (구조대원은 화면을 계속 볼 수 없다):
///   1순위 햅틱 (ScanCoach가 직접 울린다)
///   2순위 프리뷰 테두리 색
///   3순위 글자
/// 그래서 경고는 화면 중앙이 아니라 **프리뷰 테두리**에 있다 — 시야 가장자리로도 감지된다.
struct ContentView: View {
    @StateObject private var session = SessionManager()
    @StateObject private var network = NetworkManager()

    @State private var statusMessage = ""
    @State private var cameraPermissionGranted = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                header
                preview
                lidarStatusSection
                Divider()
                sensorStatusSection
                Divider()
                captureOptionsSection
                Divider()
                serverSection
                Divider()
                actionButtons
                messages
            }
            .padding()
        }
        .onAppear(perform: bootstrap)
    }

    // MARK: 헤더

    private var header: some View {
        HStack {
            Text("LiDAR Space 3D").font(.title2).bold()
            Spacer()
            Text(session.lidarAvailable ? "LiDAR" : "NO LiDAR")
                .font(.caption).bold()
                .padding(.horizontal, 8).padding(.vertical, 4)
                .background(session.lidarAvailable ? Color.green.opacity(0.2) : Color.orange.opacity(0.2))
                .foregroundColor(session.lidarAvailable ? .green : .orange)
                .clipShape(Capsule())
        }
    }

    // MARK: 프리뷰 + 코칭 테두리

    private var preview: some View {
        ZStack {
            if cameraPermissionGranted && ARCaptureManager.supportsWorldTracking {
                ARPreviewView(session: session.arCaptureManager.session,
                              showMeshOverlay: session.showMeshOverlay)
                    .frame(height: 300)
                    .clipShape(RoundedRectangle(cornerRadius: 12))
            } else {
                RoundedRectangle(cornerRadius: 12)
                    .fill(Color.black)
                    .frame(height: 300)
                    .overlay(
                        Text(ARCaptureManager.supportsWorldTracking
                             ? "카메라 권한이 필요합니다"
                             : "이 기기는 ARKit을 지원하지 않습니다")
                            .foregroundColor(.white)
                    )
            }

            // 코칭 테두리 — 시선을 화면에 두지 않아도 주변시로 감지되도록 굵게.
            RoundedRectangle(cornerRadius: 12)
                .strokeBorder(coachBorderColor, lineWidth: coachBorderWidth)
                .frame(height: 300)
                .animation(.easeInOut(duration: 0.2), value: session.coachAlert)

            if let alert = session.coachAlert {
                VStack {
                    Spacer()
                    Text(alert.message)
                        .font(.headline).bold()
                        .foregroundColor(.white)
                        .padding(.horizontal, 14).padding(.vertical, 8)
                        .background(coachBorderColor.opacity(0.85))
                        .clipShape(Capsule())
                        .padding(.bottom, 14)
                }
                .frame(height: 300)
            }
        }
    }

    private var coachBorderColor: Color {
        guard let alert = session.coachAlert else {
            return session.isRecording ? .green.opacity(0.7) : .clear
        }
        return alert.severity == .critical ? .red : .orange
    }

    private var coachBorderWidth: CGFloat {
        session.coachAlert == nil ? (session.isRecording ? 3 : 0) : 6
    }

    // MARK: LiDAR 상태

    private var lidarStatusSection: some View {
        Group {
            statusRow("Tracking", trackingText, color: trackingColor)
            statusRow("Mesh Anchors", "\(session.meshAnchorCount)",
                      color: session.meshAnchorCount > 0 ? .green : .gray)
            statusRow("Depth Frames", session.sceneDepthSupported ? "\(session.depthFrameCount)" : "미지원",
                      color: session.sceneDepthSupported ? .primary : .gray)
            statusRow("Smoothed Depth",
                      ARCaptureManager.supportsSmoothedSceneDepth ? "지원 (함께 저장)" : "미지원",
                      color: ARCaptureManager.supportsSmoothedSceneDepth ? .green : .gray)
            statusRow("Pose Rows", "\(session.poseRowCount)", color: .primary)
            statusRow("Scene Size", sceneExtentText, color: .primary)
            if !session.lastMeshSummary.isEmpty {
                statusRow("Last Mesh", session.lastMeshSummary, color: .green)
            }
        }
    }

    /// 트래킹 상태를 **사유까지** 보여준다. "limited"만 봐서는 무엇을 고쳐야 할지 알 수 없다.
    private var trackingText: String {
        switch session.trackingStateCode {
        case 2: return "NORMAL"
        case 1:
            switch session.trackingReasonCode {
            case 1: return "LIMITED — 초기화 중"
            case 2: return "LIMITED — 너무 빠른 움직임"
            case 3: return "LIMITED — 특징점 부족"
            case 4: return "LIMITED — 위치 재탐색 중"
            default: return "LIMITED"
            }
        default: return "NOT AVAILABLE"
        }
    }

    private var trackingColor: Color {
        switch session.trackingStateCode {
        case 2: return .green
        case 1: return .orange
        default: return .red
        }
    }

    private var sceneExtentText: String {
        let e = session.sceneExtent
        guard e.x > 0 || e.y > 0 || e.z > 0 else { return "—" }
        // 이 "m"이 이 프로젝트 전체의 요점이다. monocular SfM에는 없던 절대 스케일.
        return String(format: "%.1f × %.1f × %.1f m", Double(e.x), Double(e.y), Double(e.z))
    }

    // MARK: 기존 센서 상태 (유지)

    private var sensorStatusSection: some View {
        Group {
            statusRow("Recording", session.isRecording ? "● ON" : "○ OFF",
                      color: session.isRecording ? .red : .gray)
            statusRow("Video Format", session.arCaptureManager.videoFormatDescription, color: .primary)
            statusRow("Video Frames", "\(session.frameCount)", color: .primary)
            statusRow("Gyro", session.gyroActive ? "ACTIVE" : "INACTIVE",
                      color: session.gyroActive ? .green : .gray)
            statusRow("Accelerometer", session.accelActive ? "ACTIVE" : "INACTIVE",
                      color: session.accelActive ? .green : .gray)
            statusRow("Device Motion", session.deviceMotionActive ? "ACTIVE" : "INACTIVE",
                      color: session.deviceMotionActive ? .green : .gray)
            statusRow("Network", network.isConnected ? "CONNECTED" : "DISCONNECTED",
                      color: network.isConnected ? .green : .red)
        }
    }

    // MARK: 캡처 옵션

    private var captureOptionsSection: some View {
        Group {
            Text("Capture Options").font(.headline)
            Toggle("메시 오버레이 표시", isOn: $session.showMeshOverlay)
            Toggle("코칭 햅틱", isOn: Binding(get: { session.coach.hapticsEnabled },
                                          set: { session.coach.hapticsEnabled = $0 }))
            // 음성은 기본 OFF — 현장에서 폰이 말하면 무전 교신과 겹친다.
            Toggle("코칭 음성 안내", isOn: Binding(get: { session.coach.voiceEnabled },
                                            set: { session.coach.voiceEnabled = $0 }))
            Toggle("뎁스 저장 (기기 내)", isOn: $session.captureDepth)
                .disabled(session.isRecording || !session.sceneDepthSupported)
            Toggle("뎁스도 업로드 (용량 큼)", isOn: $session.uploadDepth)
                .disabled(session.isRecording || !session.captureDepth)
            Text("3D 뷰어가 그리는 것은 scene_mesh.ply 하나다. 뎁스는 오프라인 검증용이라 "
                 + "기본적으로 기기에만 남는다 — 켜면 업로드가 수백 MB가 된다.")
                .font(.caption2).foregroundColor(.secondary)
        }
    }

    // MARK: 서버

    private var serverSection: some View {
        Group {
            Text("Server").font(.headline)
            HStack {
                // 사설 IP(같은 Wi-Fi)와 공개 터널 주소를 모두 받는다.
                // 시연장에서는 폰이 셀룰러라 사설 IP로는 닿지 않는다.
                TextField("IP 또는 https://... 주소", text: $network.serverAddress)
                    .textFieldStyle(.roundedBorder)
                    .keyboardType(.URL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                TextField("Port", text: $network.serverPort)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 70)
                    .keyboardType(.numberPad)
                    // https:// 주소를 넣으면 포트는 URL에 포함되므로 의미가 없다.
                    .disabled(network.serverAddress.lowercased().hasPrefix("http"))
            }
            // 서버를 LIDAR_TOKEN으로 띄웠을 때만 필요하다. 비우면 헤더를 안 붙인다.
            SecureField("Token (공개 URL로 쓸 때만)", text: $network.authToken)
                .textFieldStyle(.roundedBorder)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            Button("CONNECT") {
                network.checkHealth { ok in
                    statusMessage = ok ? "서버 연결 성공"
                                       : "서버 연결 실패 — 주소/토큰을 확인하세요 (401이면 토큰 문제)"
                }
            }
            .buttonStyle(.bordered)

            if !network.uploadProgress.isEmpty {
                // 어디까지 갔는지 보이지 않으면, 멈췄는지 느린 건지 구분할 수 없다.
                HStack(spacing: 6) {
                    ProgressView().scaleEffect(0.7)
                    Text(network.uploadProgress).font(.caption).foregroundColor(.blue)
                }
            }
            if !network.lastUploadStatus.isEmpty {
                Text("업로드: \(network.lastUploadStatus)").font(.caption)
            }
        }
    }

    // MARK: 버튼

    private var actionButtons: some View {
        VStack(spacing: 10) {
            HStack {
                Button(session.isRecording ? "STOP SESSION"
                       : (session.isSaving ? "저장 중…" : "START SESSION")) {
                    if session.isRecording {
                        statusMessage = "저장 중... (메시 병합에 몇 초 걸립니다)"
                        session.stopSession { dir in
                            statusMessage = dir != nil
                                ? "세션 저장 완료: \(dir!.lastPathComponent)"
                                : "세션 저장 실패"
                        }
                    } else {
                        session.startSession()
                        statusMessage = "촬영 중 — 천천히 움직이세요"
                    }
                }
                .buttonStyle(.borderedProminent)
                .tint(session.isRecording ? .red : .blue)
                .disabled(!cameraPermissionGranted || session.isSaving)

                Button(network.isUploading ? "UPLOADING..."
                       : (session.isSaving ? "저장 대기 중" : "UPLOAD LAST SESSION")) {
                    guard let sessionId = session.currentSessionId else { return }
                    // 불완전한 세션을 "성공"이라며 올리지 않는다.
                    let missing = session.missingRequiredFiles()
                    guard missing.isEmpty else {
                        statusMessage = "업로드 취소 — 필수 파일 누락: \(missing.joined(separator: ", "))"
                            + " (저장이 끝나지 않았습니다. 잠시 후 다시 시도하세요)"
                        return
                    }
                    let files = session.sessionFiles()
                    let mb = Double(session.sessionUploadSize()) / 1_048_576.0
                    statusMessage = String(format: "업로드 중... (%d개 파일, %.1f MB)", files.count, mb)
                    network.uploadSession(sessionId: sessionId, files: files) { result in
                        switch result {
                        case .success:
                            // 선택적 파일(뎁스)이 빠졌으면 성공이라고만 말하지 않는다.
                            // "올라간 줄 알았는데 없다"가 가장 나쁜 실패다.
                            statusMessage = network.skippedFiles.isEmpty
                                ? "업로드 완료 — 서버 뷰어에서 3D 모델을 확인하세요"
                                : "업로드 완료 (일부 제외: \(network.skippedFiles.joined(separator: ", ")))"
                        case .failure(let error):
                            statusMessage = "업로드 실패: \(error.localizedDescription)"
                        }
                    }
                }
                .buttonStyle(.bordered)
                // 업로드 중 연타 방지 — 같은 세션이 두 번 올라가면 서버에서 /session/stop이
                // 두 번 호출되어 파이프라인이 중복 실행되고 서로 파일을 지우며 양쪽 다 실패한다.
                // 불필요해 보여도 절대 제거하지 말 것 (불변식 5번).
                // isSaving: STOP 직후 메시 병합/압축이 끝나기 전에 업로드하면
                // metadata.json과 depth.zip이 빠진 채로 올라간다 (실제로 겪은 사고).
                .disabled(session.isRecording
                          || session.isSaving
                          || session.currentSessionId == nil
                          || network.isUploading)
            }
        }
    }

    private var messages: some View {
        Group {
            if !statusMessage.isEmpty {
                Text(statusMessage).font(.footnote).foregroundColor(.secondary)
            }
            if let lastError = session.lastError {
                Text("경고: \(lastError)").font(.footnote).foregroundColor(.orange)
            }
        }
    }

    // MARK: 시작 절차

    /// 권한 -> ARSession 실행 순서.
    /// ARSCNView는 makeUIView에서 자기를 session.delegate로 잡으므로, ARSession 실행은
    /// 뷰가 만들어진 뒤인 여기(.onAppear)에서 해야 우리 delegate가 덮어써지지 않는다.
    private func bootstrap() {
        guard !cameraPermissionGranted else { return }
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            cameraPermissionGranted = true
            session.startARSession()
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { granted in
                DispatchQueue.main.async {
                    cameraPermissionGranted = granted
                    if granted {
                        session.startARSession()
                    } else {
                        statusMessage = "카메라 권한이 필요합니다 (설정 > LiDAR_Space3D)"
                    }
                }
            }
        default:
            statusMessage = "카메라 권한이 거부되어 있습니다 (설정 > LiDAR_Space3D)"
        }
    }

    private func statusRow(_ label: String, _ value: String, color: Color) -> some View {
        HStack {
            Text(label).frame(width: 130, alignment: .leading).foregroundColor(.secondary)
            Text(value).foregroundColor(color).bold()
            Spacer()
        }
    }
}

#Preview {
    ContentView()
}
