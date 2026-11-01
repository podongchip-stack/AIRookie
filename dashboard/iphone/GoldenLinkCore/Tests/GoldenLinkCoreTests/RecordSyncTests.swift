import XCTest
@testable import GoldenLinkCore

final class RecordSyncTests: XCTestCase {
    private let legacy = #"{"caseId":"case-old","apid":"SEL0001","date":"2026-11-01","startedAt":1793491200000,"updatedAt":1793491200000,"hospitals":[],"handover":{},"closed":true}"#

    func testOldDeviceRecordsStillDecodeForMigration() throws {
        let record = try JSONDecoder().decode(CaseRecord.self, from: Data(legacy.utf8))
        XCTAssertNil(record.archiveVersion)
        XCTAssertNil(record.events)
        XCTAssertTrue(record.closed)
    }

    func testServerPageKeepsHistorySeparateFromLatestStatus() throws {
        let json = #"{"requestId":"download","apid":"SEL0001","epoch":"server-epoch","cursor":103,"hasMore":false,"records":[{"caseId":"case-old","apid":"SEL0001","date":"2026-11-01","startedAt":1793491200000,"updatedAt":1793491300000,"hospitals":[{"hospitalId":"H","name":"병원","status":"rejected"}],"handover":{"careFix":"부목 고정"},"handoverEdits":{},"handoverRevision":0,"closed":true,"archiveVersion":103,"archiveEpoch":"server-epoch","events":[{"id":"event-1","hospitalId":"H","action":"hospital_approve","actor":"hospital","timestamp":"2026-11-01T00:00:00Z"},{"id":"event-2","hospitalId":"H","action":"hospital_reject","actor":"hospital","timestamp":"2026-11-01T00:01:00Z","reason":"BEDS_FULL"}]}]}"#
        let page = try JSONDecoder().decode(RecordSyncReply.self, from: Data(json.utf8))
        let record = try XCTUnwrap(page.records?.first)
        XCTAssertEqual(record.events?.map(\.action), ["hospital_approve", "hospital_reject"])
        XCTAssertEqual(record.hospitals.first?.status, "rejected")
        XCTAssertEqual(record.handover["careFix"], "부목 고정")
        XCTAssertEqual(record.archiveEpoch, page.epoch)
        XCTAssertEqual(record.archiveVersion, page.cursor)
    }

    func testPendingSaveKeepsIdAcrossOfflineRestart() throws {
        let pending = PendingHandover(caseId: "case-old", revision: 2, edits: ["notes":"수정 내용"])
        let restored = try JSONDecoder().decode(PendingHandover.self, from: JSONEncoder().encode(pending))
        let request = RecordHandoverRequest(pending: restored, token: "test-token")
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(request)) as? [String: Any])
        XCTAssertEqual(body["requestId"] as? String, pending.requestId)
        XCTAssertEqual(body["revision"] as? Int, 2)
    }
}
