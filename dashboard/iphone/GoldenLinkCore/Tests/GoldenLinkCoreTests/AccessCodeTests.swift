import XCTest
@testable import GoldenLinkCore

final class AccessCodeTests: XCTestCase {
    func testRoleComesFromCode() throws {
        let ambulance = try XCTUnwrap(AccessCode(" a-sel0111 \n"))
        XCTAssertEqual(ambulance.role, "ambulance")
        XCTAssertEqual(ambulance.normalized, "P-SEL0111")
        let hospital = try XCTUnwrap(AccessCode(" h-a1100017 "))
        XCTAssertEqual(hospital.role, "hospital")
        XCTAssertEqual(hospital.id, "A1100017")
        for code in ["H-", "P-AUTO", "H-../abc", "H-병원", "SEL0111", "P-SEL 0111"] {
            XCTAssertNil(AccessCode(code), code)
        }
    }

    func testHospitalAdvertisesCallCapabilityAndAnswers() throws {
        func object<T: Encodable>(_ value: T) throws -> [String: Any] {
            try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(value)) as? [String: Any])
        }
        let hospital = try object(IdentifyMessage(role: "hospital", id: "A1100017", callCapable: true))
        XCTAssertEqual(hospital["callCapable"] as? Bool, true)
        XCTAssertNil(try object(IdentifyMessage(role: "monitor", id: "map"))["callCapable"])
        XCTAssertEqual(try object(CallAcceptMessage(callId: "c1", deviceId: "d1"))["type"] as? String, "call_accept")
        XCTAssertEqual(try object(CallRejectMessage(callId: "c1"))["type"] as? String, "call_reject")
        XCTAssertEqual(try object(CallStateSyncMessage(callId: "c1"))["callId"] as? String, "c1")
        let incoming = try JSONDecoder().decode(CallIncoming.self, from: Data(#"{"type":"call_incoming","callId":"c1","caseId":"case1","hospitalId":"A1100017","ambulanceName":"구급 1","iceServers":[{"urls":["stun:test"]}]}"#.utf8))
        XCTAssertEqual(incoming.hospitalId, "A1100017")
        XCTAssertEqual(incoming.iceServers.count, 1)
    }
}
