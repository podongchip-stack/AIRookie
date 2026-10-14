import Foundation
import SwiftUI

// 상황판 — 구급차 한 대가 아니라 **전체 상황**(대량사고처럼 사건이 여러 건 동시에 진행될 때). hub에 관제 지도와 같은 역할
// (role=monitor)로 붙어 모든 사건의 요약(case_overview)·매칭 전 사건(case_meta)·병원 목록(map_overview)·구급차 이동을 받는다.
// 환자 상세(통화 전문·활력징후)는 hub가 관제에 보내지 않는다 — 상황판엔 필요 없다. 보기 전용.

struct BoardHospitalRef: Codable {
    var hospitalId: String
    var name: String
    var status: String
    var unavailableReason: String?
    var emergencyLevel: String?
}

struct BoardCase: Codable {
    var caseId: String
    var apid: String?
    var ambulanceName: String?
    var ambulanceGps: GpsPoint?
    var severityTag: String?
    var hospitals: [BoardHospitalRef]?
    var num: Int?
    var startedAt: String?
    var symptom: String?
    var paused: Bool?
    var ktasLevel: Int?
    var expectedDiagnosis: String?
    var zoneActive: [Int]?
}

struct BoardMeta: Codable {
    var caseId: String
    var num: Int?
    var startedAt: String?
    var symptom: String?
    var severity: String?
    var apid: String?
    var ambulanceName: String?
}

struct MapHospital: Codable, Identifiable {
    var hospitalId: String
    var name: String
    var gps: GpsPoint
    var emergencyLevel: String?
    var inFlightCount: Int?
    var availableBedCount: Int?
    var bedCountUnknown: Bool?
    var id: String { hospitalId }
}

struct MapAmbulance: Codable {
    var apid: String
    var name: String
}

struct MapOverview: Codable {
    var hospitals: [MapHospital]
    var ambulances: [MapAmbulance]
}

@MainActor
final class BoardModel: ObservableObject {
    struct Row: Identifiable {
        let caseId: String
        var meta: BoardMeta?
        var overview: BoardCase?
        var id: String { caseId }
        var num: Int? { overview?.num ?? meta?.num }
        var severity: String? { overview?.severityTag ?? meta?.severity }
        var ktas: Int {
            if let k = overview?.ktasLevel, (1...5).contains(k) { return k }
            switch severity { case "high": return 2; case "medium": return 3; case "low": return 4; default: return 3 }
        }
        var ktasEstimated: Bool { !((1...5).contains(overview?.ktasLevel ?? 0)) }
        var title: String { overview?.expectedDiagnosis ?? overview?.symptom ?? meta?.symptom ?? "증상 정보 없음" }
        var apid: String? { overview?.apid ?? meta?.apid }
        var ambulanceName: String? { overview?.ambulanceName ?? meta?.ambulanceName }
        var startedAt: String? { overview?.startedAt ?? meta?.startedAt }
        var hospitals: [BoardHospitalRef] { overview?.hospitals ?? [] }
        var confirmed: BoardHospitalRef? { hospitals.first { $0.status == "confirmed" } }
        var matched: Bool { overview != nil }
        func count(_ s: String) -> Int {
            hospitals.filter { s == "rejected" ? ($0.status == "rejected" || ($0.status == "pending" && $0.unavailableReason != nil)) : s == "pending" ? ($0.status == "pending" && $0.unavailableReason == nil) : $0.status == s }.count
        }
    }

    /// 병원별 분산 — 이 병원으로 확정된 환자 수와 병원 응답, 응급실 여유
    struct HospitalLoad: Identifiable {
        let hospitalId: String
        var name: String
        var level: String?
        var confirmed: [Row] = []
        var approved = 0
        var pending = 0
        var rejected = 0
        var available: Int?
        var bedUnknown = true
        var inFlight = 0
        var id: String { hospitalId }
        /// 이 병원으로 가는 환자 수 — 지금 진행 중인 사건의 이송 확정 수만 센다. hub의 이송 중 건수(병상 차감 보류)는
        /// 사건이 끝나도 E-Gen에 반영될 때까지(최대 도착 후 60분) 남아서, 그걸 같이 보면 끝난 사건의 병원이 계속 남았다(2026-10-15)
        var load: Int { confirmed.count }
    }

    @Published var rows: [String: Row] = [:]
    @Published var sims: [String: AmbulanceSimState] = [:]
    @Published var overview: MapOverview?
    @Published var connection: HubSocket.State = .connecting

    private var socket: HubSocket?

    var ordered: [Row] { rows.values.sorted { ($0.num ?? Int.max, $0.caseId) < ($1.num ?? Int.max, $1.caseId) } }

    func start() {
        guard socket == nil else { return }
        socket = HubSocket(role: "monitor", id: "ipad-board",
                           onMessage: { [weak self] t, d in self?.handle(t, d) },
                           onState: { [weak self] s in self?.connection = s })
    }

    /// 설정이 바뀌었을 때 — 상황판을 연 적이 있을 때만 새 주소로 다시 붙는다
    func reconnect() {
        let wasOpen = socket != nil
        socket?.close(); socket = nil
        rows = [:]; sims = [:]; overview = nil
        if wasOpen { start() }
    }

    func sim(for r: Row) -> AmbulanceSimState? { r.apid.flatMap { sims[$0] } }
    func position(of r: Row) -> GpsPoint? { sim(for: r)?.incident ?? r.overview?.ambulanceGps }

    // ── 집계 ──
    var phaseCounts: (requesting: Int, transporting: Int, arrived: Int, dispatching: Int) {
        var req = 0, tr = 0, ar = 0, dis = 0
        for r in rows.values {
            switch sim(for: r)?.phase {
            case "transporting", "rerouting": tr += 1
            case "at_hospital": ar += 1
            case "dispatching": dis += 1
            default: if r.confirmed == nil { req += 1 } else { tr += 1 }
            }
        }
        return (req, tr, ar, dis)
    }
    var ktasCounts: [Int: Int] {
        var c: [Int: Int] = [:]
        for r in rows.values { c[r.ktas, default: 0] += 1 }
        return c
    }

    var hospitalLoads: [HospitalLoad] {
        var m: [String: HospitalLoad] = [:]
        for r in rows.values {
            for h in r.hospitals {
                var l = m[h.hospitalId] ?? HospitalLoad(hospitalId: h.hospitalId, name: h.name, level: h.emergencyLevel)
                switch h.status {
                case "confirmed": l.confirmed.append(r)
                case "approved": l.approved += 1
                case "rejected": l.rejected += 1
                default: if h.unavailableReason != nil { l.rejected += 1 } else { l.pending += 1 }
                }
                m[h.hospitalId] = l
            }
        }
        // 병원 목록에서는 응급실 여유만 가져온다 — 진행 중 사건에 등장한 병원만(끝난 사건의 병원을 되살리지 않게)
        if let ov = overview {
            for h in ov.hospitals where m[h.hospitalId] != nil {
                guard var l = m[h.hospitalId] else { continue }
                l.level = l.level ?? h.emergencyLevel
                l.available = h.availableBedCount
                l.bedUnknown = h.bedCountUnknown ?? true
                l.inFlight = h.inFlightCount ?? 0
                m[h.hospitalId] = l
            }
        }
        // 확정된 환자가 있거나 승인한 병원만 — 요청만 받은 병원까지 다 넣으면 대량사고에서 목록이 수십 줄이 된다
        // 순서: 가는 환자 많은 순 → 승인 많은 순 → 대기 많은 순 → 이름 → ID. 마지막 두 칸이 동점을 끊는다 — 예전엔 동점이면
        // 사전(Dictionary) 꺼내는 순서를 그대로 써서, 화면이 1초마다 다시 그려질 때마다 동점 병원끼리 자리가 바뀌었다(2026-10-15)
        return m.values.filter { !$0.confirmed.isEmpty || $0.approved > 0 }
            .sorted { a, b in
                if a.load != b.load { return a.load > b.load }
                if a.approved != b.approved { return a.approved > b.approved }
                if a.pending != b.pending { return a.pending > b.pending }
                if a.name != b.name { return a.name < b.name }
                return a.hospitalId < b.hospitalId
            }
    }
    var requestedHospitalCount: Int { Set(rows.values.flatMap { $0.hospitals.map(\.hospitalId) }).count }

    // ── 메시지 ──
    private func handle(_ type: String, _ data: Data) {
        let dec = JSONDecoder()
        switch type {
        case "map_overview":
            if let m = try? dec.decode(MapOverview.self, from: data) { overview = m }
        case "case_meta":
            if let m = try? dec.decode(BoardMeta.self, from: data) {
                var r = rows[m.caseId] ?? Row(caseId: m.caseId); r.meta = m; rows[m.caseId] = r
            }
        case "case_overview":
            if let m = try? dec.decode(BoardCase.self, from: data) {
                var r = rows[m.caseId] ?? Row(caseId: m.caseId); r.overview = m; rows[m.caseId] = r
            }
        case "case_closed":
            if let m = try? dec.decode(CaseClosed.self, from: data) { rows[m.caseId] = nil }
        case "case_sync":
            if let m = try? dec.decode(CaseSync.self, from: data) {
                let keep = Set(m.caseIds)
                for id in rows.keys where !keep.contains(id) && rows[id]?.overview != nil { rows[id] = nil }
            }
        case "ambulance_phase", "ambulance_position":
            if let m = try? dec.decode(AmbulanceSimState.self, from: data) {
                sims[m.apid] = m
                // 사건 없이 기지로 돌아가는 구급차의 사건은 끝난 것 — 지운다(case_closed를 놓쳤을 때의 보험, 2026-10-15)
                if m.caseId == nil, ["idle", "returning"].contains(m.phase) {
                    for (id, r) in rows where r.apid == m.apid { rows[id] = nil }
                }
            }
        default:
            break
        }
    }
}
