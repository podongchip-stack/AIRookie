package xyz.goldenlink.core

import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.Json
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

/** 첫 통화 판단(2026-11-04) 메시지 모양 — hub/schema.py의 CallSignal·CallDecision과 같아야 hub가 받아들인다 */
class CallDecisionTest {
    private fun encode(message: CallSignalMessage) =
        Json.parseToJsonElement(hubJson.encodeToString(CallSignalMessage.serializer(), message)).jsonObject

    @Test fun firstCallEndCarriesAwaitDecision() {
        val json = encode(CallSignalMessage("call_ended", "SEL0001", "case-1", "H1", awaitDecision = true))
        assertEquals("call_signal", json["type"]!!.jsonPrimitive.content)
        assertEquals("call_ended", json["signal"]!!.jsonPrimitive.content)
        assertEquals("true", json["awaitDecision"]!!.jsonPrimitive.content)
    }

    @Test fun followUpCallEndDoesNotAwaitDecision() {
        // 추가 통화는 기존대로 바로 반영 — 필드를 아예 보내지 않는다(explicitNulls = false)
        val json = encode(CallSignalMessage("call_ended", "SEL0001", "case-1", "H1"))
        assertFalse(json.containsKey("awaitDecision"))
    }

    @Test fun decisionMessageShape() {
        val json = Json.parseToJsonElement(
            hubJson.encodeToString(CallDecisionMessage.serializer(), CallDecisionMessage("case-1", "confirm"))
        ).jsonObject
        assertEquals("call_decision", json["type"]!!.jsonPrimitive.content)
        assertEquals("case-1", json["caseId"]!!.jsonPrimitive.content)
        assertEquals("confirm", json["decision"]!!.jsonPrimitive.content)
        assertTrue(json["timestamp"]!!.jsonPrimitive.content.isNotBlank())
    }

    @Test fun autoDecisionFromHub() {
        // hub app._announce_auto_decision이 보내는 모양 그대로(type·source는 앱이 쓰지 않는 필드)
        val d = hubJson.decodeFromString(CallDecisionAuto.serializer(),
            """{"type":"call_decision_auto","caseId":"case-1","decision":"confirm","callOutcome":"수용","hospitalId":"H1","hospitalName":"강북삼성병원","source":"ai"}""")
        assertEquals("case-1", d.caseId)
        assertEquals("confirm", d.decision)
        assertEquals("수용", d.callOutcome)
        assertEquals("강북삼성병원", d.hospitalName)
    }
}
