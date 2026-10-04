import Foundation
import GoldenLinkCore
import Observation

/// 웹 전화 앱(dashboard/src/app/phone/page.tsx + PhoneCallView.tsx)의 상태와 규칙.
/// 휴대폰은 전화만 한다 — 출동·현장 종료·이송 승인은 태블릿/PC 대시보드에서 한다. 사건(caseId)도 만들지 않고
/// hub 출동 상태(ambulance_phase.caseId)를 그대로 쓴다.
@MainActor
@Observable
final class PhoneModel {
    // 연결
    var connection: HubSocket.State = .connecting
    var apid: String?  // 지금 보는 구급차. 자동 전환 모드면 바뀐다
    var identity: IdentityInfo?

    // hub가 알려 준 상태
    var sims: [String: AmbulanceSim] = [:]
    var scenes: [String: SceneCandidates] = [:]
    var callStatus: [String: CallStatus] = [:]
    var hubTranscripts: [String: [CallTranscriptLine]] = [:]
    var sentCount: [String: Int] = [:]  // 매칭 결과의 후보 병원 수

    // 이 기기의 통화
    var call: LocalCall?
    var session: CallSession?
    var error: String?
    var modelStatus = "모델 확인 중…"
    var tick = 0  // 화면 갱신용(통화 시간·레벨)

    struct LocalCall {
        let caseId: String
        let hospitalId: String
        let hospitalName: String
        var phase: Phase
        var startedAt: Date
        var endedAt: Date?
        enum Phase { case connecting, inCall, ended }
    }

    let models = ModelStore()
    private var monitor: HubSocket?
    private var ambulance: HubSocket?

    var autoFollow: Bool { Settings.apid.lowercased() == "auto" }

    func start() {
        stop()
        if autoFollow {
            monitor = HubSocket(role: "monitor", id: "phone-auto", onMessage: { [weak self] t, d in self?.handle(t, d, fromMonitor: true) },
                                onState: { [weak self] s in if self?.ambulance == nil { self?.connection = s } })
        } else {
            follow(Settings.apid)
        }
        if Settings.onDevice {
            Task {
                let error = await models.load()
                modelStatus = error.map { "온디바이스 모델 없음: \($0)" } ?? "온디바이스 STT·MF_BERT 준비됨"
            }
        } else {
            modelStatus = "서버 STT 모드(음성을 hub로 보냄)"
        }
    }

    func stop() {
        monitor?.close(); monitor = nil
        ambulance?.close(); ambulance = nil
        apid = nil
    }

    private func follow(_ newApid: String?) {
        guard newApid != apid else { return }
        ambulance?.close()
        ambulance = nil
        apid = newApid
        identity = nil
        guard let newApid else { return }
        ambulance = HubSocket(role: "ambulance", id: newApid, onMessage: { [weak self] t, d in self?.handle(t, d, fromMonitor: false) },
                              onState: { [weak self] s in self?.connection = s })
    }

    // MARK: - 화면이 쓰는 값

    var mySim: AmbulanceSim? { apid.flatMap { sims[$0] } }
    var simOn: Bool { identity?.simDispatch == true }
    var caseId: String? { simOn ? mySim?.caseId : nil }
    var scene: SceneCandidates? { caseId.flatMap { scenes[$0] } }
    var status: CallStatus? { caseId.flatMap { callStatus[$0] } }
    var onScene: Bool { simOn && mySim?.phase == .on_scene && caseId != nil }

    /// 자막: 온디바이스면 기기에서 인식한 줄, 서버 STT면 hub가 되돌려 준 줄
    var transcriptLines: [String] {
        if let session, Settings.onDevice { return session.lines.map(\.text) }
        return caseId.flatMap { hubTranscripts[$0] }?.map(\.text) ?? []
    }

    // MARK: - hub 메시지

    private func handle(_ type: String, _ data: Data, fromMonitor: Bool) {
        let dec = JSONDecoder()
        switch type {
        case "identity_info" where !fromMonitor:
            identity = try? dec.decode(IdentityInfo.self, from: data)
        case "ambulance_phase", "ambulance_position":
            guard let sim = try? dec.decode(AmbulanceSim.self, from: data) else { return }
            sims[sim.apid] = sim
            if fromMonitor { autoSwitch() }
        case "scene_candidates" where !fromMonitor:
            if let s = try? dec.decode(SceneCandidates.self, from: data) { scenes[s.caseId] = s }
        case "call_status" where !fromMonitor:
            if let s = try? dec.decode(CallStatus.self, from: data) { callStatus[s.caseId] = s }
        case "call_transcript" where !fromMonitor:
            if let l = try? dec.decode(CallTranscriptLine.self, from: data), let c = l.caseId { hubTranscripts[c, default: []].append(l) }
        case "match_result" where !fromMonitor:
            if let m = try? dec.decode(MatchResult.self, from: data) { sentCount[m.caseId] = m.hospitals.count }
        case "case_closed":
            if let c = try? dec.decode(CaseClosed.self, from: data) { forget(c.caseId) }
        case "case_sync" where !fromMonitor:
            if let s = try? dec.decode(CaseSync.self, from: data) {
                for id in Set(scenes.keys).union(sentCount.keys).subtracting(s.caseIds) { forget(id) }
            }
        default:
            break  // 모르는 type은 버린다
        }
    }

    private func forget(_ caseId: String) {
        scenes[caseId] = nil; callStatus[caseId] = nil; hubTranscripts[caseId] = nil; sentCount[caseId] = nil
        if call?.caseId == caseId, session == nil || call?.phase == .ended { call = nil; session = nil }
    }

    /// 웹 PhoneAutoFollow와 같은 규칙: 사건이 진행 중인 구급차로 넘어가되, 지금 보는 구급차의 사건이 진행 중이면 넘어가지 않는다
    private func autoSwitch() {
        func active(_ s: AmbulanceSim?) -> Bool { s?.caseId != nil && s?.phase != .idle && s?.phase != .returning }
        if let apid, active(sims[apid]) { return }
        if call != nil && call?.phase != .ended { return }  // 통화 중 화면 전환 방지
        let next = sims.values.filter { active($0) }.map(\.apid).sorted().first
        if next != nil || apid != nil { follow(next) }
    }

    // MARK: - 통화

    /// 병원을 누름 -> "연결 중"(1.5초 연출) -> call_started -> 녹음
    func dial(_ h: SceneCandidate) async {
        guard let caseId, let apid, call == nil else { return }
        error = nil
        guard await MicCapture.requestPermission() else { error = "마이크 권한이 꺼져 있습니다. 설정 앱에서 켜 주세요."; return }
        call = LocalCall(caseId: caseId, hospitalId: h.hospitalId, hospitalName: h.name, phase: .connecting, startedAt: Date())
        try? await Task.sleep(for: .milliseconds(1500))
        guard call?.caseId == caseId else { return }
        // 시작 신호를 먼저 보내야 hub가 이 사건으로 통화를 연다(서버 STT면 음성도 이 사건에 묶는다)
        guard ambulance?.send(CallSignalMessage(signal: "call_started", apid: apid, caseId: caseId, hospitalId: h.hospitalId)) == true else {
            call = nil
            error = "hub와 연결이 끊겨 통화를 시작하지 못했습니다. 잠시 뒤 다시 눌러 주세요."
            return
        }
        let modelsReady = await models.ready
        let onDevice = Settings.onDevice && modelsReady
        let socket = ambulance
        let s = CallSession(caseId: caseId, apid: apid, models: onDevice ? models : nil,
                            sendPCM: onDevice ? nil : { socket?.sendBinary($0) })
        s.onChange = { [weak self] in self?.tick &+= 1 }
        do {
            try s.start()
        } catch {
            _ = ambulance?.send(CallSignalMessage(signal: "call_ended", apid: apid, caseId: caseId, hospitalId: h.hospitalId))
            call = nil
            self.error = "마이크를 시작하지 못했습니다: \(error.localizedDescription)"
            return
        }
        session = s
        call?.phase = .inCall
        call?.startedAt = Date()
    }

    func hangUp() {
        guard let c = call, let apid else { return }
        if c.phase == .inCall {
            _ = ambulance?.send(CallSignalMessage(signal: "call_ended", apid: apid, caseId: c.caseId, hospitalId: c.hospitalId))
            call?.phase = .ended
            call?.endedAt = Date()
            let s = session
            Task { await s?.finish() }
        } else {
            call = nil
        }
    }
}
