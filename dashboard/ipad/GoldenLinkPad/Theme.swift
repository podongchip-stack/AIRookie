import SwiftUI

// 구급차 대시보드(웹, components/ambulance/ambulance-design.ts)와 같은 색 — 밝은 회색 바탕 · 흰 카드 · 둥근 18pt.
// 웹 AD 팔레트를 그대로 옮겼다(값을 바꾸면 웹과 같이 바꾼다).
extension Color {
    init(hex: UInt32) {
        self.init(.sRGB, red: Double((hex >> 16) & 0xff) / 255, green: Double((hex >> 8) & 0xff) / 255, blue: Double(hex & 0xff) / 255, opacity: 1)
    }
}

enum AD {
    static let bg = Color(hex: 0xF4F6FA)
    static let line = Color(hex: 0xE3E7EE)
    static let control = Color(hex: 0xD3D9E3)
    static let ink = Color(hex: 0x1B2430)
    static let navy = Color(hex: 0x14213D)
    static let ink3 = Color(hex: 0x4A5565)
    static let sub = Color(hex: 0x5A6676)
    static let muted = Color(hex: 0x7A8594)
    static let chip = Color(hex: 0xF1F3F6)
    static let blue = Color(hex: 0x1F4E9C)
    static let blueSoft = Color(hex: 0xE8EEF8)
    static let green = Color(hex: 0x168A55)
    static let greenSoft = Color(hex: 0xE3F3EB)
    static let lime = Color(hex: 0x4E8B1F)
    static let limeSoft = Color(hex: 0xEEF5E6)
    static let orange = Color(hex: 0xC75B00)
    static let orangeSoft = Color(hex: 0xFFF1E0)
    static let approve = Color(hex: 0xB45309)
    static let red = Color(hex: 0xD93025)
    static let redSoft = Color(hex: 0xFDECEA)
    static let gray = Color(hex: 0x9AA3B0)
    static let skeleton = Color(hex: 0xFAFBFC)
    static let card = Color.white
}

enum Theme {
    static func ktas(_ k: Int) -> Color {
        switch k {
        case 1: return Color(hex: 0xD93025)
        case 2: return Color(hex: 0xE8590C)
        case 3: return Color(hex: 0xC75B00)
        case 4: return Color(hex: 0x4E8B1F)
        default: return Color(hex: 0x168A55)
        }
    }
    static func ktasSoft(_ k: Int) -> Color {
        switch k {
        case 1, 2: return AD.redSoft
        case 3: return AD.orangeSoft
        default: return AD.greenSoft
        }
    }
    /// 병원 상태 알약 — 웹 STATUS_PILL과 같다(판단 대기 주황 · 후보 등록 파랑 · 수용 불가 빨강 · 이송 확정 초록)
    static func statusPill(_ s: String) -> (bg: Color, fg: Color) {
        switch s {
        case "approved": return (AD.blueSoft, AD.blue)
        case "rejected": return (AD.redSoft, AD.red)
        case "confirmed": return (AD.greenSoft, AD.green)
        default: return (AD.orangeSoft, AD.orange)
        }
    }
    /// 도착 시 유효 확률 색 — 웹 validTone과 같다: 80% 이상 파랑(믿고 출발) · 50~80 회색(참고) · 50 미만 빨강(재확인 권장)
    static func validity(_ p: Double) -> (bg: Color, fg: Color) {
        if p >= 0.8 { return (AD.blueSoft, AD.blue) }
        if p >= 0.5 { return (AD.chip, AD.ink3) }
        return (AD.redSoft, AD.red)
    }
    static func severity(_ s: String?) -> (bg: Color, fg: Color, label: String) {
        switch s {
        case "high": return (AD.redSoft, AD.red, "중증 의심")
        case "medium": return (AD.orangeSoft, AD.orange, "중등도 의심")
        case "low": return (AD.greenSoft, AD.green, "경증 의심")
        default: return (AD.chip, AD.ink3, "중증도 미상")
        }
    }
}

/// 흰 카드(연한 테두리 · 둥근 18pt) — 웹 cardStyle
struct CardModifier: ViewModifier {
    var padding: CGFloat
    func body(content: Content) -> some View {
        content
            .padding(padding)
            .background(AD.card)
            .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(AD.line, lineWidth: 1))
    }
}

extension View {
    func card(_ padding: CGFloat = 14) -> some View { modifier(CardModifier(padding: padding)) }
}

/// 알약 — 웹 pill()
struct Pill: View {
    var text: String
    var bg: Color = AD.chip
    var fg: Color = AD.ink3
    var bold = false
    var body: some View {
        Text(text)
            .font(.system(size: 11, weight: bold ? .bold : .medium))
            .lineLimit(1)
            .padding(.horizontal, 10).padding(.vertical, 3)
            .foregroundStyle(fg)
            .background(bg)
            .clipShape(Capsule())
    }
}

/// 카드 안 세 칸(병상 · AI 유효 · 전문의) — 웹 StatBox
struct StatBox: View {
    var label: String
    var value: String
    var bg: Color
    var fg: Color
    var valueColor: Color? = nil
    var body: some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(label).font(.system(size: 11.5, weight: .medium)).foregroundStyle(fg).lineLimit(1)
            Text(value).font(.system(size: 17, weight: .black)).foregroundStyle(valueColor ?? fg).lineLimit(1).minimumScaleFactor(0.7)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 10).padding(.vertical, 4)
        .background(bg)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

struct SectionTitle: View {
    var text: String
    var sub: String? = nil
    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text(text).font(.system(size: 16, weight: .bold)).foregroundStyle(AD.navy)
            if let sub { Text(sub).font(.system(size: 12)).foregroundStyle(AD.ink3).lineLimit(1) }
            Spacer(minLength: 0)
        }
    }
}

/// 가로 확률 막대(0~1) — 정보 유효성을 눈으로 보이게
struct ProbBar: View {
    var value: Double
    var height: CGFloat = 6
    var body: some View {
        GeometryReader { g in
            ZStack(alignment: .leading) {
                Capsule().fill(AD.line)
                Capsule().fill(Theme.validity(value).fg).frame(width: max(0, g.size.width * min(max(value, 0), 1)))
            }
        }.frame(height: height)
    }
}

struct Dot: View {
    var color: Color
    var size: CGFloat = 8
    var body: some View { Circle().fill(color).frame(width: size, height: size) }
}
