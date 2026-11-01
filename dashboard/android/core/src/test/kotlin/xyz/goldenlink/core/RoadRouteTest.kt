package xyz.goldenlink.core

import org.junit.jupiter.api.Assertions.assertEquals
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
}
