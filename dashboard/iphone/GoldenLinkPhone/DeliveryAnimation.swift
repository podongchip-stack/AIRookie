import SwiftUI
import CoreLocation

// 지도 투영 좌표로 표시하는 동시 전달 연출.
final class DeliveryShow {
    let caseId: String
    let durationMs: Double
    let reduceMotion: Bool
    var startedAt: Date?
    init(caseId: String, durationMs: Double, reduceMotion: Bool) {
        self.caseId = caseId; self.durationMs = durationMs; self.reduceMotion = reduceMotion
    }
}

enum DeliveryTimeline {
    static let maxTargets = 8
    private static let delay = 650.0     // 카메라가 구급차 주변으로 맞춰지는 동안
    private static let stagger = 90.0    // 병원마다 출발 간격 — 거의 동시로 보이게 짧게
    private static let flight = 800.0    // 선이 구급차에서 병원까지 그려지는 시간
    private static let pop = 350.0       // 도착한 병원의 이름 칩이 떠오르는 시간

    static func flightProgress(_ i: Int, _ t: Double, reduce: Bool) -> Double {
        reduce ? 1 : min(max((t - delay - stagger * Double(i)) / flight, 0), 1)
    }
    private static func arrivedAt(_ i: Int, reduce: Bool) -> Double { reduce ? 0 : delay + stagger * Double(i) + flight }
    /// 도착 뒤 0→1, 도착 전에는 -1
    static func popProgress(_ i: Int, _ t: Double, reduce: Bool) -> Double {
        t < arrivedAt(i, reduce: reduce) ? -1 : min((t - arrivedAt(i, reduce: reduce)) / pop, 1)
    }
    static func arrivedCount(_ n: Int, _ t: Double, reduce: Bool) -> Int { (0..<n).filter { t >= arrivedAt($0, reduce: reduce) }.count }
}

private func easeOutCubic(_ x: Double) -> Double { let d = 1 - x; return 1 - d * d * d }

/// 구급차→병원 곡선 위의 한 점 — 병원마다 휘는 방향을 번갈아 줘서 선이 겹치지 않게 한다
private func curvePoint(_ a: CGPoint, _ b: CGPoint, bend: Double, _ t: Double) -> CGPoint {
    let len = max(hypot(b.x - a.x, b.y - a.y), 1)
    let nx = -(b.y - a.y) / len, ny = (b.x - a.x) / len
    let c = CGPoint(x: (a.x + b.x) / 2 + nx * len * 0.18 * bend, y: (a.y + b.y) / 2 + ny * len * 0.18 * bend)
    let u = 1 - t
    return CGPoint(x: u * u * a.x + 2 * u * t * c.x + t * t * b.x, y: u * u * a.y + 2 * u * t * c.y + t * t * b.y)
}

private func curvePath(_ a: CGPoint, _ b: CGPoint, bend: Double, from: Double, to: Double) -> Path {
    var p = Path()
    guard to > from else { return p }
    let steps = 28
    for k in 0...steps {
        let pt = curvePoint(a, b, bend: bend, from + (to - from) * Double(k) / Double(steps))
        if k == 0 { p.move(to: pt) } else { p.addLine(to: pt) }
    }
    return p
}

struct DeliveryTarget: Identifiable {
    let id: String
    let name: String
    let coordinate: CLLocationCoordinate2D
}



/// 지도 위에 덮는 연출 — 화면을 누르면 건너뛴다
struct DeliveryOverlay: View {
    let show: DeliveryShow
    let from: CLLocationCoordinate2D
    let targets: [DeliveryTarget]
    let project: (CLLocationCoordinate2D) -> CGPoint?
    let onSkip: () -> Void

    var body: some View {
        TimelineView(.animation) { ctx in
            let t = ctx.date.timeIntervalSince(show.startedAt ?? ctx.date) * 1000
            Canvas { gc, _ in
                guard let a = project(from) else { return }
                let glow = show.reduceMotion ? 0 : 1 - min(t / 900, 1)
                gc.fill(Path(ellipseIn: CGRect(x: a.x - (20 + 18 * (1 - glow)), y: a.y - (20 + 18 * (1 - glow)),
                                               width: 2 * (20 + 18 * (1 - glow)), height: 2 * (20 + 18 * (1 - glow)))),
                        with: .color(AD.blue.opacity(0.10 + 0.12 * glow)))
                for (i, target) in targets.enumerated() {
                    guard let b = project(target.coordinate) else { continue }
                    let bend = i % 2 == 0 ? 1.0 : -1.0
                    let f = DeliveryTimeline.flightProgress(i, t, reduce: show.reduceMotion)
                    let pop = DeliveryTimeline.popProgress(i, t, reduce: show.reduceMotion)
                    let arrived = pop >= 0
                    let e = easeOutCubic(f)
                    let settle = arrived ? 0.45 - 0.2 * pop : 0.45
                    gc.stroke(curvePath(a, b, bend: bend, from: 0, to: e), with: .color(AD.blue.opacity(settle)),
                              style: StrokeStyle(lineWidth: 2, lineCap: .round))
                    if f > 0, f < 1 {
                        let head = curvePath(a, b, bend: bend, from: max(e - 0.22, 0), to: e)
                        gc.stroke(head, with: .color(.white.opacity(0.9)), style: StrokeStyle(lineWidth: 3.5, lineCap: .round))
                        gc.stroke(head, with: .color(AD.blue.opacity(0.85)), style: StrokeStyle(lineWidth: 2.2, lineCap: .round))
                    }
                    if arrived {
                        let r1 = 7 + 14 * pop
                        gc.fill(Path(ellipseIn: CGRect(x: b.x - r1, y: b.y - r1, width: 2 * r1, height: 2 * r1)), with: .color(AD.green.opacity(0.25 * (1 - pop))))
                        gc.fill(Path(ellipseIn: CGRect(x: b.x - 6, y: b.y - 6, width: 12, height: 12)), with: .color(AD.green))
                        gc.stroke(Path(ellipseIn: CGRect(x: b.x - 6, y: b.y - 6, width: 12, height: 12)), with: .color(.white), lineWidth: 1.5)
                    } else {
                        gc.fill(Path(ellipseIn: CGRect(x: b.x - 4.5, y: b.y - 4.5, width: 9, height: 9)), with: .color(.white.opacity(0.85)))
                        gc.stroke(Path(ellipseIn: CGRect(x: b.x - 4.5, y: b.y - 4.5, width: 9, height: 9)), with: .color(AD.gray), lineWidth: 1.5)
                    }
                }
            }
            .overlay {
                // 이름 칩 — 도착하면 떠오른다. 이웃한 병원과 겹치지 않게 번갈아 위·아래에 둔다
                ZStack {
                    ForEach(Array(targets.enumerated()), id: \.element.id) { i, target in
                        let pop = DeliveryTimeline.popProgress(i, t, reduce: show.reduceMotion)
                        if pop >= 0, let b = project(target.coordinate) {
                            let grow = easeOutCubic(min(pop * 1.6, 1))
                            (Text("✓ ").foregroundColor(AD.green) + Text(target.name).foregroundColor(AD.navy))
                                .font(.system(size: 12, weight: .bold)).lineLimit(1).frame(maxWidth: 150)
                                .padding(.horizontal, 8).padding(.vertical, 4)
                                .background(Capsule().fill(.white.opacity(0.96)))
                                .overlay(Capsule().stroke(AD.green, lineWidth: 1.5))
                                .scaleEffect(0.7 + 0.3 * grow).opacity(grow)
                                .position(x: b.x, y: i % 2 == 0 ? b.y - 24 : b.y + 24)
                        }
                    }
                }
            }
            .overlay(alignment: .bottom) {
                let arrived = DeliveryTimeline.arrivedCount(targets.count, t, reduce: show.reduceMotion)
                let done = arrived >= targets.count
                VStack(spacing: 2) {
                    HStack(spacing: 8) {
                        Image(systemName: done ? "checkmark.circle.fill" : "paperplane.fill").foregroundStyle(done ? AD.green : AD.blue)
                        Text(done ? "후보 병원에 전달됐습니다" : "후보 병원 \(arrived)곳에 전달 중…")
                            .font(.system(size: 16, weight: .bold)).foregroundStyle(AD.navy)
                    }
                    Text("화면을 누르면 건너뜁니다").font(.system(size: 11)).foregroundStyle(AD.muted)
                }
                .padding(.horizontal, 18).padding(.vertical, 10).background(.white.opacity(0.95), in: Capsule()).padding(.bottom, 18)
            }
            .onChange(of: t >= show.durationMs) { _, over in if over { onSkip() } }
        }
        .onAppear { if show.startedAt == nil { show.startedAt = Date() } }
        .contentShape(Rectangle())
        .onTapGesture(perform: onSkip)
    }
}
