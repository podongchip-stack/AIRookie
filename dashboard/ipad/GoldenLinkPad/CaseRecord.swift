import Foundation

// [기록] 탭 — 지난 사건과 그 사건의 병원 응답·인계확인서의 날짜별 로컬 복사본. 서버 영구 기록과 동기화한다.
// hub 보관소와 epoch·변경 순번으로 동기화한다. 병원 이벤트는 최신 상태와 별도로 보존한다.

/// 병원이 이 사건에 한 응답 — hub 매칭 결과의 status 그대로 모은다
enum ResponseGroup: CaseIterable {
    case confirmed, approved, rejected, noReply

    var label: String {
        switch self {
        case .confirmed: "이송 확정"; case .approved: "수용 승인"; case .rejected: "거부"; case .noReply: "무응답"
        }
    }

    /// pending(응답 없음)은 무응답으로 센다. 수용 승인했지만 선택되지 않은 병원은 따로 둔다
    static func of(_ status: String) -> ResponseGroup {
        switch status {
        case "confirmed": return .confirmed
        case "approved": return .approved
        case "rejected": return .rejected
        default: return .noReply
        }
    }
}

struct RecordHospital: Codable, Equatable, Identifiable {
    let hospitalId: String
    let name: String
    var status: String = "pending"
    let rejectReason: String?
    let distanceKm: Double?
    let etaMin: Double?
    var id: String { hospitalId }
    var group: ResponseGroup { ResponseGroup.of(status) }

    init(hospitalId: String, name: String, status: String = "pending", rejectReason: String? = nil,
                distanceKm: Double? = nil, etaMin: Double? = nil) {
        self.hospitalId = hospitalId; self.name = name; self.status = status
        self.rejectReason = rejectReason; self.distanceKm = distanceKm; self.etaMin = etaMin
    }
}

/// 사건 하나의 기록. `handover`는 자동값에 구급대원이 고친 칸을 얹은 최종 값(칸 id → 값)
struct CaseRecord: Codable, Equatable, Identifiable {
    let caseId: String
    let apid: String?
    let ambulanceName: String?
    /// 사건 시작 날짜(KST, yyyy-MM-dd) — 날짜별 목록의 키
    let date: String
    /// 사건 시작 시각(epoch ms)
    let startedAt: Double
    var updatedAt: Double
    let symptom: String?
    let expectedDiagnosis: String?
    let ktasLevel: Int?
    var hospitals: [RecordHospital] = []
    var handover: [String: String] = [:]
    var closed: Bool = false
    /// 서버 변경 순번. nil이면 기기에만 있던 과거 기록이다.
    var archiveVersion: Int?
    var archiveEpoch: String?
    var handoverRevision: Int?
    var handoverEdits: [String: String]?
    var events: [HospitalRecordEvent]?
    var legacyImport: Bool?
    var id: String { caseId }

    init(caseId: String, apid: String?, ambulanceName: String?, date: String, startedAt: Double, updatedAt: Double,
                symptom: String?, expectedDiagnosis: String?, ktasLevel: Int?, hospitals: [RecordHospital] = [],
                handover: [String: String] = [:], closed: Bool = false) {
        self.caseId = caseId; self.apid = apid; self.ambulanceName = ambulanceName; self.date = date
        self.startedAt = startedAt; self.updatedAt = updatedAt; self.symptom = symptom
        self.expectedDiagnosis = expectedDiagnosis; self.ktasLevel = ktasLevel
        self.hospitals = hospitals; self.handover = handover; self.closed = closed
    }

    func count(_ group: ResponseGroup) -> Int { hospitals.filter { $0.group == group }.count }
}

enum RecordDates {
    static let zone = TimeZone(identifier: "Asia/Seoul")!

    static func of(_ epochMs: Double) -> String {
        let f = DateFormatter(); f.timeZone = zone; f.dateFormat = "yyyy-MM-dd"
        return f.string(from: Date(timeIntervalSince1970: epochMs / 1000))
    }

    static func timeOf(_ epochMs: Double) -> String {
        let f = DateFormatter(); f.timeZone = zone; f.dateFormat = "HH:mm"
        return f.string(from: Date(timeIntervalSince1970: epochMs / 1000))
    }
}


struct HospitalRecordEvent: Codable, Equatable, Identifiable {
    let id: String
    let hospitalId: String
    let action: String
    let actor: String
    let timestamp: String
    let reason: String?

    var label: String {
        switch action {
        case "hospital_approve": "수용 승인"
        case "hospital_reject": "수용 거절"
        case "final_approval": "이송 확정"
        case "transport_withdraw": "이송 중 수용 철회"
        case "arrival_accepted": "도착 후 수용"
        case "arrival_refused": "도착 후 수용 불가"
        default: action
        }
    }
}

struct RecordSyncReply: Decodable {
    let requestId: String?
    let apid: String?
    let epoch: String?
    let cursor: Int?
    let hasMore: Bool?
    let records: [CaseRecord]?
    let record: CaseRecord?
    let conflict: Bool?
    let error: String?
}

struct RecordSyncRequest: Encodable {
    let type = "record_sync"
    let requestId: String
    let token: String
    let cursor: Int
    let epoch: String?
    init(requestId: String, token: String, cursor: Int, epoch: String?) {
        self.requestId = requestId; self.token = token; self.cursor = cursor; self.epoch = epoch
    }
}

struct RecordImportRequest: Encodable {
    let type = "record_import"
    let requestId: String
    let token: String
    let records: [CaseRecord]
    init(requestId: String, token: String, records: [CaseRecord]) {
        self.requestId = requestId; self.token = token; self.records = records
    }
}

struct PendingHandover: Codable, Equatable {
    let requestId: String
    let caseId: String
    let revision: Int
    let edits: [String: String]
    init(caseId: String, revision: Int, edits: [String: String]) {
        self.requestId = UUID().uuidString; self.caseId = caseId; self.revision = revision; self.edits = edits
    }
}

struct RecordHandoverRequest: Encodable {
    let type = "record_handover"
    let requestId: String
    let token: String
    let caseId: String
    let revision: Int
    let edits: [String: String]
    init(pending: PendingHandover, token: String) {
        self.requestId = pending.requestId; self.token = token; self.caseId = pending.caseId
        self.revision = pending.revision; self.edits = pending.edits
    }
}
