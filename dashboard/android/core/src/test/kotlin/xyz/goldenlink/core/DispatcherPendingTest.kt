package xyz.goldenlink.core

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

/** 관제 판단 대기(2026-11-04) 메시지 — hub app.py의 dispatcher_pending·dispatcher_notice 모양과 같아야 앱이 읽는다 */
class DispatcherPendingTest {
    @Test fun pendingDecodes() {
        val m = hubJson.decodeFromString(DispatcherPending.serializer(),
            """{"type":"dispatcher_pending","caseId":"case-1","pending":true,"hospitalId":"A1100017","hospitalName":"서울대학교병원"}""")
        assertTrue(m.pending)
        assertEquals("서울대학교병원", m.hospitalName)
    }

    @Test fun releaseHasNullHospital() {
        val m = hubJson.decodeFromString(DispatcherPending.serializer(),
            """{"type":"dispatcher_pending","caseId":"case-1","pending":false,"hospitalId":null,"hospitalName":null}""")
        assertFalse(m.pending)
        assertNull(m.hospitalName)
    }

    @Test fun noticeDecodes() {
        val n = hubJson.decodeFromString(DispatcherNotice.serializer(),
            """{"type":"dispatcher_notice","caseId":"case-1","kind":"transport_confirmed","hospitalId":"A1100052","hospitalName":"국립중앙의료원","timestamp":"2026-11-04T00:00:00Z"}""")
        assertEquals("transport_confirmed", n.kind)
        assertEquals("국립중앙의료원", n.hospitalName)
    }
}
