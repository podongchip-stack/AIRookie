import Foundation

// [기록] 탭 — 지난 사건과 그 사건의 병원 응답·인계확인서의 날짜별 로컬 복사본. 서버 영구 기록과 동기화한다.
// hub 보관소와 epoch·변경 순번으로 동기화한다. 병원 이벤트는 최신 상태와 별도로 보존한다.

/// 병원이 이 사건에 한 응답 — hub 매칭 결과의 status 그대로 모은다
public enum ResponseGroup: CaseIterable {
    case confirmed, approved, rejected, noReply

    public var label: String {
        switch self {
        case .confirmed: "이송 확정"; case .approved: "수용 승인"; case .rejected: "거부"; case .noReply: "무응답"
        }
    }

    /// pending(응답 없음)은 무응답으로 센다. 수용 승인했지만 선택되지 않은 병원은 따로 둔다
    public static func of(_ status: String) -> ResponseGroup {
        switch status {
        case "confirmed": return .confirmed
        case "approved": return .approved
        case "rejected": return .rejected
        default: return .noReply
        }
    }
}

public struct RecordHospital: Codable, Equatable, Identifiable {
    public let hospitalId: String
    public let name: String
    public var status: String = "pending"
    public let rejectReason: String?
    public let distanceKm: Double?
    public let etaMin: Double?
    public var id: String { hospitalId }
    public var group: ResponseGroup { ResponseGroup.of(status) }

    public init(hospitalId: String, name: String, status: String = "pending", rejectReason: String? = nil,
                distanceKm: Double? = nil, etaMin: Double? = nil) {
        self.hospitalId = hospitalId; self.name = name; self.status = status
        self.rejectReason = rejectReason; self.distanceKm = distanceKm; self.etaMin = etaMin
    }
}

/// 사건 하나의 기록. `handover`는 자동값에 구급대원이 고친 칸을 얹은 최종 값(칸 id → 값)
public struct CaseRecord: Codable, Equatable, Identifiable {
    public let caseId: String
    public let apid: String?
    public let ambulanceName: String?
    /// 사건 시작 날짜(KST, yyyy-MM-dd) — 날짜별 목록의 키
    public let date: String
    /// 사건 시작 시각(epoch ms)
    public let startedAt: Double
    public var updatedAt: Double
    public let symptom: String?
    public let expectedDiagnosis: String?
    public let ktasLevel: Int?
    public var hospitals: [RecordHospital] = []
    public var handover: [String: String] = [:]
    public var closed: Bool = false
    /// 서버 변경 순번. nil이면 기기에만 있던 과거 기록이다.
    public var archiveVersion: Int?
    public var archiveEpoch: String?
    public var handoverRevision: Int?
    public var handoverEdits: [String: String]?
    public var events: [HospitalRecordEvent]?
    public var legacyImport: Bool?
    public var id: String { caseId }

    public init(caseId: String, apid: String?, ambulanceName: String?, date: String, startedAt: Double, updatedAt: Double,
                symptom: String?, expectedDiagnosis: String?, ktasLevel: Int?, hospitals: [RecordHospital] = [],
                handover: [String: String] = [:], closed: Bool = false) {
        self.caseId = caseId; self.apid = apid; self.ambulanceName = ambulanceName; self.date = date
        self.startedAt = startedAt; self.updatedAt = updatedAt; self.symptom = symptom
        self.expectedDiagnosis = expectedDiagnosis; self.ktasLevel = ktasLevel
        self.hospitals = hospitals; self.handover = handover; self.closed = closed
    }

    public func count(_ group: ResponseGroup) -> Int { hospitals.filter { $0.group == group }.count }
}

public enum RecordDates {
    public static let zone = TimeZone(identifier: "Asia/Seoul")!

    public static func of(_ epochMs: Double) -> String {
        let f = DateFormatter(); f.timeZone = zone; f.dateFormat = "yyyy-MM-dd"
        return f.string(from: Date(timeIntervalSince1970: epochMs / 1000))
    }

    public static func timeOf(_ epochMs: Double) -> String {
        let f = DateFormatter(); f.timeZone = zone; f.dateFormat = "HH:mm"
        return f.string(from: Date(timeIntervalSince1970: epochMs / 1000))
    }
}


public struct HospitalRecordEvent: Codable, Equatable, Identifiable {
    public let id: String
    public let hospitalId: String
    public let action: String
    public let actor: String
    public let timestamp: String
    public let reason: String?

    public var label: String {
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

public struct RecordSyncReply: Decodable {
    public let requestId: String?
    public let apid: String?
    public let epoch: String?
    public let cursor: Int?
    public let hasMore: Bool?
    public let records: [CaseRecord]?
    public let record: CaseRecord?
    public let conflict: Bool?
    public let error: String?
}

public struct RecordSyncRequest: Encodable {
    public let type = "record_sync"
    public let requestId: String
    public let token: String
    public let cursor: Int
    public let epoch: String?
    public init(requestId: String, token: String, cursor: Int, epoch: String?) {
        self.requestId = requestId; self.token = token; self.cursor = cursor; self.epoch = epoch
    }
}

public struct RecordImportRequest: Encodable {
    public let type = "record_import"
    public let requestId: String
    public let token: String
    public let records: [CaseRecord]
    public init(requestId: String, token: String, records: [CaseRecord]) {
        self.requestId = requestId; self.token = token; self.records = records
    }
}

public struct PendingHandover: Codable, Equatable {
    public let requestId: String
    public let caseId: String
    public let revision: Int
    public let edits: [String: String]
    public init(caseId: String, revision: Int, edits: [String: String]) {
        self.requestId = UUID().uuidString; self.caseId = caseId; self.revision = revision; self.edits = edits
    }
}

public struct RecordHandoverRequest: Encodable {
    public let type = "record_handover"
    public let requestId: String
    public let token: String
    public let caseId: String
    public let revision: Int
    public let edits: [String: String]
    public init(pending: PendingHandover, token: String) {
        self.requestId = pending.requestId; self.token = token; self.caseId = pending.caseId
        self.revision = pending.revision; self.edits = pending.edits
    }
}
