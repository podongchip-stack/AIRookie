import Foundation

// 외상 부위 도해의 순수 로직 — 안드로이드 core/BodyInjury.kt(아이패드 BodyInjuryView.swift의 BodyRegion·BodyEdits·
// InjuryRisk·InjuryMapper와 BodyShape 확장)를 그대로 옮겼다.
// 부위는 통화 요약의 글자에서 낱말 규칙으로 찾는다(AI 아님). 위험도 색도 규칙이며 전문의 검토 전 초안이다 — 순위·병원 선택에는 쓰지 않는다.
// 좌표는 모두 그림 칸 기준 0~1이다(가로 0~1, 세로 0~1). 그리는 쪽이 칸 크기를 곱한다.

public enum BodyRegion: Int, CaseIterable, Hashable {
    case head, face, neck, chest, abdomen, back, pelvis, arm, hand, leg, foot

    public var label: String {
        switch self {
        case .head: "머리"; case .face: "얼굴"; case .neck: "목"; case .chest: "가슴"; case .abdomen: "배"
        case .back: "등·허리"; case .pelvis: "골반"; case .arm: "팔"; case .hand: "손"; case .leg: "다리"; case .foot: "발"
        }
    }

    public var isLimb: Bool { self == .arm || self == .leg || self == .hand || self == .foot }
}

/// 환자 기준 좌·우(그림에서는 좌우를 바꿔 그린다 — 보는 사람의 왼쪽이 환자의 오른쪽)
public enum BodySide: Hashable { case left, right, unknown
    public var label: String { switch self { case .left: "좌"; case .right: "우"; case .unknown: "" } }
}

public struct BodyMark: Hashable {
    public let region: BodyRegion
    public let side: BodySide
    public init(_ region: BodyRegion, _ side: BodySide = .unknown) { self.region = region; self.side = side }
    public var label: String { (side == .unknown ? "" : side.label + " ") + region.label }
}

/// 외상 도해를 눌러서 고친 것 — 통화 요약(AI)에 부위를 더하거나 빼고, 부위마다 처치를 적는다.
///  · 부위 → hub `patient_override.injuryStatus`(병원 화면·재매칭에 반영, "구급대원 확인" 도장)
///  · 처치 → 인계확인서의 처치 칸(기도·호흡·순환·약품·고정·기타) + 병원에는 추가 정보로
public struct BodyEdits: Equatable {
    /// 통화에 없었는데 구급대원이 찍은 부위
    public var added: Set<BodyMark> = []
    /// 통화에서 뽑혔지만 "여긴 아니다"라고 한 부위
    public var removed: Set<BodyMark> = []
    /// 부위별 처치
    public var cares: [BodyMark: [String]] = [:]

    public init(added: Set<BodyMark> = [], removed: Set<BodyMark> = [], cares: [BodyMark: [String]] = [:]) {
        self.added = added; self.removed = removed; self.cares = cares
    }

    /// 인계확인서 처치 칸으로 — "좌 다리 부목 고정"
    public var careLines: [String] { fittedCares.flatMap { mark, list in list.map { "\(mark.label) \($0)" } }.sorted() }

    /// 부위에 맞는 처치만 — 다른 기기에서 온 값이나 예전에 적은 값에 맞지 않는 처치(예: 팔에 산소투여)가 있어도 여기서 걸러진다
    public var fittedCares: [BodyMark: [String]] {
        var out: [BodyMark: [String]] = [:]
        for (mark, list) in cares {
            let kept = list.filter { BodyCare.fits(mark, $0) }
            if !kept.isEmpty { out[mark] = kept }
        }
        return out
    }

    /// hub로 보낼 증상 줄 — 구급대원이 찍은 부위
    public var addedLines: [String] { added.map { $0.label + " 외상(구급대원 확인)" }.sorted() }

    public var isEmpty: Bool { added.isEmpty && removed.isEmpty && careLines.isEmpty }

    /// 고친 부위 수(한 부위에 외상·처치를 같이 적어도 한 곳)
    public var markCount: Int { Set(added).union(removed).union(fittedCares.keys).count }

    /// 지금 내용의 지문 — 보낸 뒤 또 바뀌었는지만 본다
    public var signature: String {
        (added.map { "+" + $0.label }.sorted() + removed.map { "-" + $0.label }.sorted() + careLines).joined(separator: "|")
    }

    /// 한 부위를 적용한 새 값 — `fromCall`은 그 부위가 통화 요약에서 온 것인가
    public func applied(_ mark: BodyMark, on: Bool, careList: [String], fromCall: Bool) -> BodyEdits {
        var v = self
        if on {
            if fromCall { v.removed.remove(mark) } else { v.added.insert(mark) }
            let fitted = careList.filter { BodyCare.fits(mark, $0) }
            if fitted.isEmpty { v.cares.removeValue(forKey: mark) } else { v.cares[mark] = fitted }
        } else {
            if fromCall { v.removed.insert(mark) } else { v.added.remove(mark) }
            v.cares.removeValue(forKey: mark)
        }
        return v
    }
}

/// 외상 부위에서 고를 수 있는 처치. 어휘는 voice 처치판(2026-10-29)의 `treat_categories` 28범주이고, 한글 이름은 hub `voice_treatments.py`와
/// 글자까지 같다 — 통화에서 AI가 뽑은 처치와 대원이 도해에서 고른 처치가 같은 문자열이라 서식·병원 화면에서 겹치지 않는다.
/// 부위마다 **그 부위에 실제로 하는 처치만** 보인다. 산소·CPR·약물·정맥로처럼 부위에 속하지 않는 전신 처치는 여기에 없다 —
/// 통화 요약의 처치로는 그대로 인계확인서에 들어간다. 부위별 목록은 전문의 검토 전 초안이다(안드로이드 core/BodyInjury.kt `BodyCare`와 같다).
public enum BodyCare {
    /// 28범주 전체(순서는 voice·hub와 같다)
    public static let all: [(key: String, label: String)] = [
        ("oxygen", "산소투여"), ("suction", "기도 흡인"), ("foreign_body", "기도 이물 제거"), ("airway_basic", "기본 기도확보"),
        ("airway_advanced", "전문 기도확보"), ("ventilation", "인공호흡"), ("cpr", "CPR"), ("defib", "AED"),
        ("iv", "정맥로 확보"), ("fluid", "수액공급"), ("bleeding", "지혈"), ("med_aspirin", "아스피린 투여"),
        ("med_nitro", "니트로글리세린 투여"), ("med_glucose", "포도당 투여"), ("med_epinephrine", "에피네프린 투여"),
        ("med_bronchodilator", "기관지확장제 투여"), ("med_other", "기타 약물투여"), ("spinal", "척추 고정"), ("splint", "부목 고정"),
        ("wound", "상처처치"), ("burn", "화상 처치"), ("irrigation", "세척"), ("cold_pack", "냉찜질"), ("cooling", "냉각"),
        ("warming", "보온"), ("position", "체위 조절"), ("delivery", "분만 처치"), ("other", "기타 처치"),
    ]

    private static let common = ["지혈", "상처처치", "화상 처치", "세척", "냉찜질", "체위 조절"]
    private static let splint = "부목 고정"
    private static let spinal = "척추 고정"
    private static let airway = ["기도 흡인", "기도 이물 제거"]

    /// 그 부위에서 고를 수 있는 처치 — 가장 해당되는 것이 앞에 온다
    public static func optionsFor(_ region: BodyRegion) -> [String] {
        switch region {
        case .arm, .hand, .leg, .foot: return [splint] + common
        case .pelvis: return [splint, spinal] + common
        case .head, .back: return [spinal] + common
        case .neck: return [spinal] + airway + common
        case .face: return airway + common
        case .chest, .abdomen: return common
        }
    }

    public static func fits(_ mark: BodyMark, _ label: String) -> Bool { optionsFor(mark.region).contains(label) }
}

/// 통화 요약의 항목 하나와 그 항목이 가리키는 부위
public struct MappedInjury { public let text: String; public let marks: [BodyMark]; public let isMulti: Bool }

/// 외상 한 건의 위험도 — 규칙 기반, 전문의 검토 전 초안. 색만 나눌 뿐 순위·병원 선택에는 쓰지 않는다
public enum InjuryTier: Int, Comparable {
    case low, medium, high
    public var label: String { switch self { case .low: "낮음"; case .medium: "중간"; case .high: "높음" } }
    public static func < (a: InjuryTier, b: InjuryTier) -> Bool { a.rawValue < b.rawValue }
}

public enum InjuryRisk {
    /// 적색 깃발 — 하나라도 보이면 높음
    private static let highWords = [
        "관통", "자상", "총상", "절단", "압궤", "개방성", "개방 골절", "개방성 골절", "골반 골절", "척추 손상", "척수",
        "대량 출혈", "대량출혈", "다량 출혈", "출혈 지속", "동맥", "토혈", "객혈", "혈흉", "기흉", "혈복강", "복강 내 출혈",
        "2도 화상", "3도 화상", "흡입 화상", "기도 화상", "감전", "익수", "목맴", "교액", "질식", "기도 폐쇄",
        "의식 저하", "의식저하", "무반응", "반응 없음", "혼수", "지남력", "경련", "발작", "마비", "편마비",
        "호흡 곤란", "호흡곤란", "호흡 정지", "무호흡", "청색증", "심정지", "심폐", "쇼크", "저혈압", "저산소",
        "뇌출혈", "뇌졸중", "지주막하", "심근경색", "경색 의심", "대동맥", "아나필락시스", "패혈",
        "다발성", "중증",
    ]
    /// 구조가 상한 것 — 중간
    private static let mediumWords = [
        "골절", "탈구", "열상", "자창", "화상", "출혈", "변형", "함몰", "타박상", "혈종", "압통", "복통", "흉통",
        "깊은", "찢어", "심한", "구토", "어지럼", "실신", "발열", "호흡 불편", "숨참",
    ]
    /// 부정 표현 — "출혈 없음"처럼 없다고 말한 것은 깃발로 세지 않는다
    private static let negations = ["없음", "없다", "없습니다", "아님", "아니", "음성", "정상", "소실", "해소", "부인"]
    /// 중심부 — 낱말이 가벼워도 중간부터 본다(몸통·머리)
    private static let coreRegions: Set<BodyRegion> = [.head, .neck, .chest, .abdomen, .pelvis, .back]

    /// 한 건의 등급은 (낱말 등급, 부위 기본 등급) 중 높은 쪽이다 — "머리 타박"은 타박(낮음)이어도 머리라서 중간
    public static func tier(_ text: String, _ region: BodyRegion?) -> InjuryTier {
        if negations.contains(where: { text.contains($0) }) { return .low }
        if highWords.contains(where: { text.contains($0) }) { return .high }
        let byWord: InjuryTier = mediumWords.contains(where: { text.contains($0) }) ? .medium : .low
        let byRegion: InjuryTier = (region.map { coreRegions.contains($0) } ?? false) ? .medium : .low
        return max(byWord, byRegion)
    }

    // 활력징후·의식 — 숫자라 추측이 없다. hub transport_triage.py와 같은 공개 표준 NEWS2(RCP 2017, Scale 1)
    private struct Band { let lo: Double; let hi: Double?; let score: Int }
    private static let news2Bands: [String: [Band]] = [
        "rr": [Band(lo: 0, hi: 8, score: 3), Band(lo: 9, hi: 11, score: 1), Band(lo: 12, hi: 20, score: 0), Band(lo: 21, hi: 24, score: 2), Band(lo: 25, hi: nil, score: 3)],
        "spo2": [Band(lo: 0, hi: 91, score: 3), Band(lo: 92, hi: 93, score: 2), Band(lo: 94, hi: 95, score: 1), Band(lo: 96, hi: nil, score: 0)],
        "sbp": [Band(lo: 0, hi: 90, score: 3), Band(lo: 91, hi: 100, score: 2), Band(lo: 101, hi: 110, score: 1), Band(lo: 111, hi: 219, score: 0), Band(lo: 220, hi: nil, score: 3)],
        "hr": [Band(lo: 0, hi: 40, score: 3), Band(lo: 41, hi: 50, score: 1), Band(lo: 51, hi: 90, score: 0), Band(lo: 91, hi: 110, score: 1), Band(lo: 111, hi: 130, score: 2), Band(lo: 131, hi: nil, score: 3)],
        "bt": [Band(lo: 0, hi: 35, score: 3), Band(lo: 35.1, hi: 36, score: 1), Band(lo: 36.1, hi: 38, score: 0), Band(lo: 38.1, hi: 39, score: 1), Band(lo: 39.1, hi: nil, score: 2)],
    ]
    static func band(_ name: String, _ value: Double) -> Int {
        news2Bands[name]?.first { value >= $0.lo && ($0.hi == nil || value <= $0.hi!) }?.score ?? 0
    }

    public struct VitalTier { public let tier: InjuryTier; public let reason: String? }

    /// 최근 활력징후·의식 → (등급, 근거 한 줄). 값이 없으면 낮음·근거 없음
    public static func vitalTier(_ patient: PatientInfo?) -> VitalTier {
        guard let patient else { return VitalTier(tier: .low, reason: nil) }
        var score = 0
        var reasons: [String] = []
        if let v = patient.vitals?.last {
            let items: [(String, Double?, String)] = [("rr", v.rr, "RR"), ("spo2", v.spo2, "SpO₂"), ("sbp", v.sbp, "SBP"), ("hr", v.hr, "HR"), ("bt", v.bt, "BT")]
            for (name, value, label) in items {
                guard let value else { continue }
                let s = band(name, value)
                score += s
                if s >= 2 { reasons.append("\(label) \(value.rounded() == value ? String(Int(value)) : String(format: "%.1f", value))") }
            }
        }
        if let avpu = DisplayLabels.avpu(patient.consciousness), avpu != "A" { score += 3; reasons.append("의식 \(avpu)") }
        let tier: InjuryTier = score >= 7 ? .high : score >= 5 ? .medium : .low
        return VitalTier(tier: tier, reason: reasons.isEmpty ? nil : "NEWS2 \(score) · " + reasons.joined(separator: " · "))
    }
}

public enum InjuryMapper {
    /// 부위 낱말 — 긴 낱말을 먼저 본다("발목"이 "목"보다 먼저여야 발목 부상이 목으로 가지 않는다)
    private static let keywords: [(BodyRegion, String)] = {
        let groups: [(BodyRegion, [String])] = [
            (.head, ["머리", "두부", "두개", "뇌", "이마", "전두", "후두", "측두", "두피"]),
            (.face, ["얼굴", "안면", "눈", "코피", "코", "입", "턱", "치아", "귀", "구강"]),
            (.neck, ["목", "경부", "경추", "기도"]),
            (.chest, ["가슴", "흉부", "흉곽", "흉골", "흉통", "늑골", "갈비", "쇄골", "심장", "심와", "폐"]),
            (.abdomen, ["복부", "복강", "상복부", "하복부", "명치", "옆구리", "배", "위장", "간", "비장", "신장"]),
            (.back, ["등허리", "허리", "요추", "흉추", "척추", "견갑", "등"]),
            (.pelvis, ["골반", "둔부", "엉덩이", "치골", "사타구니", "고관절", "회음"]),
            (.arm, ["팔꿈치", "주관절", "전완", "상완", "어깨", "견관절", "상지", "팔"]),
            (.hand, ["손가락", "손목", "손등", "손바닥", "수부", "손"]),
            (.leg, ["허벅지", "대퇴", "무릎", "슬관절", "정강", "종아리", "발목", "하지", "다리"]),
            (.foot, ["발가락", "발등", "발바닥", "족부", "발"]),
        ]
        return groups.flatMap { r, ws in ws.map { (r, $0) } }.sorted { $0.1.count > $1.1.count }
    }()

    /// 부위를 하나로 못 집는 말 — 몸통과 팔다리를 다 표시한다
    private static let multiWords = ["다발성", "다발", "전신", "온몸", "여러 군데", "다수 부위"]

    public static let multiMarks: [BodyMark] = [
        BodyMark(.head), BodyMark(.chest), BodyMark(.abdomen),
        BodyMark(.arm, .left), BodyMark(.arm, .right), BodyMark(.hand, .left), BodyMark(.hand, .right),
        BodyMark(.leg, .left), BodyMark(.leg, .right), BodyMark(.foot, .left), BodyMark(.foot, .right),
    ]

    /// 통화 요약에서 부위가 보이는 항목을 뽑는다. 예상 병명은 hub가 " · "로 이어 붙인 것이라 다시 쪼갠다
    public static func parse(_ p: PatientInfo?) -> [MappedInjury] {
        guard let p else { return [] }
        var items: [String] = []
        items += (p.expectedDiagnosis ?? "").split(whereSeparator: { "·,/".contains($0) }).map(String.init)
        items += p.injuryStatus ?? []
        if let c = p.chiefComplaint { items.append(c) }
        items += (p.extraNotes ?? []).map(\.text)
        var seen = Set<String>()
        return items.map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty && seen.insert($0).inserted && !isCategoryCode($0) }
            .map { MappedInjury(text: $0, marks: marks($0), isMulti: isMulti($0)) }
    }

    public static func isMulti(_ text: String) -> Bool { multiWords.contains { text.contains($0) } }

    /// 한 항목의 부위. 같은 항목에 부위가 여럿이면 다 표시한다("머리와 다리 열상")
    public static func marks(_ text: String) -> [BodyMark] {
        if isMulti(text) { return multiMarks }
        var found: [BodyMark] = []
        var rest = text
        for (region, word) in keywords {
            guard rest.contains(word) else { continue }
            rest = rest.replacingOccurrences(of: word, with: " ")
            if found.contains(where: { $0.region == region }) { continue }
            if region.isLimb { found += sides(text).map { BodyMark(region, $0) } } else { found.append(BodyMark(region)) }
        }
        return found
    }

    /// MF_BERT 주 호소의 대분류 코드("T 외상"·"I 심혈관계")는 손상이 아니라 분류표라 그림에서 뺀다
    private static func isCategoryCode(_ text: String) -> Bool { text.range(of: "^[A-Z][ .]", options: .regularExpression) != nil }

    /// 팔·다리의 좌우. 안 적혀 있으면 양쪽 다 표시한다. "좌"·"우" 한 글자는 낱말 앞에서만 본다("염좌"에 안 걸리게)
    private static func sides(_ text: String) -> [BodySide] {
        func mark(_ one: String, _ word: String) -> Bool {
            text.contains(word) || text.range(of: "(^|[\\s(/·,])\(one)(측|쪽)?", options: .regularExpression) != nil
        }
        let left = mark("좌", "왼"), right = mark("우", "오른")
        if left, !right { return [.left] }
        if right, !left { return [.right] }
        return [.left, .right]
    }
}

/// 그림 위의 점 (0~1)
public struct Pt { public let x: Double; public let y: Double
    public init(_ x: Double, _ y: Double) { self.x = x; self.y = y }
}

/// 사람 그림의 기하 — 부위 영역(다각형)·경계선·번호 자리·탭 판정. 아이패드 BodyShape 확장과 같은 값이다
public enum BodyGeometry {
    private static let headBottom = 0.132   // 턱선
    private static let neckBottom = 0.198   // 어깨가 시작하는 곳
    private static let chestBottom = 0.360
    private static let abdomenBottom = 0.470
    private static let crotch = 0.565       // 가랑이
    private static let handSplit = 0.48     // 손목 — 팔과 손의 경계
    private static let handTip = 0.58       // 손끝
    private static let footSplit = 0.90     // 발목 — 다리와 발의 경계

    /// 몸통 경계 한 줄 — (y, 왼쪽 x, 오른쪽 x)
    private struct Row { let y: Double; let l: Double; let r: Double }
    private static let torso: [Row] = stride(from: 0, to: BodyShapeData.torso.count, by: 3).map {
        Row(y: BodyShapeData.torso[$0], l: BodyShapeData.torso[$0 + 1], r: BodyShapeData.torso[$0 + 2])
    }

    /// 실루엣 전체
    public static let outline: [Pt] = stride(from: 0, to: BodyShapeData.outline.count, by: 2).map {
        Pt(BodyShapeData.outline[$0], BodyShapeData.outline[$0 + 1])
    }

    /// 앞모습에서만 / 뒷모습에서만 보이는 부위. 머리·목·팔·다리는 양쪽에 다 있다
    public static func visible(_ r: BodyRegion, back: Bool) -> Bool {
        switch r {
        case .face, .chest, .abdomen: return !back
        case .back: return back
        default: return true
        }
    }

    private static func rect(_ y0: Double, _ y1: Double, _ x0: Double = 0, _ x1: Double = 1) -> [Pt] {
        [Pt(x0, y0), Pt(x1, y0), Pt(x1, y1), Pt(x0, y1)]
    }

    /// 한 부위를 오려 낼 영역 — 앞모습 좌표 그대로. 뒷모습은 같은 좌표에 그린 뒤 좌우를 뒤집어 보여 준다
    public static func region(_ m: BodyMark, back: Bool = false) -> [Pt] {
        if back {
            switch m.region {
            case .face, .chest, .abdomen: return []
            case .back: return band(neckBottom, abdomenBottom)
            default: break
            }
        }
        switch m.region {
        case .head: return rect(0, headBottom)
        case .face: return rect(0.055, headBottom - 0.004, 0.28, 0.72)
        case .neck: return rect(headBottom, neckBottom, 0.34, 0.66)   // 어깨까지 번지지 않게 가운데만
        case .chest: return band(neckBottom, chestBottom)
        case .abdomen: return band(chestBottom, abdomenBottom)
        case .pelvis: return rect(abdomenBottom, crotch, 0.17, 0.83)
        // 등·허리는 앞모습에 안 보인다 — 몸통 가운데 띠로 표시한다
        case .back: return rect(0.215, 0.520, 0.41, 0.59)
        case .arm: return armSide(m.side)
        case .hand: return handSide(m.side)
        case .leg: return m.side == .right ? rect(crotch, footSplit, 0.17, 0.5) : rect(crotch, footSplit, 0.5, 0.83)
        case .foot: return m.side == .right ? rect(footSplit, 1.0, 0.17, 0.5) : rect(footSplit, 1.0, 0.5, 0.83)
        }
    }

    /// 몸통 띠 — 좌우를 몸통 경계로 잘라 팔까지 칠해지지 않게 한다
    private static func band(_ y0: Double, _ y1: Double) -> [Pt] {
        let rows = torsoRows(y0, y1)
        guard !rows.isEmpty else { return [] }
        return rows.map { Pt($0.l, $0.y) } + rows.reversed().map { Pt($0.r, $0.y) }
    }

    /// 팔 — 어깨부터 손목까지, 몸통 경계 바깥쪽(환자의 오른팔이 보는 사람의 왼쪽)
    private static func armSide(_ side: BodySide) -> [Pt] {
        let rows = torsoRows(headBottom, handSplit)
        guard let first = rows.first else { return [] }
        let last = rows[rows.count - 1]
        let viewerLeft = side == .right
        let outer = viewerLeft ? 0.0 : 1.0
        return rows.map { Pt(viewerLeft ? $0.l : $0.r, $0.y) } + [Pt(outer, last.y), Pt(outer, first.y)]
    }

    /// 손 — 손목부터 손끝까지. 폭이 좁아졌다 넓어지므로 실측한 고정 가로 범위(0.17/0.83)를 쓴다
    private static func handSide(_ side: BodySide) -> [Pt] {
        let viewerLeft = side == .right
        let inner = viewerLeft ? 0.17 : 0.83
        let outer = viewerLeft ? 0.0 : 1.0
        return rect(handSplit, handTip, min(inner, outer), max(inner, outer))
    }

    private static func torsoRows(_ y0: Double, _ y1: Double) -> [Row] {
        var rows = torso.filter { $0.y > y0 && $0.y < y1 }
        if let r = at(y0) { rows.insert(r, at: 0) }
        if let r = at(y1) { rows.append(r) }
        return rows
    }

    private static func at(_ y: Double) -> Row? {
        guard let first = torso.first else { return nil }
        let last = torso[torso.count - 1]
        if y <= first.y { return Row(y: y, l: first.l, r: first.r) }
        if y >= last.y { return Row(y: y, l: last.l, r: last.r) }
        for i in 0..<(torso.count - 1) {
            let a = torso[i], b = torso[i + 1]
            if y >= a.y && y <= b.y {
                let t = (y - a.y) / max(0.0001, b.y - a.y)
                return Row(y: y, l: a.l + (b.l - a.l) * t, r: a.r + (b.r - a.r) * t)
            }
        }
        return nil
    }

    /// 부위 경계선 — 누를 수 있는 칸이 보이게 실루엣 안에 옅은 선을 긋는다. 선분 목록(시작·끝)
    public static func dividers(back: Bool = false) -> [(Pt, Pt)] {
        var out: [(Pt, Pt)] = []
        let ys = back ? [headBottom, neckBottom, abdomenBottom, crotch] : [headBottom, neckBottom, chestBottom, abdomenBottom, crotch]
        for y in ys { out.append((Pt(0, y), Pt(1, y))) }
        out.append((Pt(0.5, crotch), Pt(0.5, 1.0)))       // 다리 가운데
        let rows = torsoRows(headBottom, handSplit)         // 팔/몸통 경계
        for edge in [1, 2] {
            let pts = rows.map { Pt(edge == 1 ? $0.l : $0.r, $0.y) }
            for i in 0..<max(pts.count - 1, 0) { out.append((pts[i], pts[i + 1])) }
        }
        if let last = rows.last {                           // 손목 경계 — 팔 칸 안에서만
            out.append((Pt(0, handSplit), Pt(last.l, handSplit)))
            out.append((Pt(last.r, handSplit), Pt(1, handSplit)))
        }
        out.append((Pt(0.17, footSplit), Pt(0.83, footSplit)))   // 발목 경계
        return out
    }

    /// 번호 동그라미 자리(0~1). 뒷모습은 그림이 뒤집혀 보이므로 x도 뒤집는다
    public static func anchor(_ m: BodyMark, back: Bool) -> Pt {
        let a = anchor(m)
        return back ? Pt(1 - a.x, a.y) : a
    }

    private static func anchor(_ m: BodyMark) -> Pt {
        let right = m.side == .right
        switch m.region {
        case .head: return Pt(0.5, 0.055)
        case .face: return Pt(0.5, 0.115)
        case .neck: return Pt(0.5, 0.176)
        case .chest: return Pt(0.5, 0.265)
        case .back: return Pt(0.5, 0.345)
        case .abdomen: return Pt(0.5, 0.432)
        case .pelvis: return Pt(0.5, 0.535)
        case .arm: return Pt(right ? 0.075 : 0.925, 0.430)
        case .hand: return Pt(right ? 0.085 : 0.915, (handSplit + handTip) / 2)
        case .leg: return Pt(right ? 0.315 : 0.685, 0.760)
        case .foot: return Pt(right ? 0.315 : 0.685, (footSplit + 1) / 2)
        }
    }

    private static func contains(_ poly: [Pt], _ p: Pt) -> Bool {
        guard poly.count >= 3 else { return false }
        var inside = false
        var j = poly.count - 1
        for i in 0..<poly.count {
            let a = poly[i], b = poly[j]
            if (a.y > p.y) != (b.y > p.y), p.x < (b.x - a.x) * (p.y - a.y) / (b.y - a.y) + a.x { inside.toggle() }
            j = i
        }
        return inside
    }

    private static let hitFront: [BodyMark] = [
        BodyMark(.face), BodyMark(.neck), BodyMark(.head),
        BodyMark(.hand, .left), BodyMark(.hand, .right), BodyMark(.arm, .left), BodyMark(.arm, .right),
        BodyMark(.foot, .left), BodyMark(.foot, .right), BodyMark(.leg, .left), BodyMark(.leg, .right),
        BodyMark(.chest), BodyMark(.abdomen), BodyMark(.pelvis),
    ]
    private static let hitBack: [BodyMark] = [
        BodyMark(.neck), BodyMark(.head),
        BodyMark(.hand, .left), BodyMark(.hand, .right), BodyMark(.arm, .left), BodyMark(.arm, .right),
        BodyMark(.foot, .left), BodyMark(.foot, .right), BodyMark(.leg, .left), BodyMark(.leg, .right),
        BodyMark(.back), BodyMark(.pelvis),
    ]

    /// 누른 자리(0~1)가 어느 부위인가 — 겹치는 영역은 좁은 것부터 본다. 실루엣 밖은 nil.
    /// 뒷모습은 그림을 좌우로 뒤집어 보여 주므로 누른 자리도 되뒤집어 앞모습 좌표에서 찾는다
    public static func hit(_ p: Pt, back: Bool = false) -> BodyMark? {
        let q = back ? Pt(1 - p.x, p.y) : p
        guard contains(outline, q) else { return nil }
        return (back ? hitBack : hitFront).first { contains(region($0, back: back), q) }
    }
}
