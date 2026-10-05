import Foundation

/// MF_BERT 출력(문장 헤드 로짓 + 토큰 태그) -> v2 스키마 summary. voice/MF_BERT/decode.py의 decode()를 옮겼다.
///
/// 원본과 다른 점 하나: incidents 순서. 원본은 파이썬 set을 정렬해 주 사고 다음 순서가 실행마다 달라질 수 있다
/// (문자열 해시 무작위화). 여기서는 주 사고 다음을 labels의 보기 순서로 고정했다 — 내용은 같다.
public struct MFBertLogits {
    /// 문장 헤드 이름 -> 보기별 점수(배치 1개)
    public var heads: [String: [Float]]
    /// 복원한 토큰 줄의 태그(구간 태거 argmax), 길이 = offsets 수
    public var spanTags: [Int]

    public init(heads: [String: [Float]], spanTags: [Int]) {
        self.heads = heads
        self.spanTags = spanTags
    }
}

/// torch.argmax와 같게 최댓값이 여럿이면 앞쪽
func argmax(_ v: [Float]) -> Int {
    var best = 0
    for i in 1..<v.count where v[i] > v[best] { best = i }
    return best
}

public struct Span: Equatable {
    public let start: Int
    public let end: Int
    public let type: String
}

/// 토큰 태그 -> 글자 구간. 짝 없는 I-는 그 자리에서 새 구간을 연다.
public func decodeSpans(_ tags: [Int], offsets: [[Int]], labels: Labels = .shared) -> [Span] {
    let tagO = labels.spanTags.firstIndex(of: "O")!
    var spans: [Span] = []
    var current: Span?
    for (tag, off) in zip(tags, offsets) {
        let (start, end) = (off[0], off[1])
        if start == end || tag == -100 || tag == tagO { current = nil; continue }
        let parts = labels.spanTags[tag].split(separator: "-", maxSplits: 1).map(String.init)
        if parts[0] == "I", let cur = current, cur.type == parts[1] {
            current = Span(start: cur.start, end: end, type: cur.type)
            spans[spans.count - 1] = current!
            continue
        }
        current = Span(start: start, end: end, type: parts[1])
        spans.append(current!)
    }
    return spans
}

public func decode(text: String, logits: MFBertLogits, offsets: [[Int]], labels L: Labels = .shared) -> JSONValue {
    let undecided = L.undecided
    func single(_ name: String) -> String? {
        let label = L.single[name]![argmax(logits.heads[name]!)]
        return label == undecided ? nil : label
    }
    func positives(_ name: String) -> [String] {
        zip(L.multi[name]!, logits.heads[name]!).filter { $0.1 > 0 }.map(\.0)
    }

    let ktasLevel = Int(L.single["ktas"]![argmax(logits.heads["ktas"]!)])!

    // masked_minor: 예측 대분류에 속한 소분류(대분류가 미언급이면 미언급)만 남기고 1위
    let ccMajor = L.single["cc_major"]!, ccMinor = L.single["cc_minor"]!
    let major = argmax(logits.heads["cc_major"]!)
    let minorIdx: Int
    if major == ccMajor.firstIndex(of: undecided)! {
        minorIdx = ccMinor.firstIndex(of: undecided)!
    } else {
        let minorMajor = L.minors.map { L.majors.firstIndex(of: String($0.split(separator: "|")[0]))! } + [-1]
        let masked = zip(logits.heads["cc_minor"]!, minorMajor).map { $0.1 == major ? $0.0 : -Float.infinity }
        minorIdx = argmax(masked)
    }
    let minorLabel = ccMinor[minorIdx]
    let chiefComplaint: JSONValue
    if minorLabel == undecided {
        chiefComplaint = .object([("major", .null), ("minor", .null)])
    } else {
        let p = minorLabel.split(separator: "|", maxSplits: 1).map(String.init)
        chiefComplaint = .object([("major", .string(p[0])), ("minor", .string(p[1]))])
    }

    let sex = single("sex")
    let avpu = single("avpu")
    let medStatus = L.single["med_status"]![argmax(logits.heads["med_status"]!)]

    let primaryType = single("primary_incident")
    var incidentTypes = Set(positives("incidents"))
    if let p = primaryType { incidentTypes.insert(p) }
    var incidentDetail: [String: [String]] = [:]
    for item in positives("incident_detail") {
        let p = item.split(separator: "/", maxSplits: 1).map(String.init)
        incidentDetail[p[0], default: []].append(p[1])
    }
    let order = L.multi["incidents"]!
    let sortedTypes = incidentTypes.sorted { a, b in
        if (a == primaryType) != (b == primaryType) { return a == primaryType }
        return (order.firstIndex(of: a) ?? .max) < (order.firstIndex(of: b) ?? .max)
    }
    let incidents: [JSONValue] = sortedTypes.map { t in
        .object([("type", .string(t)), ("detail", .str(incidentDetail[t]?.first)), ("primary", .bool(t == primaryType))])
    }
    let diseaseCategory = incidentTypes.contains("질병") ? single("disease") : nil

    var treatDetail: [String: [String]] = [:]
    for item in positives("treatment_detail") {
        let p = item.split(separator: "/", maxSplits: 1).map(String.init)
        treatDetail[p[0], default: []].append(p[1])
    }
    let treatments: [JSONValue] = positives("treatment").map { item in
        let p = item.split(separator: "/", maxSplits: 1).map(String.init)
        return .object([("category", .string(p[0])), ("status", .string(p[1])), ("detail", .str(treatDetail[p[0]]?.first))])
    }

    let symptoms: [JSONValue] = positives("symptoms").map { item in
        let slash = item.lastIndex(of: "/")!  // rsplit("/", 1)
        return .object([("standard_name", .string(String(item[..<slash]))),
                        ("status", .string(String(item[item.index(after: slash)...])))])
    }

    var injurySide: [String: String] = [:]
    for item in positives("injury_side") {
        let p = item.split(separator: "/", maxSplits: 1).map(String.init)
        injurySide[p[0]] = p[1]
    }
    let injuries: [JSONValue] = positives("injury").map { item in
        let p = item.split(separator: "/", maxSplits: 1).map(String.init)
        return .object([("region", .string(p[0])), ("type", .string(p[1])), ("side", .str(injurySide[p[0]])),
                        ("status", .string("확인"))])
    }

    // 구간: offsets는 코드포인트 위치라 스칼라 배열로 자른다
    let scalars = Array(text.unicodeScalars)
    var byType: [String: [String]] = Dictionary(uniqueKeysWithValues: L.spanTypes.map { ($0, []) })
    for s in decodeSpans(logits.spanTags, offsets: offsets, labels: L) {
        var piece = ""
        piece.unicodeScalars.append(contentsOf: scalars[max(0, s.start)..<min(s.end, scalars.count)])
        byType[s.type]!.append(piece)
    }

    var vitals: [JSONValue] = []
    for spanText in byType["VITALS"]! {
        let values = parseVitals(spanText)
        if values.contains(where: { $0.1 != .null }) {
            vitals.append(.object([("sequence", .int(vitals.count + 1))] + values + [("evidence", .array([.string(spanText)]))]))
        }
    }

    let ageText = byType["AGE"]!.joined(separator: " ")
    let ageEvidence = JSONValue.array(byType["AGE"]!.map(JSONValue.string))
    let age: JSONValue
    if ageText.isEmpty {
        age = .object([("years", .null), ("months", .null), ("band", .null), ("evidence", .array([]))])
    } else {
        let a = parseAge(ageText)
        age = .object([("years", a.years.map(JSONValue.int) ?? .null), ("months", a.months.map(JSONValue.int) ?? .null),
                       ("band", .str(a.band)), ("evidence", ageEvidence)])
    }

    let onsetText = byType["ONSET"]!.first
    let onset = JSONValue.object([("text", .str(onsetText)),
                                  ("minutes_ago", onsetText.flatMap(parseOnset).map(JSONValue.int) ?? .null)])

    return .object([
        ("call_type", .null),
        ("ktas_level", .int(ktasLevel)),
        ("ktas_evidence", .null),
        ("chief_complaint", chiefComplaint),
        ("suspected_diagnosis", .array(byType["DX"]!.map { .object([("text", .string($0))]) })),
        ("vitals", .array(vitals)),
        ("consciousness", avpu.map { .array([.object([("sequence", .int(1)), ("avpu", .string($0))])]) } ?? .array([])),
        ("symptoms", .array(symptoms)),
        ("onset", onset),
        ("incidents", .array(incidents)),
        ("disease_category", .str(diseaseCategory)),
        ("injuries", .array(injuries)),
        ("treatments", .array(treatments)),
        ("age", age),
        ("sex", .str(sex)),
        ("medications", .object([("status", .string(medStatus)),
                                 ("items", .array(byType["MED"]!.map { .object([("text", .string($0))]) }))])),
        ("notes", .null),
        ("meta", .object([("not_predicted", .array(["call_type", "ktas_evidence", "notes"].map(JSONValue.string)))])),
    ])
}
