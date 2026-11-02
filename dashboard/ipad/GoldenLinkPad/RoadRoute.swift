import Foundation

/// hub 도로 경로에서 현재 위치 이후 구간을 구한다. 지도 재진입 시 지나온 경로로 되돌아가지 않는다.
enum RoadRoute {
    /// position은 경로를 생략한다. 같은 이동 구간에서만 직전 도로 좌표를 유지한다.
    static func retainedPath(_ incoming: [[Double]]?, previous: [[Double]]?,
                                    sameLeg: Bool, positionOnly: Bool) -> [[Double]]? {
        if let incoming { return incoming }
        return sameLeg && positionOnly ? previous : nil
    }

    static func remaining(_ path: [[Double]], latitude: Double, longitude: Double) -> [[Double]] {
        func valid(_ p: [Double]) -> Bool {
            p.count == 2 && p[0].isFinite && p[1].isFinite && (-90...90).contains(p[0]) && (-180...180).contains(p[1])
        }
        let position = [latitude, longitude]
        let points = path.filter(valid)
        guard valid(position), points.count > 1 else { return [] }
        let longitudeScale = cos(latitude * .pi / 180)
        var nearest = 0
        var nearestDistance = Double.infinity
        for i in 0..<(points.count - 1) {
            let a = points[i], b = points[i + 1]
            let dx = (b[1] - a[1]) * longitudeScale, dy = b[0] - a[0]
            let px = (longitude - a[1]) * longitudeScale, py = latitude - a[0]
            let length = dx * dx + dy * dy
            let t = length > 0 ? max(0, min(1, (px * dx + py * dy) / length)) : 0
            let distance = pow(px - t * dx, 2) + pow(py - t * dy, 2)
            if distance < nearestDistance { nearestDistance = distance; nearest = i }
        }
        var result = [position]
        for point in points.dropFirst(nearest + 1) where point != result.last { result.append(point) }
        return result
    }
}
