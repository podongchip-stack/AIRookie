package xyz.goldenlink.core

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.hypot
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min

/** hub 도로 경로에서 현재 위치 이후 구간을 구한다. 지도를 다시 열어도 지나온 경로로 되돌아가지 않는다(iPhone RoadRoute와 같은 계산). */
object RoadRoute {
    private fun valid(p: List<Double>) = p.size == 2 && p[0].isFinite() && p[1].isFinite() && p[0] in -90.0..90.0 && p[1] in -180.0..180.0

    fun remaining(path: List<List<Double>>, latitude: Double, longitude: Double): List<List<Double>> {
        val position = listOf(latitude, longitude)
        val points = path.filter(::valid)
        if (!valid(position) || points.size < 2) return emptyList()
        val lonScale = cos(latitude * PI / 180)
        var nearest = 0
        var best = Double.POSITIVE_INFINITY
        for (i in 0 until points.size - 1) {
            val a = points[i]; val b = points[i + 1]
            val dx = (b[1] - a[1]) * lonScale; val dy = b[0] - a[0]
            val px = (longitude - a[1]) * lonScale; val py = latitude - a[0]
            val len = dx * dx + dy * dy
            val t = if (len > 0) max(0.0, min(1.0, (px * dx + py * dy) / len)) else 0.0
            val d = Math.pow(px - t * dx, 2.0) + Math.pow(py - t * dy, 2.0)
            if (d < best) { best = d; nearest = i }
        }
        val result = mutableListOf(position)
        for (p in points.drop(nearest + 1)) if (p != result.last()) result += p
        return result
    }

    // ── 내비게이션 안내 ──

    /** 다음 회전 — 지금 위치에서 distanceM 앞, angleDeg는 오른쪽이 +·왼쪽이 −(진행 방향이 꺾이는 각) */
    data class Turn(val distanceM: Double, val angleDeg: Double)

    /** 위도·경도를 첫 점 기준 평면 미터로 바꾼다(도시 규모에서 충분히 정확). x=동, y=북 */
    internal fun toMeters(points: List<List<Double>>): List<DoubleArray> {
        if (points.isEmpty()) return emptyList()
        val lat0 = points[0][0]; val lng0 = points[0][1]
        val kx = 111_320.0 * cos(lat0 * PI / 180)
        return points.map { doubleArrayOf((it[1] - lng0) * kx, (it[0] - lat0) * 110_540.0) }
    }

    internal fun bearing(a: DoubleArray, b: DoubleArray): Double = (Math.toDegrees(atan2(b[0] - a[0], b[1] - a[1])) + 360.0) % 360.0

    /** 두 방위의 차(−180..180, 오른쪽이 +) */
    private fun angleDiff(from: Double, to: Double): Double = ((to - from + 540.0) % 360.0) - 180.0

    /** 경로를 step 미터 간격으로 다시 찍는다 — 점 간격이 들쭉날쭉해도 같은 기준으로 꺾임을 잰다. maxM까지만 */
    private fun resample(m: List<DoubleArray>, step: Double, maxM: Double): List<DoubleArray> {
        if (m.size < 2) return m
        val out = mutableListOf(m[0])
        var carry = 0.0   // 마지막으로 찍은 점에서 현재 선분 시작까지 남은 거리
        var total = 0.0
        for (i in 0 until m.size - 1) {
            val a = m[i]; val b = m[i + 1]
            val len = hypot(b[0] - a[0], b[1] - a[1])
            if (len == 0.0) continue
            var d = step - carry
            while (d <= len) {
                out += doubleArrayOf(a[0] + (b[0] - a[0]) * d / len, a[1] + (b[1] - a[1]) * d / len)
                total += step
                if (total >= maxM) return out
                d += step
            }
            carry = len - (d - step)
        }
        out += m.last()
        return out
    }

    /** 남은 경로의 총 길이(m) */
    fun lengthM(rest: List<List<Double>>): Double {
        val m = toMeters(rest.filter(::valid))
        var sum = 0.0
        for (i in 0 until m.size - 1) sum += hypot(m[i + 1][0] - m[i][0], m[i + 1][1] - m[i][1])
        return sum
    }

    /** 앞으로 3km 안의 첫 회전 — 30m 앞뒤 방향 차가 minAngleDeg 이상인 곳. 없으면 null */
    fun nextTurn(rest: List<List<Double>>, minAngleDeg: Double = 35.0): Turn? {
        val step = 10.0
        val p = resample(toMeters(rest.filter(::valid)), step, 3000.0)
        val k = 3
        var i = k
        while (i < p.size - k) {
            val delta = angleDiff(bearing(p[i - k], p[i]), bearing(p[i], p[i + k]))
            if (abs(delta) >= minAngleDeg) {
                // 같은 회전의 꼭짓점이 연달아 잡히므로 각이 가장 큰 점을 회전 지점으로 삼는다
                var best = i; var bestDelta = delta
                var j = i + 1
                while (j < p.size - k && j <= i + k) {
                    val dj = angleDiff(bearing(p[j - k], p[j]), bearing(p[j], p[j + k]))
                    if (abs(dj) > abs(bestDelta)) { best = j; bestDelta = dj }
                    j++
                }
                return Turn(best * step, bestDelta)
            }
            i++
        }
        return null
    }
}

/**
 * 경로 위의 거리로 위치·방위를 구한다 — 내비게이션 카메라가 구급차를 1초마다 오는 위치가 아니라 경로를 따라 일정한 속도로 움직이게 하려고 쓴다.
 * points는 [[위도, 경도], ...]. 유효하지 않은 점은 버린다.
 */
class RoutePath(points: List<List<Double>>) {
    private val latLng = points.filter { it.size == 2 && it[0].isFinite() && it[1].isFinite() }
    private val xy = RoadRoute.toMeters(latLng)
    private val cum = DoubleArray(xy.size).also { c -> for (i in 1 until xy.size) c[i] = c[i - 1] + Math.hypot(xy[i][0] - xy[i - 1][0], xy[i][1] - xy[i - 1][1]) }

    val isEmpty: Boolean get() = latLng.size < 2
    val lengthM: Double get() = if (cum.isEmpty()) 0.0 else cum.last()

    /** 출발점에서 d미터 간 곳의 (위도, 경도) — 범위 밖이면 양 끝에 붙인다. 경로가 비었으면 null */
    fun pointAt(d: Double): Pair<Double, Double>? {
        if (isEmpty) return null
        val x = d.coerceIn(0.0, lengthM)
        var lo = 0; var hi = cum.size - 1
        while (hi - lo > 1) { val mid = (lo + hi) / 2; if (cum[mid] <= x) lo = mid else hi = mid }
        val seg = cum[hi] - cum[lo]
        val t = if (seg > 0) (x - cum[lo]) / seg else 0.0
        return (latLng[lo][0] + (latLng[hi][0] - latLng[lo][0]) * t) to (latLng[lo][1] + (latLng[hi][1] - latLng[lo][1]) * t)
    }

    /** d미터 지점에서 aheadM 앞을 향한 방위(북 0, 시계방향). 경로가 비었거나 끝에 닿아 방향이 없으면 null */
    fun bearingAt(d: Double, aheadM: Double): Double? {
        if (isEmpty) return null
        // 끝 근처에서는 마지막 구간의 방향을 쓴다
        val from = minOf(d, maxOf(0.0, lengthM - aheadM))
        val a = pointAt(from) ?: return null
        val b = pointAt(from + aheadM) ?: return null
        val kx = 111_320.0 * Math.cos(Math.toRadians(a.first))
        val dx = (b.second - a.second) * kx; val dy = (b.first - a.first) * 110_540.0
        if (Math.hypot(dx, dy) < 0.5) return null
        return (Math.toDegrees(Math.atan2(dx, dy)) + 360.0) % 360.0
    }
}
