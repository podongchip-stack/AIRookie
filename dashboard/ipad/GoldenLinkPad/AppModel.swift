import Foundation
import SwiftUI

/// 앱 상태 — hub 메시지를 받아 사건·구급차·병원 목록을 들고, 화면이 그린다. hub에는 identify 외에 보내지 않는다.
@MainActor
final class AppModel: ObservableObject {
    struct CaseState: Identifiable {
        let caseId: String
        var meta: CaseMeta?
        var overview: MonitorCase?
        var id: String { caseId }

        var num: Int? { overview?.num ?? meta?.num }
        var severity: String? { overview?.severityTag ?? meta?.severity }
        /// KTAS — voice v2가 준 값. 없으면(매칭 전·예전 voice) 중증도로 추정(중증 2 · 중등증 3 · 경증 4)
        var ktas: Int {
            if let k = overview?.ktasLevel, (1...5).contains(k) { return k }
            switch severity { case "high": return 2; case "medium": return 3; case "low": return 4; default: return 3 }
        }
        var ktasEstimated: Bool { !((1...5).contains(overview?.ktasLevel ?? 0)) }
        var symptom: String? { overview?.symptom ?? meta?.symptom }
        var apid: String? { overview?.apid ?? meta?.apid }
        var ambulanceName: String? { overview?.ambulanceName ?? meta?.ambulanceName }
        var startedAt: String? { overview?.startedAt ?? meta?.startedAt }
        var hospitals: [CaseHospital] { overview?.hospitals ?? [] }
        var events: [CaseEvent] { overview?.events ?? meta?.events ?? [] }
        var confirmed: CaseHospital? { hospitals.first { $0.status == "confirmed" } }
        var matched: Bool { overview != nil }
        var counts: (pending: Int, approved: Int, rejected: Int, confirmed: Int) {
            var p = 0, a = 0, r = 0, c = 0
            for h in hospitals {
                switch h.status { case "approved": a += 1; case "rejected": r += 1; case "confirmed": c += 1; default: p += 1 }
            }
            return (p, a, r, c)
        }
    }

    @Published var overview: MapOverview?
    @Published var cases: [String: CaseState] = [:]
    @Published var sims: [String: AmbulanceSimState] = [:]
    @Published var selectedCaseId: String?
    @Published var connection: HubSocket.State = .connecting
    @Published var now = Date()
    @Published var closedLog: [CaseEvent] = []
    @Published var liveBoard: LiveBoard?
    @Published var liveBoardError: String?
    @Published var liveBoardLoading = false
    @Published var liveBoardFetchedAt: Date?

    private var socket: HubSocket?
    private var clock: Timer?
    private var started = false
    private var hospitalGps: [String: GpsPoint] = [:]

    var orderedCases: [CaseState] { cases.values.sorted { ($0.num ?? Int.max, $0.caseId) < ($1.num ?? Int.max, $1.caseId) } }
    var selectedCase: CaseState? {
        if let id = selectedCaseId, let c = cases[id] { return c }
        return orderedCases.first
    }

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

    /// 설정이 바뀌었을 때 — 소켓을 새 주소로 다시 붙이고 보드를 다시 받는다
    func reconnect() {
        socket?.close()
        socket = nil
        cases = [:]; sims = [:]; overview = nil; hospitalGps = [:]
        connect()
        liveBoard = nil; liveBoardError = nil
        fetchLiveBoard()
    }

    private func connect() {
        socket = HubSocket(role: "monitor", id: "ipad",
                           onMessage: { [weak self] type, data in self?.handle(type, data) },
                           onState: { [weak self] s in self?.connection = s })
    }

    // ── 위치 ──
    func position(of c: CaseState) -> GpsPoint? {
        if let apid = c.apid, let inc = sims[apid]?.incident { return inc }
        return c.overview?.ambulanceGps
    }
    func sim(for c: CaseState) -> AmbulanceSimState? { c.apid.flatMap { sims[$0] } }
    func gps(of hospitalId: String) -> GpsPoint? { hospitalGps[hospitalId] }
    func ambulanceName(_ apid: String) -> String { overview?.ambulances.first { $0.apid == apid }?.name ?? apid }

    // ── 메시지 ──
    private func handle(_ type: String, _ data: Data) {
        let dec = JSONDecoder()
        switch type {
        case "map_overview":
            if let m = try? dec.decode(MapOverview.self, from: data) {
                overview = m
                for h in m.hospitals { hospitalGps[h.hospitalId] = h.gps }
            }
        case "case_meta":
            if let m = try? dec.decode(CaseMeta.self, from: data) {
                var c = cases[m.caseId] ?? CaseState(caseId: m.caseId)
                c.meta = m
                cases[m.caseId] = c
                if selectedCaseId == nil || cases[selectedCaseId!] == nil { selectedCaseId = m.caseId }
            }
        case "case_overview":
            if let m = try? dec.decode(MonitorCase.self, from: data) {
                var c = cases[m.caseId] ?? CaseState(caseId: m.caseId)
                c.overview = m
                cases[m.caseId] = c
                for h in m.hospitals { if let g = h.gps { hospitalGps[h.hospitalId] = g } }
                if selectedCaseId == nil || cases[selectedCaseId!] == nil { selectedCaseId = m.caseId }
            }
        case "case_closed":
            if let m = try? dec.decode(CaseClosed.self, from: data), let c = cases[m.caseId] {
                closedLog.append(CaseEvent(t: ISO8601DateFormatter().string(from: Date()), kind: "c",
                                           text: "#\(c.num.map(String.init) ?? "?") 사건 종료 (\(m.reason ?? ""))"))
                cases[m.caseId] = nil
                if selectedCaseId == m.caseId { selectedCaseId = orderedCases.first?.caseId }
            }
        case "case_sync":
            if let m = try? dec.decode(CaseSync.self, from: data) {
                let keep = Set(m.caseIds)
                for id in cases.keys where !keep.contains(id) { cases[id] = nil }
                if let sel = selectedCaseId, cases[sel] == nil { selectedCaseId = orderedCases.first?.caseId }
            }
        case "ambulance_phase":
            if let m = try? dec.decode(AmbulanceSimState.self, from: data) { sims[m.apid] = m }
        case "ambulance_position":
            if var m = try? dec.decode(AmbulanceSimState.self, from: data) {
                if m.path == nil { m.path = sims[m.apid]?.path }
                sims[m.apid] = m
            }
        default:
            break
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
