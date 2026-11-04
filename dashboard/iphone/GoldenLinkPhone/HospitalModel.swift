import AVFoundation
import AudioToolbox
import Foundation
import GoldenLinkCore
import Observation

/// H-접근 코드의 병원 수신 기기. 통화 규칙은 hub가 결정하고 음성은 WebRTC가 처리한다.
@MainActor @Observable
final class HospitalModel {
    enum Phase { case incoming, connecting, active }
    struct Call {
        let id: String
        let ambulanceName: String
        var phase: Phase = .incoming
        var startedAt: Date?
    }
    var connection: HubSocket.State = .connecting
    var hospitalName: String?
    var call: Call?
    var notice: String?
    var accepting = false
    var muted = false
    var speaker = false
    private var socket: HubSocket?
    private var rtc: RtcSession?
    private var iceServers: [IceServerConfig] = []
    private var negotiation = 1
    private var pendingIce: [RtcIceIn] = []
    private var ringer: Task<Void, Never>?

    func start() {
        stop()
        guard let id = Settings.hospitalID else { return }
        socket = HubSocket(role: "hospital", id: id, callCapable: true,
            onMessage: { [weak self] type, data in self?.handle(type, data) },
            onState: { [weak self] state in
                guard let self else { return }
                let becameLive = state == .live && self.connection != .live
                self.connection = state
                if becameLive { _ = self.socket?.send(CallStateSyncMessage(callId: self.call?.id)) }
            })
    }

    func stop() {
        if let call { _ = socket?.send(CallHangupMessage(callId: call.id)) }
        endLocal()
        socket?.close(); socket = nil
        connection = .connecting
        hospitalName = nil
    }

    private func handle(_ type: String, _ data: Data) {
        let decoder = JSONDecoder()
        switch type {
        case "identity_info":
            hospitalName = (try? decoder.decode(IdentityInfo.self, from: data))?.name
        case "call_incoming":
            guard let incoming = try? decoder.decode(CallIncoming.self, from: data), incoming.hospitalId == Settings.hospitalID else { return }
            if let call {
                if call.id != incoming.callId { _ = socket?.send(CallRejectMessage(callId: incoming.callId)) }
                return
            }
            iceServers = incoming.iceServers
            notice = nil
            call = Call(id: incoming.callId, ambulanceName: incoming.ambulanceName ?? "구급대")
            ringer = Task { @MainActor [weak self] in
                while !Task.isCancelled {
                    guard self?.call?.phase == .incoming else { return }
                    AudioServicesPlayAlertSound(1007)
                    do { try await Task.sleep(for: .seconds(3)) } catch { return }
                }
            }
        case "call_state":
            guard let state = try? decoder.decode(CallState.self, from: data) else { return }
            guard state.callId == call?.id else {
                // 앱 재시작으로 음성 연결을 잃은 세션을 병원 busy 상태로 남기지 않는다.
                if state.state == "active" || state.state == "connecting" { _ = socket?.send(CallHangupMessage(callId: state.callId)) }
                return
            }
            switch state.state {
            case "ended": endLocal(); notice = CallLabels.endText(state.reason, detail: state.detail)
            case "connecting":
                stopRinging()
                if let servers = state.iceServers { iceServers = servers }
                call?.phase = .connecting
            case "active":
                stopRinging()
                call?.phase = .active
                if call?.startedAt == nil { call?.startedAt = Date() }
            default: break
            }
        case "rtc_offer":
            guard let offer = try? decoder.decode(RtcSdpIn.self, from: data), offer.callId == call?.id,
                  call?.phase != .incoming else { return }
            answer(offer)
        case "rtc_ice":
            guard let ice = try? decoder.decode(RtcIceIn.self, from: data), ice.callId == call?.id else { return }
            if let rtc {
                if (ice.negotiationRevision ?? 1) == negotiation { rtc.addRemoteIce(ice.candidate) }
            } else if pendingIce.count < 256 { pendingIce.append(ice) }
        case "call_error":
            guard let error = try? decoder.decode(CallError.self, from: data), error.callId == call?.id else { return }
            endLocal(); notice = "이미 종료됐거나 처리할 수 없는 전화입니다"
        default: break
        }
    }

    func accept() async {
        guard let incoming = call, incoming.phase == .incoming, !accepting else { return }
        accepting = true
        let granted = await AVAudioApplication.requestRecordPermission()
        // 권한 팝업 중 취소/종료/새 전화가 왔다면 이전 받기를 실행하지 않는다.
        guard call?.id == incoming.id, call?.phase == .incoming else { accepting = false; return }
        accepting = false
        guard granted else { notice = "전화 받기에 마이크 권한이 필요합니다. iPhone 설정에서 허용해 주세요."; return }
        guard connection == .live, socket?.send(CallAcceptMessage(callId: incoming.id, deviceId: Settings.deviceID)) == true else {
            notice = "서버 연결을 확인해 주세요"; return
        }
        stopRinging()
        call?.phase = .connecting
    }

    func reject() {
        guard let call, call.phase == .incoming else { return }
        _ = socket?.send(CallRejectMessage(callId: call.id))
        endLocal(); notice = "수신을 거절했습니다"
    }

    func hangup() {
        guard let call else { return }
        _ = socket?.send(CallHangupMessage(callId: call.id))
        endLocal(); notice = "통화를 종료했습니다"
    }

    func toggleMute() { muted.toggle(); rtc?.setMicMuted(muted) }
    func toggleSpeaker() {
        do {
            try AVAudioSession.sharedInstance().overrideOutputAudioPort(speaker ? .none : .speaker)
            speaker.toggle()
        } catch { notice = "오디오 출력을 변경하지 못했습니다" }
    }

    private func answer(_ offer: RtcSdpIn) {
        let id = offer.callId
        let revision = offer.negotiationRevision ?? 1
        if rtc != nil && revision <= negotiation { return }
        negotiation = revision
        rtc?.close()
        do {
            let session = try RtcSession(iceServers: iceServers,
                onLocalIce: { [weak self] candidate in Task { @MainActor in
                    guard let self, self.call?.id == id, self.negotiation == revision else { return }
                    _ = self.socket?.send(RtcIceMessage(callId: id, candidate: candidate, negotiationRevision: revision))
                } },
                onMediaReady: { [weak self] in Task { @MainActor in
                    guard let self, self.call?.id == id, self.negotiation == revision else { return }
                    _ = self.socket?.send(MediaReadyMessage(callId: id))
                } },
                onFailed: { [weak self] _ in Task { @MainActor in
                    guard let self, self.call?.id == id, self.negotiation == revision else { return }
                    self.hangup(); self.notice = "통화 연결에 실패했습니다"
                } })
            rtc = session
            for ice in pendingIce where (ice.negotiationRevision ?? 1) == revision { session.addRemoteIce(ice.candidate) }
            pendingIce.removeAll()
            session.acceptOffer(offer.sdp) { [weak self] sdp in Task { @MainActor in
                guard let self, self.call?.id == id, self.negotiation == revision else { return }
                _ = self.socket?.send(RtcSdpMessage(type: "rtc_answer", callId: id, sdp: sdp, negotiationRevision: revision))
            } }
        } catch { hangup(); notice = "통화 연결을 준비하지 못했습니다" }
    }

    private func stopRinging() { ringer?.cancel(); ringer = nil }
    private func endLocal() {
        stopRinging()
        rtc?.close(); rtc = nil
        call = nil; pendingIce.removeAll(); iceServers = []
        negotiation = 1; muted = false; speaker = false; accepting = false
    }
}
