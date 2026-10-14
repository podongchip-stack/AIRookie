import Foundation

/// 정보 생존 모델 라이브 채점 보드 — info `reliability/live_board.py`가 실제 서빙 엔진으로 창(48시간) 전체를 재생·채점한 결과.
/// hub `GET /verification/live`가 그대로 중계한다. 필드는 live_board.json(schemaVersion 4)과 같고 전부 Optional.
struct LiveBoard: Codable {
    struct Headline: Codable {
        var valueChanges: Int?     // 창 안의 병상 값 변화 수
        var bigBreaks: Int?        // 그중 θ석 이상 어긋남(모델이 "유효"라 한 claim이 깨진 수)
        var warnedBreaks: Int?     // 그중 깨지기 전 모델이 50% 미만으로 경고하고 있던 수
        var missedBreaks: Int?     // 그중 고신뢰(80% 이상)였는데 깨진 수
    }
    struct Bin: Codable, Identifiable {
        var range: String
        var survived: Int?
        var total: Int?
        var predictedPct: Double?
        var actualPct: Double?
        var id: String { range }
    }
    struct Calibration: Codable {
        var bins: [Bin]?
        var note: String?
    }
    struct Region: Codable, Identifiable {
        var label: String
        var hospitals: Int?
        var n: Int?
        var allPct: Double?
        var hiN: Int?
        var hiPct: Double?
        var warnN: Int?
        var warnPct: Double?
        var breaks: Int?
        var id: String { label }
    }
    struct RegimeCurrent: Codable {
        var level: Int?
        var breaks: Int?
        var ratio: Double?
        var ts: String?
    }
    struct Regime: Codable {
        var medianBreaks: Double?
        var current: RegimeCurrent?
        var surgePolls: Int?
    }
    struct TimePoint: Codable, Identifiable {
        var ts: String
        var n: Int
        var held: Int
        var hiN: Int?
        var hiHeld: Int?
        var warnN: Int?
        var warnHeld: Int?
        var breaks: Int?
        var surge: Int?
        var id: String { ts }
        var date: Date? { ISO.parse(ts) }
        var allPct: Double { n > 0 ? Double(held) / Double(n) * 100 : 0 }
        var hiPct: Double? { (hiN ?? 0) > 0 ? Double(hiHeld ?? 0) / Double(hiN ?? 1) * 100 : nil }
    }
    struct FeedItem: Codable, Identifiable {
        var ts: String
        var hpid: String
        var name: String
        var claimValue: Int?
        var newValue: Int?
        var delta: Int?
        var ageMin: Double?
        var pValid: Double?
        var becameFull: Bool?
        var id: String { ts + hpid }
    }

    var generatedAt: String?
    var windowHours: Int?
    var theta: Int?
    var modelTag: String?
    var polls: Int?
    var lastPollTs: String?
    var headline: Headline?
    var calibration: Calibration?
    var regions: [Region]?
    var regime: Regime?
    var timeseries: [TimePoint]?
    var feed: [FeedItem]?
    var limits: [String]?
    var demo: Bool?
    var error: String?

    /// 창 전체 유지율(%) — 그냥 믿을 때
    var overallPct: Double? {
        guard let ts = timeseries, !ts.isEmpty else { return nil }
        let n = ts.reduce(0) { $0 + $1.n }, h = ts.reduce(0) { $0 + $1.held }
        return n > 0 ? Double(h) / Double(n) * 100 : nil
    }
    /// 엔진 선별(조건부 확률 80% 이상) 유지율(%)
    var selectedPct: Double? {
        guard let ts = timeseries, !ts.isEmpty else { return nil }
        let n = ts.reduce(0) { $0 + ($1.hiN ?? 0) }, h = ts.reduce(0) { $0 + ($1.hiHeld ?? 0) }
        return n > 0 ? Double(h) / Double(n) * 100 : nil
    }
    var warnedPct: Double? {
        guard let ts = timeseries, !ts.isEmpty else { return nil }
        let n = ts.reduce(0) { $0 + ($1.warnN ?? 0) }, h = ts.reduce(0) { $0 + ($1.warnHeld ?? 0) }
        return n > 0 ? Double(h) / Double(n) * 100 : nil
    }
}
