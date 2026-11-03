import XCTest
@testable import GoldenLinkCore

final class SceneZoneTests: XCTestCase {
    func testBeforeCallScenePreservesExpandedZone() throws {
        let data = Data(#"{"caseId":"case","apid":"A","hospitals":[],"zoneActive":[1,2]}"#.utf8)
        let scene = try JSONDecoder().decode(SceneCandidates.self, from: data)
        XCTAssertEqual(scene.zoneActive, [1, 2])
    }

    func testOlderSceneWithoutZoneRemainsDecodable() throws {
        let data = Data(#"{"caseId":"case","apid":"A","hospitals":[]}"#.utf8)
        let scene = try JSONDecoder().decode(SceneCandidates.self, from: data)
        XCTAssertNil(scene.zoneActive)
    }
}
