import SwiftUI

/// 외상 부위 그림(2026-10-27) — [환자 정보] 탭 오른쪽. 통화 요약의 외상 정보를 사람 모양 위에 표시한다.
///
/// ⚠ hub가 보내는 `patientInfo`에는 **부위 필드가 없다**. voice v2(MF_BERT)의 `injuries[].region`(머리·얼굴·목·가슴·배·
/// 등·허리·골반·팔·다리)은 hub `voice_v2.py`가 `expectedDiagnosis` 한 줄("좌 다리 골절 · 교통사고")로 합쳐 보낸다.
/// 그래서 이 화면은 **예상 병명·증상·주 호소·추가 정보의 글자에서 부위 낱말을 찾는 규칙**(AI 아님)으로 그린다.
/// 어휘는 voice_v2.BODY_PART_DEPARTMENT의 10부위와 같게 두고, 못 찾은 항목은 버리지 않고 "부위 미상"으로 같이 보여 준다.
/// (부위를 제대로 받으려면 hub가 injuries를 구조 그대로 실어 보내야 한다 — 그때 이 파서를 지우면 된다.)

enum BodyRegion: String, CaseIterable, Hashable {
    case head = "머리", face = "얼굴", neck = "목", chest = "가슴", abdomen = "배"
    case back = "등·허리", pelvis = "골반", arm = "팔", leg = "다리"
    var isLimb: Bool { self == .arm || self == .leg }
}

/// 환자 기준 좌·우(그림에서는 좌우를 바꿔 그린다 — 보는 사람의 왼쪽이 환자의 오른쪽)
enum BodySide: String, Hashable { case left = "좌", right = "우", unknown = "" }

struct BodyMark: Hashable { var region: BodyRegion; var side: BodySide }

struct MappedInjury: Identifiable, Hashable {
    var text: String
    var marks: [BodyMark]
    /// "다발성·전신"처럼 부위를 하나로 못 집는 항목 — 다른 항목이 부위를 집어 주면 그림에는 안 칠한다
    var isMulti = false
    var id: String { text }
    var regionLabel: String {
        if marks.isEmpty { return "부위 미상" }
        if marks.count > 2 { return "다발성" }
        return marks.map { ($0.side == .unknown ? "" : $0.side.rawValue + " ") + $0.region.rawValue }.joined(separator: " · ")
    }
}

/// 외상 한 건의 위험도(2026-10-27) — **규칙 기반, 전문의 검토 전 초안**.
///
/// KTAS는 환자 1명에게 하나 매기는 통합 등급이고, voice(MF_BERT) v2에도 증상별 등급은 없다(증상은 "확인/부정",
/// 손상은 부위·유형만). 그래서 부위 추출과 같은 방식으로 **낱말 규칙**으로 셋으로 나눈다:
///  · 적색 깃발(관통·절단·대량 출혈·기도·의식·호흡·쇼크 등) → 높음
///  · 골절·탈구·열상·화상 같은 구조 손상, 그리고 **중심부 부위**(머리·목·가슴·배·골반·등허리) → 중간
///  · 타박·찰과·염좌 같은 것과 팔다리·얼굴 → 낮음
/// 한 건의 등급은 (낱말 등급, 부위 기본 등급) 중 **높은 쪽**이다 — "머리 타박"은 타박(낮음)이어도 머리라서 중간.
/// 색만 나눌 뿐 순위·병원 선택에는 쓰지 않는다(그건 hub가 KTAS로 한다).
enum InjuryTier: Int, Comparable {
    case low = 0, medium, high
    static func < (a: InjuryTier, b: InjuryTier) -> Bool { a.rawValue < b.rawValue }
    var label: String { self == .high ? "높음" : self == .medium ? "중간" : "낮음" }
    /// KTAS 색 체계와 같은 말: 빨강 → 주황 → 연두
    var color: Color { self == .high ? AD.red : self == .medium ? AD.orange : AD.lime }
    var soft: Color { self == .high ? AD.redSoft : self == .medium ? AD.orangeSoft : AD.limeSoft }
}

enum InjuryRisk {
    /// 적색 깃발 — 하나라도 보이면 높음
    private static let highWords = [
        // 손상 기전·형태
        "관통", "자상", "총상", "절단", "압궤", "개방성", "개방 골절", "개방성 골절", "골반 골절", "척추 손상", "척수",
        "대량 출혈", "대량출혈", "다량 출혈", "출혈 지속", "동맥", "토혈", "객혈", "혈흉", "기흉", "혈복강", "복강 내 출혈",
        "2도 화상", "3도 화상", "흡입 화상", "기도 화상", "감전", "익수", "목맴", "교액", "질식", "기도 폐쇄",
        // 상태·증상
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
    /// 부정 표현 — "출혈 없음"처럼 **없다고 말한 것**은 깃발로 세지 않는다
    private static let negations = ["없음", "없다", "없습니다", "아님", "아니", "음성", "정상", "소실", "해소", "부인"]
    /// 중심부 — 낱말이 가벼워도 중간부터 본다(몸통·머리)
    private static let coreRegions: Set<BodyRegion> = [.head, .neck, .chest, .abdomen, .pelvis, .back]

    static func tier(_ text: String, region: BodyRegion?) -> InjuryTier {
        // "의식 저하 없음"·"출혈 없음"은 낮음으로 — 통화에서 "~는 없다"가 자주 나온다
        if negations.contains(where: text.contains) { return .low }
        if highWords.contains(where: text.contains) { return .high }
        let byWord: InjuryTier = mediumWords.contains(where: text.contains) ? .medium : .low
        let byRegion: InjuryTier = region.map { coreRegions.contains($0) ? .medium : .low } ?? .low
        return max(byWord, byRegion)
    }

    // ── 활력징후·의식(이미 구조화돼 오는 값) ─────────────────────────────────
    //  글자 규칙과 달리 이건 숫자라 추측이 없다. 점수는 hub `transport_triage.py`와 **같은 공개 표준
    //  NEWS2**(RCP 2017, Scale 1)를 쓴다 — 같은 환자를 두 화면이 다르게 말하지 않게.
    private static let news2Bands: [String: [(Double, Double?, Int)]] = [
        "rr": [(0, 8, 3), (9, 11, 1), (12, 20, 0), (21, 24, 2), (25, nil, 3)],
        "spo2": [(0, 91, 3), (92, 93, 2), (94, 95, 1), (96, nil, 0)],
        "sbp": [(0, 90, 3), (91, 100, 2), (101, 110, 1), (111, 219, 0), (220, nil, 3)],
        "hr": [(0, 40, 3), (41, 50, 1), (51, 90, 0), (91, 110, 1), (111, 130, 2), (131, nil, 3)],
        "bt": [(0, 35.0, 3), (35.1, 36.0, 1), (36.1, 38.0, 0), (38.1, 39.0, 1), (39.1, nil, 2)],
    ]
    private static func band(_ name: String, _ value: Double) -> Int {
        news2Bands[name]?.first { value >= $0.0 && ($0.1 == nil || value <= $0.1!) }?.2 ?? 0
    }

    /// 최근 활력징후·의식 → (등급, 근거 한 줄). 값이 없으면 낮음·근거 없음
    static func vitalTier(_ patient: PatientInfo?) -> (tier: InjuryTier, reason: String?) {
        guard let patient else { return (.low, nil) }
        var score = 0
        var reasons: [String] = []
        if let v = patient.vitals?.last {
            let items: [(String, Double?, String)] = [
                ("rr", v.rr, "RR"), ("spo2", v.spo2, "SpO₂"), ("sbp", v.sbp, "SBP"), ("hr", v.hr, "HR"), ("bt", v.bt, "BT"),
            ]
            for (name, value, label) in items {
                guard let value else { continue }
                let s = band(name, value)
                score += s
                if s >= 2 { reasons.append("\(label) \(value.rounded() == value ? String(Int(value)) : String(format: "%.1f", value))") }
            }
        }
        if let avpu = Labels.avpu(patient.consciousness), avpu != "A" {
            score += 3
            reasons.append("의식 \(avpu)")
        }
        let tier: InjuryTier = score >= 7 ? .high : score >= 5 ? .medium : .low
        return (tier, reasons.isEmpty ? nil : "NEWS2 \(score) · " + reasons.joined(separator: " · "))
    }

    #if DEBUG
    static func selfCheck() {
        assert(tier("좌 다리 골절", region: .leg) == .medium)       // 팔다리 + 골절
        assert(tier("머리 타박", region: .head) == .medium)          // 가벼운 낱말이어도 머리
        assert(tier("흉부 관통상", region: .chest) == .high)
        assert(tier("손목 찰과상", region: .arm) == .low)
        assert(tier("의식 저하", region: nil) == .high)              // 부위 없는 전신 증상도 등급은 매긴다
        assert(tier("복부 압통", region: .abdomen) == .medium)
        assert(tier("의식 저하 없음", region: nil) == .low)          // 부정 표현
        assert(tier("활동성 출혈 없음", region: .arm) == .low)
        assert(tier("개방성 골절", region: .leg) == .high)
        assert(tier("경색 의심", region: .chest) == .high)
        assert(band("spo2", 88) == 3 && band("sbp", 85) == 3)       // NEWS2 표(hub와 같은 값)
    }
    #endif
}

enum InjuryMapper {
    /// 부위 낱말 — 긴 낱말을 먼저 본다("발목"이 "목"보다 먼저여야 발목 부상이 목으로 가지 않는다)
    private static let keywords: [(BodyRegion, String)] = {
        let table: [BodyRegion: [String]] = [
            .head: ["머리", "두부", "두개", "뇌", "이마", "전두", "후두", "측두", "두피"],
            .face: ["얼굴", "안면", "눈", "코피", "코", "입", "턱", "치아", "귀", "구강"],
            .neck: ["목", "경부", "경추", "기도"],
            .chest: ["가슴", "흉부", "흉곽", "흉골", "흉통", "늑골", "갈비", "쇄골", "심장", "심와", "폐"],
            .abdomen: ["복부", "복강", "상복부", "하복부", "명치", "옆구리", "배", "위장", "간", "비장", "신장"],
            .back: ["등허리", "허리", "요추", "흉추", "척추", "견갑", "등"],
            .pelvis: ["골반", "둔부", "엉덩이", "치골", "사타구니", "고관절", "회음"],
            .arm: ["팔꿈치", "주관절", "전완", "상완", "손가락", "손목", "어깨", "견관절", "상지", "팔", "손"],
            .leg: ["허벅지", "대퇴", "무릎", "슬관절", "정강", "종아리", "발목", "발가락", "족부", "하지", "다리", "발"],
        ]
        return table.flatMap { r, ws in ws.map { (r, $0) } }.sorted { $0.1.count > $1.1.count }
    }()
    /// 부위를 하나로 못 집는 말 — 몸통과 팔다리를 다 표시한다
    private static let multiWords = ["다발성", "다발", "전신", "온몸", "여러 군데", "다수 부위"]
    private static let multiMarks: [BodyMark] = [
        BodyMark(region: .head, side: .unknown), BodyMark(region: .chest, side: .unknown),
        BodyMark(region: .abdomen, side: .unknown),
        BodyMark(region: .arm, side: .left), BodyMark(region: .arm, side: .right),
        BodyMark(region: .leg, side: .left), BodyMark(region: .leg, side: .right),
    ]

    /// 통화 요약에서 부위가 보이는 항목을 뽑는다. 예상 병명은 hub가 " · "로 이어 붙인 것이라 다시 쪼갠다.
    static func parse(_ p: PatientInfo?) -> [MappedInjury] {
        guard let p else { return [] }
        var items: [String] = []
        items += (p.expectedDiagnosis ?? "").components(separatedBy: CharacterSet(charactersIn: "·,/"))
        items += p.injuryStatus ?? []
        if let c = p.chiefComplaint { items.append(c) }
        items += (p.extraNotes ?? []).map(\.text)

        var seen = Set<String>()
        return items.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty && seen.insert($0).inserted && !isCategoryCode($0) }
            .map { MappedInjury(text: $0, marks: marks(in: $0), isMulti: isMulti($0)) }
    }

    static func isMulti(_ text: String) -> Bool { multiWords.contains(where: text.contains) }

    /// 한 항목의 부위. 같은 항목에 부위가 여럿이면 다 표시한다("머리와 다리 열상")
    static func marks(in text: String) -> [BodyMark] {
        if isMulti(text) { return multiMarks }
        var found: [BodyMark] = []
        var rest = text
        for (region, word) in keywords where rest.contains(word) {
            // 이미 찾은 부위는 건너뛰고, 쓴 낱말은 지워 더 짧은 낱말이 같은 글자를 다시 집지 않게("발목" → "목")
            rest = rest.replacingOccurrences(of: word, with: " ")
            if found.contains(where: { $0.region == region }) { continue }
            found += region.isLimb ? sides(in: text).map { BodyMark(region: region, side: $0) }
                                   : [BodyMark(region: region, side: .unknown)]
        }
        return found
    }

    /// MF_BERT 주 호소의 대분류 코드("T 외상"·"I 심혈관계")는 손상이 아니라 분류표라 그림에서 뺀다
    private static func isCategoryCode(_ text: String) -> Bool {
        text.range(of: "^[A-Z][ .]", options: .regularExpression) != nil
    }

    /// 팔·다리의 좌우. 안 적혀 있으면 양쪽 다 표시한다(어느 쪽인지 모른다는 뜻).
    /// "좌"·"우" 한 글자는 **낱말 앞에서만** 본다 — 안 그러면 "염좌"·"열상 우측 아님" 같은 말에 걸린다
    private static func sides(in text: String) -> [BodySide] {
        func mark(_ one: String, _ word: String) -> Bool {
            text.contains(word) || text.range(of: "(^|[\\s(/·,])\(one)(측|쪽)?", options: .regularExpression) != nil
        }
        let left = mark("좌", "왼")
        let right = mark("우", "오른")
        if left && !right { return [.left] }
        if right && !left { return [.right] }
        return [.left, .right]      // 양쪽 또는 미상
    }

    #if DEBUG
    /// 자체 검사 — 앱이 DEBUG로 뜰 때 한 번 돈다(틀리면 바로 멈춘다)
    static func selfCheck() {
        assert(marks(in: "좌 다리 골절") == [BodyMark(region: .leg, side: .left)])
        assert(marks(in: "우측 발목 염좌") == [BodyMark(region: .leg, side: .right)])   // 발목이 목보다 먼저
        assert(marks(in: "손목 자상") == [BodyMark(region: .arm, side: .left), BodyMark(region: .arm, side: .right)])
        assert(marks(in: "발목 염좌") == [BodyMark(region: .leg, side: .left), BodyMark(region: .leg, side: .right)])  // "염좌"의 좌는 좌우가 아니다
        assert(marks(in: "좌측 팔 골절") == [BodyMark(region: .arm, side: .left)])
        assert(marks(in: "경부 통증").first?.region == .neck)
        assert(marks(in: "흉통(심장성)").first?.region == .chest)
        assert(marks(in: "교통사고 다발성 외상").count == multiMarks.count)
        assert(marks(in: "호흡 곤란").isEmpty)                                          // 부위 없는 증상
        assert(Set(marks(in: "머리 열상과 다리 골절").map(\.region)) == [.head, .leg])
        assert(isMulti("다발성 외상") && !isMulti("머리 열상"))
        assert(isCategoryCode("T 외상") && !isCategoryCode("타박상"))   // 주 호소 대분류는 손상이 아니다
    }
    #endif
}

// ── 그림 ──────────────────────────────────────────────────────────────────────

/// 사람 모양 — 실루엣 하나를 통째로 그리고(`BodyShape.outline`, 팀이 고른 2D 인체 그림을 윤곽선으로 딴 것),
/// 다친 부위만 그 부위 영역으로 오려서 빨강으로 덧칠한다. 부위 영역은 가로 띠(머리·목·가슴·배·골반)와
/// 몸통 좌우 경계(`BodyShape.torso`, 팔/몸통을 가르는 선)로 만든다 — 그림이 바뀌어도 `tools/trace_body.py`만 다시 돌리면 된다.
struct BodyFigure: View {
    /// 부위별 위험도 — 색이 등급을 따라간다(높음 빨강 · 중간 주황 · 낮음 연두)
    var tiers: [BodyMark: InjuryTier]
    var marks: Set<BodyMark> { Set(tiers.keys) }

    var body: some View {
        GeometryReader { g in
            let side = min(g.size.width / BodyShape.ratio, g.size.height)
            let box = CGSize(width: side * BodyShape.ratio, height: side)
            ZStack {
                Canvas { ctx, _ in
                    let body = BodyShape.path(box)
                    ctx.fill(body, with: .color(AD.navy))
                    // 칠하는 순서를 머리 → 다리로 고정한다(Set은 순서가 없어 겹치는 자리가 그때그때 달라진다)
                    for item in numbered {
                        // 부위 색 = 그 부위 위험도(높음 빨강 · 중간 주황 · 낮음 연두)
                        let color = tiers[item.mark]?.color ?? AD.red
                        ctx.drawLayer { layer in
                            layer.clip(to: BodyShape.region(item.mark, box))
                            layer.fill(body, with: .color(color))
                        }
                    }
                }
                .frame(width: box.width, height: box.height)
                // 다친 부위 번호 — 그림 위에 흰 글씨 동그라미
                ForEach(Array(numbered.enumerated()), id: \.offset) { _, item in
                    let p = BodyShape.anchor(item.mark)
                    Text("\(item.n)")
                        .font(.system(size: 12, weight: .heavy)).foregroundStyle(.white)
                        .frame(width: 21, height: 21)
                        .background(tiers[item.mark]?.color ?? AD.red).clipShape(Circle())
                        .overlay(Circle().stroke(.white, lineWidth: 1.5))
                        .position(x: p.x * box.width, y: p.y * box.height)
                }
            }
            .frame(width: box.width, height: box.height)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    /// 번호는 머리부터 발끝 순서로 매긴다(옆 목록과 같은 순서)
    var numbered: [(n: Int, mark: BodyMark)] {
        let order = BodyRegion.allCases
        let sorted = marks.sorted {
            (order.firstIndex(of: $0.region)!, $0.side.rawValue) < (order.firstIndex(of: $1.region)!, $1.side.rawValue)
        }
        return sorted.enumerated().map { ($0.offset + 1, $0.element) }
    }
}

extension BodyShape {
    /// 실루엣 전체
    static func path(_ s: CGSize) -> Path {
        var p = Path()
        p.move(to: CGPoint(x: outline[0].0 * s.width, y: outline[0].1 * s.height))
        for q in outline.dropFirst() { p.addLine(to: CGPoint(x: q.0 * s.width, y: q.1 * s.height)) }
        p.closeSubpath()
        return p
    }

    // 부위 경계(세로 위치, 0~1). 그림의 목·어깨·허리·가랑이 자리에 맞췄다
    private static let headBottom: CGFloat = 0.132   // 턱선
    private static let neckBottom: CGFloat = 0.198   // 어깨가 시작하는 곳
    private static let chestBottom: CGFloat = 0.360
    private static let abdomenBottom: CGFloat = 0.470
    private static let crotch: CGFloat = 0.565   // 가랑이

    /// 한 부위를 오려 낼 영역(실루엣과 겹치는 부분만 칠해진다)
    static func region(_ m: BodyMark, _ s: CGSize) -> Path {
        func rect(_ y0: CGFloat, _ y1: CGFloat, _ x0: CGFloat = 0, _ x1: CGFloat = 1) -> Path {
            Path(CGRect(x: x0 * s.width, y: y0 * s.height, width: (x1 - x0) * s.width, height: (y1 - y0) * s.height))
        }
        switch m.region {
        case .head: return rect(0, headBottom)
        case .face: return rect(0.055, headBottom - 0.004, 0.28, 0.72)
        case .neck: return rect(headBottom, neckBottom, 0.34, 0.66)   // 어깨까지 번지지 않게 가운데만
        case .chest: return band(neckBottom, chestBottom, s)
        case .abdomen: return band(chestBottom, abdomenBottom, s)
        case .pelvis: return band(abdomenBottom, crotch, s)
        // 등·허리는 앞모습에 안 보인다 — 몸통 가운데 띠로 표시한다(번호·목록으로 구분)
        case .back: return rect(0.215, 0.520, 0.41, 0.59)
        case .arm: return armSide(m.side, s)
        // 가랑이 아래 좌우 — 양옆 끝은 손끝이 내려오는 자리라 뺀다(손이 다리로 칠해졌다)
        case .leg: return m.side == .right ? rect(crotch, 1, 0.17, 0.5) : rect(crotch, 1, 0.5, 0.83)
        }
    }

    /// 몸통 띠 — 좌우를 몸통 경계로 잘라 팔까지 칠해지지 않게 한다
    private static func band(_ y0: CGFloat, _ y1: CGFloat, _ s: CGSize) -> Path {
        let rows = torsoRows(y0, y1)
        var p = Path()
        guard let first = rows.first else { return p }
        p.move(to: CGPoint(x: first.1 * s.width, y: first.0 * s.height))
        for r in rows { p.addLine(to: CGPoint(x: r.1 * s.width, y: r.0 * s.height)) }
        for r in rows.reversed() { p.addLine(to: CGPoint(x: r.2 * s.width, y: r.0 * s.height)) }
        p.closeSubpath()
        return p
    }

    /// 팔 — 몸통 경계 바깥쪽 전체(환자의 오른팔이 보는 사람의 왼쪽)
    private static func armSide(_ side: BodySide, _ s: CGSize) -> Path {
        // 허리 아래로는 몸통 경계가 다리 경계로 바뀌므로, 마지막 경계선을 손끝(0.68)까지 곧게 내린다
        let rows = torsoRows(0.185, 0.550)
        let viewerLeft = side == .right
        var p = Path()
        guard let first = rows.first, let last = rows.last else { return p }
        func edge(_ r: (CGFloat, CGFloat, CGFloat)) -> CGFloat { viewerLeft ? r.1 : r.2 }
        let outer = viewerLeft ? 0 : s.width
        p.move(to: CGPoint(x: edge(first) * s.width, y: first.0 * s.height))
        for r in rows { p.addLine(to: CGPoint(x: edge(r) * s.width, y: r.0 * s.height)) }
        p.addLine(to: CGPoint(x: edge(last) * s.width, y: 0.68 * s.height))
        p.addLine(to: CGPoint(x: outer, y: 0.68 * s.height))
        p.addLine(to: CGPoint(x: outer, y: first.0 * s.height))
        p.closeSubpath()
        return p
    }

    /// 몸통 경계에서 y 구간만 잘라 온다(끝은 사이값으로 맞춘다)
    private static func torsoRows(_ y0: CGFloat, _ y1: CGFloat) -> [(CGFloat, CGFloat, CGFloat)] {
        var rows = torso.filter { $0.0 > y0 && $0.0 < y1 }
        if let a = at(y0) { rows.insert(a, at: 0) }
        if let b = at(y1) { rows.append(b) }
        return rows
    }
    private static func at(_ y: CGFloat) -> (CGFloat, CGFloat, CGFloat)? {
        guard let first = torso.first, let last = torso.last else { return nil }
        if y <= first.0 { return (y, first.1, first.2) }
        if y >= last.0 { return (y, last.1, last.2) }
        for (a, b) in zip(torso, torso.dropFirst()) where y >= a.0 && y <= b.0 {
            let t = (y - a.0) / max(0.0001, b.0 - a.0)
            return (y, a.1 + (b.1 - a.1) * t, a.2 + (b.2 - a.2) * t)
        }
        return nil
    }

    /// 번호 동그라미 자리(0~1)
    static func anchor(_ m: BodyMark) -> CGPoint {
        switch m.region {
        case .head: return CGPoint(x: 0.5, y: 0.055)
        case .face: return CGPoint(x: 0.5, y: 0.115)
        case .neck: return CGPoint(x: 0.5, y: 0.176)
        case .chest: return CGPoint(x: 0.5, y: 0.265)
        case .back: return CGPoint(x: 0.5, y: 0.345)
        case .abdomen: return CGPoint(x: 0.5, y: 0.432)
        case .pelvis: return CGPoint(x: 0.5, y: 0.535)
        case .arm: return CGPoint(x: m.side == .right ? 0.075 : 0.925, y: 0.430)
        case .leg: return CGPoint(x: m.side == .right ? 0.315 : 0.685, y: 0.760)
        }
    }
}

/// [환자 정보] 탭 오른쪽 카드 — 사람 그림 가운데, 다친 부위에서 **선을 바깥으로 빼서** 설명을 단다(2026-10-27).
/// 예전엔 그림 왼쪽·목록 오른쪽이었는데, 어느 설명이 어느 부위인지 번호로만 이어져 한눈에 안 들어왔다.
/// 부위를 못 찾은 항목(전신 증상)은 선 없이 오른다리 옆에 모아 둔다.
struct BodyInjuryCard: View {
    @EnvironmentObject private var model: AppModel

    private var patient: PatientInfo? { model.result?.patientInfo }
    private var injuries: [MappedInjury] { InjuryMapper.parse(patient) }
    /// 부위를 **집어서** 말한 항목(다발성 제외)
    private var specific: [MappedInjury] { injuries.filter { !$0.marks.isEmpty && !$0.isMulti } }
    /// 그림에 칠할 항목 — 구체적인 게 하나도 없을 때만 "다발성"이 몸 전체를 칠한다
    private var located: [MappedInjury] { specific.isEmpty ? injuries.filter { !$0.marks.isEmpty } : specific }
    /// 선 없이 옆에 모아 둘 항목 — 부위를 못 찾은 것 + (구체적 부위가 있을 때의) 다발성
    private var unlocated: [MappedInjury] {
        injuries.filter { $0.marks.isEmpty || ($0.isMulti && !specific.isEmpty) }
    }
    private var marks: Set<BodyMark> { Set(located.flatMap(\.marks)) }
    /// 부위별 위험도 — 그 부위에 걸린 항목 중 가장 높은 등급(규칙, 전문의 검토 전 초안)
    private var tiers: [BodyMark: InjuryTier] {
        var out: [BodyMark: InjuryTier] = [:]
        for injury in located {
            for mark in injury.marks {
                let tier = InjuryRisk.tier(injury.text, region: mark.region)
                out[mark] = max(out[mark] ?? .low, tier)
            }
        }
        return out
    }
    /// 부위를 못 찾은 항목(전신 증상)의 등급 — 의식 저하·호흡 곤란 같은 적색 깃발을 놓치지 않게 같이 매긴다
    private var generalTier: InjuryTier {
        max(unlocated.map { InjuryRisk.tier($0.text, region: nil) }.max() ?? .low, vital.tier)
    }
    /// 활력징후·의식으로 본 전신 위험(NEWS2, hub 이송 중 판정과 같은 표)
    private var vital: (tier: InjuryTier, reason: String?) { InjuryRisk.vitalTier(patient) }
    private var showsGeneral: Bool { !unlocated.isEmpty || vital.reason != nil }

    /// 부위 하나에 붙일 설명(같은 부위에 여러 항목이면 한 상자에 모은다)
    private struct Callout: Identifiable {
        let mark: BodyMark
        let n: Int
        let title: String
        let text: String
        let tier: InjuryTier
        var left: Bool = false
        var y: CGFloat = 0
        var id: String { mark.region.rawValue + mark.side.rawValue }
    }

    private var callouts: [Callout] {
        let marked = tiers
        let numbers = Dictionary(uniqueKeysWithValues: BodyFigure(tiers: marked).numbered.map { ($0.mark, $0.n) })
        return marked.keys.map { mark in
            let items = located.filter { $0.marks.contains(mark) }
            let title = (mark.side == .unknown ? "" : mark.side.rawValue + " ") + mark.region.rawValue
            return Callout(mark: mark, n: numbers[mark] ?? 0, title: title,
                           text: items.map(\.text).joined(separator: " · "), tier: marked[mark] ?? .low)
        }
        .sorted { $0.n < $1.n }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text("외상 부위").font(.system(size: 16, weight: .bold)).foregroundStyle(AD.navy)
                Spacer(minLength: 0)
                if let k = patient?.ktasLevel { Pill(text: "KTAS \(k)", bg: Theme.ktasSoft(k), fg: Theme.ktas(k), bold: true) }
                if !marks.isEmpty { Pill(text: "\(marks.count)곳", bg: AD.redSoft, fg: AD.red, bold: true) }
            }
            if patient == nil {
                Spacer(minLength: 0)
                VStack(spacing: 8) {
                    Image(systemName: "figure.stand").font(.system(size: 34)).foregroundStyle(AD.muted)
                    Text("통화 요약이 도착하면 외상 부위를 표시합니다").font(.system(size: 14, weight: .medium)).foregroundStyle(AD.ink3)
                }
                .frame(maxWidth: .infinity)
                Spacer(minLength: 0)
            } else {
                diagram
                HStack(spacing: 10) {
                    Text("환자 기준 좌·우(그림은 좌우가 바뀌어 보입니다)")
                        .font(.system(size: 10.5)).foregroundStyle(AD.muted)
                    Text("색 = 위험도(규칙 · 전문의 검토 전 초안)")
                        .font(.system(size: 10.5)).foregroundStyle(AD.muted)
                    ForEach([InjuryTier.high, .medium, .low], id: \.self) { t in
                        HStack(spacing: 3) { Dot(color: t.color, size: 7)
                            Text(t.label).font(.system(size: 10.5, weight: .semibold)).foregroundStyle(AD.ink3) }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .center)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .card()
    }

    // 설명 상자 크기 — 선을 그릴 자리를 계산하려면 미리 정해 둬야 한다
    private static let boxW: CGFloat = 210
    private static let boxH: CGFloat = 46
    private static let gap: CGFloat = 10        // 상자끼리 최소 간격

    private var diagram: some View {
        GeometryReader { g in
            let figH = max(120, g.size.height)
            let figW = figH * BodyShape.ratio
            let figX = (g.size.width - figW) / 2
            // 칸이 좁으면 설명 상자를 줄인다(아이패드를 세로로 세웠을 때)
            let bw = max(130, min(Self.boxW, (g.size.width - figW) / 2 - 26))
            let placed = place(callouts, height: g.size.height)
            ZStack(alignment: .topLeading) {
                // 부위 → 설명 상자로 가는 선(꺾인 선). 그림·상자 아래에 깔린다
                Canvas { ctx, _ in
                    for c in placed {
                        let anchor = BodyShape.anchor(c.mark)
                        let from = CGPoint(x: figX + anchor.x * figW, y: anchor.y * figH)
                        let toX = c.left ? figX - 14 : figX + figW + 14
                        let to = CGPoint(x: toX, y: c.y)
                        var path = Path()
                        path.move(to: from)
                        path.addLine(to: CGPoint(x: toX + (c.left ? -18 : 18), y: from.y))
                        path.addLine(to: to)
                        ctx.stroke(path, with: .color(c.tier.color.opacity(0.55)),
                                   style: StrokeStyle(lineWidth: 1.5, lineCap: .round, lineJoin: .round))
                        ctx.fill(Path(ellipseIn: CGRect(x: from.x - 3, y: from.y - 3, width: 6, height: 6)),
                                 with: .color(c.tier.color))
                    }
                }
                BodyFigure(tiers: tiers)
                    .frame(width: figW, height: figH)
                    .position(x: g.size.width / 2, y: figH / 2)
                ForEach(placed) { c in
                    box(c, width: bw)
                        .position(x: c.left ? figX - 14 - bw / 2 : figX + figW + 14 + bw / 2, y: c.y)
                }
                if showsGeneral {
                    // 부위 미상·전신 증상 — 선 없이 오른다리 옆에
                    generalBox(width: bw)
                        .position(x: figX + figW + 14 + bw / 2,
                                  y: min(g.size.height - Self.boxH / 2,
                                         max(0.80 * figH, (placed.filter { !$0.left }.map(\.y).max() ?? 0) + Self.boxH + Self.gap * 2)))
                }
                if callouts.isEmpty && unlocated.isEmpty {
                    Text("통화 요약에 외상 항목이 없습니다")
                        .font(.system(size: 13)).foregroundStyle(AD.muted)
                        .position(x: g.size.width / 2, y: g.size.height - 14)
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    /// 상자를 좌우로 나눠 세로로 쌓는다 — 팔·다리는 그쪽 편, 가운데 부위는 번갈아. 겹치면 아래로 민다
    private func place(_ items: [Callout], height: CGFloat) -> [Callout] {
        var out: [Callout] = []
        var midlineLeft = true
        for var c in items {
            switch (c.mark.region, c.mark.side) {
            case (_, .right): c.left = true          // 환자의 오른쪽 = 그림의 왼쪽
            case (_, .left): c.left = false
            default:
                c.left = midlineLeft
                midlineLeft.toggle()
            }
            c.y = BodyShape.anchor(c.mark).y * height
            out.append(c)
        }
        for side in [true, false] {
            var last: CGFloat = -.infinity
            for i in out.indices where out[i].left == side {
                out[i].y = max(out[i].y, last + Self.boxH + Self.gap)
                last = out[i].y
            }
            // 아래로 넘치면 전체를 위로 당긴다
            if let overflow = out.filter({ $0.left == side }).map(\.y).max(), overflow > height - Self.boxH / 2 {
                let shift = overflow - (height - Self.boxH / 2)
                for i in out.indices where out[i].left == side { out[i].y = max(Self.boxH / 2, out[i].y - shift) }
            }
        }
        return out
    }

    private func box(_ c: Callout, width: CGFloat) -> some View {
        HStack(alignment: .top, spacing: 7) {
            Text("\(c.n)").font(.system(size: 11, weight: .heavy)).foregroundStyle(.white)
                .frame(width: 20, height: 20).background(c.tier.color).clipShape(Circle())
            VStack(alignment: .leading, spacing: 1) {
                HStack(spacing: 5) {
                    Text(c.title).font(.system(size: 12.5, weight: .bold)).foregroundStyle(c.tier.color)
                    Pill(text: c.tier.label, bg: c.tier.soft, fg: c.tier.color)
                }
                Text(c.text).font(.system(size: 13)).foregroundStyle(AD.ink)
                    .lineLimit(2).fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 10).padding(.vertical, 7)
        .frame(width: width, alignment: .leading)
        .background(AD.card)
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).stroke(c.tier.soft, lineWidth: 1.5))
    }

    private func generalBox(width: CGFloat) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 5) {
                Text("부위 미상 · 전신 증상").font(.system(size: 11.5, weight: .semibold)).foregroundStyle(AD.muted)
                if generalTier > .low { Pill(text: generalTier.label, bg: generalTier.soft, fg: generalTier.color) }
            }
            if !unlocated.isEmpty {
                Text(unlocated.map(\.text).joined(separator: " · "))
                    .font(.system(size: 13)).foregroundStyle(AD.ink3)
                    .lineLimit(3).fixedSize(horizontal: false, vertical: true)
            }
            if let reason = vital.reason {
                Text(reason).font(.system(size: 11.5, weight: .semibold)).foregroundStyle(vital.tier.color)
                    .lineLimit(2).fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.horizontal, 10).padding(.vertical, 7)
        .frame(width: width, alignment: .leading)
        .background(AD.chip)
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}
