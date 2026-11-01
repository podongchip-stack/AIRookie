package xyz.goldenlink.phone

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import xyz.goldenlink.phone.ui.DeliveryTimeline

/** 요약 전달 연출의 시간 배치 — 전부 연출 시간(2.6초) 안에 도착하고, 거의 동시에 출발한다 */
class DeliveryTimelineTest {
    private val n = DeliveryTimeline.MAX_TARGETS

    @Test
    fun everyHospitalArrivesWithinTheShow() {
        assertEquals(0, DeliveryTimeline.arrivedCount(n, 0, false))
        assertEquals(n, DeliveryTimeline.arrivedCount(n, 2_600, false))
        assertTrue(DeliveryTimeline.pop(n - 1, 2_600, false) >= 0f)   // 마지막 병원도 도착해 커졌다 돌아오는 중이거나 끝난 뒤
    }

    @Test
    fun hospitalsStartAlmostTogether() {
        // 마지막 병원이 출발하는 순간에도 첫 병원은 아직 날아가는 중이어야 순차가 아니라 동시로 보인다
        val lastStart = 650L + 90L * (n - 1)
        assertEquals(0f, DeliveryTimeline.flight(n - 1, lastStart, false))
        assertTrue(DeliveryTimeline.flight(0, lastStart, false) in 0.5f..0.99f)
        assertTrue(DeliveryTimeline.flight(n - 1, lastStart + 100, false) > 0f)
    }

    @Test
    fun reducedMotionShowsEveryoneAtOnce() {
        assertEquals(n, DeliveryTimeline.arrivedCount(n, 0, true))
        assertEquals(1f, DeliveryTimeline.flight(3, 0, true))
    }
}
