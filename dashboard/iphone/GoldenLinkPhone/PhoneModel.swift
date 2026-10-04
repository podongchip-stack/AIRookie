import Foundation
import GoldenLinkCore
import Observation

/// 웹 전화 앱(dashboard/src/app/phone/page.tsx + PhoneCallView.tsx)의 상태와 규칙.
/// 휴대폰은 전화만 한다 — 출동·현장 종료·이송 승인은 태블릿/PC 대시보드에서 한다. 사건(caseId)도 만들지 않고
/// hub 출동 상태(ambulance_phase.caseId)를 그대로 쓴다.
///
/// 2026-10-05: 통화는 [취소]와 [전송]으로 끝난다 — [전송]을 눌러야만 음성을 처리해 병원에 보낸다. 현장 첫 통화 뒤에도
/// 환자 상태가 바뀌면 추가 통화를 할 수 있고(현장: 다른 병원 / 이송 중: 목적지 병원), 새 요약은 환자 정보에 덧붙는다.
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
    var matchVersion: [String: Int] = [:]  // 사건별로 매칭 결과를 받은 횟수 — 추가 통화가 반영됐는지 판단
    var destinations: [String: MatchResult.Hospital] = [:]  // 사건별 이송 확정 병원

    // 이 기기의 통화
    var call: LocalCall?
    var session: CallSession?
    var error: String?
    var notice: String?  // 화면 위에 잠깐 뜨는 안내(일시정지 등)
    var modelStatus = ""
    var wantsExtraCall = false  // 현장에서 전달 뒤 [추가 통화]를 눌러 병원 목록을 다시 연 상태
    var tick = 0  // 화면 갱신용(통화 시간·레벨)

    struct LocalCall {
        let caseId: String
        let hospitalId: String
        let hospitalName: String
        let followup: Bool
        var phase: Phase
        var startedAt: Date
        var endedAt: Date?
        var matchVersionAtSend = 0
        enum Phase { case connecting, inCall, ended }
    }

    let models = ModelStore()
    private var monitor: HubSocket?
    private var ambulance: HubSocket?
    private var noticeTask: Task<Void, Never>?

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
                // 모델이 없을 때의 문구는 띄우지 않는다(2026-10-05 요청) — 그때는 조용히 서버 음성 인식으로 동작한다
                modelStatus = error == nil ? "온디바이스 음성 인식·구조화" : "서버 음성 인식"
            }
        } else {
            modelStatus = "서버 음성 인식"
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
        wantsExtraCall = false
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
    var phase: AmbulancePhase { mySim?.phase ?? .idle }
    var onScene: Bool { simOn && phase == .on_scene && caseId != nil }
    /// 이송 중·재선택 대기 — 목적지(또는 다른) 병원과 추가 통화를 할 수 있는 단계
    var inTransport: Bool { simOn && caseId != nil && (phase == .transporting || phase == .rerouting) }
    var paused: Bool { mySim?.paused == true }
    var sent: Bool { caseId.flatMap { sentCount[$0] } != nil }
    var destination: MatchResult.Hospital? {
        guard let caseId else { return nil }
        if let d = destinations[caseId] { return d }
        if let hid = mySim?.hospitalId, let name = scene?.hospitals.first(where: { $0.hospitalId == hid })?.name {
            return MatchResult.Hospital(hospitalId: hid, name: name, status: "confirmed")
        }
        return nil
    }

    /// 자막: 온디바이스면 기기에서 인식한 줄, 서버 STT면 hub가 되돌려 준 줄
    var transcriptLines: [String] {
        if let session, Settings.onDevice, call != nil { return session.lines.map(\.text) }
        return caseId.flatMap { hubTranscripts[$0] }?.map(\.text) ?? []
    }

    /// 전송한 통화가 반영됐는가(이 통화를 보낸 뒤 매칭 결과가 새로 왔는가)
    var delivered: Bool {
        guard let c = call, c.phase == .ended else { return false }
        return (matchVersion[c.caseId] ?? 0) > c.matchVersionAtSend
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
            if sim.apid == apid, sim.phase != .on_scene { wantsExtraCall = false }
            if fromMonitor { autoSwitch() }
        case "scene_candidates" where !fromMonitor:
            if let s = try? dec.decode(SceneCandidates.self, from: data) { scenes[s.caseId] = s }
        case "call_status" where !fromMonitor:
            if let s = try? dec.decode(CallStatus.self, from: data) { callStatus[s.caseId] = s }
        case "call_transcript" where !fromMonitor:
            if let l = try? dec.decode(CallTranscriptLine.self, from: data), let c = l.caseId { hubTranscripts[c, default: []].append(l) }
        case "match_result" where !fromMonitor:
            if let m = try? dec.decode(MatchResult.self, from: data) {
                sentCount[m.caseId] = m.hospitals.count
                matchVersion[m.caseId, default: 0] += 1
                destinations[m.caseId] = m.hospitals.first { $0.status == "confirmed" }
            }
        case "action_refused" where !fromMonitor:
            if let r = try? dec.decode(ActionRefused.self, from: data) {
                show(r.reason == "paused" ? "현재 시연 일시정지 중입니다." : "지금은 통화를 시작할 수 없습니다.")
                if call?.phase == .connecting { call = nil }
            }
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
        matchVersion[caseId] = nil; destinations[caseId] = nil
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

    /// 화면 위 안내를 잠깐(2.5초) 띄운다
    func show(_ text: String) {
        notice = text
        noticeTask?.cancel()
        noticeTask = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(2500))
            if !Task.isCancelled { self?.notice = nil }
        }
    }

    // MARK: - 통화

    /// 현장 병원 목록에서 고른 병원과 통화
    func dial(_ h: SceneCandidate) async {
        await dial(hospitalId: h.hospitalId, name: h.name)
    }

    /// 병원을 누름 -> "연결 중"(1.5초 연출) -> call_started -> 녹음. 첫 통화든 추가 통화든 같다(추가 통화는 hub가 덧붙인다)
    func dial(hospitalId: String, name: String) async {
        guard let caseId, let apid, call == nil else { return }
        error = nil
        if paused {
            show("현재 시연 일시정지 중입니다.")
            return
        }
        guard await MicCapture.requestPermission() else { error = "마이크 권한이 꺼져 있습니다. 설정 앱에서 켜 주세요."; return }
        let followup = sent
        call = LocalCall(caseId: caseId, hospitalId: hospitalId, hospitalName: name, followup: followup, phase: .connecting, startedAt: Date())
        try? await Task.sleep(for: .milliseconds(1500))
        guard call?.caseId == caseId, call?.phase == .connecting else { return }  // 연결 중에 취소함
        // 시작 신호를 먼저 보내야 hub가 이 사건으로 통화를 연다(서버 STT면 음성도 이 사건에 묶는다)
        guard ambulance?.send(CallSignalMessage(signal: "call_started", apid: apid, caseId: caseId, hospitalId: hospitalId)) == true else {
            call = nil
            error = "hub와 연결이 끊겨 통화를 시작하지 못했습니다. 잠시 뒤 다시 눌러 주세요."
            return
        }
        let modelsReady = await models.ready
        let onDevice = Settings.onDevice && modelsReady
        let socket = ambulance
        let s = CallSession(caseId: caseId, apid: apid, models: onDevice ? models : nil,
                            sendPCM: onDevice ? nil : { socket?.sendBinary($0) },
                            sendSummary: { [weak self] payload in
                                guard let self else { return "hub 연결 없음" }
                                return await self.sendSummary(payload)
                            })
        s.onChange = { [weak self] in self?.tick &+= 1 }
        do {
            try s.start()
        } catch {
            _ = ambulance?.send(CallSignalMessage(signal: "call_ended", apid: apid, caseId: caseId, hospitalId: hospitalId, cancelled: true))
            call = nil
            self.error = "마이크를 시작하지 못했습니다: \(error.localizedDescription)"
            return
        }
        session = s
        call?.phase = .inCall
        call?.startedAt = Date()
    }

    /// [취소] — 아무것도 전송하지 않는다. 녹음·인식을 버리고 hub에는 취소로 알려 "통화 중" 표시만 지운다
    func cancelCall() {
        guard let c = call else { return }
        if c.phase == .inCall, let apid {
            _ = ambulance?.send(CallSignalMessage(signal: "call_ended", apid: apid, caseId: c.caseId, hospitalId: c.hospitalId, cancelled: true))
            session?.cancel()
        }
        call = nil
        session = nil
        show("통화를 취소했습니다 — 전달하지 않았습니다")
    }

    /// [전송] — 통화를 끝내고 이때만 음성을 처리(인식·구조화)해 병원에 보낸다
    func sendCall() {
        guard let c = call, c.phase == .inCall, let apid else { return }
        if paused {
            show("현재 시연 일시정지 중입니다.")
            return
        }
        _ = ambulance?.send(CallSignalMessage(signal: "call_ended", apid: apid, caseId: c.caseId, hospitalId: c.hospitalId))
        call?.phase = .ended
        call?.endedAt = Date()
        call?.matchVersionAtSend = matchVersion[c.caseId] ?? 0
        wantsExtraCall = false
        let s = session
        Task { await s?.finish() }
    }

    /// 종료 화면의 [확인] — 다음 화면(전달됨 · 추가 통화)으로
    func dismissEnded() {
        call = nil
        session = nil
    }

    /// 온디바이스 요약을 hub로 — WebSocket으로 보낸다(공개 도메인은 /voice/* HTTP를 열지 않는다). 소켓이 없으면 HTTP로.
    private func sendSummary(_ payload: JSONValue) async -> String? {
        if case let .object(pairs) = payload, let socket = ambulance, socket.isOpen {
            return socket.send(JSONValue.object([("type", .string("voice_summary"))] + pairs)) ? nil : "hub 전송 실패"
        }
        return await HubHTTP.postSummary(payload)
    }
}
