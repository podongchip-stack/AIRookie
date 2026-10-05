import Foundation

/// summary(v2 17필드)처럼 모양이 자유로운 JSON. voice/schema.py가 summary를 dict로 두는 것과 같은 이유 —
/// 모델 출력을 그대로 hub로 넘기고 여기서 타입을 좁히지 않는다. null도 의미가 있어 그대로 남긴다.
public enum JSONValue: Equatable, Sendable {
    case null
    case bool(Bool)
    case int(Int)
    case double(Double)
    case string(String)
    case array([JSONValue])
    case object([(String, JSONValue)])  // 키 순서를 지켜야 Python 출력과 눈으로 대조하기 쉽다

    public static func == (a: JSONValue, b: JSONValue) -> Bool {
        switch (a, b) {
        case (.null, .null): return true
        case let (.bool(x), .bool(y)): return x == y
        case let (.int(x), .int(y)): return x == y
        case let (.double(x), .double(y)): return x == y
        case let (.int(x), .double(y)), let (.double(y), .int(x)): return Double(x) == y
        case let (.string(x), .string(y)): return x == y
        case let (.array(x), .array(y)): return x == y
        case let (.object(x), .object(y)):
            // 비교는 순서 무관(Python dict 비교와 같게)
            guard x.count == y.count else { return false }
            let dy = Dictionary(y, uniquingKeysWith: { a, _ in a })
            return x.allSatisfy { k, v in dy[k] == v }
        default: return false
        }
    }

    public subscript(key: String) -> JSONValue? {
        if case let .object(pairs) = self { return pairs.first { $0.0 == key }?.1 }
        return nil
    }

    public static func str(_ s: String?) -> JSONValue { s.map(JSONValue.string) ?? .null }
}

extension JSONValue: Codable {
    private struct Key: CodingKey {
        var stringValue: String
        var intValue: Int? { nil }
        init(stringValue: String) { self.stringValue = stringValue }
        init?(intValue: Int) { nil }
    }

    public init(from decoder: Decoder) throws {
        if let c = try? decoder.container(keyedBy: Key.self) {
            // JSONDecoder는 키 순서를 주지 않는다 — 읽을 때는 순서가 의미 없다(비교는 순서 무관)
            self = .object(try c.allKeys.sorted { $0.stringValue < $1.stringValue }
                .map { ($0.stringValue, try c.decode(JSONValue.self, forKey: $0)) })
            return
        }
        if var c = try? decoder.unkeyedContainer() {
            var out: [JSONValue] = []
            while !c.isAtEnd { out.append(try c.decode(JSONValue.self)) }
            self = .array(out)
            return
        }
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let b = try? c.decode(Bool.self) { self = .bool(b) }
        else if let i = try? c.decode(Int.self) { self = .int(i) }
        else if let d = try? c.decode(Double.self) { self = .double(d) }
        else { self = .string(try c.decode(String.self)) }
    }

    public func encode(to encoder: Encoder) throws {
        switch self {
        case .null: var c = encoder.singleValueContainer(); try c.encodeNil()
        case let .bool(b): var c = encoder.singleValueContainer(); try c.encode(b)
        case let .int(i): var c = encoder.singleValueContainer(); try c.encode(i)
        case let .double(d): var c = encoder.singleValueContainer(); try c.encode(d)
        case let .string(s): var c = encoder.singleValueContainer(); try c.encode(s)
        case let .array(a):
            var c = encoder.unkeyedContainer()
            for v in a { try c.encode(v) }
        case let .object(pairs):
            var c = encoder.container(keyedBy: Key.self)
            for (k, v) in pairs { try c.encode(v, forKey: Key(stringValue: k)) }
        }
    }
}
