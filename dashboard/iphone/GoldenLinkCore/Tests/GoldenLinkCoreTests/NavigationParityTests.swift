import XCTest
@testable import GoldenLinkCore

final class NavigationParityTests: XCTestCase {
    // Android RoadRouteTest와 같은 경로: 북으로 1km → 동으로 2km.
    let right = [[37.0, 127.0], [37.0045, 127.0], [37.009, 127.0], [37.009, 127.0112], [37.009, 127.0224]]
    func testRouteDistancePositionAndBearing() throws {
        let path = RoutePath(right)
        XCTAssertEqual(path.lengthM, 2986, accuracy: 60)
        XCTAssertEqual(try XCTUnwrap(path.bearingAt(0, aheadM: 60)), 0, accuracy: 1)
        XCTAssertEqual(try XCTUnwrap(path.bearingAt(1100, aheadM: 60)), 90, accuracy: 1)
        XCTAssertEqual(try XCTUnwrap(path.pointAt(500))[0], 37.0045, accuracy: 0.0003)
        XCTAssertEqual(path.pointAt(1e9), right.last)
        XCTAssertNil(RoutePath([]).pointAt(10))
        XCTAssertNil(RoutePath([[.nan, 127], [37, 127]]).pointAt(10))
    }
    func testTurnDirectionAndDistanceMatchAndroid() throws {
        let turn = try XCTUnwrap(RoadRoute.nextTurn(right))
        XCTAssertEqual(turn.distanceM, 1000, accuracy: 40)
        XCTAssertTrue((70...110).contains(turn.angleDeg))
        let left = try XCTUnwrap(RoadRoute.nextTurn([[37, 127], [37.009, 127], [37.009, 126.9888]]))
        XCTAssertTrue((-110 ... -70).contains(left.angleDeg))
        XCTAssertNil(RoadRoute.nextTurn([[37, 127], [37, 127.02], [37.0001, 127.04]]))
    }
    func testCameraPredictsAlongRouteThenStopsAndHonorsPause() throws {
        var camera = NavigationCamera()
        let first = try XCTUnwrap(camera.frame(position: right[0], route: right, speedHint: 100, time: 0))
        let next = try XCTUnwrap(camera.frame(position: right[0], route: right, speedHint: 100, time: 1))
        XCTAssertGreaterThan(next.latitude, first.latitude)
        XCTAssertEqual(next.longitude, first.longitude, accuracy: 0.00001)
        let stale = try XCTUnwrap(camera.frame(position: right[0], route: right, speedHint: 100, time: 3))
        let stopped = try XCTUnwrap(camera.frame(position: right[0], route: right, speedHint: 100, time: 4))
        XCTAssertEqual(stale.latitude, stopped.latitude, accuracy: 0.000001)
        let paused = try XCTUnwrap(camera.frame(position: right[0], route: right, speedHint: 100, time: 5, moving: false))
        XCTAssertEqual(paused.latitude, first.latitude, accuracy: 0.000001)
        XCTAssertTrue(paused.height.isFinite)
        XCTAssertNil(camera.frame(position: [.nan, 127], route: right, speedHint: nil, time: 6))
    }
    func testBodyCareVocabularyAndRegionFiltering() {
        XCTAssertEqual(BodyCare.all.count, 28)
        XCTAssertEqual(Set(BodyCare.all.map(\.label)).count, 28)
        XCTAssertTrue(BodyCare.optionsFor(.leg).contains("부목 고정"))
        XCTAssertFalse(BodyCare.optionsFor(.chest).contains("부목 고정"))
        XCTAssertTrue(BodyCare.optionsFor(.neck).contains("기도 흡인"))
        let mark = BodyMark(.leg, .left)
        let e = BodyEdits(cares: [mark: ["부목 고정", "산소 투여", "정맥로 확보", "드레싱"]])
        XCTAssertEqual(e.careLines, ["좌 다리 부목 고정"])
        XCTAssertEqual(e.applied(mark, on: true, careList: ["상처처치", "기도 흡인"], fromCall: false).careLines, ["좌 다리 상처처치"])
    }
}
