import XCTest
@testable import GoldenLinkCore

final class RoadRouteTests: XCTestCase {
    let route = [[37.5, 127.0], [37.51, 127.0], [37.51, 127.01], [37.52, 127.01]]

    func testPositionMessagesKeepRoadFromPhaseMessage() throws {
        let phase = try JSONDecoder().decode(AmbulanceSim.self, from: Data(#"{"apid":"SEL0111","caseId":"case-1","phase":"dispatching","gps":{"lat":37.5,"lng":127},"path":[[37.5,127],[37.51,127],[37.51,127.01],[37.52,127.01]]}"#.utf8))
        var displayed = phase.path
        for latitude in [37.501, 37.502, 37.503] {
            let data = Data("{\"apid\":\"SEL0111\",\"caseId\":\"case-1\",\"phase\":\"dispatching\",\"gps\":{\"lat\":\(latitude),\"lng\":127}}".utf8)
            let position = try JSONDecoder().decode(AmbulanceSim.self, from: data)
            displayed = RoadRoute.retainedPath(position.path, previous: displayed,
                sameLeg: position.caseId == phase.caseId && position.phase == phase.phase, positionOnly: true)
            XCTAssertEqual(displayed, route)
            XCTAssertEqual(RoadRoute.remaining(displayed ?? [], latitude: latitude, longitude: 127).suffix(3), route.suffix(3))
        }
    }

    func testNewLegAndExplicitPhaseWithoutRouteClearPreviousRoad() {
        XCTAssertNil(RoadRoute.retainedPath(nil, previous: route, sameLeg: false, positionOnly: true))
        XCTAssertNil(RoadRoute.retainedPath(nil, previous: route, sameLeg: true, positionOnly: false))
        let replacement = Array(route.reversed())
        XCTAssertEqual(RoadRoute.retainedPath(replacement, previous: route, sameLeg: false, positionOnly: false), replacement)
    }

    func testReturnKeepsRoadCorners() {
        XCTAssertEqual(RoadRoute.remaining(route, latitude: 37.505, longitude: 127.0),
                       [[37.505, 127.0], [37.51, 127.0], [37.51, 127.01], [37.52, 127.01]])
    }
    func testReopeningDoesNotReplayPassedSegments() {
        XCTAssertEqual(RoadRoute.remaining(route, latitude: 37.51, longitude: 127.005),
                       [[37.51, 127.005], [37.51, 127.01], [37.52, 127.01]])
    }
    func testDestinationHasNoMovementLeft() {
        XCTAssertEqual(RoadRoute.remaining(route, latitude: 37.52, longitude: 127.01), [[37.52, 127.01]])
    }
    func testInvalidAndDuplicatePointsDoNotBreakRoute() {
        XCTAssertEqual(RoadRoute.remaining([[.nan, 127], [], [37.5, 127], [37.5, 127], [37.51, 127]], latitude: 37.505, longitude: 127),
                       [[37.505, 127], [37.51, 127]])
        XCTAssertEqual(RoadRoute.remaining([], latitude: 37.5, longitude: 127), [])
    }
    func testReturnMessageIncludesAnimationTiming() throws {
        let data = Data(#"{"apid":"SEL0111","phase":"returning","gps":{"lat":37.5,"lng":127},"etaSec":450,"speedup":15,"path":[[37.5,127],[37.51,127]],"base":{"lat":37.51,"lng":127}}"#.utf8)
        let sim = try JSONDecoder().decode(AmbulanceSim.self, from: data)
        XCTAssertEqual(sim.phase, .returning)
        XCTAssertEqual(sim.etaSec! / sim.speedup!, 30)
        XCTAssertNil(sim.caseId)
    }
}
