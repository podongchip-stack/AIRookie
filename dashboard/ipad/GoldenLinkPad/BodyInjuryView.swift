import SwiftUI

/// 외상 부위 그림(2026-10-27) — [환자 정보] 탭 오른쪽. 통화 요약의 외상 정보를 사람 모양 위에 표시한다.
///
/// ⚠ hub가 보내는 `patientInfo`에는 **부위 필드가 없다**. voice v2(MF_BERT)의 `injuries[].region`(머리·얼굴·목·가슴·배·
/// 등·허리·골반·팔·다리)은 hub `voice_v2.py`가 `expectedDiagnosis` 한 줄("좌 다리 골절 · 교통사고")로 합쳐 보낸다.
/// 그래서 이 화면은 **예상 병명·증상·주 호소·추가 정보의 글자에서 부위 낱말을 찾는 규칙**(AI 아님)으로 그린다.
/// 어휘는 voice_v2.BODY_PART_DEPARTMENT의 10부위에 **손·발을 더 쪼갠 것**이다(2026-10-29) — 팔·다리 끝(손목·발목 아래)만
/// 따로 떼어 더 세세하게 짚을 수 있게 했다. voice 쪽 10부위는 그대로이므로, 이 화면이 글자에서 "손"·"발" 낱말을
/// 찾아 그 둘을 가려낸다(규칙, voice_v2 스키마 변경 없음). 못 찾은 항목은 버리지 않고 "부위 미상"으로 같이 보여 준다.
/// (부위를 제대로 받으려면 hub가 injuries를 구조 그대로 실어 보내야 한다 — 그때 이 파서를 지우면 된다.)

enum BodyRegion: String, CaseIterable, Hashable {
    case head = "머리", face = "얼굴", neck = "목", chest = "가슴", abdomen = "배"
    case back = "등·허리", pelvis = "골반", arm = "팔", hand = "손", leg = "다리", foot = "발"
    var isLimb: Bool { self == .arm || self == .leg || self == .hand || self == .foot }
}

/// 환자 기준 좌·우(그림에서는 좌우를 바꿔 그린다 — 보는 사람의 왼쪽이 환자의 오른쪽)
enum BodySide: String, Hashable { case left = "좌", right = "우", unknown = "" }

struct BodyMark: Hashable { var region: BodyRegion; var side: BodySide }

/// 외상 도해를 **눌러서** 고친 것(2026-10-28) — 통화 요약(AI)에 부위를 더하거나 빼고, 부위마다 한 처치를 적는다.
/// 흔들리는 차 안에서 글자를 고치는 것보다 탭이 빠르고, 적은 것은 두 갈래로 흘러간다:
///  · 부위 → hub `patient_override.injuryStatus`(병원 화면·재매칭에 반영, "구급대원 확인" 도장)
///  · 처치 → 인계확인서의 처치 칸(기도·호흡·순환·약품·고정·기타) + 병원에는 추가 정보로
/// 저장하지 않는다 — 앱을 다시 켜면 hub가 돌려준 `injuryStatus`에서 부위가 다시 읽힌다(처치는 인계확인서에 남는다).
struct BodyEdits {
    /// 통화에 없었는데 구급대원이 찍은 부위
    var added: Set<BodyMark> = []
    /// 통화에서 뽑혔지만 "여긴 아니다"라고 한 부위
    var removed: Set<BodyMark> = []
    /// 부위별 처치
    var cares: [BodyMark: [String]] = [:]

    /// 현장에서 손으로 적던 것들 — 서식의 처치 칸으로 분류되는 말로 둔다(`Handover.care`)
    static let careOptions = ["지혈", "드레싱", "부목 고정", "경추보호대", "척추 고정", "냉찜질", "창상 세척", "산소 투여", "정맥로 확보"]

    static func label(_ m: BodyMark) -> String {
        (m.side == .unknown ? "" : m.side.rawValue + " ") + m.region.rawValue
    }
    /// 인계확인서 처치 칸으로 — "좌 다리 부목 고정"
    var careLines: [String] {
        cares.flatMap { mark, list in list.map { "\(BodyEdits.label(mark)) \($0)" } }.sorted()
    }
    /// hub로 보낼 증상 줄 — 구급대원이 찍은 부위
    var addedLines: [String] { added.map { BodyEdits.label($0) + " 외상(구급대원 확인)" }.sorted() }
    var isEmpty: Bool { added.isEmpty && removed.isEmpty && careLines.isEmpty }
    /// 고친 부위 수(한 부위에 외상·처치를 같이 적어도 한 곳)
    var markCount: Int { Set(added).union(removed).union(cares.filter { !$0.value.isEmpty }.keys).count }
    /// 지금 내용의 지문 — 보낸 뒤 또 바뀌었는지만 본다
    var signature: String {
        (added.map { "+" + BodyEdits.label($0) }.sorted()
            + removed.map { "-" + BodyEdits.label($0) }.sorted()
            + careLines).joined(separator: "|")
    }
}

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
            .arm: ["팔꿈치", "주관절", "전완", "상완", "어깨", "견관절", "상지", "팔"],
            .hand: ["손가락", "손목", "손등", "손바닥", "수부", "손"],
            .leg: ["허벅지", "대퇴", "무릎", "슬관절", "정강", "종아리", "발목", "하지", "다리"],
            .foot: ["발가락", "발등", "발바닥", "족부", "발"],
        ]
        return table.flatMap { r, ws in ws.map { (r, $0) } }.sorted { $0.1.count > $1.1.count }
    }()
    /// 부위를 하나로 못 집는 말 — 몸통과 팔다리를 다 표시한다
    private static let multiWords = ["다발성", "다발", "전신", "온몸", "여러 군데", "다수 부위"]
    private static let multiMarks: [BodyMark] = [
        BodyMark(region: .head, side: .unknown), BodyMark(region: .chest, side: .unknown),
        BodyMark(region: .abdomen, side: .unknown),
        BodyMark(region: .arm, side: .left), BodyMark(region: .arm, side: .right),
        BodyMark(region: .hand, side: .left), BodyMark(region: .hand, side: .right),
        BodyMark(region: .leg, side: .left), BodyMark(region: .leg, side: .right),
        BodyMark(region: .foot, side: .left), BodyMark(region: .foot, side: .right),
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
        assert(marks(in: "손목 자상") == [BodyMark(region: .hand, side: .left), BodyMark(region: .hand, side: .right)])  // 손목은 팔이 아니라 손
        assert(marks(in: "발목 염좌") == [BodyMark(region: .leg, side: .left), BodyMark(region: .leg, side: .right)])  // "염좌"의 좌는 좌우가 아니다. 발목은 다리
        assert(marks(in: "좌측 팔 골절") == [BodyMark(region: .arm, side: .left)])
        assert(marks(in: "우측 손가락 열상") == [BodyMark(region: .hand, side: .right)])
        assert(marks(in: "발가락 동상") == [BodyMark(region: .foot, side: .left), BodyMark(region: .foot, side: .right)])
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
    /// 뒷모습 — 같은 실루엣을 좌우로 뒤집어 그린다(사람 실루엣은 앞뒤가 사실상 같다)
    var back = false
    var marks: Set<BodyMark> { Set(tiers.keys) }
    /// 이 보기에서 보이는 부위만 칠하고 번호를 단다
    private var shown: [(n: Int, mark: BodyMark)] { numbered.filter { BodyShape.visible($0.mark.region, back: back) } }

    var body: some View {
        GeometryReader { g in
            let side = min(g.size.width / BodyShape.ratio, g.size.height)
            let box = CGSize(width: side * BodyShape.ratio, height: side)
            ZStack {
                Canvas { ctx, _ in
                    // 뒷모습은 좌표계를 통째로 뒤집어 그린다 — 부위 영역·경계선 좌표는 앞모습 그대로 쓰면서
                    // 보이는 좌우만 바뀐다(뒷모습에서 보이는 왼쪽 = 환자의 왼쪽)
                    if back { ctx.translateBy(x: box.width, y: 0); ctx.scaleBy(x: -1, y: 1) }
                    let body = BodyShape.path(box)
                    ctx.fill(body, with: .color(AD.navy))
                    // 칠하는 순서를 머리 → 다리로 고정한다(Set은 순서가 없어 겹치는 자리가 그때그때 달라진다)
                    for item in shown {
                        // 부위 색 = 그 부위 위험도(높음 빨강 · 중간 주황 · 낮음 연두)
                        let color = tiers[item.mark]?.color ?? AD.red
                        ctx.drawLayer { layer in
                            layer.clip(to: BodyShape.region(item.mark, box, back: back))
                            layer.fill(body, with: .color(color))
                        }
                    }
                    // 부위 경계 — 누를 수 있는 칸이 보이게 옅은 선으로(실루엣 안쪽만)
                    ctx.drawLayer { layer in
                        layer.clip(to: body)
                        layer.stroke(BodyShape.dividers(box, back: back), with: .color(.white.opacity(0.22)),
                                     style: StrokeStyle(lineWidth: 1, dash: [3, 3]))
                    }
                }
                .frame(width: box.width, height: box.height)
                // 다친 부위 번호 — 그림 위에 흰 글씨 동그라미
                ForEach(Array(shown.enumerated()), id: \.offset) { _, item in
                    let p = BodyShape.anchor(item.mark, back: back)
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
    // 실측값(2026-10-29) — 실제 윤곽선에서 팔이 가장 가늘어지는 자리(손목) 0.48, 완전히 사라지는 자리(손끝) 0.5745 + 여유.
    // 이전엔 손목 0.58·손끝 0.68로 더 아래에 둬서, 그 자리엔 그림에 팔도 손도 없어(이미 다리로 넘어간 뒤) 손이 안 칠해졌다.
    private static let handSplit: CGFloat = 0.48   // 손목 — 팔과 손의 경계
    private static let handTip: CGFloat = 0.58     // 손끝 — 손이 끝나는 자리
    private static let footSplit: CGFloat = 0.90   // 발목 — 다리와 발의 경계

    /// 앞모습에서만 / 뒷모습에서만 보이는 부위(2026-10-28). 머리·목·팔·다리는 양쪽에 다 있다
    static func visible(_ r: BodyRegion, back: Bool) -> Bool {
        switch r {
        case .face, .chest, .abdomen: return !back
        case .back: return back
        default: return true
        }
    }

    /// 한 부위를 오려 낼 영역(실루엣과 겹치는 부분만 칠해진다).
    /// 뒷모습(`back`)은 **같은 좌표계에 그린 뒤 좌우를 뒤집어** 보여 준다 — 그래서 여기 좌표는 앞모습 기준 그대로이고,
    /// 등·허리만 몸통 한 칸(목~허리)으로 넓어지고 가슴·배·얼굴은 빠진다
    static func region(_ m: BodyMark, _ s: CGSize, back: Bool = false) -> Path {
        if back {
            switch m.region {
            case .face, .chest, .abdomen: return Path()
            case .back: return band(neckBottom, abdomenBottom, s)
            default: break
            }
        }
        return regionFront(m, s)
    }

    private static func regionFront(_ m: BodyMark, _ s: CGSize) -> Path {
        func rect(_ y0: CGFloat, _ y1: CGFloat, _ x0: CGFloat = 0, _ x1: CGFloat = 1) -> Path {
            Path(CGRect(x: x0 * s.width, y: y0 * s.height, width: (x1 - x0) * s.width, height: (y1 - y0) * s.height))
        }
        switch m.region {
        case .head: return rect(0, headBottom)
        case .face: return rect(0.055, headBottom - 0.004, 0.28, 0.72)
        case .neck: return rect(headBottom, neckBottom, 0.34, 0.66)   // 어깨까지 번지지 않게 가운데만
        case .chest: return band(neckBottom, chestBottom, s)
        case .abdomen: return band(chestBottom, abdomenBottom, s)
        // 손끝이 골반 높이까지 내려와 몸통 경계 추적에 같이 잡힌다(다리와 같은 문제) — 좌우 끝을 잘라 손을 뺀다
        case .pelvis: return rect(abdomenBottom, crotch, 0.17, 0.83)
        // 등·허리는 앞모습에 안 보인다 — 몸통 가운데 띠로 표시한다(번호·목록으로 구분)
        case .back: return rect(0.215, 0.520, 0.41, 0.59)
        case .arm: return armSide(m.side, s)
        case .hand: return handSide(m.side, s)
        // 가랑이 아래 좌우 — 양옆 끝은 손끝이 내려오는 자리라 뺀다(손이 다리로 칠해졌다). 발목 밑(발)은 따로 뗀다
        case .leg: return m.side == .right ? rect(crotch, footSplit, 0.17, 0.5) : rect(crotch, footSplit, 0.5, 0.83)
        case .foot: return m.side == .right ? rect(footSplit, 1, 0.17, 0.5) : rect(footSplit, 1, 0.5, 0.83)
        }
    }

    /// 부위 경계선(2026-10-28) — 어디를 누르면 어디가 잡히는지 보이게, 실루엣 안에 옅은 선을 긋는다.
    /// 가로 선은 머리·목·가슴·배·골반의 경계, 세로 선은 다리 가운데와 팔/몸통 경계다(그리는 쪽에서 실루엣으로 오린다)
    static func dividers(_ s: CGSize, back: Bool = false) -> Path {
        var p = Path()
        for y in (back ? [headBottom, neckBottom, abdomenBottom, crotch] : [headBottom, neckBottom, chestBottom, abdomenBottom, crotch]) {
            p.move(to: CGPoint(x: 0, y: y * s.height))
            p.addLine(to: CGPoint(x: s.width, y: y * s.height))
        }
        // 다리 가운데
        p.move(to: CGPoint(x: 0.5 * s.width, y: crotch * s.height))
        p.addLine(to: CGPoint(x: 0.5 * s.width, y: s.height))
        // 팔/몸통 경계 — 어깨 아래부터 손목까지 몸통 가장자리를 따라간다
        let rows = torsoRows(headBottom, handSplit)
        for edge in [1, 2] {
            guard let first = rows.first else { break }
            p.move(to: CGPoint(x: (edge == 1 ? first.1 : first.2) * s.width, y: first.0 * s.height))
            for r in rows { p.addLine(to: CGPoint(x: (edge == 1 ? r.1 : r.2) * s.width, y: r.0 * s.height)) }
        }
        // 손목 경계 — 팔 칸 안에서만 짧게 긋는다(몸통을 가로지르지 않게)
        if let last = rows.last {
            p.move(to: CGPoint(x: 0, y: handSplit * s.height))
            p.addLine(to: CGPoint(x: last.1 * s.width, y: handSplit * s.height))
            p.move(to: CGPoint(x: last.2 * s.width, y: handSplit * s.height))
            p.addLine(to: CGPoint(x: s.width, y: handSplit * s.height))
        }
        // 발목 경계
        p.move(to: CGPoint(x: 0.17 * s.width, y: footSplit * s.height))
        p.addLine(to: CGPoint(x: 0.83 * s.width, y: footSplit * s.height))
        return p
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

    /// 팔 — 어깨부터 손목까지, 몸통 경계 바깥쪽(환자의 오른팔이 보는 사람의 왼쪽)
    private static func armSide(_ side: BodySide, _ s: CGSize) -> Path {
        // 목(가운데 좁은 띠, 0.34~0.66)이 어깨까지 못 미쳐서, 머리 바로 아래부터 시작해 그 틈(어깨 경사면)을 팔로 메운다.
        // 몸통 경계 추적을 손목(handSplit)까지 바로 따라간다 — 손목이 실제 그림에서 팔이 가장 가늘어지는 자리다
        let rows = torsoRows(headBottom, handSplit)
        let viewerLeft = side == .right
        var p = Path()
        guard let first = rows.first, let last = rows.last else { return p }
        func edge(_ r: (CGFloat, CGFloat, CGFloat)) -> CGFloat { viewerLeft ? r.1 : r.2 }
        let outer = viewerLeft ? 0 : s.width
        p.move(to: CGPoint(x: edge(first) * s.width, y: first.0 * s.height))
        for r in rows { p.addLine(to: CGPoint(x: edge(r) * s.width, y: r.0 * s.height)) }
        p.addLine(to: CGPoint(x: outer, y: last.0 * s.height))
        p.addLine(to: CGPoint(x: outer, y: first.0 * s.height))
        p.closeSubpath()
        return p
    }

    /// 손 — 손목(handSplit)부터 손끝(handTip)까지. 손은 손가락이 갈라지며 폭이 좁아졌다 넓어지므로 몸통 경계값을
    /// 그대로 못 쓰고, 실제 윤곽선에서 실측한 가로 범위를 고정값(0.17/0.83 — 다리 칸 경계와 같다)으로 못박았다.
    private static func handSide(_ side: BodySide, _ s: CGSize) -> Path {
        let viewerLeft = side == .right
        let inner: CGFloat = viewerLeft ? 0.17 : 0.83
        let outer: CGFloat = viewerLeft ? 0 : 1
        let x0 = min(inner, outer), x1 = max(inner, outer)
        return Path(CGRect(x: x0 * s.width, y: handSplit * s.height,
                            width: (x1 - x0) * s.width, height: (handTip - handSplit) * s.height))
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

    /// 누른 자리가 어느 부위인가(2026-10-28) — 겹치는 영역은 좁은 것부터 본다(얼굴 → 목 → 머리 → 팔다리 → 몸통).
    /// 실루엣 밖은 nil이고, 등·허리는 앞모습에 안 보이므로 탭으로 집히지 않는다(통화 요약에서만 들어온다)
    static func hit(_ p: CGPoint, _ s: CGSize, back: Bool = false) -> BodyMark? {
        // 뒷모습은 그림을 좌우로 뒤집어 보여 주므로, 누른 자리도 되뒤집어 앞모습 좌표계에서 찾는다
        // (좌우가 저절로 맞는다 — 뒷모습에서 보이는 왼쪽이 환자의 왼쪽)
        let q = back ? CGPoint(x: s.width - p.x, y: p.y) : p
        guard path(s).contains(q) else { return nil }
        let order: [BodyMark] = back ? [
            BodyMark(region: .neck, side: .unknown), BodyMark(region: .head, side: .unknown),
            BodyMark(region: .hand, side: .left), BodyMark(region: .hand, side: .right),
            BodyMark(region: .arm, side: .left), BodyMark(region: .arm, side: .right),
            BodyMark(region: .foot, side: .left), BodyMark(region: .foot, side: .right),
            BodyMark(region: .leg, side: .left), BodyMark(region: .leg, side: .right),
            BodyMark(region: .back, side: .unknown), BodyMark(region: .pelvis, side: .unknown),
        ] : [
            BodyMark(region: .face, side: .unknown), BodyMark(region: .neck, side: .unknown),
            BodyMark(region: .head, side: .unknown),
            BodyMark(region: .hand, side: .left), BodyMark(region: .hand, side: .right),
            BodyMark(region: .arm, side: .left), BodyMark(region: .arm, side: .right),
            BodyMark(region: .foot, side: .left), BodyMark(region: .foot, side: .right),
            BodyMark(region: .leg, side: .left), BodyMark(region: .leg, side: .right),
            BodyMark(region: .chest, side: .unknown), BodyMark(region: .abdomen, side: .unknown),
            BodyMark(region: .pelvis, side: .unknown),
        ]
        return order.first { region($0, s, back: back).contains(q) }
    }

    #if DEBUG
    /// 탭 → 부위 자체 검사(그림이 바뀌면 여기서 멈춘다) + 적은 것이 어떤 줄로 나가는지
    static func selfCheck() {
        let s = CGSize(width: 320 * ratio, height: 320)
        func at(_ x: CGFloat, _ y: CGFloat) -> BodyMark? { hit(CGPoint(x: x * s.width, y: y * s.height), s) }
        assert(at(0.5, 0.11)?.region == .face)
        assert(at(0.5, 0.17)?.region == .neck)
        assert(at(0.5, 0.26)?.region == .chest)
        assert(at(0.5, 0.43)?.region == .abdomen)
        assert(at(0.5, 0.53)?.region == .pelvis)
        assert(at(0.32, 0.80) == BodyMark(region: .leg, side: .right))   // 그림 왼쪽 = 환자 오른쪽
        assert(at(0.68, 0.80) == BodyMark(region: .leg, side: .left))
        assert(at(0.32, 0.96) == BodyMark(region: .foot, side: .right))  // 발목 밑 — 다리가 아니라 발
        assert(at(0.68, 0.96) == BodyMark(region: .foot, side: .left))
        assert(at(0.05, 0.40) == BodyMark(region: .arm, side: .right))   // 손목 위 — 팔
        assert(at(0.05, 0.52) == BodyMark(region: .hand, side: .right))  // 손목 밑 — 손(2026-10-29 전엔 이 자리가 비어 안 집혔다)
        assert(at(0.95, 0.52) == BodyMark(region: .hand, side: .left))
        assert(at(0.5, 1.4) == nil)                                      // 그림 밖

        // 뒷모습 — 좌우가 뒤집혀 보인다(보이는 왼쪽 = 환자 왼쪽)
        func atBack(_ x: CGFloat, _ y: CGFloat) -> BodyMark? {
            hit(CGPoint(x: x * s.width, y: y * s.height), s, back: true)
        }
        assert(atBack(0.32, 0.80) == BodyMark(region: .leg, side: .left))
        assert(atBack(0.68, 0.80) == BodyMark(region: .leg, side: .right))
        assert(atBack(0.5, 0.26)?.region == .back && atBack(0.5, 0.43)?.region == .back)   // 가슴·배 자리가 등·허리
        assert(atBack(0.5, 0.53)?.region == .pelvis && atBack(0.5, 0.11)?.region == .head) // 둔부 · 뒤통수(얼굴 아님)
        assert(visible(.back, back: true) && !visible(.back, back: false))
        assert(visible(.chest, back: false) && !visible(.chest, back: true))
        assert(visible(.leg, back: true) && visible(.leg, back: false))

        var e = BodyEdits()
        e.added.insert(BodyMark(region: .leg, side: .left))
        e.cares[BodyMark(region: .leg, side: .left)] = ["지혈", "부목 고정"]
        assert(e.addedLines == ["좌 다리 외상(구급대원 확인)"])
        assert(e.careLines == ["좌 다리 부목 고정", "좌 다리 지혈"])
        assert(!e.isEmpty && BodyEdits().isEmpty)
        // 한 부위에 외상·처치를 같이 적어도 한 곳, 지문은 더 고치면 달라진다(전달 여부 판정)
        assert(e.markCount == 1)
        let before = e.signature
        e.added.insert(BodyMark(region: .back, side: .unknown))
        assert(e.signature != before && e.markCount == 2)
    }
    #endif

    /// 번호 동그라미 자리(0~1). 뒷모습은 그림이 뒤집혀 보이므로 x도 뒤집는다
    static func anchor(_ m: BodyMark, back: Bool) -> CGPoint {
        let a = anchor(m)
        return back ? CGPoint(x: 1 - a.x, y: a.y) : a
    }

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
        case .hand: return CGPoint(x: m.side == .right ? 0.085 : 0.915, y: (handSplit + handTip) / 2)
        case .leg: return CGPoint(x: m.side == .right ? 0.315 : 0.685, y: 0.760)
        case .foot: return CGPoint(x: m.side == .right ? 0.315 : 0.685, y: (footSplit + 1) / 2)
        }
    }
}

/// [환자 정보] 탭 오른쪽 카드 — 사람 그림 가운데, 다친 부위에서 **선을 바깥으로 빼서** 설명을 단다(2026-10-27).
/// 예전엔 그림 왼쪽·목록 오른쪽이었는데, 어느 설명이 어느 부위인지 번호로만 이어져 한눈에 안 들어왔다.
/// 부위를 못 찾은 항목(전신 증상)은 선 없이 오른다리 옆에 모아 둔다.
struct BodyInjuryCard: View {
    @EnvironmentObject private var model: AppModel

    /// 앞모습 / 뒷모습 — 등·허리·둔부는 뒤에서만 집힌다
    @State private var back = false
    /// 마지막으로 병원에 보낸 내용의 지문 — 그 뒤로 또 고쳤는지만 본다
    @State private var sentSignature = ""
    @State private var tapped: BodyMark?
    @State private var draftOn = true
    @State private var draftCares: [String] = []
    @State private var sharedBase: [String: String] = [:]

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
    /// 부위별 위험도 — 그 부위에 걸린 항목 중 가장 높은 등급(규칙, 전문의 검토 전 초안)
    private var tiers: [BodyMark: InjuryTier] {
        var out: [BodyMark: InjuryTier] = [:]
        for injury in located {
            for mark in injury.marks where !model.bodyEdits.removed.contains(mark) {
                let tier = InjuryRisk.tier(injury.text, region: mark.region)
                out[mark] = max(out[mark] ?? .low, tier)
            }
        }
        // 구급대원이 눌러 찍은 부위 — 적은 처치까지 같이 보고 등급을 매긴다(규칙은 통화 항목과 같다)
        for mark in model.bodyEdits.added {
            let text = (["외상"] + (model.bodyEdits.cares[mark] ?? [])).joined(separator: " ")
            out[mark] = max(out[mark] ?? .low, InjuryRisk.tier(text, region: mark.region))
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
        return marked.keys.filter { BodyShape.visible($0.region, back: back) }.map { mark in
            var texts = located.filter { $0.marks.contains(mark) }.map(\.text)
            if texts.isEmpty { texts = ["외상(구급대원 확인)"] }
            texts += (model.bodyEdits.cares[mark] ?? []).map { "처치 " + $0 }
            return Callout(mark: mark, n: numbers[mark] ?? 0, title: BodyEdits.label(mark),
                           text: texts.joined(separator: " · "), tier: marked[mark] ?? .low)
        }
        .sorted { $0.n < $1.n }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            // firstTextBaseline이면 [앞|뒤] 안의 배지(숫자)가 뜰 때와 안 뜰 때 faceSwitch의 기준선이 달라져서
            // 배지가 있을 때만 통째로 위로 밀려 카드 위쪽에 잘렸다 — center로 바꿔 배지 유무와 무관하게 고정
            HStack(alignment: .center, spacing: 8) {
                Text("외상 부위").font(.system(size: 16, weight: .bold)).foregroundStyle(AD.navy)
                Spacer(minLength: 0)
                if patient != nil {
                    Text("부위를 눌러 고치거나 처치를 적습니다").font(.system(size: 11)).foregroundStyle(AD.muted)
                    faceSwitch
                }
                if let k = patient?.ktasLevel { Pill(text: "KTAS \(k)", bg: Theme.ktasSoft(k), fg: Theme.ktas(k), bold: true) }
                if !tiers.isEmpty { Pill(text: "\(tiers.count)곳", bg: AD.redSoft, fg: AD.red, bold: true) }
                if !model.bodyEdits.isEmpty { Pill(text: "구급대원 수정", bg: AD.orangeSoft, fg: AD.orange, bold: true) }
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
                sendBar
                HStack(spacing: 10) {
                    Text(back ? "뒷모습 — 보이는 왼쪽이 환자의 왼쪽입니다" : "앞모습 — 환자 기준 좌·우(그림은 좌우가 바뀌어 보입니다)")
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

    /// 적은 것을 한 번에 보내는 줄 — 고친 게 없으면 아예 안 보인다
    @ViewBuilder private var sendBar: some View {
        let e = model.bodyEdits
        if !e.isEmpty || e.signature != sentSignature {
            HStack(spacing: 8) {
                if e.signature == sentSignature {
                    Pill(text: "병원에 전달함", bg: AD.greenSoft, fg: AD.green, bold: true)
                    Text("부위 \(e.markCount)곳 · 처치 \(e.careLines.count)건").font(.system(size: 11.5)).foregroundStyle(AD.muted)
                } else {
                    Pill(text: "전달 전", bg: AD.orangeSoft, fg: AD.orange, bold: true)
                    Text("구급대원이 고친 부위 \(e.markCount)곳 · 처치 \(e.careLines.count)건").font(.system(size: 11.5)).foregroundStyle(AD.ink3)
                }
                Spacer(minLength: 0)
                if e.signature != sentSignature {
                    Button { send() } label: {
                        Label("병원에 전달", systemImage: "paperplane.fill")
                            .font(.system(size: 13, weight: .bold)).foregroundStyle(.white)
                            .padding(.horizontal, 16).frame(minHeight: 32)
                            .background(model.paused ? AD.gray : AD.blue).clipShape(Capsule())
                    }
                    .buttonStyle(.plain).disabled(model.paused)
                }
            }
            .padding(.horizontal, 10).padding(.vertical, 6)
            .background(AD.chip).clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        }
    }

    /// [앞 | 뒤] — 반대쪽에만 있는 부위 수를 배지로 알려 준다(등·허리가 뒤에 있는 걸 놓치지 않게)
    private var faceSwitch: some View {
        HStack(spacing: 2) {
            seg("앞", false)
            seg("뒤", true)
        }
        .padding(2).background(AD.chip).clipShape(Capsule())
        // 칸 어디를 눌러도 앞↔뒤로 넘어간다(2026-10-28) — 두 칸뿐이라 '그 칸 고르기'와 결과가 같고, 과녁이 두 배다
        .contentShape(Capsule())
        .onTapGesture { withAnimation(.easeInOut(duration: 0.15)) { back.toggle(); tapped = nil } }
    }
    private func seg(_ title: String, _ value: Bool) -> some View {
        // 이쪽 보기에만 있는 부위 수(머리·팔·다리처럼 양쪽에 다 있는 건 안 센다)
        let hidden = tiers.keys.filter {
            BodyShape.visible($0.region, back: value) && !BodyShape.visible($0.region, back: !value)
        }.count
        let on = back == value
        return HStack(spacing: 4) {
            Text(title).font(.system(size: 12, weight: on ? .bold : .medium)).foregroundStyle(on ? AD.navy : AD.ink3)
            if !on, hidden > 0 {
                Text("\(hidden)").font(.system(size: 10, weight: .bold)).foregroundStyle(.white)
                    .padding(.horizontal, 5).frame(minHeight: 16).background(AD.red).clipShape(Capsule())
            }
        }
        .padding(.horizontal, 10).frame(minHeight: 26)
        .background(on ? AD.card : .clear).clipShape(Capsule())
    }

    // 설명 상자 크기 — 선을 그릴 자리를 계산하려면 미리 정해 둬야 한다.
    // 46이었던 적이 있는데 실제 카드(제목 줄 + 2줄 설명 + 상하 패딩)는 70pt 안팎이라, 부위가 많아
    // 간격을 좁혀 붙일 때마다 카드끼리 겹쳤다 — box()에도 같은 값을 최소 높이로 강제해 틀어지지 않게 한다
    private static let boxW: CGFloat = 210
    private static let boxH: CGFloat = 70
    private static let gap: CGFloat = 10        // 상자끼리 최소 간격

    private var diagram: some View {
        GeometryReader { g in
            let figH = max(120, g.size.height)
            let figW = figH * BodyShape.ratio
            let figX = (g.size.width - figW) / 2
            // 칸이 좁으면 설명 상자를 줄인다(아이패드를 세로로 세웠을 때)
            let bw = max(130, min(Self.boxW, (g.size.width - figW) / 2 - 26))
            // "부위 미상" 회색 박스 자리를 바닥에 미리 비워 둔다 — 안 비우면 place()가 꽉 채운 뒤
            // generalBox가 바닥 한계에 깎여 마지막 상자와 겹쳤다(다리처럼 아래쪽 부위를 찍을 때 특히)
            let reserve = (showsGeneral && !back) ? Self.boxH + Self.gap * 2 : 0
            let placed = place(callouts, height: g.size.height - reserve)
            // 카드가 많아 상자가 칸 높이를 넘으면(이전엔 여기서 눌러 담아 겹쳤다) 그만큼 칸을 늘리고 스크롤한다
            let contentH = max(g.size.height, (placed.map(\.y).max() ?? 0) + Self.boxH / 2 + Self.gap + reserve)
            ScrollView(.vertical, showsIndicators: false) {
            ZStack(alignment: .topLeading) {
                BodyFigure(tiers: tiers, back: back)
                    .frame(width: figW, height: figH)
                    .contentShape(Rectangle())
                    // 그림을 누르면 그 부위가 열린다(2026-10-28) — 장갑 낀 손으로 글자를 고치는 것보다 빠르다
                    .gesture(SpatialTapGesture().onEnded { v in
                        guard let m = BodyShape.hit(v.location, CGSize(width: figW, height: figH), back: back) else { return }
                        draftOn = tiers[m] != nil
                        draftCares = model.bodyEdits.cares[m] ?? []
                        sharedBase = model.caseEdits.fields
                        withAnimation(.easeOut(duration: 0.15)) { tapped = m }
                    })
                    .position(x: g.size.width / 2, y: figH / 2)
                if showsGeneral, !back {
                    // 부위 미상·전신 증상 — 선 없이 오른다리 옆에. 연결선보다 먼저 그려서(아래 Canvas가 위) 선이
                    // 이 상자를 가로질러도 가려지지 않는다
                    generalBox(width: bw)
                        .position(x: figX + figW + 14 + bw / 2,
                                  y: min(contentH - Self.boxH / 2,
                                         max(0.80 * figH, (placed.filter { !$0.left }.map(\.y).max() ?? 0) + Self.boxH + Self.gap * 2)))
                }
                // 부위 → 설명 상자로 가는 선(일직선). generalBox 위, 설명 상자들 아래에 깔린다
                Canvas { ctx, _ in
                    for c in placed {
                        let anchor = BodyShape.anchor(c.mark, back: back)
                        let from = CGPoint(x: figX + anchor.x * figW, y: anchor.y * figH)
                        let toX = c.left ? figX - 14 : figX + figW + 14
                        let to = CGPoint(x: toX, y: c.y)
                        var path = Path()
                        path.move(to: from)
                        path.addLine(to: to)
                        ctx.stroke(path, with: .color(c.tier.color.opacity(0.55)),
                                   style: StrokeStyle(lineWidth: 1.5, lineCap: .round, lineJoin: .round))
                        ctx.fill(Path(ellipseIn: CGRect(x: from.x - 3, y: from.y - 3, width: 6, height: 6)),
                                 with: .color(c.tier.color))
                    }
                }
                // 장식용 선일 뿐이라 그림 전체를 덮어도 탭은 그 아래 BodyFigure로 그냥 지나간다
                .allowsHitTesting(false)
                ForEach(placed) { c in
                    box(c, width: bw)
                        .position(x: c.left ? figX - 14 - bw / 2 : figX + figW + 14 + bw / 2, y: c.y)
                }
                if callouts.isEmpty && unlocated.isEmpty {
                    Text("통화 요약에 외상 항목이 없습니다")
                        .font(.system(size: 13)).foregroundStyle(AD.muted)
                        .position(x: g.size.width / 2, y: contentH - 14)
                }
            }
            .frame(width: g.size.width, height: contentH)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        // 항상 바닥 가운데에 띄우던 것 — 다리·골반처럼 아래쪽을 찍으면 그 자리 설명 상자들과 겹쳤다.
        // 설명 상자는 그림 좌우에만 쌓이니 가운데(그림 위)에 띄우면 겹치지 않는다
        .overlay { if let m = tapped { editPanel(m) } }
    }

    /// 부위 하나를 고치는 칸 — 외상 있음/없음과 그 부위에 한 처치
    private func editPanel(_ m: BodyMark) -> some View {
        let fromCall = callMarks.contains(m)
        return VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Text(BodyEdits.label(m)).font(.system(size: 15, weight: .heavy)).foregroundStyle(AD.navy)
                if fromCall { Pill(text: "통화 요약", bg: AD.blueSoft, fg: AD.blue) }
                Spacer(minLength: 0)
                Button { tapped = nil } label: {
                    Image(systemName: "xmark").font(.system(size: 12, weight: .bold)).foregroundStyle(AD.ink3)
                        .frame(width: 26, height: 26).background(AD.chip).clipShape(Circle())
                }
            }
            HStack(spacing: 6) {
                ForEach([true, false], id: \.self) { on in
                    Button { draftOn = on; if !on { draftCares = [] } } label: {
                        Text(on ? "외상 있음" : "외상 없음")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(draftOn == on ? .white : AD.ink3)
                            .padding(.horizontal, 14).frame(minHeight: 34)
                            .background(draftOn == on ? (on ? AD.red : AD.gray) : AD.chip).clipShape(Capsule())
                            .animation(nil, value: draftOn)
                    }
                    .buttonStyle(.plain)
                }
                Spacer(minLength: 0)
            }
            if draftOn {
                Text("이 부위에 한 처치").font(.system(size: 11.5)).foregroundStyle(AD.muted)
                FlowChips(options: BodyEdits.careOptions, selected: $draftCares)
            }
            HStack(spacing: 8) {
                // 여기서는 보내지 않는다(2026-10-28) — 부위마다 보내면 병원에 쪽지가 여러 장 가고 "구급대원 확인" 도장도
                // 여러 번 찍힌다. 다 적은 뒤 카드 아래 [병원에 전달]로 **한 번에** 나간다
                Text("적은 뒤 아래 [병원에 전달]로 한 번에 보냅니다").font(.system(size: 11)).foregroundStyle(AD.muted)
                Spacer(minLength: 0)
                Button { apply(m); tapped = nil } label: {
                    Text("적용").font(.system(size: 13, weight: .bold)).foregroundStyle(.white)
                        .padding(.horizontal, 20).frame(minHeight: 34)
                        .background(AD.blue).clipShape(Capsule())
                }
                .buttonStyle(.plain)
            }
        }
        .padding(12)
        .frame(maxWidth: 420)
        .background(AD.card)
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).stroke(AD.line, lineWidth: 1))
        .shadow(color: .black.opacity(0.12), radius: 10, y: 4)
    }

    /// 통화 요약에서 나온 부위(구급대원이 더한 것은 빼고) — 패널의 "통화 요약" 표시와 제외 처리에 쓴다
    private var callMarks: Set<BodyMark> { Set(located.flatMap(\.marks)) }

    /// 고친 내용을 모델에 넣고 hub로 보낸다 — 부위는 증상(injuryStatus) 칸, 처치는 추가 정보로
    private func apply(_ m: BodyMark) {
        var e = model.bodyEdits
        if draftOn {
            if callMarks.contains(m) { e.removed.remove(m) } else { e.added.insert(m) }
            e.cares[m] = draftCares.isEmpty ? nil : draftCares
        } else {
            if callMarks.contains(m) { e.removed.insert(m) } else { e.added.remove(m) }
            e.cares[m] = nil
        }
        model.bodyEdits = e
        model.shareBody(m, base: sharedBase)
    }

    /// 적은 것을 **한 번에** 병원으로 — 부위는 증상(injuryStatus) 칸, 처치는 추가 정보 한 줄
    private func send() {
        let e = model.bodyEdits
        // 증상 칸 = 통화에서 온 것 중 **빼지 않은 것** + 구급대원이 찍은 부위
        let kept = (patient?.injuryStatus ?? []).filter { text in
            let marks = InjuryMapper.marks(in: text)
            return marks.isEmpty || !marks.allSatisfy(e.removed.contains)
        }
        guard model.sendPatientOverride(expectedDiagnosis: nil, injuryStatus: kept + e.addedLines,
                                        ktasLevel: nil, requiredDepartment: nil, chiefComplaint: nil) else { return }
        // 처치 전송이 실패하면 "보냄"으로 표시하지 않는다 — 다시 누르면 둘 다 다시 간다
        if !e.careLines.isEmpty, !model.sendExtraNote("[처치] " + e.careLines.joined(separator: " · ")) { return }
        sentSignature = e.signature
    }

    /// 상자를 좌우로 나눠 세로로 쌓는다 — 팔·다리는 그쪽 편, 가운데 부위는 번갈아. 겹치면 아래로 민다
    private func place(_ items: [Callout], height: CGFloat) -> [Callout] {
        var out: [Callout] = []
        var midlineLeft = true
        for var c in items {
            switch (c.mark.region, c.mark.side) {
            // 앞모습은 환자의 오른쪽이 그림의 왼쪽, 뒷모습은 그대로다
            case (_, .right): c.left = !back
            case (_, .left): c.left = back
            default:
                c.left = midlineLeft
                midlineLeft.toggle()
            }
            c.y = BodyShape.anchor(c.mark, back: back).y * height
            out.append(c)
        }
        for side in [true, false] {
            var last: CGFloat = -.infinity
            for i in out.indices where out[i].left == side {
                out[i].y = max(out[i].y, last + Self.boxH + Self.gap)
                last = out[i].y
            }
        }
        // 넘치면 더 눌러 담지 않는다 — 눌러 담으면 상자 간격이 상자 키(boxH)보다 좁아져 글자가 가려졌다.
        // 대신 호출부가 이 결과의 최대 y로 칸 높이를 늘려 스크롤하게 둔다(상자끼리는 항상 안 겹침)
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
        // 간격 계산이 boxH를 가정하므로 실제 높이도 최소 그만큼으로 — 안 그러면 좁은 간격에서 다시 겹친다
        .frame(minHeight: Self.boxH, alignment: .top)
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

/// 여러 개를 고르는 알약 줄 — 칸 폭에 맞춰 줄바꿈한다(처치 고르기)
struct FlowChips: View {
    let options: [String]
    @Binding var selected: [String]

    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 92), spacing: 6)], alignment: .leading, spacing: 6) {
            ForEach(options, id: \.self) { o in
                let on = selected.contains(o)
                Button {
                    if on { selected.removeAll { $0 == o } } else { selected.append(o) }
                } label: {
                    Text(o).font(.system(size: 12.5, weight: on ? .bold : .medium))
                        .foregroundStyle(on ? .white : AD.ink3)
                        .lineLimit(1).frame(maxWidth: .infinity).frame(minHeight: 32)
                        .background(on ? AD.blue : AD.chip).clipShape(Capsule())
                }
                .buttonStyle(.plain)
            }
        }
    }
}
