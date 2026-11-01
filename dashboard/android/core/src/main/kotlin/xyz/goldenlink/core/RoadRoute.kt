package xyz.goldenlink.core

import kotlin.math.PI
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
}
