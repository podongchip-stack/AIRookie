import XCTest
@testable import GoldenLinkCore

/// 첫 통화 판단(2026-11-04) 메시지 모양 — hub/schema.py의 CallSignal·CallDecision과 같아야 hub가 받아들인다
final class CallDecisionTests: XCTestCase {
    private func object<T: Encodable>(_ value: T) throws -> [String: Any] {
        let data = try JSONEncoder().encode(value)
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    func testFirstCallEndCarriesAwaitDecision() throws {
        let json = try object(CallSignalMessage(signal: "call_ended", apid: "SEL0001", caseId: "case-1", hospitalId: "H1", awaitDecision: true))
        XCTAssertEqual(json["type"] as? String, "call_signal")
        XCTAssertEqual(json["signal"] as? String, "call_ended")
        XCTAssertEqual(json["awaitDecision"] as? Bool, true)
    }

    func testFollowUpCallEndDoesNotAwaitDecision() throws {
        // 추가 통화는 기존대로 바로 반영 — 필드를 아예 보내지 않는다
        let json = try object(CallSignalMessage(signal: "call_ended", apid: "SEL0001", caseId: "case-1", hospitalId: "H1"))
        XCTAssertNil(json["awaitDecision"])
    }

    func testDecisionMessageShape() throws {
        let json = try object(CallDecisionMessage(caseId: "case-1", decision: "confirm"))
        XCTAssertEqual(json["type"] as? String, "call_decision")
        XCTAssertEqual(json["caseId"] as? String, "case-1")
        XCTAssertEqual(json["decision"] as? String, "confirm")
        XCTAssertFalse((json["timestamp"] as? String ?? "").isEmpty)
    }

    func testAutoDecisionFromHub() throws {
        // hub app._announce_auto_decision이 보내는 모양 그대로(type·source는 앱이 쓰지 않는 필드)
        let raw = #"{"type":"call_decision_auto","caseId":"case-1","decision":"confirm","callOutcome":"수용","hospitalId":"H1","hospitalName":"강북삼성병원","source":"ai"}"#
        let d = try JSONDecoder().decode(CallDecisionAuto.self, from: Data(raw.utf8))
        XCTAssertEqual(d.caseId, "case-1")
        XCTAssertEqual(d.decision, "confirm")
        XCTAssertEqual(d.callOutcome, "수용")
        XCTAssertEqual(d.hospitalName, "강북삼성병원")
    }
}
