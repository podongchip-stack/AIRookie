import Foundation

/// 플랫폼과 무관하게 접근 코드가 통화 역할을 정한다.
public struct AccessCode: Equatable {
    public let role: String
    public let id: String
    public var normalized: String { (role == "hospital" ? "H-" : "P-") + id }

    public init?(_ code: String) {
        let text = code.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        guard text.hasPrefix("P-") || text.hasPrefix("A-") || text.hasPrefix("H-") else { return nil }
        let id = String(text.dropFirst(2))
        guard !id.isEmpty, id != "AUTO", id.allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber) }) else { return nil }
        self.role = text.hasPrefix("H-") ? "hospital" : "ambulance"
        self.id = id
    }
}
