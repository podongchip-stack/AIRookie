import Foundation

// Android RoadRoute/RoutePath와 같은 규칙 기반 경로 계산. 의료 판단·병원 순위에는 사용하지 않는다.
extension RoadRoute {
    public struct Turn: Equatable { public let distanceM: Double; public let angleDeg: Double }
    static func validPoint(_ p: [Double]) -> Bool {
        p.count == 2 && p.allSatisfy(\.isFinite) && (-90...90).contains(p[0]) && (-180...180).contains(p[1])
    }
    static func meters(_ points: [[Double]]) -> [[Double]] {
        guard let a = points.first else { return [] }
        return points.map { [($0[1] - a[1]) * 111_320 * cos(a[0] * .pi / 180), ($0[0] - a[0]) * 110_540] }
    }
    static func bearing(_ a: [Double], _ b: [Double]) -> Double {
        (atan2(b[0] - a[0], b[1] - a[1]) * 180 / .pi + 360).truncatingRemainder(dividingBy: 360)
    }
    public static func angleDifference(_ from: Double, _ to: Double) -> Double {
        (to - from + 540).truncatingRemainder(dividingBy: 360) - 180
    }
    public static func lengthM(_ rest: [[Double]]) -> Double { RoutePath(rest).lengthM }
    public static func nextTurn(_ rest: [[Double]], minAngleDeg: Double = 35) -> Turn? {
        let m = meters(rest.filter(validPoint))
        guard m.count > 1 else { return nil }
        var p = [m[0]], carry = 0.0, total = 0.0
        outer: for i in 0..<(m.count - 1) {
            let a = m[i], b = m[i + 1], len = hypot(b[0] - a[0], b[1] - a[1])
            guard len > 0 else { continue }
            var d = 10 - carry
            while d <= len {
                p.append([a[0] + (b[0] - a[0]) * d / len, a[1] + (b[1] - a[1]) * d / len])
                total += 10
                if total >= 3000 { break outer }
                d += 10
            }
            carry = len - (d - 10)
        }
        if total < 3000 { p.append(m.last!) }
        guard p.count > 6 else { return nil }
        func delta(_ i: Int) -> Double { angleDifference(bearing(p[i - 3], p[i]), bearing(p[i], p[i + 3])) }
        for i in 3..<(p.count - 3) where abs(delta(i)) >= minAngleDeg {
            var best = i, angle = delta(i)
            for j in (i + 1)..<min(p.count - 3, i + 4) where abs(delta(j)) > abs(angle) { best = j; angle = delta(j) }
            return Turn(distanceM: Double(best) * 10, angleDeg: angle)
        }
        return nil
    }
}

public struct RoutePath {
    private let points: [[Double]]
    private let cumulative: [Double]
    public var isEmpty: Bool { points.count < 2 }
    public var lengthM: Double { cumulative.last ?? 0 }
    public init(_ path: [[Double]]) {
        points = path.filter(RoadRoute.validPoint)
        let xy = RoadRoute.meters(points)
        var c = xy.isEmpty ? [] : [0.0]
        if xy.count > 1 {
            for i in 1..<xy.count { c.append(c[i - 1] + hypot(xy[i][0] - xy[i - 1][0], xy[i][1] - xy[i - 1][1])) }
        }
        cumulative = c
    }
    public func pointAt(_ distance: Double) -> [Double]? {
        guard !isEmpty, distance.isFinite else { return nil }
        let x = min(max(distance, 0), lengthM)
        var lo = 0, hi = cumulative.count - 1
        while hi - lo > 1 { let mid = (lo + hi) / 2; if cumulative[mid] <= x { lo = mid } else { hi = mid } }
        let len = cumulative[hi] - cumulative[lo], t = len > 0 ? (x - cumulative[lo]) / len : 0
        return [points[lo][0] + (points[hi][0] - points[lo][0]) * t, points[lo][1] + (points[hi][1] - points[lo][1]) * t]
    }
    public func bearingAt(_ distance: Double, aheadM: Double) -> Double? {
        let from = min(distance, max(0, lengthM - aheadM))
        guard let a = pointAt(from), let b = pointAt(from + aheadM) else { return nil }
        let dx = (b[1] - a[1]) * 111_320 * cos(a[0] * .pi / 180), dy = (b[0] - a[0]) * 110_540
        guard hypot(dx, dy) >= 0.5 else { return nil }
        return (atan2(dx, dy) * 180 / .pi + 360).truncatingRemainder(dividingBy: 360)
    }
}

/// 1초마다 받는 GPS 사이를 경로 위에서 추정 주행하고 새 GPS와의 차이는 서서히 보정한다.
public struct NavigationCamera {
    public struct Frame { public let latitude: Double; public let longitude: Double; public let rotation: Double; public let height: Double }
    private var lastTime: Double?, fixTime: Double?, fix: [Double] = [], path = RoutePath([])
    private var lat = 0.0, lng = 0.0, rotation = 0.0, logHeight = log(4645.92), speed = 0.0
    private var offLat = 0.0, offLng = 0.0
    public init() {}
    public mutating func frame(position: [Double], route: [[Double]], speedHint: Double?, time: Double, moving: Bool = true) -> Frame? {
        guard RoadRoute.validPoint(position), time.isFinite else { return nil }
        let dt = min(max(time - (lastTime ?? (time - 0.033)), 0.001), 0.2), first = lastTime == nil
        lastTime = time
        if fix != position || fixTime == nil {
            if let ft = fixTime, time - ft > 0.2 {
                let v = hypot((position[1] - fix[1]) * 111_320 * cos(position[0] * .pi / 180), (position[0] - fix[0]) * 110_540) / (time - ft)
                speed = speed == 0 ? v : 0.6 * speed + 0.4 * v
            }
            offLat = first ? 0 : lat - position[0]; offLng = first ? 0 : lng - position[1]
            fix = position; fixTime = time
            path = RoutePath(RoadRoute.remaining(route, latitude: position[0], longitude: position[1]))
            if speed == 0, let hint = speedHint, hint.isFinite, hint > 0 { speed = hint }
        }
        let distance = moving ? speed * min(max(time - (fixTime ?? time), 0), 1.5) : 0
        let p = path.pointAt(distance) ?? position
        offLat *= exp(-dt / 0.6); offLng *= exp(-dt / 0.6)
        lat = p[0] + offLat; lng = p[1] + offLng
        if let bearing = path.bearingAt(distance, aheadM: 60 + speed * 0.5) {
            let target = (360 - bearing).truncatingRemainder(dividingBy: 360)
            rotation = first ? target : (rotation + RoadRoute.angleDifference(rotation, target) * (1 - exp(-dt / 0.5)) + 360).truncatingRemainder(dividingBy: 360)
        }
        let screen = min(max(speed * 7, 2500), 60_000)
        let target = min(max(log(screen * 4645.92 / 1750), log(4645.92)), log(4645.92 * 64))
        logHeight = first ? target : logHeight + (target - logHeight) * (1 - exp(-dt / 1.2))
        return Frame(latitude: lat, longitude: lng, rotation: rotation, height: exp(logHeight))
    }
}
