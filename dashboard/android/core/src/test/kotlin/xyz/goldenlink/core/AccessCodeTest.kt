package xyz.goldenlink.core

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Test

class AccessCodeTest {
    @Test fun phoneAndTabletCodesShareTheAmbulanceId() {
        assertEquals("SEL0111", AccessCode.ambulanceId("P-SEL0111"))
        assertEquals("SEL0111", AccessCode.ambulanceId("  a-sel0111 "))
    }

    @Test fun autoAndMalformedCodesAreRejected() {
        assertNull(AccessCode.ambulanceId("P-AUTO"))
        assertNull(AccessCode.ambulanceId("auto"))
        assertNull(AccessCode.ambulanceId("SEL0111"))
        assertNull(AccessCode.ambulanceId("P-"))
        assertNull(AccessCode.ambulanceId("P-SEL 0111"))
        assertNull(AccessCode.ambulanceId("P-SEL-0111"))
    }
}
