import AVFoundation
import Foundation
import GoldenLinkCore
import WebRTC

/// 실제 양방향 통화(WebRTC, 2026-11-04)의 한 통화 연결 — 구급대는 offer를 만들고 병원은 answer를 만든다.
/// 마이크 음성만 주고받는다(영상 없음). 연결 협상 메시지는 hub가 중계하고(call_sessions.py), 음성은 직접 또는 TURN으로 간다.
/// 안드로이드 `Rtc.kt`(RtcSession)와 같은 규칙이다 — 그쪽이 실제 기기에서 hub와 연동 검증됐다.
///
/// 콜백(onLocalIce·onMediaReady·onFailed)은 WebRTC 스레드에서 불린다 — 호출한 쪽(PhoneModel)이 메인 액터로 옮겨 쓴다.
/// "준비 완료(onMediaReady)"는 연결(connected)과 상대 오디오 수신을 둘 다 확인했을 때 한 번만 알린다 — 병원이 받았다는
/// 사실만으로, 또는 상대가 조용하다는 이유로 통화 시작을 정하지 않는다(개발계획서 §5·§10).
///
/// iOS 대상 Xcode 빌드 확인. 실제 기기 사이의 음성 송수신은 별도 검증이 필요하다.
final class RtcSession: NSObject, RTCPeerConnectionDelegate, @unchecked Sendable {
    private let onLocalIce: @Sendable (IceCandidatePayload) -> Void
    private let onMediaReady: @Sendable () -> Void
    private let onFailed: @Sendable (String) -> Void

    private var factory: RTCPeerConnectionFactory?
    private var pc: RTCPeerConnection?
    private var source: RTCAudioSource?
    private var track: RTCAudioTrack?

    private let lock = NSLock()
    private var closed = false
    private var remoteSet = false
    private var pendingIce: [RTCIceCandidate] = []
    private var connected = false
    private var remoteAudio = false
    private var readyAnnounced = false

    init(iceServers: [IceServerConfig],
         onLocalIce: @escaping @Sendable (IceCandidatePayload) -> Void,
         onMediaReady: @escaping @Sendable () -> Void,
         onFailed: @escaping @Sendable (String) -> Void) throws {
        self.onLocalIce = onLocalIce
        self.onMediaReady = onMediaReady
        self.onFailed = onFailed
        super.init()

        // 통화용 오디오 세션: 마이크+수화부(전화기처럼), 에코 제거(voiceChat). WebRTC 기본 설정은 스피커 우선이라 바꾼다
        let audioConfig = RTCAudioSessionConfiguration.webRTC()
        audioConfig.category = AVAudioSession.Category.playAndRecord.rawValue
        audioConfig.mode = AVAudioSession.Mode.voiceChat.rawValue
        audioConfig.categoryOptions = [.allowBluetooth]
        RTCAudioSessionConfiguration.setWebRTC(audioConfig)

        let factory = RTCPeerConnectionFactory()
        self.factory = factory
        let config = RTCConfiguration()
        config.iceServers = iceServers.filter { !$0.urls.isEmpty }.map {
            RTCIceServer(urlStrings: $0.urls, username: $0.username, credential: $0.credential)
        }
        config.sdpSemantics = .unifiedPlan
        config.continualGatheringPolicy = .gatherContinually
        let constraints = RTCMediaConstraints(mandatoryConstraints: nil, optionalConstraints: nil)
        guard let connection = factory.peerConnection(with: config, constraints: constraints, delegate: self) else {
            throw NSError(domain: "RtcSession", code: 1, userInfo: [NSLocalizedDescriptionKey: "PeerConnection을 만들지 못했습니다"])
        }
        pc = connection
        let audioSource = factory.audioSource(with: RTCMediaConstraints(mandatoryConstraints: nil, optionalConstraints: nil))
        source = audioSource
        let audioTrack = factory.audioTrack(with: audioSource, trackId: "audio0")
        track = audioTrack
        connection.add(audioTrack, streamIds: ["stream0"])
    }

    /// offer를 만들어 로컬 설명으로 적용한 뒤 돌려준다
    func createOffer(_ completion: @escaping @Sendable (String) -> Void) {
        guard let connection = pc else { return }
        let constraints = RTCMediaConstraints(mandatoryConstraints: ["OfferToReceiveAudio": "true"], optionalConstraints: nil)
        connection.offer(for: constraints) { [weak self] description, error in
            guard let self, let description, error == nil else { self?.fail("offer 생성 실패: \(error?.localizedDescription ?? "")"); return }
            connection.setLocalDescription(description) { [weak self] error in
                if let error { self?.fail("offer 적용 실패: \(error.localizedDescription)"); return }
                completion(description.sdp)
            }
        }
    }

    /// 병원의 answer를 적용한다
    func applyAnswer(_ sdp: String) {
        pc?.setRemoteDescription(RTCSessionDescription(type: .answer, sdp: sdp)) { [weak self] error in
            if let error { self?.fail("answer 적용 실패: \(error.localizedDescription)"); return }
            self?.remoteDescriptionApplied()
        }
    }

    /// 병원 모드: 구급대 offer를 적용하고 answer를 만든다.
    func acceptOffer(_ sdp: String, completion: @escaping @Sendable (String) -> Void) {
        guard let connection = pc else { return }
        connection.setRemoteDescription(RTCSessionDescription(type: .offer, sdp: sdp)) { [weak self] error in
            guard let self else { return }
            if let error { self.fail("offer 적용 실패: \(error.localizedDescription)"); return }
            self.remoteDescriptionApplied()
            connection.answer(for: RTCMediaConstraints(mandatoryConstraints: nil, optionalConstraints: nil)) { [weak self] answer, error in
                guard let answer, error == nil else { self?.fail("answer 생성 실패"); return }
                connection.setLocalDescription(answer) { [weak self] error in
                    if let error { self?.fail("answer 적용 실패: \(error.localizedDescription)"); return }
                    completion(answer.sdp)
                }
            }
        }
    }

    /// 상대의 ICE 후보. 상대 설명을 적용하기 전에 온 것은 모아 두었다가 적용 뒤 한꺼번에 넣는다
    func addRemoteIce(_ payload: IceCandidatePayload) {
        let candidate = RTCIceCandidate(sdp: payload.candidate, sdpMLineIndex: Int32(payload.sdpMLineIndex), sdpMid: payload.sdpMid)
        lock.lock(); defer { lock.unlock() }
        if closed { return }
        if remoteSet { pc?.add(candidate) { _ in } } else { pendingIce.append(candidate) }
    }

    private func remoteDescriptionApplied() {
        lock.lock(); defer { lock.unlock() }
        remoteSet = true
        for candidate in pendingIce { pc?.add(candidate) { _ in } }
        pendingIce.removeAll()
    }

    func setMicMuted(_ muted: Bool) { track?.isEnabled = !muted }

    /// 마이크·연결·오디오를 모두 정리한다. 여러 번 불러도 한 번만 처리한다. 가장 먼저 마이크 트랙을 끈다
    func close() {
        lock.lock()
        if closed { lock.unlock(); return }
        closed = true
        lock.unlock()
        track?.isEnabled = false
        pc?.close()
        pc = nil; track = nil; source = nil; factory = nil
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    private func fail(_ reason: String) {
        lock.lock(); let isClosed = closed; lock.unlock()
        if !isClosed { onFailed(reason) }
    }

    private func announceReadyIfNeeded() {
        lock.lock()
        let fire = !closed && !readyAnnounced && connected && remoteAudio
        if fire { readyAnnounced = true }
        lock.unlock()
        if fire { onMediaReady() }
    }

    // MARK: - RTCPeerConnectionDelegate

    func peerConnection(_ peerConnection: RTCPeerConnection, didGenerate candidate: RTCIceCandidate) {
        lock.lock(); let isClosed = closed; lock.unlock()
        if isClosed { return }
        onLocalIce(IceCandidatePayload(sdpMid: candidate.sdpMid, sdpMLineIndex: Int(candidate.sdpMLineIndex), candidate: candidate.sdp))
    }

    func peerConnection(_ peerConnection: RTCPeerConnection, didChange newState: RTCPeerConnectionState) {
        switch newState {
        case .connected:
            lock.lock(); connected = true; lock.unlock()
            announceReadyIfNeeded()
        case .failed:
            fail("connection_failed")
        default:
            break  // disconnected는 일시적일 수 있다 — hub의 유예·종료 규칙에 맡긴다
        }
    }

    func peerConnection(_ peerConnection: RTCPeerConnection, didAdd rtpReceiver: RTCRtpReceiver, streams mediaStreams: [RTCMediaStream]) {
        if rtpReceiver.track?.kind == "audio" {
            lock.lock(); remoteAudio = true; lock.unlock()
            announceReadyIfNeeded()
        }
    }

    func peerConnection(_ peerConnection: RTCPeerConnection, didChange stateChanged: RTCSignalingState) {}
    func peerConnection(_ peerConnection: RTCPeerConnection, didAdd stream: RTCMediaStream) {}
    func peerConnection(_ peerConnection: RTCPeerConnection, didRemove stream: RTCMediaStream) {}
    func peerConnectionShouldNegotiate(_ peerConnection: RTCPeerConnection) {}
    func peerConnection(_ peerConnection: RTCPeerConnection, didChange newState: RTCIceConnectionState) {}
    func peerConnection(_ peerConnection: RTCPeerConnection, didChange newState: RTCIceGatheringState) {}
    func peerConnection(_ peerConnection: RTCPeerConnection, didRemove candidates: [RTCIceCandidate]) {}
    func peerConnection(_ peerConnection: RTCPeerConnection, didOpen dataChannel: RTCDataChannel) {}
}
