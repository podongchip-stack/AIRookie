import UIKit
import Foundation
import GoldenLinkCore
import Observation
import KakaoMapsSDK
import SwiftUI

/// 웹 전화 앱(dashboard/src/app/phone/page.tsx + PhoneCallView.tsx)의 상태와 규칙.
/// 휴대폰은 전화만 한다 — 출동·현장 종료·이송 승인은 태블릿/PC 대시보드에서 한다. 사건(caseId)도 만들지 않고
/// hub 출동 상태(ambulance_phase.caseId)를 그대로 쓴다.
///
/// 통화는 [취소]와 [통화 종료]([전송])로 끝난다 — 눌러야만 음성을 처리한다. 현장 첫 통화는 끝낸 뒤 [이송확정](통화 병원으로 출발,
/// 요약은 그 병원에만)/[이송불가](요약을 존 전체에 동시 전달)를 고른다(2026-11-04). 현장 첫 통화 뒤에도
/// 환자 상태가 바뀌면 추가 통화를 할 수 있고(현장: 다른 병원 / 이송 중: 목적지 병원), 새 요약은 환자 정보에 덧붙는다(바로 반영).
@MainActor
@Observable
final class PhoneModel {
    /// 아래 탭 — [통화]는 예전 전화 앱 그대로, [환자 정보]·[이송]·[기록]은 아이패드 구급차 앱의 화면(2026-10-29)
    enum Tab { case call, patient, transport, records }

    // 연결
    var connection: HubSocket.State = .connecting {
        didSet {
            if connection == .live, oldValue != .live { liveSince = Date(); recordRequest = nil; syncRecords() }
            else if connection != .live { recordSyncStatus = "오프라인 · 기기 기록 표시 중" }
        }
    }
    let caseEdits = CaseEditSync()
    var accessRequired = Settings.accessCode.isEmpty
    var apid: String?  // 접근 코드로 정한 소속 구급차
    /// 요약이 병원들에 전달되는 모습을 지도에서 보여 주는 중(안드로이드 DeliveryShow와 같다)
    final class DeliveryShow {
        let caseId: String
        let durationMs: Int
        let reduceMotion: Bool
        /// 지도가 준비돼 연출이 실제로 시작된 시각(nil이면 아직) — 지도를 불러오는 동안 연출 시간이 흘러가 버리지 않게 지도가 채운다
        var readyAt: Date?
        init(caseId: String, durationMs: Int, reduceMotion: Bool) {
            self.caseId = caseId; self.durationMs = durationMs; self.reduceMotion = reduceMotion
        }
    }
    var deliveryShow: DeliveryShow?
    var identity: IdentityInfo?

    // hub가 알려 준 상태
    var sims: [String: AmbulanceSim] = [:]
    var scenes: [String: SceneCandidates] = [:]
    var callStatus: [String: CallStatus] = [:]
    var hubTranscripts: [String: [CallTranscriptLine]] = [:]
    var sentCount: [String: Int] = [:]  // 매칭 결과의 후보 병원 수
    var results: [String: MatchResult] = [:]  // 사건별 최신 매칭 결과 — 환자 정보·이송 탭이 쓴다(2026-10-29)
    var matchVersion: [String: Int] = [:]  // 사건별로 매칭 결과를 받은 횟수 — 추가 통화가 반영됐는지 판단
    var destinations: [String: MatchResult.Hospital] = [:]  // 사건별 이송 확정 병원
    var sceneInputMode: [String: String] = [:]  // 사건별 시연 콘솔 ② 현장 확인 방식("voice" | "template")
    var transportInputMode: [String: String] = [:]  // 사건별 시연 콘솔 ④ 이송 중 통화 방식(2026-10-06)

    // 이 기기의 통화
    var call: LocalCall?
    var session: CallSession?
    var error: String?
    var notice: String?  // 화면 위에 잠깐 뜨는 안내(일시정지 등)
    var wantsExtraCall = false  // 현장에서 전달 뒤 [추가 통화]를 눌러 병원 목록을 다시 연 상태
    var tick = 0  // 화면 갱신용(통화 시간·레벨)

    var kakaoCamera: CameraPosition?
    var kakaoFittedPath: [[Double]] = []
    var animatedDeliveries: Set<String> = []
    /// 출동·이송 시작 때 한 번만 전체 경로를 맞춘다. 지도 데이터가 늦게 오면 요청을 유지한다.
    var routeFitRequest: String?
    var sceneMapFocusKey: String?
    var responseMapFocusKey: String?
    var routePaths: [String: [[Double]]] = [:]
    var extraNoteDrafts: [String: String] = [:]
    var extraNoteDraft: String {
        get { caseId.flatMap { extraNoteDrafts[$0] } ?? "" }
        set { if let caseId { extraNoteDrafts[caseId] = newValue } }
    }
    var tab: Tab = .call
    var pendingConfirmId: String?  // 이송 승인을 보내고 hub의 확정 응답을 기다리는 병원
    /// caseId -> 관제 판단 대기의 원인 병원 이름(2026-11-04). 대기 중엔 이송 승인 대신 상황실이 병원을 지정한다
    var dispatcherPending: [String: String] = [:]
    var incidentAddress: String?   // 인계확인서 "출발지 주소" — hub가 좌표를 주소로 바꿔 준다
    /// 통화 화면 지도의 병원 핀 좌표 — hub map_overview(병원 목록)에서 hospitalId로 찾는다. 현장 후보 메시지엔 좌표가 없다
    var hospitalGps: [String: GPS] = [:]
    var bodyEdits = BodyEdits()       // 외상 도해에서 구급대원이 고친 부위·처치 — 새 사건이면 비운다
    var bodySentSignature = ""        // 마지막으로 병원에 보낸 도해 내용의 지문 — 그 뒤로 또 고쳤는지만 본다
    /// 인계확인서 시각 칸 — 출동 단계가 바뀐 그 순간. hub는 단계만 보내고 시각은 안 보내므로 앱이 기억한다
    var phaseTimes: [String: Date] = [:]
    private var trackedSim: AmbulanceSim?  // 지금 따라가는 구급차의 직전 상태 — 단계 전환을 알아채는 용도
    private var liveSince: Date?           // 소켓이 연결된 시각 — 직후 따라잡기(지난 결과 재전송)는 화면을 자동 전환하지 않는다

    /// 지난 사건 기록(기록 탭) — 날짜별로 기기에 쌓는다. 바뀔 때마다 recordsRev가 올라 화면이 다시 읽는다
    let records = RecordStore()
    var recordsRev = 0
    var recordSyncStatus = "구급차를 선택하면 기록을 동기화합니다."
    var handoverConflict: CaseRecord?
    private var recordRequest: (id: String, at: Date)?
    private var recordSyncTask: Task<Void, Never>?


    struct LocalCall {
        let caseId: String
        let hospitalId: String
        let hospitalName: String
        let followup: Bool
        var phase: Phase
        var startedAt: Date
        var endedAt: Date?
        var matchVersionAtSend = 0
        var callRoundAtSend = 0
        /// 현장 첫 통화를 끝낸 뒤 구급대원의 판단(2026-11-04): nil = 아직 고르지 않음, "confirm" = 통화 병원으로 이송 확정, "reject" = 이송불가(존 전체 전달)
        var decision: String?
        var decidedAt: Date?
        /// 실제 통화(WebRTC, 2026-11-04) — 병원 앱과 음성을 직접 주고받는다. 이 통화엔 STT·요약·이송 판단이 없다. callId는 hub 통화 식별자
        var webrtc = false
        var callId: String?
        enum Phase { case connecting, inCall, ended }
    }

    let models = ModelStore()
    private var mapSocket: HubSocket?
    private var ambulance: HubSocket?
    private var noticeTask: Task<Void, Never>?

    func start() {
        stop()
        let id = Settings.apid.trimmingCharacters(in: .whitespaces).uppercased()
        guard !id.isEmpty else { return }  // 접근 코드를 입력하기 전엔 어디에도 연결하지 않는다
        follow(id)
        // 병원 좌표(map_overview)만 받는 읽기 전용 소켓 — 다른 메시지는 거른다(구급차 위치가 초당 전 차량분 오므로 해석하지 않는다)
        mapSocket = HubSocket(role: "monitor", id: "phone-map", onMessage: { [weak self] t, d in
            if t == "map_overview" { self?.handle(t, d) }
        }, onState: { _ in })
        recordSyncTask = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                do { try await Task.sleep(for: .seconds(15)) } catch { return }
                self?.syncRecords()
                self?.caseEdits.tick()
                if let self, self.onScene, self.call == nil, !self.sent { self.requestFirstCall() }
            }
        }
        // 모델이 없으면 조용히 서버 음성 인식으로 동작한다(2026-10-05 요청)
        if Settings.onDevice {
            Task { _ = await models.load() }
        }
    }

    func stop() {
        releaseRealCall()  // 실제 통화 중이던 마이크·연결을 먼저 정리한다
        recordSyncTask?.cancel(); recordSyncTask = nil; recordRequest = nil
        mapSocket?.close(); mapSocket = nil
        ambulance?.close(); ambulance = nil
        apid = nil
        records.configure(apid: nil); recordsRev += 1
    }

    private func follow(_ newApid: String?) {
        guard newApid != apid else { return }
        ambulance?.close()
        ambulance = nil
        apid = newApid
        records.configure(apid: newApid)
        recordRequest = nil; handoverConflict = nil; recordsRev += 1
        recordSyncStatus = "기록 연결 대기 중"
        identity = nil
        wantsExtraCall = false
        deliveryShow = nil
        trackedSim = nil; phaseTimes = [:]; incidentAddress = nil; pendingConfirmId = nil; resetBody()
        guard let newApid else { return }
        ambulance = HubSocket(role: "ambulance", id: newApid, onMessage: { [weak self] t, d in self?.handle(t, d) },
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
    /// 운영자의 시연 일시정지(조작 잠금). 추가 통화로 이동만 멈춘 경우("call")는 통화·전송을 막지 않는다
    var paused: Bool { mySim?.paused == true && mySim?.pauseReason != "call" }
    /// 지금 사건이 관제 판단 대기면 원인 병원 이름, 아니면 nil
    var waitingDispatcher: String? { (result?.caseId ?? caseId).flatMap { dispatcherPending[$0] } }
    static let dispatcherWaitText = "관제 판단 대기 중입니다. 상황실이 이송 병원을 지정합니다."
    /// 이송 중 추가 통화 동안 구급차 이동이 멈춰 있다(통화 내용이 반영되면 hub가 다시 출발시킨다)
    var transportHeld: Bool { mySim?.paused == true && mySim?.pauseReason == "call" }
    var sent: Bool { caseId.flatMap { sentCount[$0] } != nil }
    var result: MatchResult? { caseId.flatMap { results[$0] } }
    var patient: PatientInfo? { result?.patientInfo }
    /// 이송이 확정된 병원
    var confirmed: MatchResult.Hospital? { result?.hospitals.first { $0.status == "confirmed" } }
    /// "사고가 발생했는가" — 출동 중·현장·이송·도착·재선택 중이거나 이 구급차 사건의 결과가 있으면 true
    var hasIncident: Bool { simOn && caseId != nil && (result != nil || (phase != .idle && phase != .returning)) }
    /// 콘솔 ②가 "정해진 상황 선택" 중이면 현장 첫 통화를 못 한다(이송 중 통화는 ④ 방식을 따른다)
    var sceneCallBlocked: Bool { !inTransport && !sent && caseId.map { sceneInputMode[$0] == "template" } == true }
    /// 콘솔 ④가 "정해진 상황 선택" 중이면 이송 중 [목적지 병원과 통화]를 못 한다(2026-10-06)
    var transportCallBlocked: Bool { phase == .transporting && caseId.map { transportInputMode[$0] == "template" } == true }
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
        guard let result = results[c.caseId] else { return false }
        return (matchVersion[c.caseId] ?? 0) > c.matchVersionAtSend
            && (result.patientInfo?.callRound ?? 1) > c.callRoundAtSend
    }

    // MARK: - hub 메시지

    private func handle(_ type: String, _ data: Data) {
        let dec = JSONDecoder()
        defer { syncLiveCase() }
        switch type {
        case "live_case_state", "live_case_error":
            caseEdits.accept(data)
        // 실제 통화(WebRTC) — 지금 통화(callId)에 대한 메시지만 따른다
        case "call_state":
            if let s = try? dec.decode(CallState.self, from: data) { onRealCallState(s) }
        case "rtc_answer":
            if let a = try? dec.decode(RtcSdpIn.self, from: data), call?.webrtc == true, call?.callId == a.callId { rtc?.applyAnswer(a.sdp) }
        case "rtc_ice":
            if let i = try? dec.decode(RtcIceIn.self, from: data), call?.webrtc == true, call?.callId == i.callId { rtc?.addRemoteIce(i.candidate) }
        case "call_error":
            if let e = try? dec.decode(CallError.self, from: data), call?.webrtc == true, call?.callId == e.callId { endRealCall("통화를 처리하지 못했습니다") }
        case "call_connection_error":
            if call?.phase == .connecting { call = nil; callRequestId = nil; show("현재 단계에서는 전화할 수 없습니다") }
        case "first_call_error":
            show("첫 통화 추천 요청을 처리하지 못했습니다. 현재 사건을 확인해 주세요.")
        case "records_changed":
            syncRecords()
        case "record_sync_result", "record_import_result", "record_handover_result", "record_error":
            handleRecordReply(type, data)
        case "map_overview":
            if let m = try? dec.decode(MapOverview.self, from: data) {
                for h in m.hospitals { hospitalGps[h.hospitalId] = h.gps }
            }
        case "identity_info":
            identity = try? dec.decode(IdentityInfo.self, from: data)
            syncLiveCase()
            caseEdits.reconnect()
        case "ambulance_phase", "ambulance_position":
            guard let sim = try? dec.decode(AmbulanceSim.self, from: data) else { return }
            if let path = sim.path { routePaths[sim.apid] = path }
            else if sims[sim.apid]?.phase != sim.phase || sims[sim.apid]?.caseId != sim.caseId { routePaths[sim.apid] = nil }
            sims[sim.apid] = sim
            if sim.apid == apid, sim.phase != .on_scene { wantsExtraCall = false }
            if sim.apid == apid { trackPhase(sim) }
        case "scene_candidates":
            if let s = try? dec.decode(SceneCandidates.self, from: data) {
                scenes[s.caseId] = s
            }
        case "scene_input_mode":
            if let s = try? dec.decode(SceneInputMode.self, from: data) {
                if s.stage == "transport" { transportInputMode[s.caseId] = s.mode } else { sceneInputMode[s.caseId] = s.mode }
            }
        case "call_status":
            if let s = try? dec.decode(CallStatus.self, from: data) {
                callStatus[s.caseId] = s
                if s.requestId == callRequestId, s.caseId == call?.caseId, s.hospitalId == call?.hospitalId {
                    if s.state == "calling" { Task { await self.beginConnectedCall() } }
                    if ["no_answer", "cancelled"].contains(s.state) {
                        session?.cancel(); session = nil; call = nil; callRequestId = nil
                        show(s.state == "no_answer" ? "전화 미응답 — 다음 추천 병원을 확인하세요" : "전화 요청이 취소됐습니다")
                    }
                }
            }
        case "call_transcript":
            if let l = try? dec.decode(CallTranscriptLine.self, from: data), let c = l.caseId { hubTranscripts[c, default: []].append(l) }
        case "match_result":
            if let m = try? dec.decode(MatchResult.self, from: data) {
                if let apid, let a = m.apid, a != apid { return }  // 다른 구급차 사건
                // 자동 전환: 이 사건의 매칭 결과가 처음 오면(=음성 요약 도착, 추가 통화 회차 제외) 환자 정보로,
                // 이송 시작은 ambulance_phase에서 통화 지도로 전환한다. 연결 직후 따라잡기 결과는 전환하지 않는다
                let firstForCase = results[m.caseId] == nil
                results[m.caseId] = m
                let settled = liveSince.map { Date().timeIntervalSince($0) > 3 } ?? true
                // 이 기기에서 건 통화의 요약은 아래 delivered 분기에서 연출한다(여기서 먼저 넘기지 않는다).
                // 시연 콘솔 등 다른 곳에서 들어온 요약도 같은 전달 연출을 보여 준 뒤 환자 정보로 넘어간다
                if settled, firstForCase, (m.patientInfo?.callRound ?? 1) <= 1, phase != .transporting, call?.caseId != m.caseId { startDeliveryShow(m.caseId) }
                let confirmedId = m.hospitals.first { $0.status == "confirmed" }?.hospitalId
                if let p = pendingConfirmId, p == confirmedId { pendingConfirmId = nil }
                sentCount[m.caseId] = m.hospitals.count
                matchVersion[m.caseId, default: 0] += 1
                destinations[m.caseId] = m.hospitals.first { $0.status == "confirmed" }
                snapshotCase(m.caseId)
                // 이번 통화의 새 요약이 반영되면 성공 확인 화면을 거치지 않고 환자 정보로.
                // 병원 응답·주기 갱신만으로는 callRound가 늘지 않으므로 통화 처리를 닫지 않는다.
                if call?.caseId == m.caseId, delivered {
                    // 이송확정이면 요약이 통화 병원 한 곳에만 갔고 구급차가 바로 출발한다 — 존 전체 전달 연출 없이 통화 지도(이송)로
                    let confirmedByCall = call?.decision == "confirm"
                    dismissEnded()
                    if confirmedByCall { tab = .call } else { startDeliveryShow(m.caseId) }
                }
            }
        case "action_refused":
            if let r = try? dec.decode(ActionRefused.self, from: data) {
                pendingConfirmId = nil
                show(r.reason == "paused" ? "현재 시연 일시정지 중입니다."
                     : r.reason == "template_mode" ? "콘솔이 정해진 상황 선택 중이라 전화할 수 없습니다."
                     : r.reason == "already_arrived" ? "이미 병원에 도착해 이송 병원을 바꿀 수 없습니다. 현재 병원의 수용 불가 처리 후 다시 선택해 주세요."
                     : r.reason == "confirm_failed" ? "이송 확정을 처리하지 못해 존 안 병원 전체에 전달했습니다. 구급차 대시보드를 확인해 주세요."
                     : r.reason == "no_pending_decision" ? "이 통화는 이미 처리됐습니다."
                     : r.reason == "dispatcher_pending" ? Self.dispatcherWaitText
                     : "지금은 통화를 시작할 수 없습니다.")
                if call?.phase == .connecting, call?.webrtc != true { call = nil }  // 실제 통화는 call_state(ended)로 정리한다
                if r.reason == "no_pending_decision", call?.phase == .ended { call = nil; session = nil }
            }
        case "case_closed":
            if let c = try? dec.decode(CaseClosed.self, from: data) { forget(c.caseId) }
        // 관제 판단 대기(2026-11-04) — 여러 환자가 한 병원에 몰려 상황실이 병원을 정한다. 그동안 이송 승인은 막힌다
        case "dispatcher_pending":
            if let p = try? dec.decode(DispatcherPending.self, from: data) {
                if p.pending {
                    dispatcherPending[p.caseId] = p.hospitalName ?? "1순위 병원"
                    show("관제 판단 대기 — \(p.hospitalName ?? "1순위 병원")에 여러 환자가 몰려 상황실이 병원을 지정합니다.")
                } else {
                    dispatcherPending[p.caseId] = nil
                }
            }
        case "dispatcher_notice":
            if let n = try? dec.decode(DispatcherNotice.self, from: data) {
                dispatcherPending[n.caseId] = nil
                if n.kind == "transport_confirmed" { show("상황실이 \(n.hospitalName ?? "병원")(으)로 이송 병원을 지정했습니다.") }
            }
        case "case_sync":
            if let s = try? dec.decode(CaseSync.self, from: data) {
                for id in Set(scenes.keys).union(sentCount.keys).union(results.keys).subtracting(s.caseIds) { forget(id) }
            }
        default:
            break  // 모르는 type은 버린다
        }
    }

    private func forget(_ caseId: String) {
        closeRecord(caseId)
        results[caseId] = nil
        dispatcherPending[caseId] = nil
        scenes[caseId] = nil; callStatus[caseId] = nil; hubTranscripts[caseId] = nil; sentCount[caseId] = nil
        matchVersion[caseId] = nil; destinations[caseId] = nil; sceneInputMode[caseId] = nil
        transportInputMode[caseId] = nil
        if deliveryShow?.caseId == caseId { deliveryShow = nil }
        if call?.caseId == caseId, session == nil || call?.phase == .ended { call = nil; session = nil }
    }

    /// 요약이 반영되면 환자 정보로 바로 넘기지 않고, 현장 지도에서 병원들로 전달되는 연출을 먼저 보여 준다.
    /// 현장이 아니거나(이송 중 추가 통화) 지도에 찍을 병원 좌표가 없으면 연출 없이 바로 넘어간다
    private func startDeliveryShow(_ caseId: String) {
        let anyTarget = results[caseId]?.hospitals.contains { hospitalGps[$0.hospitalId] != nil } == true
        if !onScene || mySim?.gps == nil || !anyTarget || Settings.kakaoNativeAppKey.isEmpty { tab = .patient; return }
        // 기기의 "동작 줄이기" 설정이면 움직임 없이 병원이 켜진 상태만 잠깐 보여 준다
        let reduce = UIAccessibility.isReduceMotionEnabled
        let show = DeliveryShow(caseId: caseId, durationMs: reduce ? 1200 : 2600, reduceMotion: reduce)
        deliveryShow = show
        tab = .call
        // 연출은 지도가 준비된 뒤 시계를 흘려 끝내지만, 지도가 끝내 준비되지 않아도 막히지 않게 여유를 두고 끝낸다
        Task { @MainActor [weak self] in
            try? await Task.sleep(for: .milliseconds(show.durationMs + 5_000))
            if let self, self.deliveryShow === show { self.finishDelivery() }
        }
    }

    /// 연출이 끝났거나 구급대원이 눌러 건너뛰었다 — 환자 정보 탭으로
    func finishDelivery() {
        guard deliveryShow != nil else { return }
        deliveryShow = nil
        tab = .patient
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

    func requestFirstCall(noAnswer: String? = nil) {
        guard let caseId else { return }
        var body: [String: Any] = ["type": "first_call_request", "caseId": caseId]
        if let noAnswer { body["noAnswerHospitalId"] = noAnswer }
        guard let data = try? JSONSerialization.data(withJSONObject: body), ambulance?.sendJSON(data) == true else {
            show("hub 연결을 확인해 주세요. 추천 요청을 보내지 못했습니다."); return
        }
    }

    var callRequestId: String?

    @discardableResult
    func connectionAction(_ operation: String) -> Bool {
        guard let c = call, let rid = callRequestId,
              let data = try? JSONSerialization.data(withJSONObject: ["type":"call_connection", "operation":operation,
                "caseId":c.caseId, "hospitalId":c.hospitalId, "requestId":rid, "timestamp":isoNow()]) else { return false }
        return ambulance?.sendJSON(data) == true
    }

    func noAnswerNext() {
        guard call?.phase == .connecting else { return }
        if call?.webrtc == true { hangupRealCall(); return }  // 실제 통화는 시연 연출의 "미응답 다음 병원" 규칙이 없다 — 발신을 취소한다
        if !connectionAction("no_answer") { show("hub 연결을 확인해 주세요") }
    }

    // MARK: - 실제 통화(WebRTC, 2026-11-04)
    // 설정의 [실제 통화]가 켜져 있으면 병원을 눌러 거는 전화가 시연 연출이 아니라 병원 코드로 접속한 앱과의 실제 음성 통화가 된다.
    // 흐름: call_invite → (병원이 받으면) hub가 connecting → 이쪽이 offer를 만들어 보냄 → answer·ICE 교환 → 양쪽 media_ready → active.
    // 이 통화엔 STT·요약·이송 판단이 없다(다음 단계). 모든 hub 메시지는 지금 통화의 callId와 같을 때만 따른다.
    // 안드로이드 PhoneModel.kt의 같은 이름 함수들과 같은 규칙이다(그쪽이 실기기·hub 연동 검증됨). 이쪽은 Mac에서 빌드 확인이 필요하다.

    private var rtc: RtcSession?
    private var rtcNegotiation = 1

    private func startRealCall(caseId: String, hospitalId: String, name: String) {
        let callId = UUID().uuidString
        var c = LocalCall(caseId: caseId, hospitalId: hospitalId, hospitalName: name, followup: sent, phase: .connecting, startedAt: Date())
        c.webrtc = true
        c.callId = callId
        call = c
        if ambulance?.send(CallInviteMessage(callId: callId, caseId: caseId, hospitalId: hospitalId, deviceId: Settings.deviceID)) != true {
            call = nil
            error = "hub 연결이 끊겨 전화를 걸지 못했습니다."
        }
    }

    private func onRealCallState(_ s: CallState) {
        guard let c = call, c.webrtc, c.callId == s.callId else { return }
        switch s.state {
        case "connecting":
            guard rtc == nil else { return }  // 같은 상태가 다시 오면(재접속 동기화) 연결을 새로 만들지 않는다
            let callId = s.callId
            do {
                let session = try RtcSession(
                    iceServers: s.iceServers ?? [],
                    onLocalIce: { [weak self] candidate in Task { @MainActor in self?.sendRealIce(callId, candidate) } },
                    onMediaReady: { [weak self] in Task { @MainActor in self?.sendMediaReady(callId) } },
                    onFailed: { [weak self] _ in Task { @MainActor in self?.failRealCall(callId) } })
                rtc = session
                session.createOffer { [weak self] sdp in Task { @MainActor in self?.sendOffer(callId, sdp) } }
            } catch {
                _ = ambulance?.send(CallHangupMessage(callId: callId))
                endRealCall("통화 연결을 준비하지 못했습니다")
            }
        case "active":
            call?.phase = .inCall
            call?.startedAt = Date()
        case "ended":
            endRealCall(CallLabels.endText(s.reason, detail: s.detail))
        default:
            break
        }
    }

    private func sendOffer(_ callId: String, _ sdp: String) {
        guard call?.callId == callId else { return }
        _ = ambulance?.send(RtcSdpMessage(type: "rtc_offer", callId: callId, sdp: sdp, negotiationRevision: rtcNegotiation))
    }

    private func sendRealIce(_ callId: String, _ candidate: IceCandidatePayload) {
        guard call?.callId == callId else { return }
        _ = ambulance?.send(RtcIceMessage(callId: callId, candidate: candidate, negotiationRevision: rtcNegotiation))
    }

    private func sendMediaReady(_ callId: String) {
        guard call?.callId == callId else { return }
        _ = ambulance?.send(MediaReadyMessage(callId: callId))
    }

    private func failRealCall(_ callId: String) {
        guard call?.callId == callId else { return }
        _ = ambulance?.send(CallHangupMessage(callId: callId))
        endRealCall("통화 연결에 실패했습니다")
    }

    /// [취소]/[통화 종료] — 마이크·연결을 바로 끄고 hub에 알린다. hub 응답이 늦어도 마이크는 이미 꺼져 있다
    func hangupRealCall() {
        guard let c = call, c.webrtc, let id = c.callId else { return }
        _ = ambulance?.send(CallHangupMessage(callId: id))
        endRealCall(c.phase == .connecting ? "발신을 취소했습니다" : "통화를 종료했습니다")
    }

    /// 실제 통화의 자원을 정리하고 병원 목록으로 돌아간다. 여러 번 불러도 안전하다
    private func endRealCall(_ message: String) {
        releaseRealCall()
        if call?.webrtc == true { call = nil }
        show(message)
    }

    private func releaseRealCall() {
        rtc?.close()
        rtc = nil
    }

    /// 현장 병원 목록에서 고른 병원과 통화
    func dial(_ h: SceneCandidate) async {
        await dial(hospitalId: h.hospitalId, name: h.name)
    }

    /// hub에 연결 요청 → 관제의 전화 응답 이후에만 녹음 시작.
    func dial(hospitalId: String, name: String) async {
        guard let caseId, let apid, call == nil else { return }
        error = nil
        if paused {
            show("현재 시연 일시정지 중입니다.")
            return
        }
        if sceneCallBlocked || transportCallBlocked {
            show("콘솔이 정해진 상황 선택 중이라 전화할 수 없습니다.")
            return
        }
        guard await MicCapture.requestPermission() else { error = "마이크 권한이 꺼져 있습니다. 설정 앱에서 켜 주세요."; return }
        if Settings.realCall { startRealCall(caseId: caseId, hospitalId: hospitalId, name: name); return }
        let followup = sent
        call = LocalCall(caseId: caseId, hospitalId: hospitalId, hospitalName: name, followup: followup, phase: .connecting, startedAt: Date())
        callRequestId = UUID().uuidString
        if !connectionAction("request") {
            call = nil; error = "hub 연결이 끊겨 전화 요청을 보내지 못했습니다."
        }
    }

    private func beginConnectedCall() async {
        guard let c = call, c.phase == .connecting, let apid else { return }
        let caseId = c.caseId, hospitalId = c.hospitalId
        call?.phase = .inCall
        let modelsReady = await models.ready
        guard call?.caseId == caseId, call?.hospitalId == hospitalId, call?.phase == .inCall else { return }
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
        if c.webrtc { hangupRealCall(); return }  // 실제 통화: 받기 전엔 발신 취소, 통화 중엔 종료 — 같은 hangup이다
        if c.phase == .connecting {
            if !connectionAction("cancel") { show("hub 연결을 확인해 주세요"); return }
        }
        if c.phase == .inCall, let apid {
            _ = ambulance?.send(CallSignalMessage(signal: "call_ended", apid: apid, caseId: c.caseId, hospitalId: c.hospitalId, cancelled: true))
            session?.cancel()
        }
        call = nil
        session = nil
        show("통화를 취소했습니다 — 전달하지 않았습니다")
    }

    /// [통화 종료](현장 첫 통화) / [전송](추가 통화) — 통화를 끝내고 이때만 음성을 처리(인식·구조화)한다.
    /// 추가 통화는 바로 병원에 반영되고, 현장 첫 통화는 요약을 hub가 붙잡아 두었다가 구급대원이 [이송확정]/[이송불가]를 고르면 처리한다(2026-11-04)
    func sendCall() {
        if call?.webrtc == true { hangupRealCall(); return }
        guard let c = call, c.phase == .inCall, let apid else { return }
        if paused {
            show("현재 시연 일시정지 중입니다.")
            return
        }
        _ = ambulance?.send(CallSignalMessage(signal: "call_ended", apid: apid, caseId: c.caseId, hospitalId: c.hospitalId,
                                              awaitDecision: c.followup ? nil : true))
        call?.phase = .ended
        call?.endedAt = Date()
        call?.matchVersionAtSend = matchVersion[c.caseId] ?? 0
        call?.callRoundAtSend = results[c.caseId]?.patientInfo?.callRound ?? (results[c.caseId] == nil ? 0 : 1)
        wantsExtraCall = false
        let s = session
        Task { await s?.finish() }
    }

    /// 통화를 끝낸 구급대원의 판단(2026-11-04) — [이송확정]: 통화한 병원으로 바로 출발(요약은 그 병원에만),
    /// [이송불가]: 요약을 존 안 다른 후보 병원 전체에 동시에 전달. 요약 정리가 끝나기 전에 눌러도 hub가 순서를 맞춘다
    func decideTransport(confirm: Bool) {
        guard let c = call, c.phase == .ended, !c.followup, c.decision == nil else { return }
        if paused {
            show("현재 시연 일시정지 중입니다.")
            return
        }
        let decision = confirm ? "confirm" : "reject"
        guard ambulance?.send(CallDecisionMessage(caseId: c.caseId, decision: decision)) == true else {
            show("hub 연결을 확인해 주세요. 선택을 전하지 못했습니다.")
            return
        }
        call?.decision = decision
        call?.decidedAt = Date()
        if confirm { pendingConfirmId = c.hospitalId }  // 이송 탭도 "확정 요청 중"으로 보인다 — hub가 확정을 돌려주면 풀린다
    }

    /// 완료한 통화의 화면 상태를 정리한다. 실패 시 다시 통화할 때도 쓴다.
    /// 판단 없이 닫는 첫 통화(인식된 말이 없는 경우)는 hub의 판단 대기도 닫는다
    func dismissEnded() {
        if let c = call, c.phase == .ended, !c.followup, c.decision == nil {
            _ = ambulance?.send(CallDecisionMessage(caseId: c.caseId, decision: "cancel"))
        }
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

    // MARK: - 환자 정보 · 이송 (아이패드 AppModel과 같은 규칙, 2026-10-29)

    /// 출동 단계가 바뀐 순간을 인계확인서 시각 칸에 적고, 사고 현장이 정해지면 좌표를 주소로 바꿔 둔다
    private func trackPhase(_ sim: AmbulanceSim) {
        let prev = trackedSim
        trackedSim = sim
        if sim.phase == .transporting,
           prev?.phase != .transporting || prev?.caseId != sim.caseId || prev?.hospitalId != sim.hospitalId {
            tab = .call
            routeFitRequest = "\(sim.caseId ?? sim.apid)-\(sim.hospitalId ?? "destination")"
        } else if sim.phase == .dispatching,
                  prev?.phase != .dispatching || prev?.caseId != sim.caseId {
            tab = .call
            routeFitRequest = "\(sim.caseId ?? sim.apid)-dispatch"
        } else if sim.phase == .returning, prev?.phase != .returning {
            tab = .call
            routeFitRequest = "\(sim.apid)-return"
        } else if ![.transporting, .dispatching, .returning].contains(sim.phase) {
            routeFitRequest = nil
        }
        // 새 출동(다른 caseId)이 시작되면 지난 사건의 시각·주소를 비운다 — 비운 뒤에 이번 단계를 적는다(순서가 반대면 방금 적은 시각이 지워진다)
        if let c = sim.caseId, c != prev?.caseId {
            phaseTimes = [:]; incidentAddress = nil; pendingConfirmId = nil; resetBody()
            phaseTimes["requestedAt"] = Date()
        }
        if sim.phase != prev?.phase || sim.caseId != prev?.caseId {
            recordPhaseTime(sim.phase.rawValue)
            if let c = sim.caseId { snapshotCase(c) }
        }
        if sim.incident?.lat != prev?.incident?.lat || sim.incident?.lng != prev?.incident?.lng {
            incidentAddress = nil
            if let p = sim.incident { fetchIncidentAddress(p) }
        }
    }

    /// 이미 적힌 칸은 덮지 않는다 — 처음 그 단계에 들어간 때가 맞다
    private func recordPhaseTime(_ phase: String) {
        let now = Date()
        let key: String?
        switch phase {
        case "dispatching": key = "dispatchedAt"
        case "on_scene": key = "sceneArrivedAt"
        case "transporting": key = "transportStartedAt"
        case "at_hospital": key = "transportEndedAt"
        default: key = nil
        }
        // 출동 단계 전환을 못 본 채(앱을 늦게 켜거나 재연결) 진행 중인 사건을 받았으면, 적어도 '출동 일시'는 이 사건을 처음 본 때로 적는다
        if ["on_scene", "transporting", "at_hospital", "rerouting"].contains(phase), phaseTimes["dispatchedAt"] == nil { phaseTimes["dispatchedAt"] = now }
        guard let key, phaseTimes[key] == nil else { return }
        phaseTimes[key] = now
        if phaseTimes["requestedAt"] == nil { phaseTimes["requestedAt"] = now }
    }

    /// 사고 현장 좌표 -> 주소(hub 대리 호출). 실패하면 조용히 둔다 — 인계확인서가 좌표를 그대로 적는다
    private func fetchIncidentAddress(_ p: GPS) {
        guard let base = Settings.httpBase else { return }
        var comps = URLComponents(url: base.appendingPathComponent("geocode/reverse"), resolvingAgainstBaseURL: false)
        comps?.queryItems = [URLQueryItem(name: "lat", value: "\(p.lat)"), URLQueryItem(name: "lng", value: "\(p.lng)")]
        guard let url = comps?.url else { return }
        Task { [weak self] in
            guard let self else { return }
            guard let (data, resp) = try? await URLSession.shared.data(from: url), (resp as? HTTPURLResponse)?.statusCode == 200,
                  let body = try? JSONDecoder().decode([String: String?].self, from: data), let address = body["address"] ?? nil,
                  !address.isEmpty else { return }
            // 늦게 온 응답이 다른 사건을 덮지 않게 — 지금 사건의 좌표일 때만
            if self.mySim?.incident?.lat == p.lat, self.mySim?.incident?.lng == p.lng { self.incidentAddress = address }
        }
    }

    /// 이송 승인(구급대원 판단) — 웹 handleApprove와 같은 형식. 병원이 승인한 병원에만 버튼이 열린다
    func approve(_ hospitalId: String) {
        if paused { show("현재 시연 일시정지 중입니다."); return }
        if waitingDispatcher != nil { show(Self.dispatcherWaitText); return }
        guard let id = result?.caseId ?? caseId, let ambulance else { return }
        pendingConfirmId = hospitalId
        if !ambulance.send(ApprovalAction(caseId: id, hospitalId: hospitalId, timestamp: isoNow())) {
            pendingConfirmId = nil
            show("hub에 연결되지 않아 보내지 못했습니다.")
        }
    }

    /// 추가 정보 전송 — 통화 요약에 없는 것을 적어 후보 병원들에 보낸다. 순위 칸이 아니라 재매칭·승인 초기화는 없다. 보냈으면 true
    @discardableResult
    func sendExtraNote(_ text: String) -> Bool {
        let note = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if paused { show("현재 시연 일시정지 중입니다."); return false }
        guard !note.isEmpty else { return false }
        guard let id = result?.caseId ?? caseId, let ambulance else {
            show("진행 중인 사건이 없어 보내지 못했습니다."); return false
        }
        guard ambulance.send(ExtraNoteMessage(caseId: id, extraNote: note, timestamp: isoNow())) else {
            show("hub에 연결되지 않아 보내지 못했습니다."); return false
        }
        show("추가 정보를 병원에 전달했습니다.")
        return true
    }

    /// 이 사건의 지금 상태를 기록에 올린다(없으면 새로, 있으면 갱신). 병원 응답·환자 요약·인계확인서 최종 값을 한 덩이로 둔다
    func snapshotCase(_ id: String) {
        guard let r = results[id] else { return }
        let current = id == caseId
        let p = r.patientInfo
        let now = Date()
        let old = records.byCase(id)
        // 서버 버전이 있는 복사본은 지연 도착한 실시간 메시지로 덮어쓰지 않는다.
        // 현재 화면은 results를 쓰고, 기록 탭은 서버 변경 순번으로만 갱신한다.
        if old?.archiveVersion != nil { return }
        let requestedAt = current ? phaseTimes["requestedAt"].map { $0.timeIntervalSince1970 * 1000 } : nil
        let started = old?.startedAt ?? requestedAt ?? now.timeIntervalSince1970 * 1000
        let confirmedHospital = r.hospitals.first { $0.status == "confirmed" }
        // 지금 따라가는 사건이 아니면 시각·출발지·도해 처치를 새로 만들지 못한다 — 이전 기록 값을 그대로 둔다
        let auto = current
            ? Handover.auto(patient: p, confirmed: confirmedHospital, ambulanceName: identity?.name, apid: apid,
                            times: phaseTimes, incident: mySim?.incident, incidentAddress: incidentAddress, bodyCare: bodyEdits.careLines)
            : Handover.auto(patient: p, confirmed: confirmedHospital, ambulanceName: identity?.name, apid: apid,
                            times: [:], incident: nil, incidentAddress: nil)
        let values = (old?.handover ?? [:]).merging(auto) { _, new in new }.merging(Handover.loadEdits(id)) { _, new in new }
        var record = CaseRecord(
            caseId: id, apid: r.apid ?? apid, ambulanceName: old?.ambulanceName ?? identity?.name,
            date: RecordDates.of(started), startedAt: started, updatedAt: now.timeIntervalSince1970 * 1000,
            symptom: p?.chiefComplaint ?? p?.expectedDiagnosis, expectedDiagnosis: p?.expectedDiagnosis, ktasLevel: p?.ktasLevel,
            hospitals: r.hospitals.map { RecordHospital(hospitalId: $0.hospitalId, name: $0.name, status: $0.status, rejectReason: $0.rejectReason,
                                                        distanceKm: $0.roadDistanceKm ?? $0.distanceKm, etaMin: $0.etaMin) },
            handover: values, closed: old?.closed == true
        )
        record.archiveVersion = old?.archiveVersion
        record.archiveEpoch = old?.archiveEpoch
        record.handoverRevision = old?.handoverRevision
        record.handoverEdits = old?.handoverEdits
        record.events = old?.events
        record.legacyImport = old?.legacyImport
        records.upsert(record)
        recordsRev += 1
    }

    /// 사건이 끝났음을 기록에 남긴다
    private func closeRecord(_ id: String) {
        guard let old = records.byCase(id), old.archiveVersion == nil, !old.closed else { return }
        var closed = old; closed.closed = true; closed.updatedAt = Date().timeIntervalSince1970 * 1000
        records.upsert(closed)
        recordsRev += 1
    }

    private func resetBody() { bodyEdits = BodyEdits(); bodySentSignature = "" }

    /// 외상 도해에서 고친 것을 한 번에 병원으로 — 부위는 증상(injuryStatus) 칸, 처치는 추가 정보 한 줄(아이패드 BodyInjuryCard.send와 같다)
    @discardableResult
    func sendBodyEdits() -> Bool {
        let e = bodyEdits
        // 증상 칸 = 통화에서 온 것 중 빼지 않은 것 + 구급대원이 찍은 부위
        let kept = (patient?.injuryStatus ?? []).filter { text in
            let marks = InjuryMapper.marks(text)
            return marks.isEmpty || !marks.allSatisfy { e.removed.contains($0) }
        }
        guard sendPatientOverride(expectedDiagnosis: nil, injuryStatus: kept + e.addedLines, ktasLevel: nil, requiredDepartment: nil, chiefComplaint: nil) else { return false }
        if !e.careLines.isEmpty { sendExtraNote("[처치] " + e.careLines.joined(separator: " · ")) }
        bodySentSignature = e.signature
        return true
    }

    /// 통화 요약 확인·수정 — 바뀐 칸만 담아 보낸다. 순위 칸(예상 병명·KTAS·필요 진료과)이 바뀌면 hub가 다시 매칭한다
    @discardableResult
    func sendPatientOverride(expectedDiagnosis: String?, injuryStatus: [String]?, ktasLevel: Int?, requiredDepartment: String?, chiefComplaint: String?) -> Bool {
        if paused { show("현재 시연 일시정지 중입니다."); return false }
        guard let id = result?.caseId ?? caseId, let ambulance else {
            show("진행 중인 사건이 없어 보내지 못했습니다."); return false
        }
        let msg = PatientOverrideMessage(caseId: id, timestamp: isoNow(), expectedDiagnosis: expectedDiagnosis,
                                         injuryStatus: injuryStatus, ktasLevel: ktasLevel,
                                         requiredDepartment: requiredDepartment, chiefComplaint: chiefComplaint)
        guard ambulance.send(msg) else { show("hub에 연결되지 않아 보내지 못했습니다."); return false }
        show("환자 정보를 전달했습니다")
        return true
    }
}


// MARK: - 영구 기록 동기화 (변경 순번 / 재접속 / 오프라인 수정 대기열)
extension PhoneModel {
    func syncRecords() {
        guard let apid, let socket = ambulance, socket.isOpen else { return }
        let token = RecordAccess.token(apid)
        guard !token.isEmpty else { recordSyncStatus = "설정에 구급차별 기록 동기화 키를 입력해 주세요."; return }
        if let request = recordRequest, Date().timeIntervalSince(request.at) < 20 { return }
        let id: String
        let sent: Bool
        // 기존 설치에만 있던 기록은 20개씩 이관한다. 서버 기록이 있으면 서버 값을 유지한다.
        let legacy = records.legacyRecords()
        if !legacy.isEmpty {
            id = UUID().uuidString
            sent = socket.send(RecordImportRequest(requestId: id, token: token, records: legacy))
        } else if handoverConflict == nil, let pending = records.pending.first {
            id = pending.requestId
            sent = socket.send(RecordHandoverRequest(pending: pending, token: token))
        } else {
            id = UUID().uuidString
            let cursor = records.cursor
            sent = socket.send(RecordSyncRequest(requestId: id, token: token, cursor: cursor.cursor, epoch: cursor.epoch))
        }
        if sent { recordRequest = (id, Date()); recordSyncStatus = "기록 동기화 중…" }
        else { recordRequest = nil; recordSyncStatus = "연결되면 기록 동기화를 재시도합니다." }
    }

    private func applyArchived(_ record: CaseRecord) -> Bool {
        guard record.apid == apid else { return false }
        // 재전송된 쓰기 영수증/페이지가 더 최신인 로컬 서버 사본을 뒤로 돌리지 않는다.
        if let old = records.byCase(record.caseId), old.archiveEpoch == record.archiveEpoch, (old.archiveVersion ?? 0) > (record.archiveVersion ?? 0) { return true }
        guard records.upsert(record) else { return false }
        if !records.pending.contains(where: { $0.caseId == record.caseId }) && !caseEdits.ownsCase(record.caseId) {
            Handover.saveEdits(record.caseId, record.handoverEdits ?? [:])
        }
        recordsRev += 1
        return true
    }

    private func handleRecordReply(_ type: String, _ data: Data) {
        guard let reply = try? JSONDecoder().decode(RecordSyncReply.self, from: data),
              let requestId = reply.requestId, recordRequest?.id == requestId else { return }
        recordRequest = nil
        if type == "record_error" {
            recordSyncStatus = reply.error == "unauthorized" ? "기록 동기화 키 또는 구급차 ID를 확인해 주세요." : "기록 동기화 실패 — 다음 연결 때 다시 시도합니다."
            return
        }
        guard reply.apid == apid else { return }
        if type == "record_handover_result", let record = reply.record {
            if reply.conflict == true {
                handoverConflict = record
                _ = applyArchived(record)
                recordSyncStatus = "다른 기기에서 인계확인서를 수정했습니다. 저장할 내용을 선택해 주세요."
                return
            }
            let remaining = records.pending.filter { $0.requestId != requestId }.map { pending in
                pending.caseId == record.caseId
                    ? PendingHandover(caseId: pending.caseId, revision: record.handoverRevision ?? 0, edits: pending.edits)
                    : pending
            }
            guard records.savePending(remaining), applyArchived(record) else {
                recordSyncStatus = "기기 저장 공간을 확인해 주세요."; return
            }
        } else {
            for record in reply.records ?? [] {
                guard applyArchived(record) else { recordSyncStatus = "기기 저장 공간을 확인해 주세요."; return }
            }
            if type == "record_sync_result" {
                guard let epoch = reply.epoch, let cursor = reply.cursor,
                      records.saveCursor(.init(epoch: epoch, cursor: cursor)) else {
                    recordSyncStatus = "기록 동기화 위치를 저장하지 못했습니다."; return
                }
            }
        }
        if reply.hasMore == true || type != "record_sync_result" { syncRecords() }
        else { recordSyncStatus = handoverConflict == nil ? "서버 기록과 동기화됨" : "인계확인서 수정 충돌 확인이 필요합니다." }
    }

    /// 기기에서 저장한 수정은 먼저 파일에 보관하고, 연결이 돌아오면 같은 requestId로 재전송한다.
    func queueHandover(_ caseId: String, edits: [String: String], revision: Int? = nil) {
        let old = records.byCase(caseId)
        let pending = PendingHandover(caseId: caseId, revision: revision ?? old?.handoverRevision ?? 0, edits: edits)
        // 이미 전송한 요청은 응답을 받을 때까지 보존한다(두 번째 수정은 다음 버전으로 처리).
        var outbox = records.pending
        if let index = outbox.firstIndex(where: { $0.caseId == caseId && $0.requestId != recordRequest?.id }) { outbox.remove(at: index) }
        outbox.append(pending)
        guard records.savePending(outbox) else { show("수정 대기열을 저장하지 못했습니다."); return }
        syncRecords()
    }

    func resolveHandover(useMine: Bool) {
        guard let conflict = handoverConflict else { return }
        let mine = records.pending.last { $0.caseId == conflict.caseId }
        var outbox = records.pending.filter { $0.caseId != conflict.caseId }
        if useMine, let mine {
            outbox.append(PendingHandover(caseId: conflict.caseId, revision: conflict.handoverRevision ?? 0, edits: mine.edits))
        }
        guard records.savePending(outbox) else { return }
        if !useMine { Handover.saveEdits(conflict.caseId, conflict.handoverEdits ?? [:]) }
        handoverConflict = nil
        syncRecords()
    }
}


// MARK: - 같은 구급대의 아이폰·아이패드 수동 수정 동기화
extension PhoneModel {
    func syncLiveCase() {
        caseEdits.onUpdate = { [weak self] in
            guard let self, let id = self.caseId else { return }
            Handover.saveEdits(id, self.caseEdits.handover)
            self.applySharedBody()
            self.recordsRev += 1
        }
        caseEdits.activate(caseId: caseId, apid: apid, server: Settings.hubBase, initialHandover: Handover.loadEdits(caseId)) { [weak self] data in
            self?.ambulance?.sendJSON(data) ?? false
        }
    }
    func shareHandover(caseId: String, draft: [String: String], auto: [String: String], touched: Set<String>, base: [String: String]) {
        var changes: [String: String?] = [:]
        for id in touched {
            let value = (draft[id] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            changes["h:" + id] = .some(value == (auto[id] ?? "").trimmingCharacters(in: .whitespacesAndNewlines) ? nil : value)
        }
        if !caseEdits.submit(caseId: caseId, changes: changes, base: base) { show("사건이 변경되어 저장하지 못했습니다.") }
    }
    func shareBody(_ mark: BodyMark, base: [String: String]) {
        guard let id = caseId else { return }
        let r = mark.region
        let side = mark.side == .left ? "좌" : mark.side == .right ? "우" : ""
        let key = "b:" + r.label + ":" + side
        let body = SharedBodyValue(added: bodyEdits.added.contains(mark), removed: bodyEdits.removed.contains(mark), cares: bodyEdits.fittedCares[mark] ?? [])
        guard let data = try? JSONEncoder().encode(body), let value = String(data: data, encoding: .utf8) else { return }
        _ = caseEdits.submit(caseId: id, changes: [key: value], base: base)
    }
    private func applySharedBody() {
        var edits = BodyEdits()
        for (key, text) in caseEdits.fields where key.hasPrefix("b:") {
            let parts = key.split(separator: ":", omittingEmptySubsequences: false).map(String.init)
            guard parts.count == 3, let region = BodyRegion.allCases.first(where: {  $0.label == parts[1] }),
                  let data = text.data(using: .utf8), let value = try? JSONDecoder().decode(SharedBodyValue.self, from: data) else { continue }
            let side: BodySide = parts[2] == "좌" ? .left : parts[2] == "우" ? .right : .unknown
            let mark = BodyMark(region, side)
            if value.added { edits.added.insert(mark) }
            if value.removed { edits.removed.insert(mark) }
            let fitted = value.cares.filter { BodyCare.fits(mark, $0) }
            if !fitted.isEmpty { edits.cares[mark] = fitted }
        }
        bodyEdits = edits
    }
}
