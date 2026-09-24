import Foundation
import Combine
import ARKit
import UIKit
import simd

/// 4D 고정 녹화에서 "폰이 제자리에 고정돼 있는가"와 발열을 감시한다.
///
/// 4D는 카메라가 움직이지 않는다는 전제로 사람의 움직임만 시간대별로 분리한다. 거치대가 밀리거나
/// 누가 폰을 건드리면 그 뒤 구간은 배경까지 흔들려 보여 그 전제가 깨진다. 그래서 START 직후
/// 손을 뗀 자세를 기준으로 잡고, 거기서 3cm 또는 2° 넘게 벗어나면 진동으로 알린다.
///
/// ScanCoach와 같은 방식으로 session.currentFrame을 읽기만 한다(ARFrame을 붙잡지 않는다).
/// 이벤트는 coaching.csv(timestamp,event_type,detail)에 함께 남긴다 — 서버 화이트리스트에
/// 새 파일을 추가하지 않아도 되고, 사후에 "어느 구간이 흔들렸는지" 영상과 대조할 수 있다.
final class FixedMountMonitor: ObservableObject {
    static let maxTranslationM: Float = 0.03
    static let maxRotationDeg: Float = 2.0
    /// START를 누른 손이 폰에서 떨어질 시간. 이 뒤의 자세를 기준으로 삼는다.
    private static let settleSeconds: TimeInterval = 1.5
    private static let hapticInterval: TimeInterval = 3.0

    @Published private(set) var driftAlert: String?
    @Published private(set) var currentTranslationM: Float = 0
    @Published private(set) var currentRotationDeg: Float = 0
    @Published private(set) var thermalState: ProcessInfo.ThermalState = .nominal

    // metadata.json으로 나가는 요약값
    private(set) var maxTranslationM: Float = 0
    private(set) var maxRotationDeg: Float = 0
    private(set) var driftEventCount = 0
    private(set) var thermalSeconds: [String: Double] = [:]

    private weak var session: ARSession?
    private var logger: CSVLogger?
    private var timer: Timer?
    private var startTime: TimeInterval = -1
    private var lastTickTime: TimeInterval = -1
    private var reference: simd_float4x4?
    private var drifting = false
    private var lastHaptic: TimeInterval = -.greatestFiniteMagnitude
    private let haptic = UINotificationFeedbackGenerator()

    func start(session: ARSession, logger: CSVLogger?) {
        stop()
        self.session = session
        self.logger = logger
        maxTranslationM = 0; maxRotationDeg = 0; driftEventCount = 0
        thermalSeconds = [:]; reference = nil; drifting = false; startTime = -1; lastTickTime = -1
        haptic.prepare()
        // 4Hz면 충분하다 — 거치대가 밀리는 것은 한순간이 아니라 그 뒤 계속 유지되는 상태다.
        timer = Timer.scheduledTimer(withTimeInterval: 0.25, repeats: true) { [weak self] _ in self?.tick() }
    }

    /// 로거는 닫지 않는다 — coaching.csv는 ScanCoach와 함께 쓰고, 닫는 것은 ScanCoach 몫이다.
    func stop() {
        timer?.invalidate()
        timer = nil
        driftAlert = nil
        logger = nil
    }

    /// 거치대를 다시 고정한 뒤 현재 자세를 새 기준으로 삼는다.
    func resetReference() {
        reference = nil
        startTime = session?.currentFrame?.timestamp ?? -1
        drifting = false
        driftAlert = nil
    }

    private func tick() {
        let thermal = ProcessInfo.processInfo.thermalState
        if thermal != thermalState {
            thermalState = thermal
            log(event: "thermal", detail: Self.name(of: thermal))
        }
        guard let frame = session?.currentFrame else { return }
        let t = frame.timestamp
        if lastTickTime > 0 {
            thermalSeconds[Self.name(of: thermal), default: 0] += t - lastTickTime
        }
        lastTickTime = t
        if startTime < 0 { startTime = t }

        guard case .normal = frame.camera.trackingState else { return }
        let pose = frame.camera.transform
        guard let ref = reference else {
            if t - startTime >= Self.settleSeconds {
                reference = pose
                log(event: "mount_reference", detail: "기준 자세 확정")
            }
            return
        }

        let dt = simd_distance(SIMD3(pose.columns.3.x, pose.columns.3.y, pose.columns.3.z),
                               SIMD3(ref.columns.3.x, ref.columns.3.y, ref.columns.3.z))
        let rRef = simd_float3x3(SIMD3(ref.columns.0.x, ref.columns.0.y, ref.columns.0.z),
                                 SIMD3(ref.columns.1.x, ref.columns.1.y, ref.columns.1.z),
                                 SIMD3(ref.columns.2.x, ref.columns.2.y, ref.columns.2.z))
        let rNow = simd_float3x3(SIMD3(pose.columns.0.x, pose.columns.0.y, pose.columns.0.z),
                                 SIMD3(pose.columns.1.x, pose.columns.1.y, pose.columns.1.z),
                                 SIMD3(pose.columns.2.x, pose.columns.2.y, pose.columns.2.z))
        let rel = rRef.transpose * rNow
        let trace = rel.columns.0.x + rel.columns.1.y + rel.columns.2.z
        let angle = acos(max(-1, min(1, (trace - 1) / 2))) * 180 / .pi

        currentTranslationM = dt
        currentRotationDeg = angle
        maxTranslationM = max(maxTranslationM, dt)
        maxRotationDeg = max(maxRotationDeg, angle)

        let over = dt > Self.maxTranslationM || angle > Self.maxRotationDeg
        if over && !drifting {
            drifting = true
            driftEventCount += 1
            log(event: "mount_drift", detail: String(format: "%.3fm %.1fdeg", dt, angle))
        } else if !over && drifting {
            drifting = false
            log(event: "mount_recovered", detail: String(format: "%.3fm %.1fdeg", dt, angle))
        }
        driftAlert = drifting ? String(format: "거치대가 움직였어요 (%.0fcm · %.1f°) — 다시 고정하세요", dt * 100, angle) : nil
        if drifting, t - lastHaptic >= Self.hapticInterval {
            haptic.notificationOccurred(.warning)
            lastHaptic = t
        }
    }

    private func log(event: String, detail: String) {
        let t = session?.currentFrame?.timestamp ?? 0
        logger?.write(String(format: "%.6f,%@,%@\n", t, event, detail))
    }

    static func name(of state: ProcessInfo.ThermalState) -> String {
        switch state {
        case .nominal:  return "nominal"
        case .fair:     return "fair"
        case .serious:  return "serious"
        case .critical: return "critical"
        @unknown default: return "unknown"
        }
    }
}
