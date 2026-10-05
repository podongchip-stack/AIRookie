import Foundation

// voice/MF_BERT/parse.py를 한 줄씩 옮겼다 — 모델이 찾은 VITALS·AGE·ONSET 구간을 규칙으로 읽는다(규칙 기반).
// 정규식은 원본과 같은 문자열을 쓰고(NSRegularExpression = ICU), 위치는 UTF-16 단위다. 통화 텍스트(한글·영숫자)는
// 전부 BMP라 UTF-16 위치 = Python 코드포인트 위치다. 원본이 바뀌면 이 파일과 Tests의 픽스처를 함께 갱신한다.

public let currentYear = 2026

private let digits: [Character: Int] = ["영": 0, "일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "륙": 6, "칠": 7, "팔": 8, "구": 9]
private let units: [Character: Int] = ["십": 10, "백": 100, "천": 1000]
private let nativeTens: [(String, Int)] = [("열", 10), ("스물", 20), ("스무", 20), ("서른", 30), ("마흔", 40), ("쉰", 50),
                                           ("예순", 60), ("일흔", 70), ("여든", 80), ("아흔", 90)]
private let nativeOnes: [(String, Int)] = [("하나", 1), ("한", 1), ("둘", 2), ("두", 2), ("셋", 3), ("세", 3), ("석", 3), ("넷", 4),
                                           ("네", 4), ("넉", 4), ("다섯", 5), ("여섯", 6), ("일곱", 7), ("여덟", 8), ("아홉", 9)]
private let sino = "영일이삼사오육륙칠팔구십백천"

/// Python `sorted(keys, key=len, reverse=True)`와 같은 순서(같은 길이는 원래 순서 유지)
private func alternation(_ pairs: [(String, Int)]) -> String {
    pairs.enumerated().sorted { a, b in
        a.element.0.count != b.element.0.count ? a.element.0.count > b.element.0.count : a.offset < b.offset
    }.map(\.element.0).joined(separator: "|")
}

let nativeTensRE = alternation(nativeTens)
let nativeOnesRE = alternation(nativeOnes)

/// 수 하나: 아라비아(소수 포함) | 한자어 수사(띄어쓰기 허용, 점 소수 허용) | 고유어
public let numberRE = "(?:\\d+(?:\\.\\d+)?"
    + "|[\(sino)](?:\\s?[\(sino)])*(?:\\s?점\\s?[\(sino)](?:\\s?[\(sino)])*)?"
    + "|(?:\(nativeTensRE))(?:\(nativeOnesRE))?|(?:\(nativeOnesRE)))"

// MARK: - 정규식 도우미 (Python re의 search / match / fullmatch / finditer)

struct Rx {
    let re: NSRegularExpression
    init(_ pattern: String) { re = try! NSRegularExpression(pattern: pattern) }

    func search(_ s: String) -> RxMatch? {
        let ns = s as NSString
        return re.firstMatch(in: s, range: NSRange(location: 0, length: ns.length)).map { RxMatch(m: $0, s: ns) }
    }

    /// 문자열 맨 앞에서만(re.match)
    func match(_ s: String) -> RxMatch? {
        let ns = s as NSString
        return re.firstMatch(in: s, options: .anchored, range: NSRange(location: 0, length: ns.length)).map { RxMatch(m: $0, s: ns) }
    }

    func finditer(_ s: String) -> [RxMatch] {
        let ns = s as NSString
        return re.matches(in: s, range: NSRange(location: 0, length: ns.length)).map { RxMatch(m: $0, s: ns) }
    }
}

struct RxMatch {
    let m: NSTextCheckingResult
    let s: NSString
    var start: Int { m.range.location }
    var end: Int { m.range.location + m.range.length }
    func group(_ i: Int = 0) -> String? {
        let r = m.range(at: i)
        return r.location == NSNotFound ? nil : s.substring(with: r)
    }
}

private var rxCache: [String: Rx] = [:]
private let rxLock = NSLock()
func rx(_ pattern: String) -> Rx {
    rxLock.lock(); defer { rxLock.unlock() }
    if let r = rxCache[pattern] { return r }
    let r = Rx(pattern)
    rxCache[pattern] = r
    return r
}

/// re.fullmatch — 전체가 맞아야 한다(백트래킹 포함)
func fullmatch(_ pattern: String, _ s: String) -> RxMatch? { rx("(?:\(pattern))\\z").match(s) }

/// Python 슬라이스 s[a:b] (UTF-16 위치, 범위 밖은 잘라냄)
func slice(_ s: String, _ a: Int, _ b: Int? = nil) -> String {
    let ns = s as NSString
    let lo = max(0, min(a, ns.length)), hi = max(lo, min(b ?? ns.length, ns.length))
    return ns.substring(with: NSRange(location: lo, length: hi - lo))
}

func charAt(_ s: String, _ i: Int) -> String { slice(s, i, i + 1) }

private func isHangul(_ c: String) -> Bool { rx("[가-힣]").match(c) != nil }
private func isDigitString(_ s: String) -> Bool { !s.isEmpty && s.allSatisfy { $0.isNumber && $0.isASCII } }

// MARK: - 수 읽기

func sinoInt(_ raw: String) -> Int? {
    let s = raw.replacingOccurrences(of: " ", with: "")
    if s.isEmpty || s.contains(where: { !sino.contains($0) }) { return nil }
    if s.count > 1 && s.allSatisfy({ digits[$0] != nil }) {  // "구칠" 같은 자릿수 나열
        return Int(s.map { String(digits[$0]!) }.joined())
    }
    var total = 0, current = 0
    for c in s {
        if let d = digits[c] { current = d } else { total += (current == 0 ? 1 : current) * units[c]!; current = 0 }
    }
    return total + current
}

/// 수 하나를 읽는다. 못 읽으면 nil.
public func toNumber(_ raw: String) -> Double? {
    var token = raw.trimmingCharacters(in: .whitespacesAndNewlines)
    if token.isEmpty { return nil }
    if fullmatch("\\d+(?:\\.\\d+)?", token) != nil { return Double(token) }
    if let m = fullmatch("(\(nativeTensRE))?(\(nativeOnesRE))?", token), m.group(1) != nil || m.group(2) != nil {
        let tens = m.group(1).flatMap { g in nativeTens.first { $0.0 == g }?.1 } ?? 0
        let ones = m.group(2).flatMap { g in nativeOnes.first { $0.0 == g }?.1 } ?? 0
        return Double(tens + ones)
    }
    if token.contains("점") {
        let parts = token.split(separator: "점", maxSplits: 1, omittingEmptySubsequences: false).map(String.init)
        let w = sinoInt(parts[0])
        let f = parts[1].replacingOccurrences(of: " ", with: "").compactMap { digits[$0] }.map(String.init).joined()
        guard let w, !f.isEmpty else { return nil }
        return Double("\(w).\(f)")
    }
    let chars = Array(token)
    if chars.count > 1, "이일".contains(chars[chars.count - 1]), digits[chars[chars.count - 2]] != nil {  // "구십삼이고"의 "이"는 조사
        token = String(chars.dropLast())
    }
    return sinoInt(token).map(Double.init)
}

/// Python _as_int: 정수면 int로, 아니면 소수 그대로
func asInt(_ x: Double) -> JSONValue { x == x.rounded() && abs(x) < 1e15 ? .int(Int(x)) : .double(x) }

/// 글 안의 첫 수. "맥박이 100"의 "이"처럼 낱말에 붙은 한 글자 한자어 수사는 건너뛴다.
func firstNumber(_ text: String) -> RxMatch? {
    for m in rx("(\(numberRE))").finditer(text) {
        let token = m.group(1)!
        if (token as NSString).length == 1 && !isDigitString(token) {
            let before = m.start > 0 ? charAt(text, m.start - 1) : " "
            let after = m.end < (text as NSString).length ? charAt(text, m.end) : " "
            if isHangul(before) || isHangul(after) { continue }
        }
        return m
    }
    return nil
}

// MARK: - 활력징후

let unmeasurableRE = "(안\\s?잡|잡히지\\s?않|측정\\S*\\s?(?:안|불가|되지\\s?않)|체크\\S*\\s?안|촉지\\S*\\s?(?:안|않|불가)|안\\s?나와|무맥)"
/// 원본 dict 순서 그대로(키 탐색 순서가 결과에 영향)
let vitalKeys: [(String, String)] = [
    ("hr", "(?:맥박|심박수?|HR|펄스|pulse)"),
    ("rr", "(?:호흡수?|RR)"),
    ("spo2", "(?:산소\\s?포화도|산소\\s?포아도|포화도|새츄레이션|사츄레이션|SpO2|SPO2|산소)"),
    ("glucose", "(?:혈당|BST|bst|당\\s?수치)"),
    ("bt", "(?:체온|열|BT)"),
]
let bpRE = "(?:혈압|BP)?\\s*(?:은|는|이)?\\s*(\(numberRE))\\s*(?:에|/|바이|over)\\s*(\(numberRE))"
public let vitalFields = ["sbp", "dbp", "hr", "rr", "bt", "spo2", "glucose"]

/// 활력징후 보고 한 묶음 -> [sbp, dbp, hr, rr, bt, spo2, glucose] (없는 값은 .null)
public func parseVitals(_ text: String) -> [(String, JSONValue)] {
    var out: [String: JSONValue] = Dictionary(uniqueKeysWithValues: vitalFields.map { ($0, JSONValue.null) })
    let t = text
    let unmeasurable = rx(unmeasurableRE)
    if let bpKey = rx("(혈압|BP)").search(t), unmeasurable.search(slice(t, bpKey.end, bpKey.end + 12)) != nil {
        out["sbp"] = .string("측정불가"); out["dbp"] = .string("측정불가")
    } else if let m = rx(bpRE).search(t), let s = toNumber(m.group(1)!), let d = toNumber(m.group(2)!), s > d {
        out["sbp"] = asInt(s); out["dbp"] = asInt(d)
    }
    let anyKey = rx(vitalKeys.map(\.1).joined(separator: "|") + "|혈압|BP")
    let number = rx("(\(numberRE))")
    for (key, pattern) in vitalKeys {
        for km in rx(pattern).finditer(t) {
            let rest = slice(t, km.end, km.end + 30)
            if key == "rr", km.group()!.hasPrefix("호흡"), rx("\\s?(?:곤란|음|기|정지|이\\s|을|이\\s?얕|이\\s?빠)").match(rest) != nil {
                continue  // 호흡곤란·호흡음 등은 호흡수가 아니다
            }
            let window = anyKey.search(rest).map { slice(rest, 0, $0.start) } ?? rest  // 다음 활력징후 키워드 앞까지만 본다
            if unmeasurable.search(slice(window, 0, 20)) != nil && rx("\\d").search(slice(window, 0, 20)) == nil {
                out[key] = .string("측정불가")
                break
            }
            var nm: RxMatch?
            if key == "spo2" {  // "산소 15리터에 94%"처럼 다른 수가 끼면 %가 붙은 수가 포화도다
                nm = rx("(\(numberRE))\\s?(?:%|퍼센트|프로|퍼)").search(window)
                if nm == nil {
                    nm = number.finditer(window).first { c in
                        rx("\\s?(?:리터|L|l|ℓ)").match(slice(window, c.end)) == nil
                            && !((c.group(1)! as NSString).length == 1 && !isDigitString(c.group(1)!))
                    }
                    if let found = nm, found.start > 15 { nm = nil }
                }
            }
            if nm == nil {
                // 키워드 뒤 짧은 군말("분당", "재측정 결과는", "실온에서") 다음의 첫 수
                nm = firstNumber(window)
                if nm == nil || nm!.start > 15 { continue }
            }
            guard var value = toNumber(nm!.group(1)!) else { continue }
            if key == "bt" {
                if let bu = rx("\\s?도\\s?(\(numberRE))\\s?부?").match(slice(window, nm!.end)), value == value.rounded(.towardZero),
                   let frac = toNumber(bu.group(1)!), frac < 10 {
                    value += frac / 10
                }
                if !(30...43).contains(value) { continue }
            }
            out[key] = asInt(value)
            break
        }
    }
    if out["bt"] == .null, let m = rx("(\(numberRE))\\s?도(?:\\s?(\(numberRE))\\s?부)?").search(t) {  // "36.8도로 정상"처럼 키워드 없이
        if var value = toNumber(m.group(1)!) {
            if let frac = m.group(2) { value += (toNumber(frac) ?? 0) / 10 }
            if (34...42).contains(value) { out["bt"] = asInt(value) }
        }
    }
    return vitalFields.map { ($0, out[$0]!) }
}

// MARK: - 나이

/// 나이 구간 -> years, months, band. 연령대만 말하면 band만.
public func parseAge(_ t: String) -> (years: Int?, months: Int?, band: String?) {
    if rx("10\\s?세\\s?미만").search(t) != nil { return (nil, nil, "10세 미만") }
    if let m = rx("(\(numberRE))\\s?년생").search(t), let n = toNumber(m.group(1)!) {
        let year = n < 100 ? Int(n) + (n > Double(currentYear % 100) ? 1900 : 2000) : Int(n)
        return (currentYear - year, nil, nil)
    }
    if let m = rx("생후\\s?(\(numberRE))\\s?(개월|일|주)").search(t) ?? rx("(\(numberRE))\\s?(개월)").search(t),
       let n = toNumber(m.group(1)!) {
        return (nil, m.group(2) == "개월" ? Int(n) : 0, nil)
    }
    if rx("(신생아|출생|태어난|갓\\s?난|방금\\s?낳)").search(t) != nil { return (nil, 0, nil) }
    for m in rx("(\(numberRE))\\s?(?:세|살)").finditer(t) {
        let token = m.group(1)!
        // "여성분이세요"의 "이"처럼 낱말 속 한 글자는 수가 아니다
        if (token as NSString).length == 1, !isDigitString(token), m.start > 0, isHangul(charAt(t, m.start - 1)) { continue }
        if let n = toNumber(token), n < 130 { return (Int(n), nil, nil) }
    }
    if let m = rx("(\(numberRE))\\s?대").search(t), let n = toNumber(m.group(1)!),
       n.truncatingRemainder(dividingBy: 10) == 0, (10...100).contains(n) {
        return (nil, nil, n >= 90 ? "90대 이상" : "\(Int(n))대")
    }
    if rx("(애기|아기|영아|유아|남아|여아|신생아)").search(t) != nil { return (nil, nil, "10세 미만") }
    return (nil, nil, nil)
}

// MARK: - 발생 시점

private let onsetUnits: [String: Double] = ["분": 1, "시간": 60, "일": 1440, "주일": 10080, "주": 10080, "달": 43200, "개월": 43200]
private let nativeDays: [(String, Int)] = [("하루", 1), ("이틀", 2), ("사흘", 3), ("나흘", 4), ("닷새", 5), ("엿새", 6), ("이레", 7),
                                           ("열흘", 10), ("보름", 15)]

/// 발생 시각 구간 -> 몇 분 전. 계산할 수 없으면 nil.
public func parseOnset(_ text: String) -> Int? {
    let clock = rx("(\(numberRE))\\s?시\\s?(\(numberRE))\\s?분")  // 시각(오후 2시 15분)은 경과 시간이 아니다
    var t = clock.re.stringByReplacingMatches(in: text, range: NSRange(location: 0, length: (text as NSString).length),
                                              withTemplate: " ")
    t = t.replacingOccurrences(of: "일주일", with: "1주일")
    if rx("(방금|막\\s?전)").search(t) != nil { return 0 }
    if t.contains("반나절") { return 720 }
    if rx("(엊그제|그저께|그제)").search(t) != nil { return 2880 }
    if let m = rx("(" + nativeDays.map(\.0).joined(separator: "|") + ")(?!\\s?종일)").search(t) {
        return nativeDays.first { $0.0 == m.group(1) }!.1 * 1440
    }
    guard let m = rx("(\(numberRE))\\s?(시간|분|주일|일|주|달|개월)(?!\\s?(?:후|뒤))(\\s?반)?(?:\\s?(\(numberRE))\\s?분)?").search(t),
          let n = toNumber(m.group(1)!) else { return nil }
    let unit = onsetUnits[m.group(2)!]!
    var minutes = n * unit
    if m.group(3) != nil { minutes += unit / 2 }
    if let extra = m.group(4), m.group(2) == "시간" { minutes += toNumber(extra) ?? 0 }
    return Int(minutes)
}
