import SwiftUI

// spider 화면(web/style.css)과 같은 색 — 가운데 WebView와 양옆 네이티브 패널이 한 화면처럼 보이게
extension Color {
    init(hex: UInt32) {
        self.init(.sRGB, red: Double((hex >> 16) & 0xff) / 255, green: Double((hex >> 8) & 0xff) / 255, blue: Double(hex & 0xff) / 255, opacity: 1)
    }
}

enum Theme {
    static let bg = Color(hex: 0x0a1024)
    static let panel = Color(hex: 0x0f1530)
    static let panel2 = Color(hex: 0x151c3c)
    static let ink = Color(hex: 0xf2f1ec)
    static let ink2 = Color(hex: 0xb9b8ae)
    static let muted = Color(hex: 0x7c7b74)
    static let line = Color(hex: 0x2b2d45)
    static let ok = Color(hex: 0x5ee37f)
    static let occ = Color(hex: 0x4fd1ff)
    static let clash = Color(hex: 0xff3b3b)
    static let sug = Color(hex: 0x7fffd4)
    static let amber = Color(hex: 0xffb039)
    static let g4 = Color(hex: 0x9ad0ff), g3 = Color(hex: 0x2a7ff0), g2 = Color(hex: 0x4f9cff), g1 = Color(hex: 0x7fb6ff)

    static func ktas(_ k: Int) -> Color {
        switch k {
        case 1: return Color(hex: 0xff5c5c)
        case 2: return Color(hex: 0xff7a45)
        case 3: return Color(hex: 0xffb039)
        case 4: return Color(hex: 0xffd96b)
        default: return Color(hex: 0xd8d08a)
        }
    }
    static func grade(_ level: String?) -> Color {
        switch level {
        case "권역응급의료센터": return g4
        case "지역응급의료센터": return g3
        case "지역응급의료기관": return g2
        default: return g1
        }
    }
    static func status(_ s: String) -> Color {
        switch s {
        case "approved": return ok
        case "rejected": return muted
        case "confirmed": return Color(hex: 0xff7a45)
        default: return amber
        }
    }
    /// 유효 확률 색: 80% 이상 초록 · 50~80 호박 · 50 미만 빨강 (대시보드와 같은 단계)
    static func validity(_ p: Double) -> Color { p >= 0.8 ? ok : p >= 0.5 ? amber : clash }
}

struct PanelModifier: ViewModifier {
    var padding: CGFloat
    func body(content: Content) -> some View {
        content
            .padding(padding)
            .background(Theme.panel)
            .clipShape(RoundedRectangle(cornerRadius: 6))
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(Theme.line, lineWidth: 1))
    }
}

extension View {
    func panel(_ padding: CGFloat = 12) -> some View { modifier(PanelModifier(padding: padding)) }
}

struct Chip: View {
    var text: String
    var color: Color = Theme.ink2
    var filled = false
    var body: some View {
        Text(text)
            .font(.system(size: 11, weight: .semibold))
            .padding(.horizontal, 6).padding(.vertical, 2)
            .foregroundStyle(filled ? Theme.bg : color)
            .background(filled ? color : Color.clear)
            .overlay(RoundedRectangle(cornerRadius: 3).stroke(color.opacity(filled ? 0 : 0.8), lineWidth: 1))
            .clipShape(RoundedRectangle(cornerRadius: 3))
    }
}

struct SectionTitle: View {
    var text: String
    var sub: String? = nil
    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(text).font(.system(size: 14, weight: .semibold)).foregroundStyle(Theme.ink)
            if let sub { Text(sub).font(.system(size: 11)).foregroundStyle(Theme.muted) }
            Spacer()
        }
    }
}

/// 가로 확률 막대(0~1)
struct ProbBar: View {
    var value: Double
    var height: CGFloat = 6
    var body: some View {
        GeometryReader { g in
            ZStack(alignment: .leading) {
                RoundedRectangle(cornerRadius: 3).fill(Theme.line)
                RoundedRectangle(cornerRadius: 3).fill(Theme.validity(value)).frame(width: max(0, g.size.width * min(max(value, 0), 1)))
            }
        }.frame(height: height)
    }
}
