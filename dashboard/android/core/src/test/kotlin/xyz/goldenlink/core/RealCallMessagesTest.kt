package xyz.goldenlink.core

import kotlinx.serialization.KSerializer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Test

/** 실제 통화(WebRTC) 메시지 모양(2026-11-04) — hub/call_sessions.py·schema.py와 같아야 hub가 받아들이고, hub 메시지를 앱이 읽는다 */
class RealCallMessagesTest {
    private fun <T> obj(value: T, serializer: KSerializer<T>): JsonObject =
        Json.parseToJsonElement(hubJson.encodeToString(serializer, value)).jsonObject

    @Test fun inviteAndAnswerShapes() {
        val invite = obj(CallInviteMessage("call-1", "case-1", "A1100017", "dev-1"), CallInviteMessage.serializer())
        assertEquals("call_invite", invite["type"]!!.jsonPrimitive.content)
        assertEquals("call-1", invite["callId"]!!.jsonPrimitive.content)
        assertEquals("A1100017", invite["hospitalId"]!!.jsonPrimitive.content)
        val offer = obj(RtcSdpMessage("rtc_offer", "call-1", "v=0"), RtcSdpMessage.serializer())
        assertEquals("rtc_offer", offer["type"]!!.jsonPrimitive.content)
        assertEquals("1", offer["negotiationRevision"]!!.jsonPrimitive.content)
        assertEquals("call_hangup", obj(CallHangupMessage("c"), CallHangupMessage.serializer())["type"]!!.jsonPrimitive.content)
        assertEquals("media_ready", obj(MediaReadyMessage("c"), MediaReadyMessage.serializer())["type"]!!.jsonPrimitive.content)
    }

    @Test fun iceCandidateIsRelayedAsObject() {
        val candidate = buildJsonObject {
            put("sdpMid", JsonPrimitive("0")); put("sdpMLineIndex", JsonPrimitive(0))
            put("candidate", JsonPrimitive("candidate:1 1 udp 1 10.0.0.1 5000 typ host"))
        }
        val json = obj(RtcIceMessage("call-1", candidate), RtcIceMessage.serializer())
        assertEquals("rtc_ice", json["type"]!!.jsonPrimitive.content)
        assertEquals("0", json["candidate"]!!.jsonObject["sdpMid"]!!.jsonPrimitive.content)
    }

    @Test fun syncWithoutCallIdOmitsIt() {
        val json = obj(CallStateSyncMessage(), CallStateSyncMessage.serializer())
        assertFalse(json.containsKey("callId"))
        assertEquals("call_state_sync", json["type"]!!.jsonPrimitive.content)
    }

    @Test fun identifyCarriesCallCapableOnlyForHospitalApp() {
        val hospital = obj(IdentifyMessage("hospital", "A1100017", callCapable = true), IdentifyMessage.serializer())
        assertEquals("true", hospital["callCapable"]!!.jsonPrimitive.content)
        assertFalse(obj(IdentifyMessage("ambulance", "SEL0001"), IdentifyMessage.serializer()).containsKey("callCapable"))
    }

    @Test fun hubMessagesAreReadWithUnknownFieldsIgnored() {
        val state = hubJson.decodeFromString(CallState.serializer(),
            """{"type":"call_state","callId":"c1","state":"connecting","sessionRevision":2,"iceServers":[{"urls":["stun:x"]},{"urls":["turn:y"],"username":"u","credential":"p"}],"mediaReady":{"caller":false},"extra":1}""")
        assertEquals("connecting", state.state)
        assertEquals(2, state.iceServers!!.size)
        assertEquals("u", state.iceServers!![1].username)
        assertNull(state.reason)
        val incoming = hubJson.decodeFromString(CallIncoming.serializer(),
            """{"type":"call_incoming","callId":"c1","caseId":"case","hospitalId":"H","ambulanceName":"구급 1호차","ringingSec":30.0,"iceServers":[]}""")
        assertEquals("구급 1호차", incoming.ambulanceName)
        val ice = hubJson.decodeFromString(RtcIceIn.serializer(),
            """{"type":"rtc_ice","callId":"c1","negotiationRevision":1,"candidate":{"sdpMid":"0","candidate":"x"}}""")
        assertEquals("0", ice.candidate["sdpMid"]!!.jsonPrimitive.content)
    }

    @Test fun hospitalAccessCode() {
        assertEquals("A1100017", AccessCode.hospitalId("H-A1100017"))
        assertEquals("A1100017", AccessCode.hospitalId("  h-a1100017 "))
        assertNull(AccessCode.hospitalId("P-SEL0111"))
        assertNull(AccessCode.hospitalId("H-"))
        assertNull(AccessCode.hospitalId("H-A11 00017"))
        assertNull(AccessCode.ambulanceId("H-A1100017"))
    }

    @Test fun endTextsAreFromThisDevicesPointOfView() {
        assertEquals("상대가 통화를 종료했습니다", CallLabels.endText("remote_hangup"))
        assertEquals("통화를 종료했습니다", CallLabels.endText("local_hangup"))
        assertEquals("현재 시연 일시정지 중입니다.", CallLabels.endText("refused", "paused"))
        assertEquals("통화를 시작할 수 없습니다", CallLabels.endText("refused", "알 수 없는 이유"))
        assertEquals("통화가 종료됐습니다", CallLabels.endText(null))
    }
}
