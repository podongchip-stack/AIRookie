import XCTest
@testable import GoldenLinkCore

/// 관제 판단 대기(2026-11-04) 메시지 — hub app.py의 dispatcher_pending·dispatcher_notice 모양과 같아야 앱이 읽는다
final class DispatcherPendingTests: XCTestCase {
    func testPendingDecodes() throws {
        let json = #"{"type":"dispatcher_pending","caseId":"case-1","pending":true,"hospitalId":"A1100017","hospitalName":"서울대학교병원"}"#
        let m = try JSONDecoder().decode(DispatcherPending.self, from: Data(json.utf8))
        XCTAssertTrue(m.pending)
        XCTAssertEqual(m.hospitalName, "서울대학교병원")
    }

    func testReleaseHasNullHospital() throws {
        let json = #"{"type":"dispatcher_pending","caseId":"case-1","pending":false,"hospitalId":null,"hospitalName":null}"#
        let m = try JSONDecoder().decode(DispatcherPending.self, from: Data(json.utf8))
        XCTAssertFalse(m.pending)
        XCTAssertNil(m.hospitalName)
    }

    func testNoticeDecodes() throws {
        let json = #"{"type":"dispatcher_notice","caseId":"case-1","kind":"transport_confirmed","hospitalId":"A1100052","hospitalName":"국립중앙의료원","timestamp":"2026-11-04T00:00:00Z"}"#
        let n = try JSONDecoder().decode(DispatcherNotice.self, from: Data(json.utf8))
        XCTAssertEqual(n.kind, "transport_confirmed")
        XCTAssertEqual(n.hospitalName, "국립중앙의료원")
    }
}
