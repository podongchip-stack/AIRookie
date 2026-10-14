import Foundation

// hub ↔ 구급차 대시보드 메시지. 웹 dashboard/src/types/dashboard.ts · hub/schema.py와 같은 이름이다.
// 구급차 소켓(role=ambulance, id=apid)으로 받는 것: identity_info · match_result(HubMatchResult) · scene_candidates ·
// ambulance_phase/position · call_status · call_transcript · case_closed · case_sync · action_refused.
// 필드는 거의 전부 Optional — hub가 예전 버전이어도 디코딩이 깨지지 않게.

struct GpsPoint: Codable, Hashable {
    var lat: Double
    var lng: Double
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
    var diseaseName: String?
    var diseaseGroup: String?
    var matched: Bool?
}

/// 매칭 결과의 병원 하나(HospitalMatch)
struct HospitalMatch: Codable, Identifiable {
    var hospitalId: String
    var name: String
    var gps: GpsPoint?
    var distanceKm: Double
    var roadDistanceKm: Double?
    var zone: Int?
    var specialtyMatch: SpecialtyMatch?
    var availableBedCount: Int?
    var bedCountUnknown: Bool?
    var bedDataStale: Bool?
    var erBedCapacity: Int?
    var erOccupancyPct: Int?
    var status: String         // pending | approved | rejected | confirmed
    var etaMin: Int?
    var travelMin: Double?
    var travelBasis: String?
    var finalScore: Double?
    var reliability: ReliabilityInfo?
    var bedReliability: BedReliabilityMatch?
    var bedReliabilityByType: [String: BedReliabilityMatch]?
    var severeFreshness: SevereFreshness?
    var rejectReason: String?
    var unavailableReason: String?
    var acceptanceMessages: [AcceptanceMessageMatch]?
    var demoteReasons: [String]?
    var excluded: Bool?
    var emergencyLevel: String?
    var travelBonusMin: Double?
    var bonusReasons: [String]?
    var inFlightCount: Int?
    var loadPenaltyMin: Double?
    var loadReason: String?
    var occupancyPenaltyMin: Double?
    var occupancyReason: String?
    var id: String { hospitalId }
}

struct Vital: Codable {
    var sequence: Int?
    var sbp: Double?
    var dbp: Double?
    var hr: Double?
    var rr: Double?
    var bt: Double?
    var spo2: Double?
    var glucose: Double?

    /// 웹 formatVital과 같은 표기
    var text: String {
        func n(_ v: Double?) -> String? { v.map { $0.rounded() == $0 ? String(Int($0)) : String(format: "%.1f", $0) } }
        var parts: [String] = []
        if let s = n(sbp) { parts.append("BP \(s)/\(n(dbp) ?? "?")") }
        if let h = n(hr) { parts.append("HR \(h)") }
        if let r = n(rr) { parts.append("RR \(r)") }
        if let o = n(spo2) { parts.append("SpO₂ \(o)%") }
        if let t = n(bt) { parts.append("BT \(t)℃") }
        if let g = n(glucose) { parts.append("혈당 \(g)") }
        return parts.joined(separator: " · ")
    }
}

struct PatientUpdate: Codable, Identifiable {
    var callRound: Int
    var expectedDiagnosis: String?
    var severityTag: String?
    var ktasLevel: Int?
    var id: Int { callRound }
}

struct PatientInfo: Codable {
    var injuryStatus: [String]?
    var expectedDiagnosis: String?
    var severityTag: String?
    var patient: String?
    var treatment: [String]?
    var ktasLevel: Int?
    var vitals: [Vital]?
    var consciousness: String?
    var onset: String?
    var chiefComplaint: String?
    var requiredDepartment: String?
    var callRound: Int?
    var previousCalls: [PatientUpdate]?
    var confirmedBy: String?
    var confirmedAt: String?
}

struct HubMatchResult: Codable {
    var caseId: String
    var patientInfo: PatientInfo?
    var zoneActive: [Int]?
    var hospitals: [HospitalMatch]
    var ambulanceName: String?
    var apid: String?
    var ambulanceGps: GpsPoint?
    var paused: Bool?
}

struct SceneSpecialty: Codable {
    var department: String
    var doctorCount: Int?
}

/// 매칭 전 현장 후보(내비 도착 시간순, 규칙) — 통화가 끝나면 매칭 결과로 바뀐다
struct SceneCandidate: Codable, Identifiable {
    var hospitalId: String
    var name: String
    var distanceKm: Double
    var roadDistanceKm: Double?
    var etaMin: Int?
    var gps: GpsPoint?
    var availableBedCount: Int?
    var bedCountUnknown: Bool?
    var bedReliability: BedReliabilityMatch?
    var firstCallRecommended: Bool?
    var emergencyLevel: String?
    var specialties: [SceneSpecialty]?
    var id: String { hospitalId }
}

struct SceneCandidates: Codable {
    var caseId: String
    var apid: String?
    var zoneActive: [Int]?
    var hospitals: [SceneCandidate]
    var reportedSymptom: String?
    var reportedSeverity: String?
}

struct AmbulanceSimState: Codable {
    var apid: String
    var caseId: String?
    var phase: String
    var gps: GpsPoint?
    var etaSec: Double?
    var incident: GpsPoint?
    var base: GpsPoint?
    var hospitalId: String?
    var paused: Bool?
    var pauseReason: String?
}

struct CallStatus: Codable {
    var caseId: String
    var apid: String?
    var hospitalName: String?
    var device: String?
    var state: String          // calling | ended
    var startedAt: String?
    var endedAt: String?
    var followup: Bool?
    var cancelled: Bool?
}

struct CallTranscriptLine: Codable, Identifiable {
    var apid: String?
    var caseId: String?
    var start: Double?
    var end: Double?
    var text: String
    var id: String { "\(start ?? 0)|\(text)" }
}

struct IdentityInfo: Codable {
    var role: String?
    var id: String?
    var name: String?
    var known: Bool?
    var simDispatch: Bool?
    var gps: GpsPoint?
}

struct CaseClosed: Codable {
    var caseId: String
    var reason: String?
}

struct CaseSync: Codable {
    var caseIds: [String]
}

struct ActionRefused: Codable {
    var caseId: String?
    var reason: String?
}

struct Envelope: Codable {
    var type: String?
}

struct IdentifyMessage: Encodable {
    var type = "identify"
    var role: String
    var id: String
}

/// 구급대원 이송 승인 — 웹 handleApprove와 같은 형식
struct ApprovalAction: Encodable {
    var caseId: String
    var action = "final_approval"
    var hospital_id: String
    var actor = "paramedic"
    var timestamp: String
}

// ── 표시 도우미 ──
enum Labels {
    static func status(_ s: String) -> String {
        switch s {
        case "approved": return "후보 등록"
        case "rejected": return "수용 불가"
        case "confirmed": return "이송 확정"
        default: return "판단 대기"
        }
    }
    static func phase(_ p: String?) -> String {
        switch p {
        case "dispatching": return "현장으로 출동 중"
        case "on_scene": return "현장 도착"
        case "transporting": return "병원으로 이송 중"
        case "at_hospital": return "병원 도착 — 수용 결과 대기"
        case "rerouting": return "재선택 대기"
        case "returning": return "기지로 복귀 중"
        case "idle": return "출동 대기"
        default: return p ?? "출동 대기"
        }
    }
    static func demote(_ r: String) -> String {
        switch r {
        case "declared_no": return "수용 불가 신고"
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
        switch c { case "high": return "신뢰도 높음"; case "medium": return "신뢰도 보통"; case "low": return "신뢰도 낮음"; default: return c }
    }
    static let bedField: [String: String] = ["hvoc": "수술실", "hvicc": "중환자실", "hvgc": "입원실", "hv28": "소아", "hv29": "음압"]

    static func age(_ sec: Double, isMin: Bool = false) -> String {
        let prefix = isMin ? "최소 " : ""
        if sec < 60 { return prefix + "방금" }
        if sec < 3600 { return prefix + "\(max(Int((sec / 60).rounded()), 1))분 전" }
        let h = sec / 3600
        return prefix + (h < 10 ? String(format: "%.1f시간 전", h) : "\(Int(h.rounded()))시간 전")
    }
    static func minutes(_ sec: Double) -> String {
        if sec < 3600 { return "\(max(Int((sec / 60).rounded()), 1))분" }
        return String(format: "%.1f시간", sec / 3600)
    }
    static func clock(_ iso: String?) -> String {
        guard let iso, let d = ISO.parse(iso) else { return "" }
        let f = DateFormatter(); f.locale = Locale(identifier: "ko_KR"); f.dateFormat = "HH:mm:ss"
        return f.string(from: d)
    }
    static func elapsed(_ sec: Double) -> String {
        let s = max(Int(sec), 0)
        return s >= 3600 ? String(format: "%d:%02d:%02d", s / 3600, (s % 3600) / 60, s % 60) : String(format: "%02d:%02d", s / 60, s % 60)
    }
    static func distance(km: Double, road: Double?) -> String {
        if let road { return String(format: "%.1f km", road) }
        return String(format: "직선 %.1f km", km)
    }
}

enum ISO {
    private static let withFrac: ISO8601DateFormatter = { let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]; return f }()
    private static let plain: ISO8601DateFormatter = { let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime]; return f }()
    static func parse(_ s: String) -> Date? { withFrac.date(from: s) ?? plain.date(from: s) }
    static func now() -> String { withFrac.string(from: Date()) }
}
