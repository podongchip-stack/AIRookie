import XCTest
@testable import GoldenLinkCore

final class RoadRouteTests: XCTestCase {
    let route = [[37.5, 127.0], [37.51, 127.0], [37.51, 127.01], [37.52, 127.01]]

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
