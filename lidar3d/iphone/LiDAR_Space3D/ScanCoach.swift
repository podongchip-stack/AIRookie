import Foundation
import ARKit
import AVFoundation
import Combine
import UIKit
import simd

/// 실시간 스캔 코칭. "촬영이 조금만 빨라도 등록률이 20%대로 떨어지던" 문제를
/// 후처리가 아니라 **촬영 단계에서 사전 차단**하는 장치다.
///
/// 설계 원칙 — 햅틱 우선:
/// 구조대원은 화면을 계속 주시할 수 없다. 한 손에 폰, 시선은 현장에 있다. 그래서 경고의
/// 1순위는 진동, 2순위는 화면 테두리 색, 음성은 기본 OFF다.
/// (음성을 기본 OFF로 둔 이유: 응급현장에서 폰이 말을 하면 무전 교신과 겹쳐 소음이 된다.
///  필요하면 UI에서 켤 수 있다.)
///
/// 왜 ARSessionDelegate를 쓰지 않고 CADisplayLink로 폴링하는가:
/// ARSession의 delegate는 **하나뿐**이고 그건 ARCaptureManager가 데이터 기록용으로 쓰고 있다.
/// 코칭이 delegate를 뺏으면 기록이 멈춘다. session.currentFrame을 12Hz로 읽으면 서로 간섭이
/// 전혀 없다. (같은 이유로 코칭은 ARFrame을 절대 보관하지 않는다 — 붙잡으면 ARKit의 프레임
/// 풀이 고갈되어 세션이 통째로 멎는다.)
///
/// 실패 시 확인할 것:
/// - 경고가 전혀 안 뜸      -> isActive 플래그, thresholds.enabled, 그리고 warmupSec(초반 5초는 무시)
/// - 경고가 쉴 새 없이 깜빡임 -> debounce 상수(아래 hold/clear 값)를 키울 것
/// - 진동이 안 옴           -> 저전력 모드에서는 iOS가 햅틱을 무시한다. 기기 설정 확인
final class ScanCoach: NSObject, ObservableObject {

    // MARK: 경고 모델

    struct Alert: Equatable {
        enum Severity { case caution, critical }
        enum Code: String {
            case trackingLost        // 트래킹 손실/제한
            case moveSlower          // 너무 빠르게 이동
            case rotateSlower        // 너무 빠르게 회전
            case lowLight            // 조명 부족
            case tooClose            // 너무 가까움
        }
        var severity: Severity
        var code: Code

        var message: String {
            switch code {
            case .trackingLost:  return "잠시 멈추세요 — 위치 추적 불안정"
            case .moveSlower:    return "천천히 이동하세요"
            case .rotateSlower:  return "천천히 돌리세요"
            case .lowLight:      return "조명이 부족합니다"
            case .tooClose:      return "조금 물러서세요"
            }
        }
    }

    /// 임계값. 상수를 코드에 박지 않고 한곳에 모아 실측 후 조정할 수 있게 한다.
    /// 기본값은 CedarScan이 실제 스캔 세션에서 얻은 값을 출발점으로 삼았다.
    struct Thresholds {
        var enabled = true
        var maxSpeedSoft: Double = 0.7      // m/s — 이 이상이면 주의
        var maxSpeedHard: Double = 1.0      // m/s — 이 이상이면 심각
        var maxRotationSoft: Double = 60    // deg/s
        var maxRotationHard: Double = 100   // deg/s
        var lowLightSoft: Double = 250      // ambientIntensity (1000이 Apple 기준 중립)
        var trackingWarnAfterSec: Double = 1.0
        var warmupSec: Double = 5.0         // 초반 N초는 VIO 초기화 중이라 무시
        /// LiDAR는 25~30cm 아래에서 정확도가 급격히 떨어진다. 벽에 바짝 붙으면 메시에 구멍이 난다.
        var tooCloseMeters: Float = 0.35
    }

    @Published private(set) var alert: Alert?
    /// UI 토글. 기본: 햅틱 ON, 음성 OFF.
    /// @Published인 이유: SwiftUI Toggle이 바인딩으로 읽는데, 일반 var이면 값을 바꿔도
    /// 뷰가 다시 그려지지 않아 **스위치가 눌린 채로 돌아오지 않는다.**
    /// 앱을 껐다 켜도 유지된다 (SessionManager의 촬영 옵션과 같은 이유).
    @Published var hapticsEnabled = ScanCoach.pref("coachHaptics", default: true) {
        didSet { UserDefaults.standard.set(hapticsEnabled, forKey: "opt.coachHaptics") }
    }
    @Published var voiceEnabled = ScanCoach.pref("coachVoice", default: false) {
        didSet { UserDefaults.standard.set(voiceEnabled, forKey: "opt.coachVoice") }
    }

    private static func pref(_ key: String, default fallback: Bool) -> Bool {
        let full = "opt.\(key)"
        guard UserDefaults.standard.object(forKey: full) != nil else { return fallback }
        return UserDefaults.standard.bool(forKey: full)
    }
    var thresholds = Thresholds()
    /// 뎁스가 실제로 켜진 세션에서만 "너무 가까움"을 판단한다.
    /// frame.sceneDepth != nil로 암묵 추론하지 않는 이유: 나중에 다른 캡처 모드를 추가하는 사람이
    /// 아무도 선택하지 않은 동작을 조용히 물려받게 된다. 플래그로 명시한다.
    var tooCloseEnabled = false

    private weak var session: ARSession?
    private var displayLink: CADisplayLink?
    private var logger: CSVLogger?
    private var isActive = false

    // 속도 계산용 포즈 슬라이딩 윈도우. 프레임 간 차분은 노이즈가 너무 커서 반드시 평균이 필요하다.
    private struct PoseSample { var t: TimeInterval; var pos: SIMD3<Float>; var quat: simd_quatf }
    private var poses: [PoseSample] = []

    private var sessionStartTime: TimeInterval = -1
    private var overspeedSince: TimeInterval = -1
    private var overRotationSince: TimeInterval = -1
    private var lowLightSince: TimeInterval = -1
    private var limitedSince: TimeInterval = -1
    private var tooCloseSince: TimeInterval = -1
    private var alertRaisedAt: TimeInterval = -1
    private var allClearSince: TimeInterval = -1

    private let cautionHaptic = UIImpactFeedbackGenerator(style: .medium)
    private let criticalHaptic = UINotificationFeedbackGenerator()
    private var speech: AVSpeechSynthesizerBox?

    private(set) var eventCount = 0

    init(session: ARSession) {
        self.session = session
        super.init()
    }

    // MARK: 생명주기

    /// - Parameter logger: coaching.csv. 사후에 "어느 구간에서 촬영이 불안정했는지"를
    ///   메시 품질과 대조하기 위한 기록이다. nil이면 경고는 뜨되 기록만 안 한다.
    func start(logger: CSVLogger?) {
        self.logger = logger
        eventCount = 0
        guard thresholds.enabled, displayLink == nil else { return }
        let link = CADisplayLink(target: self, selector: #selector(tick))
        // 12Hz면 충분하다. 60Hz로 돌리면 배터리만 먹고 판단은 더 정확해지지 않는다
        // (어차피 0.6초 윈도우로 평균을 내기 때문에).
        link.preferredFrameRateRange = CAFrameRateRange(minimum: 8, maximum: 15, preferred: 12)
        link.add(to: .main, forMode: .common)
        displayLink = link
        cautionHaptic.prepare()
        criticalHaptic.prepare()
    }

    func stop() {
        displayLink?.invalidate()
        displayLink = nil
        alert = nil
        isActive = false
        logger?.close()
        logger = nil
        poses.removeAll()
        sessionStartTime = -1
    }

    /// 실제로 녹화 중일 때만 true. 대기 화면에서 경고를 울리면 성가시기만 하다.
    func setActive(_ active: Bool) {
        isActive = active
        if !active { alert = nil; poses.removeAll() }
    }

    // MARK: 메인 루프 (12Hz, 읽기만 — ARFrame을 보관하지 않는다)

    @objc private func tick() {
        guard let frame = session?.currentFrame else { return }
        let t = frame.timestamp
        let camera = frame.camera
        let transform = camera.transform
        let pos = SIMD3(transform.columns.3.x, transform.columns.3.y, transform.columns.3.z)
        let rot = simd_float3x3(
            simd_normalize(SIMD3(transform.columns.0.x, transform.columns.0.y, transform.columns.0.z)),
            simd_normalize(SIMD3(transform.columns.1.x, transform.columns.1.y, transform.columns.1.z)),
            simd_normalize(SIMD3(transform.columns.2.x, transform.columns.2.y, transform.columns.2.z))
        )
        guard pos.x.isFinite, pos.y.isFinite, pos.z.isFinite else { return }
        let quat = simd_quatf(rot)
        let light = frame.lightEstimate.map { Double($0.ambientIntensity) }

        if sessionStartTime < 0 { sessionStartTime = t }
        let warmedUp = (t - sessionStartTime) > thresholds.warmupSec

        // ARKit이 relocalize에 성공하면 카메라 위치가 순간적으로 점프한다. 그대로 미분하면
        // 실제로는 가만히 있었는데도 "초속 5m"라는 가짜 스파이크가 나와 헛경고가 뜬다.
        // 물리적으로 불가능한 속도가 보이면 윈도우를 통째로 버린다.
        if let last = poses.last {
            let dt = t - last.t
            if dt > 0, simd_distance(pos, last.pos) / Float(dt) > 3 {
                poses.removeAll(keepingCapacity: true)
            }
        }
        poses.append(PoseSample(t: t, pos: pos, quat: quat))
        while let first = poses.first, t - first.t > 0.6 { poses.removeFirst() }

        var speed: Float = 0
        var rotationDps: Float = 0
        if let first = poses.first, t - first.t >= 0.25 {
            let span = Float(t - first.t)
            speed = simd_distance(pos, first.pos) / span
            let dq = first.quat.inverse * quat
            var angle = abs(dq.angle)
            if angle > .pi { angle = 2 * .pi - angle }
            rotationDps = angle * 180 / .pi / span
        }

        // .initializing은 정상적인 시작 과정이므로 경고하지 않는다.
        let trackingLimited: Bool
        switch camera.trackingState {
        case .limited(let reason): trackingLimited = reason != .initializing
        case .notAvailable:        trackingLimited = warmedUp
        case .normal:              trackingLimited = false
        }

        guard isActive else { return }

        latch(&overspeedSince,    Double(speed) > thresholds.maxSpeedSoft, t)
        latch(&overRotationSince, Double(rotationDps) > thresholds.maxRotationSoft, t)
        latch(&lowLightSince,     (light ?? .greatestFiniteMagnitude) < thresholds.lowLightSoft, t)
        latch(&limitedSince,      trackingLimited, t)

        // 코칭이 꺼져 있으면 CVPixelBuffer를 잠글 이유가 없다 (틱마다 비용이 든다).
        let frontDepth: Float = tooCloseEnabled
            ? (Self.centerDepth(of: frame) ?? .greatestFiniteMagnitude)
            : .greatestFiniteMagnitude
        latch(&tooCloseSince, frontDepth < thresholds.tooCloseMeters, t)

        resolve(now: t, speed: speed, rotationDps: rotationDps)
    }

    /// 조건이 "언제부터" 참이었는지만 기억한다. 순간값으로 경고를 띄우면 미친 듯이 깜빡인다.
    private func latch(_ since: inout TimeInterval, _ active: Bool, _ now: TimeInterval) {
        if active { if since < 0 { since = now } } else { since = -1 }
    }

    /// 카메라 정면 거리(m) — 뎁스맵 중심 주변 5점의 중앙값.
    /// 평균이 아니라 중앙값인 이유: 유리/반사면에서 한두 점이 0이나 튄 값으로 나와도
    /// 경고가 오작동하지 않게 하려는 것이다.
    private static func centerDepth(of frame: ARFrame) -> Float? {
        guard let depth = frame.sceneDepth?.depthMap,
              CVPixelBufferGetPixelFormatType(depth) == kCVPixelFormatType_DepthFloat32
        else { return nil }
        CVPixelBufferLockBaseAddress(depth, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(depth, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddress(depth) else { return nil }
        let w = CVPixelBufferGetWidth(depth), h = CVPixelBufferGetHeight(depth)
        let rowBytes = CVPixelBufferGetBytesPerRow(depth)
        guard w >= 4, h >= 4 else { return nil }

        let points = [(w/2, h/2), (w/4, h/2), (3*w/4, h/2), (w/2, h/4), (w/2, 3*h/4)]
        var samples: [Float] = []
        for (x, y) in points {
            let v = base.advanced(by: y * rowBytes + x * 4)
                .assumingMemoryBound(to: Float32.self).pointee
            if v.isFinite && v > 0 { samples.append(v) }
        }
        guard samples.count >= 3 else { return nil }
        return samples.sorted()[samples.count / 2]
    }

    // MARK: 경고 선택 — 우선순위를 두고 한 번에 하나만 띄운다

    private func resolve(now: TimeInterval, speed: Float, rotationDps: Float) {
        var candidate: Alert?

        // 우선순위: 트래킹 손실 > 너무 가까움 > 이동속도 > 회전속도 > 조명
        // 트래킹 손실이 1순위인 이유: 나머지는 품질이 나빠지는 것이지만, 트래킹이 끊기면
        // 그 시점부터의 데이터가 **다른 좌표계**에 쌓여 메시가 두 조각으로 갈라진다.
        if limitedSince > 0, now - limitedSince > thresholds.trackingWarnAfterSec {
            candidate = Alert(severity: .critical, code: .trackingLost)
        } else if tooCloseSince > 0, now - tooCloseSince > 0.7,
                  Double(speed) <= thresholds.maxSpeedHard,
                  Double(rotationDps) <= thresholds.maxRotationHard {
            // 속도/회전이 심각 수준이면 아래 critical에 자리를 양보한다
            // (벽에 바짝 붙어 빠르게 훑는 건 두 경고 모두의 최악 케이스다).
            candidate = Alert(severity: .caution, code: .tooClose)
        } else if overspeedSince > 0, now - overspeedSince > 0.5 {
            candidate = Alert(severity: Double(speed) > thresholds.maxSpeedHard ? .critical : .caution,
                              code: .moveSlower)
        } else if overRotationSince > 0, now - overRotationSince > 0.5 {
            candidate = Alert(severity: Double(rotationDps) > thresholds.maxRotationHard ? .critical : .caution,
                              code: .rotateSlower)
        } else if lowLightSince > 0, now - lowLightSince > 1.0 {
            candidate = Alert(severity: .caution, code: .lowLight)
        }

        if let candidate {
            allClearSince = -1
            guard alert != candidate else { return }
            // 현재 경고를 최소 1.5초는 유지한다 (더 심각한 것이 오면 예외).
            // 이게 없으면 두 조건이 번갈아 참이 될 때 글자가 미친 듯이 바뀌어 읽을 수가 없다.
            if let current = alert, now - alertRaisedAt < 1.5,
               !(candidate.severity == .critical && current.severity == .caution) {
                return
            }
            let isNew = (alert == nil) || (alert?.severity == .caution && candidate.severity == .critical)
            alert = candidate
            alertRaisedAt = now
            log(candidate, at: now, speed: speed, rotationDps: rotationDps)
            if isNew { fireFeedback(candidate, now: now) }
        } else if alert != nil {
            // 즉시 끄지 않고 1초 잠잠한 뒤에 내린다 (경계선에서 깜빡이는 것 방지).
            if allClearSince < 0 {
                allClearSince = now
            } else if now - allClearSince > 1.0, now - alertRaisedAt > 1.5 {
                logRaw(now, "clear", "")
                alert = nil
                allClearSince = -1
            }
        }
    }

    private func fireFeedback(_ alert: Alert, now: TimeInterval) {
        if hapticsEnabled {
            switch alert.severity {
            case .caution:  cautionHaptic.impactOccurred()
            case .critical: criticalHaptic.notificationOccurred(.warning)
            }
        }
        if voiceEnabled {
            speech = speech ?? AVSpeechSynthesizerBox()
            speech?.speak(alert.message, notBefore: 5.0, now: now)
        }
    }

    // MARK: coaching.csv

    private func log(_ alert: Alert, at t: TimeInterval, speed: Float, rotationDps: Float) {
        let detail = String(format: "severity=%@;speed_mps=%.2f;rot_dps=%.1f",
                            alert.severity == .critical ? "critical" : "caution",
                            Double(speed), Double(rotationDps))
        logRaw(t, alert.code.rawValue, detail)
    }

    private func logRaw(_ t: TimeInterval, _ type: String, _ detail: String) {
        // timestamp는 ARFrame.timestamp 원본. arkit_pose.csv와 **같은 시계**라서
        // 별도 보정 없이 그대로 조인된다 (불변식 1번).
        logger?.write(String(format: "%.6f,%@,%@\n", t, type, detail))
        eventCount += 1
    }

    static let coachingCSVHeader = "timestamp,event_type,detail"
}

/// AVSpeechSynthesizer를 감싸 "최근 N초 안에는 다시 말하지 않기"만 담당한다.
/// 별도 타입으로 뺀 이유: 음성은 기본 OFF라 대부분의 세션에서 아예 생성되지 않아야 한다
/// (AVSpeechSynthesizer는 초기화만으로도 오디오 세션을 건드린다).
final class AVSpeechSynthesizerBox {
    private let synthesizer = AVSpeechSynthesizer()
    private var lastSpokenAt: TimeInterval = -1000

    func speak(_ text: String, notBefore interval: TimeInterval, now: TimeInterval) {
        guard now - lastSpokenAt > interval else { return }
        lastSpokenAt = now
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = AVSpeechSynthesisVoice(language: "ko-KR")
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate
        synthesizer.speak(utterance)
    }
}
