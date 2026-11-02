package xyz.goldenlink.core

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class RoadRouteTest {
    private val path = listOf(listOf(37.0, 127.0), listOf(37.0, 127.1), listOf(37.0, 127.2), listOf(37.1, 127.2))

    @Test
    fun dropsPassedSegments() {
        val r = RoadRoute.remaining(path, 37.0, 127.12)
        assertEquals(listOf(37.0, 127.12), r.first())
        assertEquals(listOf(37.1, 127.2), r.last())
        assertEquals(3, r.size)            // 현재 위치 + 남은 두 꼭짓점
    }

    @Test
    fun emptyWhenNoPath() {
        assertTrue(RoadRoute.remaining(emptyList(), 37.0, 127.0).isEmpty())
        assertTrue(RoadRoute.remaining(listOf(listOf(37.0, 127.0)), 37.0, 127.0).isEmpty())
    }

    // 북쪽으로 1km 간 뒤 동쪽(오른쪽)으로 꺾는 길 — 위도 0.009° ≈ 1km
    private val rightTurn = listOf(listOf(37.0, 127.0), listOf(37.0045, 127.0), listOf(37.009, 127.0), listOf(37.009, 127.0112), listOf(37.009, 127.0224))

    @Test
    fun routePathBearingAndPoint() {
        val path = RoutePath(rightTurn)
        assertEquals(0.0, path.bearingAt(0.0, 60.0)!!, 1.0)                               // 북쪽
        assertEquals(90.0, path.bearingAt(1100.0, 60.0)!!, 1.0)                           // 꺾인 뒤 동쪽
        val east = RoutePath(listOf(listOf(37.0, 127.0), listOf(37.0, 127.01)))
        assertEquals(90.0, east.bearingAt(0.0, 60.0)!!, 1.0)
        val mid = path.pointAt(500.0)!!                                                   // 북쪽으로 500m — 위도 약 0.0045°
        assertEquals(37.0045, mid.first, 0.0003)
        assertEquals(127.0, mid.second, 0.00001)
        assertEquals(2986.0, path.lengthM, 60.0)
        assertEquals(37.009, path.pointAt(1e9)!!.first, 0.01)                             // 범위 밖은 끝에 붙는다
        assertTrue(RoutePath(listOf(listOf(37.0, 127.0))).pointAt(10.0) == null)
        assertNull(RoutePath(emptyList()).bearingAt(0.0, 60.0))
    }

    @Test
    fun findsNextTurnWithSideAndDistance() {
        val t = RoadRoute.nextTurn(rightTurn)!!
        assertEquals(1000.0, t.distanceM, 40.0)
        assertTrue(t.angleDeg in 70.0..110.0)                                             // 오른쪽 약 90°
        val left = listOf(listOf(37.0, 127.0), listOf(37.009, 127.0), listOf(37.009, 126.9888))
        assertTrue(RoadRoute.nextTurn(left)!!.angleDeg in -110.0..-70.0)                  // 왼쪽
    }

    @Test
    fun noTurnOnStraightRoad() {
        assertNull(RoadRoute.nextTurn(listOf(listOf(37.0, 127.0), listOf(37.0, 127.02), listOf(37.0001, 127.04))))
    }

    @Test
    fun lengthIsSumOfSegments() {
        assertEquals(1000.0, RoadRoute.lengthM(listOf(listOf(37.0, 127.0), listOf(37.009, 127.0))), 20.0)
    }
}
