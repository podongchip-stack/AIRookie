import Foundation
import SwiftUI

extension Notification.Name {
    /// 화면 자동 전환 요청 — userInfo ["screen": Screen.rawValue]. RootView가 받아 바꾼다(2026-10-16)
    static let switchScreen = Notification.Name("switchScreen")
}

/// 병원 응답 기록 한 줄(2026-10-16) — 매칭 결과가 올 때마다 병원별 상태를 직전과 비교해 바뀐 것만 남긴다(시각 = 이 패드가 받은 때)
struct ResponseEvent: Identifiable {
    let id = UUID()
    let at: Date
    let hospital: String
    let text: String
    let kind: String   // approved | rejected | unavailable | confirmed | zone
}

/// "더 나은 병원"(이송 중 목적지 변경 제안, 2026-10-16) — 지금 목적지보다 도착 시 병상 정보가 맞을 확률이 높은 승인 병원
struct BetterHospital: Identifiable {
    let match: HospitalMatch
    let rArrive: Double
    var id: String { match.hospitalId }
    var bedText: String {
        if match.bedCountUnknown == true { return "병상 미상" }
        return "병상 \(match.availableBedCount ?? 0)석"
    }
}

/// 앱 상태 — 이 아이패드가 실린 구급차 한 대의 화면(웹 /ambulance?id=와 같은 역할).
/// 구급차 소켓(role=ambulance)으로 자기 사건(매칭 결과·현장 후보·통화·이동)을 받고, apid가 "auto"면 감시 소켓(role=monitor)으로
/// 출동하는 구급차를 찾아 그 구급차로 넘어간다(웹 AmbulanceAutoFollow · 아이폰 앱과 같은 규칙).
@MainActor
final class AppModel: ObservableObject {
    let caseEdits = CaseEditSync()
    @Published var handoverVersion = 0
    @Published var accessRequired = Settings.accessCode.isEmpty

    // 연결
    @Published var connection: HubSocket.State = .connecting {
        didSet {
            if connection == .live, oldValue != .live { liveSince = Date(); recordRequest = nil; syncRecords() }
            else if connection != .live { recordSyncStatus = "오프라인 · 기기 기록 표시 중" }
        }
    }
    /// 소켓이 막 연결된 직후엔 따라잡기(지난 결과 재전송)가 쏟아진다 — 그건 "음성 도착"이 아니라 자동 전환하지 않는다
    private var liveSince: Date?
    @Published private(set) var apid: String?        // 지금 따라가는 구급차(auto면 출동 전엔 nil)
    @Published var ambulanceName: String?
    @Published var simDispatch = false

    // 이 구급차의 상태
    @Published var sim: AmbulanceSimState?
    @Published var result: HubMatchResult?
    @Published var scene: SceneCandidates?
    @Published var callStatus: CallStatus?
    @Published var transcript: [CallTranscriptLine] = []
    @Published var pendingConfirmId: String?
    @Published var notice: String?
    @Published var receivedAt: Date?
    /// 사고 현장 주소(인계확인서 "출발지 주소") — hub가 좌표를 주소로 바꿔 준다. 못 구하면 nil이고 그때만 좌표를 적는다
    @Published var incidentAddress: String?
    /// 인계확인서(출동 및 처치 기록지)의 시각 칸 — 출동 단계가 바뀐 **그 순간**을 적어 둔다.
    /// hub는 단계만 보내고 시각은 안 보내므로 앱이 기억한다. 사건이 바뀌면 지운다
    @Published var phaseTimes: [String: Date] = [:]
    /// 외상 도해에서 구급대원이 **탭으로 고친 것**(2026-10-28) — 부위 추가·제외와 부위별 처치.
    /// hub로는 `patient_override.injuryStatus`로, 인계확인서로는 처치 칸으로 흘러간다. 사건이 바뀌면 비운다
    @Published var bodyEdits = BodyEdits()
    /// 구급차 소켓을 붙인 시각 — 연결 직후 오는 **따라잡기**(진행 중이던 사건)는 화면을 자동으로 바꾸지 않는다(README의 규칙)
    private var connectedAt: Date?
    @Published var responseLog: [ResponseEvent] = []
    /// 현장 Pre-KTAS(1~5) — 현장에 도착하면 1이 미리 골라져 있고, 바꾸면 hub가 첫 연락 추천 순서로 후보를 다시 보낸다(현장 화면)
    var needsInitialMapCenter = true
    @Published var preKtas: Int?
    /// 통화 요약이 후보 병원들에 전달되는 연출(현장 지도 위, SceneScreen) — 끝나면 환자 정보로 넘어간다
    @Published var deliveryShow: DeliveryShow?

    /// 지난 사건 기록([기록] 화면) — 날짜별로 기기에 쌓고 hub 보관소와 동기화한다(RecordSync.swift). 바뀔 때마다 recordsRev가 올라 화면이 다시 읽는다
    let records = RecordStore()
    @Published var recordsRev = 0
    @Published var recordSyncStatus = "구급차를 선택하면 기록을 동기화합니다."
    @Published var handoverConflict: CaseRecord?
    var recordRequest: (id: String, at: Date)?
    private var recordSyncTask: Task<Void, Never>?

    // 공통
    @Published var now = Date()
    @Published var liveBoard: LiveBoard?
    @Published var liveBoardError: String?
    @Published var liveBoardLoading = false
    @Published var liveBoardFetchedAt: Date?

    private var monitor: HubSocket?
    var ambulance: HubSocket?
    private var monitorSims: [String: AmbulanceSimState] = [:]
    private var clock: Timer?
    private var started = false
    private var noticeTask: Task<Void, Never>?

    var autoFollow: Bool { Settings.apid.trimmingCharacters(in: .whitespaces).lowercased() == "auto" }

    /// 지금 사건 id — 출동 시뮬레이션이 들고 있는 caseId가 기준(웹과 같음), 없으면 매칭 결과·현장 후보
    var caseId: String? { sim?.caseId ?? result?.caseId ?? scene?.caseId }
    /// "사고가 발생했는가" — 출동 중·현장·이송·도착·재선택 중이거나 이 구급차 사건의 결과가 있으면 true
    var hasIncident: Bool {
        if let s = sim, s.caseId != nil, !["idle", "returning"].contains(s.phase) { return true }
        return result != nil || scene != nil
    }
    var confirmed: HospitalMatch? { result?.hospitals.first { $0.status == "confirmed" } }
    var paused: Bool { sim?.paused == true && sim?.pauseReason != "call" || result?.paused == true }

    func start() {
        guard !started else { return }
        started = true
        connect()
        clock = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self else { return }
                self.now = Date()
                self.caseEdits.tick()
                // 라이브 보드는 서버가 20분 캐시 — 10분마다 다시 받는다
                if let at = self.liveBoardFetchedAt, Date().timeIntervalSince(at) > 600, !self.liveBoardLoading { self.fetchLiveBoard() }
            }
        }
        fetchLiveBoard()
        recordSyncTask = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                do { try await Task.sleep(for: .seconds(15)) } catch { return }
                self?.syncRecords()
                if let self, self.sim?.phase == "on_scene", self.result == nil, self.preKtas != nil { self.requestFirstCall() }
            }
        }
    }

    /// 설정이 바뀌었을 때 — 소켓을 새 주소·새 구급차로 다시 붙이고 보드를 다시 받는다
    func reconnect() {
        monitor?.close(); monitor = nil
        ambulance?.close(); ambulance = nil
        apid = nil
        clearCase()
        monitorSims = [:]
        connect()
        liveBoard = nil; liveBoardError = nil
        fetchLiveBoard()
    }

    /// 구급대 코드 변경 시 이전 소켓·사건·타이머를 정리하고 입장 화면으로 돌아간다.
    func changeAccessCode() {
        monitor?.close(); monitor = nil
        ambulance?.close(); ambulance = nil
        clock?.invalidate(); clock = nil
        recordSyncTask?.cancel(); recordSyncTask = nil
        records.configure(apid: nil); recordsRev += 1
        noticeTask?.cancel(); noticeTask = nil
        started = false
        apid = nil; ambulanceName = nil
        monitorSims = [:]
        clearCase()
        liveBoard = nil; liveBoardError = nil; liveBoardFetchedAt = nil
        Settings.accessCode = ""
        accessRequired = true
    }

    private func connect() {
        if autoFollow {
            monitor = HubSocket(role: "monitor", id: "ipad-auto",
                                onMessage: { [weak self] t, d in self?.handleMonitor(t, d) },
                                onState: { [weak self] s in if self?.ambulance == nil { self?.connection = s } })
        } else {
            follow(Settings.apid.trimmingCharacters(in: .whitespaces))
        }
    }

    private func follow(_ next: String?) {
        guard next != apid || (next != nil && ambulance == nil) else { return }
        ambulance?.close(); ambulance = nil
        apid = next
        clearCase()
        ambulanceName = nil
        records.configure(apid: (next?.isEmpty ?? true) ? nil : next)
        recordRequest = nil; handoverConflict = nil; recordsRev += 1
        recordSyncStatus = "기록 연결 대기 중"
        guard let next, !next.isEmpty else { return }
        connectedAt = Date()
        ambulance = HubSocket(role: "ambulance", id: next,
                              onMessage: { [weak self] t, d in self?.handleAmbulance(t, d) },
                              onState: { [weak self] s in self?.connection = s })
    }

    private func clearCase() {
        sim = nil; result = nil; scene = nil; callStatus = nil; transcript = []; pendingConfirmId = nil; responseLog = []; receivedAt = nil; phaseTimes = [:]; incidentAddress = nil; bodyEdits = BodyEdits(); preKtas = nil; deliveryShow = nil
    }

    // ── 자동 따라가기(monitor 소켓) ──
    private func handleMonitor(_ type: String, _ data: Data) {
        guard type == "ambulance_phase" || type == "ambulance_position",
              let m = try? JSONDecoder().decode(AmbulanceSimState.self, from: data) else { return }
        monitorSims[m.apid] = m
        func active(_ s: AmbulanceSimState?) -> Bool { s?.caseId != nil && !["idle", "returning"].contains(s?.phase ?? "idle") }
        // 지금 보는 구급차의 사건이 진행 중이면 넘어가지 않는다
        if let apid, active(monitorSims[apid]) { return }
        let next = monitorSims.values.filter { active($0) }.map(\.apid).sorted().first
        if let next { follow(next) }
        else if let apid, let s = monitorSims[apid], s.caseId == nil, ["idle", "returning"].contains(s.phase) { follow(nil) }
    }

    // ── 구급차 소켓 ──
    private func handleAmbulance(_ type: String, _ data: Data) {
        let dec = JSONDecoder()
        defer { syncLiveCase() }
        switch type {
        case "live_case_state", "live_case_error":
            caseEdits.accept(data)
        case "identity_info":
            syncLiveCase()
            caseEdits.reconnect()
            if let m = try? dec.decode(IdentityInfo.self, from: data) {
                ambulanceName = m.name ?? ambulanceName
                simDispatch = m.simDispatch ?? simDispatch
            }
        case "match_result":
            if let m = try? dec.decode(HubMatchResult.self, from: data) {
                if let apid, let a = m.apid, a != apid { return }
                // 출동 시뮬레이션이 다른 사건을 들고 있으면 지난 사건의 따라잡기는 무시
                if let c = sim?.caseId, c != m.caseId { return }
                // 자동 전환(2026-10-16): 이 사건의 매칭 결과가 처음 오면(=음성 요약 도착, 추가 통화 회차 제외) 병원 리스트로,
                let firstForCase = result?.caseId != m.caseId
                logResponses(old: firstForCase ? nil : result, new: m)
                result = m
                snapshotCase(m.caseId)
                let catchup = Date().timeIntervalSince(connectedAt ?? .distantPast) < 3
                if firstForCase, !catchup, (m.patientInfo?.callRound ?? 1) <= 1 { startDeliveryShow(m) }
                receivedAt = Date()
                if m.ambulanceName != nil { ambulanceName = m.ambulanceName }
                if let p = pendingConfirmId, m.hospitals.contains(where: { $0.hospitalId == p && $0.status == "confirmed" }) { pendingConfirmId = nil }
            }
        case "scene_candidates":
            if let m = try? dec.decode(SceneCandidates.self, from: data) {
                if let c = sim?.caseId, c != m.caseId { return }
                scene = m
                // 다른 기기에서 바꾼 Pre-KTAS도 지도와 선택 버튼에 함께 반영한다.
                preKtas = m.preKtas
            }
        case "ambulance_phase", "ambulance_position":
            if var m = try? dec.decode(AmbulanceSimState.self, from: data), m.apid == apid {
                m.path = RoadRoute.retainedPath(m.path, previous: sim?.path,
                    sameLeg: sim?.caseId == m.caseId && sim?.phase == m.phase && sim?.hospitalId == m.hospitalId,
                    positionOnly: type == "ambulance_position")
                let previousCase = sim?.caseId
                let previousPhase = sim?.phase
                let previousIncident = sim?.incident
                sim = m
                // 새 출동(다른 caseId)이 시작되면 지난 사건 화면을 비운다 — 시각 칸을 먼저 비우고 나서
                // 이번 단계를 적는다(순서가 반대면 방금 적은 출동·현장도착 시각이 지워진다)
                if let c = m.caseId, c != previousCase {
                    if result?.caseId != c { result = nil }
                    if scene?.caseId != c { scene = nil }
                    transcript = []
                    phaseTimes = ["requestedAt": Date()]      // 새 사건 — 시각 칸을 새로 적는다
                    incidentAddress = nil
                    bodyEdits = BodyEdits()
                    preKtas = nil; deliveryShow = nil
                    requestScreen(.map)      // 새 출동은 지도에서 시작한다(안드로이드와 같은 흐름)
                }
                if m.phase == "on_scene", m.phase != previousPhase || m.caseId != previousCase, preKtas == nil, scene?.preKtasCleared != true, result == nil { preKtas = 1; requestFirstCall() }
                if m.phase != previousPhase || m.caseId != previousCase { recordPhaseTime(m.phase); if let c = m.caseId { snapshotCase(c) } }
                if m.incident?.lat != previousIncident?.lat || m.incident?.lng != previousIncident?.lng {
                    incidentAddress = nil
                    if let p = m.incident { fetchIncidentAddress(p) }
                }
                // 사건이 끝나 기지로(복귀·대기) — 결과를 접는다
                if m.caseId == nil, ["idle", "returning"].contains(m.phase) { result = nil; scene = nil; callStatus = nil; transcript = []; pendingConfirmId = nil; responseLog = [] }
            }
        case "call_status":
            if let m = try? dec.decode(CallStatus.self, from: data), m.apid == nil || m.apid == apid { callStatus = m }
        case "call_transcript":
            if let m = try? dec.decode(CallTranscriptLine.self, from: data), m.apid == nil || m.apid == apid {
                transcript.append(m)
                if transcript.count > 200 { transcript.removeFirst(transcript.count - 200) }
            }
        case "case_closed":
            if let m = try? dec.decode(CaseClosed.self, from: data), m.caseId == result?.caseId || m.caseId == scene?.caseId {
                closeRecord(m.caseId)
                result = nil; scene = nil; callStatus = nil; transcript = []; pendingConfirmId = nil; responseLog = []
            }
        case "case_sync":
            if let m = try? dec.decode(CaseSync.self, from: data) {
                let keep = Set(m.caseIds)
                if let c = result?.caseId, !keep.contains(c) { closeRecord(c); result = nil }
                if let c = scene?.caseId, !keep.contains(c), sim?.caseId != c { scene = nil }
            }
        case "records_changed":
            syncRecords()
        case "record_sync_result", "record_import_result", "record_handover_result", "record_error":
            handleRecordReply(type, data)
        case "action_refused":
            if let m = try? dec.decode(ActionRefused.self, from: data) {
                pendingConfirmId = nil
                show(m.reason == "paused" ? "현재 시연 일시정지 중입니다." : "hub가 요청을 거부했습니다 (\(m.reason ?? ""))")
            }
        default:
            break
        }
    }

    // ── 이송 승인(구급대원 판단) — 웹 handleApprove와 같은 형식. 병원이 승인한 병원에만 버튼이 열린다 ──
    func approve(_ hospitalId: String) {
        if paused { show("현재 시연 일시정지 중입니다."); return }
        guard let caseId = result?.caseId ?? caseId, let ambulance else { return }
        pendingConfirmId = hospitalId
        if !ambulance.send(ApprovalAction(caseId: caseId, hospital_id: hospitalId, timestamp: ISO.now())) {
            pendingConfirmId = nil
            show("hub에 연결되지 않아 보내지 못했습니다.")
        }
    }

    /// 출동 단계 → 인계확인서 시각 칸(이미 적힌 칸은 덮지 않는다 — 처음 그 단계에 들어간 때가 맞다)
    private func recordPhaseTime(_ phase: String) {
        let key: String?
        switch phase {
        case "dispatching": key = "dispatchedAt"
        case "on_scene": key = "sceneArrivedAt"
        case "transporting": key = "transportStartedAt"
        case "at_hospital": key = "transportEndedAt"
        default: key = nil
        }
        // 출동 단계 전환을 못 본 채(앱을 늦게 켜거나 재연결) 진행 중인 사건을 받았으면, 적어도 '출동 일시'는
        // 이 사건을 처음 본 때로 적어 둔다 — 서식의 필수 칸이고 비워 두면 사람이 되짚어 적어야 한다
        if ["on_scene", "transporting", "at_hospital", "rerouting"].contains(phase), phaseTimes["dispatchedAt"] == nil {
            phaseTimes["dispatchedAt"] = Date()
        }
        guard let key, phaseTimes[key] == nil else { return }
        phaseTimes[key] = Date()
        if phaseTimes["requestedAt"] == nil { phaseTimes["requestedAt"] = Date() }
    }

    /// 사고 현장 좌표 → 주소(hub 대리 호출). 실패하면 조용히 둔다 — 인계확인서가 좌표를 그대로 적는다
    private func fetchIncidentAddress(_ point: GpsPoint) {
        guard let url = Settings.reverseGeocodeURL(point) else { return }
        Task { @MainActor in
            guard let (data, resp) = try? await URLSession.shared.data(from: url),
                  (resp as? HTTPURLResponse)?.statusCode == 200,
                  let body = try? JSONDecoder().decode([String: String?].self, from: data),
                  let address = body["address"] ?? nil, !address.isEmpty else { return }
            // 늦게 온 응답이 다른 사건을 덮지 않게 — 지금 사건의 좌표일 때만
            if sim?.incident?.lat == point.lat, sim?.incident?.lng == point.lng { incidentAddress = address }
        }
    }

    // ── 추가 정보 전송(2026-10-26) — 통화 요약에 없는 것을 구급대원이 적어 후보 병원들에 보낸다 ──
    /// 보냈으면 true. hub는 patient_override로 받아 PatientInfo.extraNotes에 쌓고 같은 사건의 후보 병원 탭에 다시 보낸다
    /// (순위 칸이 아니라 재매칭·승인 초기화는 없다).
    func sendExtraNote(_ text: String) -> Bool {
        let note = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if paused { show("현재 시연 일시정지 중입니다."); return false }
        guard !note.isEmpty else { return false }
        guard let caseId = result?.caseId ?? caseId, let ambulance else {
            show("진행 중인 사건이 없어 보내지 못했습니다."); return false
        }
        if !ambulance.send(ExtraNoteMessage(caseId: caseId, extraNote: note, timestamp: ISO.now())) {
            show("hub에 연결되지 않아 보내지 못했습니다."); return false
        }
        show("추가 정보를 병원에 전달했습니다.")
        return true
    }

    /// 통화 요약 확인·수정(2026-10-27) — 바뀐 칸만 담아 hub로 보낸다. hub가 환자 정보를 갈아 끼워(순위 칸이면 재매칭)
    /// 같은 사건의 후보 병원 탭·관제 지도·시연 콘솔에 갱신본을 다시 뿌리고, 요약 카드에 "구급대원 확인" 도장이 찍힌다
    func sendPatientOverride(expectedDiagnosis: String?, injuryStatus: [String]?,
                             ktasLevel: Int?, requiredDepartment: String?, chiefComplaint: String?) -> Bool {
        if paused { show("현재 시연 일시정지 중입니다."); return false }
        guard let caseId = result?.caseId ?? caseId, let ambulance else {
            show("진행 중인 사건이 없어 보내지 못했습니다."); return false
        }
        let msg = PatientOverrideMessage(caseId: caseId, expectedDiagnosis: expectedDiagnosis,
                                         injuryStatus: injuryStatus, ktasLevel: ktasLevel,
                                         requiredDepartment: requiredDepartment, chiefComplaint: chiefComplaint,
                                         timestamp: ISO.now())
        if !ambulance.send(msg) { show("hub에 연결되지 않아 보내지 못했습니다."); return false }
        let changed = [expectedDiagnosis != nil, injuryStatus != nil, ktasLevel != nil,
                       requiredDepartment != nil, chiefComplaint != nil].contains(true)
        show(changed ? "수정한 내용을 병원에 전달했습니다." : "통화 요약을 확인했습니다.")
        return true
    }

    /// 병원별 상태를 직전 결과와 비교해 바뀐 것만 응답 기록에 남긴다. 사건이 바뀌면 비운다(연결 직후 따라잡기엔 시각이 없어 남기지 않음)
    private func logResponses(old: HubMatchResult?, new m: HubMatchResult) {
        guard let old else { responseLog = []; return }
        func key(_ h: HospitalMatch) -> String { h.status == "pending" && h.unavailableReason != nil ? "unavailable" : h.status }
        let prev = Dictionary(old.hospitals.map { ($0.hospitalId, key($0)) }, uniquingKeysWith: { a, _ in a })
        let now = Date()
        var added: [ResponseEvent] = []
        for h in m.hospitals {
            let k = key(h)
            guard k != "pending", k != prev[h.hospitalId] else { continue }
            let text: String
            switch k {
            case "approved": text = "수용 승인"
            case "confirmed": text = "이송 확정"
            case "unavailable": text = "병상 없음(E-Gen)"
            default: text = "수용 불가" + (h.rejectReason.map { " · \(Labels.reject($0))" } ?? "")
            }
            added.append(ResponseEvent(at: now, hospital: h.name, text: text, kind: k))
        }
        let oldZone = old.zoneActive?.max() ?? 1, newZone = m.zoneActive?.max() ?? 1
        if newZone > oldZone {
            let fresh = m.hospitals.filter { prev[$0.hospitalId] == nil }.count
            added.append(ResponseEvent(at: now, hospital: "Zone \(newZone)", text: "요청 범위 확장 · 새 후보 \(fresh)곳", kind: "zone"))
        }
        if !added.isEmpty { responseLog = Array((added + responseLog).prefix(20)) }
    }

    func requestScreen(_ s: Screen) {
        guard let t = liveSince, Date().timeIntervalSince(t) > 3 else { return }
        NotificationCenter.default.post(name: .switchScreen, object: nil, userInfo: ["screen": s.rawValue])
    }

    // ── 더 나은 병원(2026-10-16) — 이송 중에만. 데이터 정확성 기준: 지금 목적지보다 "도착 때 그 병상 숫자가 아직 맞을 확률"(정보 생존
    // 모델, AI)이 15%p 이상 높은, 지금 보낼 수 있는 승인 병원. 최대 2곳, 확률 높은 순. hub 순위는 건드리지 않는 제안이고 바꿀지는
    // 구급대원이 [변경] → 확인으로 정한다(이송 승인과 같은 요청). 목적지에 확률이 없으면(모델 값 없음·병상 미상) 비교할 수 없어 안 띄운다.
    static let betterMarginP = 0.15
    var destinationRArrive: Double? {
        confirmed?.bedReliability.map { BedReliability.live($0, now: now).rArrive }
    }
    var betterHospitals: [BetterHospital] {
        guard sim?.phase == "transporting", let r = result, let c = confirmed, let base = destinationRArrive else { return [] }
        return r.hospitals
            .filter { $0.hospitalId != c.hospitalId && HospitalRules.canTransportNow($0) }
            .compactMap { h -> BetterHospital? in
                guard let br = h.bedReliability else { return nil }
                let p = BedReliability.live(br, now: now).rArrive
                return p >= base + Self.betterMarginP ? BetterHospital(match: h, rArrive: p) : nil
            }
            .sorted { $0.rArrive > $1.rArrive }
            .prefix(2).map { $0 }
    }

    // ── 현장 Pre-KTAS · 요약 전달 연출 ──
    func setPreKtas(_ k: Int) { preKtas = k; requestFirstCall() }

    /// hub에 첫 연락 추천 순서를 다시 요청한다 — hub가 scene_candidates를 그 Pre-KTAS 기준으로 다시 보낸다
    func requestFirstCall() {
        guard let caseId, let k = preKtas else { return }
        let body: [String: Any] = ["type": "first_call_request", "caseId": caseId, "ktas": k]
        guard let data = try? JSONSerialization.data(withJSONObject: body), ambulance?.sendJSON(data) == true else {
            show("hub 연결을 확인해 주세요. 추천 요청을 보내지 못했습니다."); return
        }
    }

    /// 요약이 반영되면 환자 정보로 바로 넘기지 않고, 현장 지도에서 병원들로 전달되는 연출을 먼저 보여 준다.
    /// 현장이 아니거나 지도에 찍을 병원 좌표가 없으면 연출 없이 바로 넘어간다
    private func startDeliveryShow(_ m: HubMatchResult) {
        let anyTarget = m.hospitals.contains { $0.gps != nil } || (scene?.hospitals.contains { $0.gps != nil } ?? false)
        guard sim?.phase == "on_scene", sim?.gps != nil || sim?.incident != nil, anyTarget else { requestScreen(.patient); return }
        let reduce = UIAccessibility.isReduceMotionEnabled
        let show = DeliveryShow(caseId: m.caseId, durationMs: reduce ? 1200 : 2600, reduceMotion: reduce)
        deliveryShow = show
        requestScreen(.map)
        // 연출이 멈춰도 여기서 반드시 끝낸다
        Task { @MainActor [weak self] in
            try? await Task.sleep(for: .milliseconds(Int(show.durationMs) + 5000))
            if self?.deliveryShow?.caseId == show.caseId { self?.finishDelivery() }
        }
    }

    func finishDelivery() {
        guard deliveryShow != nil else { return }
        deliveryShow = nil
        requestScreen(.patient)      // 연출이 끝났거나 눌러서 건너뛰었다 — 환자 정보로
    }

    func show(_ text: String) {
        notice = text
        noticeTask?.cancel()
        noticeTask = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(2500))
            if !Task.isCancelled { self?.notice = nil }
        }
    }

    // ── 정보 생존 모델 라이브 보드 ──
    func fetchLiveBoard() {
        guard let url = Settings.liveBoardURL, !liveBoardLoading else { return }
        liveBoardLoading = true
        Task {
            defer { liveBoardLoading = false }
            do {
                var req = URLRequest(url: url)
                req.timeoutInterval = 100   // 첫 생성이 수십 초(이후 20분 캐시)
                let (data, resp) = try await URLSession.shared.data(for: req)
                let board = try JSONDecoder().decode(LiveBoard.self, from: data)
                if let err = board.error, (resp as? HTTPURLResponse)?.statusCode != 200 {
                    liveBoardError = err
                } else {
                    liveBoard = board; liveBoardError = nil
                }
                liveBoardFetchedAt = Date()
            } catch {
                liveBoardError = "라이브 보드를 받지 못했습니다: \(error.localizedDescription)"
                liveBoardFetchedAt = Date()
            }
        }
    }
}


// MARK: - 같은 구급대의 아이폰·아이패드 수동 수정 동기화
extension AppModel {
    func syncLiveCase() {
        caseEdits.onUpdate = { [weak self] in
            guard let self, let id = self.caseId else { return }
            Handover.saveEdits(id, self.caseEdits.handover)
            self.applySharedBody()
            self.handoverVersion += 1
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
        let key = "b:" + r.rawValue + ":" + side
        let body = SharedBodyValue(added: bodyEdits.added.contains(mark), removed: bodyEdits.removed.contains(mark), cares: bodyEdits.fittedCares[mark] ?? [])
        guard let data = try? JSONEncoder().encode(body), let value = String(data: data, encoding: .utf8) else { return }
        _ = caseEdits.submit(caseId: id, changes: [key: value], base: base)
    }
    private func applySharedBody() {
        var edits = BodyEdits()
        for (key, text) in caseEdits.fields where key.hasPrefix("b:") {
            let parts = key.split(separator: ":", omittingEmptySubsequences: false).map(String.init)
            guard parts.count == 3, let region = BodyRegion.allCases.first(where: { $0.rawValue == parts[1] }),
                  let data = text.data(using: .utf8), let value = try? JSONDecoder().decode(SharedBodyValue.self, from: data) else { continue }
            let side: BodySide = parts[2] == "좌" ? .left : parts[2] == "우" ? .right : .unknown
            let mark = BodyMark(region: region, side: side)
            if value.added { edits.added.insert(mark) }
            if value.removed { edits.removed.insert(mark) }
            let fitted = value.cares.filter { BodyCare.fits(mark, $0) }
            if !fitted.isEmpty { edits.cares[mark] = fitted }
        }
        bodyEdits = edits
    }
}
