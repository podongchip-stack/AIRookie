import Foundation

// 환자 정보(통화 요약) 메시지와 표시 규칙. 안드로이드 core/PatientInfo.kt(아이패드 HubMessages.swift의 PatientInfo·Labels,
// BedReliability.swift)와 같은 식이다.

public struct Vital: Decodable, Equatable {
    public let sequence: Int?
    public let sbp: Double?
    public let dbp: Double?
    public let hr: Double?
    public let rr: Double?
    public let bt: Double?
    public let spo2: Double?
    public let glucose: Double?

    /// 웹 formatVital과 같은 표기
    public var text: String {
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

public struct PatientUpdate: Decodable, Equatable, Identifiable {
    public let callRound: Int
    public let expectedDiagnosis: String?
    public let severityTag: String?
    public let ktasLevel: Int?
    public var id: Int { callRound }
}

/// 구급대원이 직접 적어 보낸 추가 정보 한 줄 — hub PatientInfo.extraNotes
public struct ExtraNote: Decodable, Equatable, Identifiable {
    public let text: String
    public let at: String
    public var id: String { at + text }
}

public struct PatientInfo: Decodable, Equatable {
    public let injuryStatus: [String]?
    public let expectedDiagnosis: String?
    public let severityTag: String?
    public let patient: String?
    public let treatment: [String]?
    public let ktasLevel: Int?
    public let vitals: [Vital]?
    public let consciousness: String?
    public let onset: String?
    public let chiefComplaint: String?
    public let requiredDepartment: String?
    public let callRound: Int?
    public let previousCalls: [PatientUpdate]?
    public let confirmedBy: String?
    public let confirmedAt: String?
    public let extraNotes: [ExtraNote]?
}

/// 병상 정보 신뢰도의 실시간 감쇠 — S(age) = 1 − Φ((ln age − ln m) / σ). dashboard/src/lib/bedReliability.ts·hub/bed_reliability.py와 같은 식.
/// 병원이 "현재 정보 확인"을 눌렀으면 조건부 생존 S(a)/S(u). 파라미터가 없으면 hub가 보낸 스칼라 그대로(정지값)
public enum BedLive {
    public struct Live { public let authority: Double; public let rArrive: Double; public let live: Bool; public let ageSec: Double? }

    /// erfc(x) — Numerical Recipes erfcc, 상대 오차 1.2e-7 이하(확률을 % 정수로 보이는 데 충분)
    private static func erfc(_ x: Double) -> Double {
        let z = abs(x)
        let t = 1.0 / (1.0 + 0.5 * z)
        let r = t * exp(-z * z - 1.26551223 + t * (1.00002368 + t * (0.37409196 + t * (0.09678418 + t * (-0.18628806 +
            t * (0.27886807 + t * (-1.13520398 + t * (1.48851587 + t * (-0.82215223 + t * 0.17087277)))))))))
        return x >= 0 ? r : 2.0 - r
    }

    public static func survival(_ predT: Double, _ age: Double, _ sigma: Double) -> Double {
        if age <= 0 { return 1.0 }
        let z = (log(max(age, 1e-9)) - log(max(predT, 1e-9))) / (max(sigma, 1e-9) * 2.0.squareRoot())
        return min(max(0.5 * erfc(z), 0.0), 1.0)
    }

    public static func of(_ br: BedReliability, now nowMillis: Double) -> Live {
        guard let predT = br.predictedSurvivalSec, let bornISO = br.bornAt, let born = isoDate(bornISO) else {
            return Live(authority: br.authority ?? 0, rArrive: br.rArrive ?? 0, live: false, ageSec: nil)
        }
        let sigma = br.sigma ?? 1.0
        let age = max((nowMillis - born.timeIntervalSince1970 * 1000) / 1000.0, 0.0)
        let sU = br.confirmedAgeSec.map { max(survival(predT, $0, sigma), 1e-12) } ?? 1.0
        return Live(authority: min(survival(predT, age, sigma) / sU, 1.0),
                    rArrive: min(survival(predT, age + (br.horizonSec ?? 0), sigma) / sU, 1.0), live: true, ageSec: age)
    }

    public static func pct(_ p: Double) -> String { "\(Int((p * 100).rounded()))%" }

    private static func isoDate(_ s: String) -> Date? { isoNow.date(from: s) ?? isoPlain.date(from: s) }
    private static let isoNow: ISO8601DateFormatter = { let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]; return f }()
    private static let isoPlain: ISO8601DateFormatter = { let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime]; return f }()
}

/// 화면 표시 문구 — 안드로이드 DisplayLabels(아이패드 Labels)
public enum DisplayLabels {
    /// 의식 수준 글자 → A·V·P·U 한 글자. hub는 "통증 반응(P)"처럼 풀어서 보내므로 괄호 안을 본다
    public static func avpu(_ text: String?) -> String? {
        guard let text, !text.isEmpty else { return nil }
        if let m = text.range(of: "\\(([AVPU])\\)", options: .regularExpression) {
            return String(text[m].dropFirst().dropLast())
        }
        let first = String(text.prefix(1)).uppercased()
        return ["A", "V", "P", "U"].contains(first) ? first : nil
    }

    public static func status(_ s: String) -> String {
        switch s {
        case "approved": return "후보 등록"
        case "rejected": return "수용 불가"
        case "confirmed": return "이송 확정"
        default: return "판단 대기"
        }
    }

    public static func reject(_ code: String?) -> String {
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

    public static func age(_ sec: Double) -> String {
        if sec < 60 { return "방금" }
        if sec < 3600 { return "\(max(Int((sec / 60).rounded()), 1))분 전" }
        let h = sec / 3600
        return h < 10 ? String(format: "%.1f시간 전", h) : "\(Int(h.rounded()))시간 전"
    }

    public static func minutes(_ sec: Double) -> String {
        if sec < 3600 { return "\(max(Int((sec / 60).rounded()), 1))분" }
        return String(format: "%.1f시간", sec / 3600)
    }
}
