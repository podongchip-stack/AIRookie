import Foundation
import SwiftUI

extension Notification.Name {
    /// 화면 자동 전환 요청 — userInfo ["screen": Screen.rawValue]. RootView가 받아 바꾼다(2026-10-16)
    static let switchScreen = Notification.Name("switchScreen")
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
    // 연결
    @Published var connection: HubSocket.State = .connecting {
        didSet { if connection == .live, oldValue != .live { liveSince = Date() } }
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

    // 공통
    @Published var now = Date()
    @Published var liveBoard: LiveBoard?
    @Published var liveBoardError: String?
    @Published var liveBoardLoading = false
    @Published var liveBoardFetchedAt: Date?

    private var monitor: HubSocket?
    private var ambulance: HubSocket?
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
                // 라이브 보드는 서버가 20분 캐시 — 10분마다 다시 받는다
                if let at = self.liveBoardFetchedAt, Date().timeIntervalSince(at) > 600, !self.liveBoardLoading { self.fetchLiveBoard() }
            }
        }
        fetchLiveBoard()
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
        guard let next, !next.isEmpty else { return }
        ambulance = HubSocket(role: "ambulance", id: next,
                              onMessage: { [weak self] t, d in self?.handleAmbulance(t, d) },
                              onState: { [weak self] s in self?.connection = s })
    }

    private func clearCase() {
        sim = nil; result = nil; scene = nil; callStatus = nil; transcript = []; pendingConfirmId = nil; receivedAt = nil
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
        switch type {
        case "identity_info":
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
                // 이송 확정이 처음 보이면(hub 응답) 구급차 지도로
                let firstForCase = result?.caseId != m.caseId
                let wasConfirmed = confirmed != nil
                result = m
                if firstForCase, (m.patientInfo?.callRound ?? 1) <= 1 { requestScreen(.hospitals) }
                if !wasConfirmed, confirmed != nil { requestScreen(.ambulance) }
                receivedAt = Date()
                if m.ambulanceName != nil { ambulanceName = m.ambulanceName }
                if let p = pendingConfirmId, m.hospitals.contains(where: { $0.hospitalId == p && $0.status == "confirmed" }) { pendingConfirmId = nil }
            }
        case "scene_candidates":
            if let m = try? dec.decode(SceneCandidates.self, from: data) {
                if let c = sim?.caseId, c != m.caseId { return }
                scene = m
            }
        case "ambulance_phase", "ambulance_position":
            if let m = try? dec.decode(AmbulanceSimState.self, from: data), m.apid == apid {
                let previousCase = sim?.caseId
                sim = m
                // 새 출동(다른 caseId)이 시작되면 지난 사건 화면을 비운다
                if let c = m.caseId, c != previousCase {
                    if result?.caseId != c { result = nil }
                    if scene?.caseId != c { scene = nil }
                    transcript = []
                }
                // 사건이 끝나 기지로(복귀·대기) — 결과를 접는다
                if m.caseId == nil, ["idle", "returning"].contains(m.phase) { result = nil; scene = nil; callStatus = nil; transcript = []; pendingConfirmId = nil }
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
                result = nil; scene = nil; callStatus = nil; transcript = []; pendingConfirmId = nil
            }
        case "case_sync":
            if let m = try? dec.decode(CaseSync.self, from: data) {
                let keep = Set(m.caseIds)
                if let c = result?.caseId, !keep.contains(c) { result = nil }
                if let c = scene?.caseId, !keep.contains(c), sim?.caseId != c { scene = nil }
            }
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

    private func requestScreen(_ s: Screen) {
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
