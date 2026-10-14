import Foundation

// hub → 관제(role=monitor) 메시지. hub/schema.py의 MapOverview·CaseMeta·MonitorCase(+MonitorCaseHospital 설명 필드, 2026-10-14)·
// AmbulanceSimState·CaseClosed와 같다. 필드는 거의 전부 Optional — hub가 예전 버전이어도 디코딩이 깨지지 않게.

struct GpsPoint: Codable, Hashable {
    var lat: Double
    var lng: Double
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

struct MapAmbulance: Codable, Identifiable {
    var apid: String
    var name: String
    var gps: GpsPoint
    var base: GpsPoint?
    var id: String { apid }
}

struct MapOverview: Codable {
    var hospitals: [MapHospital]
    var ambulances: [MapAmbulance]
    var simDispatch: Bool?
}

struct SpecialtyMatch: Codable {
    var department: String?
    var score: Double?
    var basis: String?        // exact / embedding / none
    var doctorCount: Int?
}

/// 병상 숫자가 아직 유효할 확률(infosurv, AI). 곡선 파라미터가 오면 BedReliability.live()가 초 단위로 감쇠시킨다.
struct BedReliabilityMatch: Codable {
    var authority: Double
    var rArrive: Double
    var horizonSec: Double
    var ttlSec: Double?
    var modelTag: String?
    var predictedSurvivalSec: Double?
    var bornAt: String?
    var sigma: Double?
    var confirmedAgeSec: Double?
}

/// 심평원 대조 신뢰도(hospital_score) — 매칭된 중증질환군에 대한 5단계 판정과 근거 문장
struct ReliabilityInfo: Codable {
    var group: String
    var score: Double
    var confidence: String
    var basis: [String]?
}

/// 중증질환 수용 신고의 신선도(규칙) — 언제 적 신고인가
struct SevereFreshness: Codable {
    var group: String
    var value: String          // "Y" | "불가능"
    var ageSec: Double
    var ageIsMin: Bool?
    var ruleRemainingSec: Double?
}

struct AcceptanceMessageMatch: Codable {
    var kind: String?          // er | severe
    var message: String?
    var department: String?
    var diseaseGroup: String?
    var matched: Bool?
}

struct CaseHospital: Codable, Identifiable {
    var hospitalId: String
    var name: String
    var status: String         // pending | approved | rejected | confirmed
    var distanceKm: Double
    var roadDistanceKm: Double?
    var rejectReason: String?
    var unavailableReason: String?
    var zone: Int
    var respondedAt: String?
    // 설명 필드(2026-10-14)
    var gps: GpsPoint?
    var emergencyLevel: String?
    var availableBedCount: Int?
    var bedCountUnknown: Bool?
    var bedDataStale: Bool?
    var erBedCapacity: Int?
    var erOccupancyPct: Int?
    var travelMin: Double?
    var travelBasis: String?
    var etaMin: Int?
    var finalScore: Double?
    var specialtyMatch: SpecialtyMatch?
    var bedReliability: BedReliabilityMatch?
    var reliability: ReliabilityInfo?
    var severeFreshness: SevereFreshness?
    var demoteReasons: [String]?
    var bonusReasons: [String]?
    var loadReason: String?
    var occupancyReason: String?
    var inFlightCount: Int?
    var excluded: Bool?
    var acceptanceMessages: [AcceptanceMessageMatch]?
    var id: String { hospitalId }
}

struct CaseEvent: Codable, Identifiable {
    var t: String?
    var kind: String?
    var text: String?
    var id: String { (t ?? "") + (text ?? "") }
}

struct MonitorCase: Codable {
    var caseId: String
    var apid: String?
    var ambulanceName: String?
    var ambulanceGps: GpsPoint?
    var severityTag: String?
    var zoneActive: [Int]?
    var zoneBandKm: Double?
    var hospitals: [CaseHospital]
    var num: Int?
    var startedAt: String?
    var symptom: String?
    var events: [CaseEvent]?
    var zoneExpandAt: String?
    var paused: Bool?
    // 환자 요약(2026-10-14) — 통화 전문·활력징후는 안 온다
    var ktasLevel: Int?
    var expectedDiagnosis: String?
    var chiefComplaint: String?
    var requiredDepartment: String?
    var patient: String?
    var confirmedBy: String?
}

struct CaseMeta: Codable {
    var caseId: String
    var num: Int?
    var startedAt: String?
    var symptom: String?
    var severity: String?
    var apid: String?
    var ambulanceName: String?
    var events: [CaseEvent]?
}

struct AmbulanceSimState: Codable {
    var apid: String
    var caseId: String?
    var phase: String
    var gps: GpsPoint?
    var heading: Double?
    var etaSec: Double?
    var path: [[Double]]?      // [lat, lng] 목록
    var base: GpsPoint?
    var incident: GpsPoint?
    var hospitalId: String?
    var paused: Bool?
    var pauseReason: String?
}

struct CaseClosed: Codable {
    var caseId: String
    var reason: String?
}

struct CaseSync: Codable {
    var caseIds: [String]
}

struct Envelope: Codable {
    var type: String?
}

struct IdentifyMessage: Encodable {
    var type = "identify"
    var role: String
    var id: String
}

// ── 표시 도우미 ──
enum Labels {
    static func status(_ s: String) -> String {
        switch s {
        case "approved": return "수용 승인"
        case "rejected": return "수용 불가"
        case "confirmed": return "이송 확정"
        default: return "판단 대기"
        }
    }
    static func phase(_ p: String?) -> String {
        switch p {
        case "dispatching": return "출동 중"
        case "on_scene": return "현장"
        case "transporting": return "이송 중"
        case "at_hospital": return "병원 도착"
        case "rerouting": return "재선택"
        case "returning": return "복귀 중"
        case "idle": return "대기"
        default: return p ?? ""
        }
    }
    static func severity(_ s: String?) -> String {
        switch s {
        case "high": return "중증"
        case "medium": return "중등증"
        case "low": return "경증"
        default: return ""
        }
    }
    static func grade(_ level: String?) -> String {
        switch level {
        case "권역응급의료센터": return "권역"
        case "지역응급의료센터": return "지역센터"
        case "지역응급의료기관": return "지역기관"
        case "응급실운영신고기관": return "응급실"
        default: return level ?? ""
        }
    }
    static func demote(_ r: String) -> String {
        switch r {
        case "declared_no": return "수용 불가 신고(E-Gen)"
        case "severe_blocked": return "병원 차단 메시지"
        case "beds_full": return "확인된 만실"
        case "rejected": return "이 사건 거절"
        default: return r
        }
    }
    static func reject(_ code: String?) -> String {
        switch code {
        case "beds_full", "BEDS_FULL": return "병상 없음"
        case "NO_WARD": return "병동 없음"
        case "NO_DEPARTMENT": return "진료과 없음"
        case "NO_EQUIPMENT": return "장비 없음"
        case "ON_CALL_MISMATCH": return "당직 불일치"
        case "NIGHT_UNAVAILABLE": return "야간 불가"
        case "OR_OCCUPIED": return "수술실 사용 중"
        case "STAFF_BUSY": return "의료진 바쁨"
        case "SEVERITY_EXCEEDED": return "중증도 초과"
        case "AGE_LIMIT": return "연령 제한"
        case "UNSPECIFIED", nil: return "사유 없음"
        default: return code ?? ""
        }
    }
    static func confidence(_ c: String) -> String {
        switch c { case "high": return "높음"; case "medium": return "보통"; case "low": return "낮음"; default: return c }
    }
    static func age(_ sec: Double, isMin: Bool = false) -> String {
        let prefix = isMin ? "최소 " : ""
        if sec < 60 { return prefix + "방금" }
        if sec < 3600 { return prefix + "\(max(Int((sec / 60).rounded()), 1))분 전" }
        let h = sec / 3600
        return prefix + (h < 10 ? String(format: "%.1f시간 전", h) : "\(Int(h.rounded()))시간 전")
    }
    static func minutes(_ sec: Double) -> String {
        if sec < 3600 { return "\(Int((sec / 60).rounded()))분" }
        return String(format: "%.1f시간", sec / 3600)
    }
    static func clock(_ iso: String?) -> String {
        guard let iso, let d = ISO.parse(iso) else { return "" }
        let f = DateFormatter(); f.locale = Locale(identifier: "ko_KR"); f.dateFormat = "HH:mm:ss"
        return f.string(from: d)
    }
}

enum ISO {
    private static let withFrac: ISO8601DateFormatter = { let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]; return f }()
    private static let plain: ISO8601DateFormatter = { let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime]; return f }()
    static func parse(_ s: String) -> Date? { withFrac.date(from: s) ?? plain.date(from: s) }
}
