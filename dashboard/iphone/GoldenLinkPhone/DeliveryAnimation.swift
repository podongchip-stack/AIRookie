import GoldenLinkCore
import SwiftUI

// 통화 요약이 후보 병원들에 전달되는 모습 — 안드로이드 DeliveryAnimation.kt와 같은 시간표다. 구급차에서 병원마다 곡선이 거의 동시에
// 그려지고, 도착한 병원에 ✓ 이름표가 뜬다. 순차 전화가 아니라 존 안 병원에 동시에 전달한다는 서비스 방식을 보여 주는 연출이다.
// 선은 화면 위에 따로 그리지 않고 지도 안의 도형으로 그린다(CallMapView) — 확대·이동에도 병원 위치에 붙어 있다.
// 병원이 많으면 앞의 8곳만 그리고 숫자는 전체를 센다.

/// 전달 연출에 그릴 병원
struct DeliveryTarget: Equatable {
    let id: String
    let name: String
    let gps: GPS
}

/// 지도가 받는 연출 입력
struct DeliveryInput: Equatable {
    let caseId: String
    let from: GPS
    let targets: [DeliveryTarget]
    let durationMs: Int
    let reduceMotion: Bool
}

enum DeliveryTimeline {
    static let maxTargets = 8
    private static let delayMs = 650     // 카메라가 구급차를 가운데로 옮기는 동안
    private static let staggerMs = 90    // 병원마다 출발 간격 — 거의 동시로 보이게 짧게
    private static let flightMs = 800    // 선이 구급차에서 병원까지 그려지는 시간
    private static let popMs = 350       // 도착한 병원의 이름표가 떠오르는 시간

    /// 선이 그려진 정도 0→1
    static func flight(_ i: Int, t: Int, reduce: Bool) -> Double {
        reduce ? 1 : min(1, max(0, Double(t - delayMs - staggerMs * i) / Double(flightMs)))
    }

    private static func arrivedAt(_ i: Int, reduce: Bool) -> Int { reduce ? 0 : delayMs + staggerMs * i + flightMs }

    /// 도착 뒤 0→1, 도착 전에는 -1
    static func pop(_ i: Int, t: Int, reduce: Bool) -> Double {
        let at = arrivedAt(i, reduce: reduce)
        return t < at ? -1 : min(1, Double(t - at) / Double(popMs))
    }

    static func arrivedCount(_ n: Int, t: Int, reduce: Bool) -> Int {
        (0..<n).filter { t >= arrivedAt($0, reduce: reduce) }.count
    }
}

/// 연출 중 아래 카드 — 도착한 병원 수가 올라가고, 모두 도착하면 전체 수로 바뀐다
struct DeliveryCardView: View {
    let show: PhoneModel.DeliveryShow
    let shown: Int
    let total: Int

    var body: some View {
        TimelineView(.animation) { context in
            let t = show.readyAt.map { Int(context.date.timeIntervalSince($0) * 1000) } ?? 0
            let arrived = DeliveryTimeline.arrivedCount(shown, t: t, reduce: show.reduceMotion)
            let done = arrived >= shown
            let count = done ? total : arrived
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 10) {
                    Image(systemName: done ? "checkmark.circle.fill" : "paperplane.fill")
                        .foregroundStyle(done ? AD.green : AD.blue).font(.system(size: 22))
                    Text(done ? "후보 병원 \(count)곳에 전달됐습니다" : "후보 병원 \(count)곳에 전달 중…")
                        .font(.system(size: 16, weight: .bold)).foregroundStyle(AD.navy)
                }
                Text("화면을 누르면 건너뜁니다").font(.system(size: 11)).foregroundStyle(AD.muted)
            }
        }
    }
}
