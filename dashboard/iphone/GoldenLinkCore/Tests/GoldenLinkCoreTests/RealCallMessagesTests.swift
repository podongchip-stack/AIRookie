import XCTest
@testable import GoldenLinkCore

/// 실제 통화(WebRTC) 메시지 모양(2026-11-04) — hub/call_sessions.py와 같아야 hub가 받아들이고, hub 메시지를 앱이 읽는다.
/// 안드로이드 RealCallMessagesTest.kt와 같은 항목이다.
final class RealCallMessagesTests: XCTestCase {
    private func object<T: Encodable>(_ value: T) throws -> [String: Any] {
        let data = try JSONEncoder().encode(value)
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    func testInviteAndSdpShapes() throws {
        let invite = try object(CallInviteMessage(callId: "call-1", caseId: "case-1", hospitalId: "A1100017", deviceId: "dev-1"))
        XCTAssertEqual(invite["type"] as? String, "call_invite")
        XCTAssertEqual(invite["callId"] as? String, "call-1")
        XCTAssertEqual(invite["hospitalId"] as? String, "A1100017")
        let offer = try object(RtcSdpMessage(type: "rtc_offer", callId: "call-1", sdp: "v=0"))
        XCTAssertEqual(offer["type"] as? String, "rtc_offer")
        XCTAssertEqual(offer["negotiationRevision"] as? Int, 1)
        XCTAssertEqual(try object(CallHangupMessage(callId: "c"))["type"] as? String, "call_hangup")
        XCTAssertEqual(try object(MediaReadyMessage(callId: "c"))["type"] as? String, "media_ready")
    }

    func testIceCandidateIsSentAsObject() throws {
        let json = try object(RtcIceMessage(callId: "call-1", candidate: IceCandidatePayload(sdpMid: "0", sdpMLineIndex: 0, candidate: "candidate:1 1 udp 1 10.0.0.1 5000 typ host")))
        XCTAssertEqual(json["type"] as? String, "rtc_ice")
        let candidate = try XCTUnwrap(json["candidate"] as? [String: Any])
        XCTAssertEqual(candidate["sdpMid"] as? String, "0")
        XCTAssertEqual(candidate["sdpMLineIndex"] as? Int, 0)
    }

    func testHubMessagesAreReadWithUnknownFieldsIgnored() throws {
        let state = try JSONDecoder().decode(CallState.self, from: Data("""
        {"type":"call_state","callId":"c1","state":"connecting","sessionRevision":2,
         "iceServers":[{"urls":["stun:x"]},{"urls":["turn:y"],"username":"u","credential":"p"}],"mediaReady":{"caller":false},"extra":1}
        """.utf8))
        XCTAssertEqual(state.state, "connecting")
        XCTAssertEqual(state.iceServers?.count, 2)
        XCTAssertEqual(state.iceServers?[1].username, "u")
        XCTAssertNil(state.reason)
        let ice = try JSONDecoder().decode(RtcIceIn.self, from: Data(
            #"{"type":"rtc_ice","callId":"c1","negotiationRevision":1,"candidate":{"sdpMid":"0","sdpMLineIndex":0,"candidate":"x"}}"#.utf8))
        XCTAssertEqual(ice.candidate.sdpMid, "0")
        let answer = try JSONDecoder().decode(RtcSdpIn.self, from: Data(#"{"type":"rtc_answer","callId":"c1","sdp":"v=0","negotiationRevision":1}"#.utf8))
        XCTAssertEqual(answer.sdp, "v=0")
    }

    func testEndTextsAreFromThisDevicesPointOfView() {
        XCTAssertEqual(CallLabels.endText("remote_hangup"), "상대가 통화를 종료했습니다")
        XCTAssertEqual(CallLabels.endText("local_hangup"), "통화를 종료했습니다")
        XCTAssertEqual(CallLabels.endText("refused", detail: "paused"), "현재 시연 일시정지 중입니다.")
        XCTAssertEqual(CallLabels.endText("refused", detail: "알 수 없는 이유"), "통화를 시작할 수 없습니다")
        XCTAssertEqual(CallLabels.endText(nil), "통화가 종료됐습니다")
    }
}
