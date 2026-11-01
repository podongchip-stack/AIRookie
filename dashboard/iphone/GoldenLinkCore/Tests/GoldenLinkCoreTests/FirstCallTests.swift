import XCTest
@testable import GoldenLinkCore

final class FirstCallTests: XCTestCase {
    func testKtasBeforeDistanceAndMissingPolicy() throws {
        let data = Data("""
        [{"hospitalId":"near","name":"near","distanceKm":1,"availableBedCount":1,"bedCountUnknown":false,"supportedKtas":[4,5]},
         {"hospitalId":"far","name":"far","distanceKm":3,"roadDistanceKm":5,"availableBedCount":1,"bedCountUnknown":false,"supportedKtas":[1,2,3,4,5]},
         {"hospitalId":"road","name":"road","distanceKm":4,"roadDistanceKm":4,"availableBedCount":1,"bedCountUnknown":false,"supportedKtas":[2,3,4,5]},
         {"hospitalId":"unknown","name":"unknown","distanceKm":0.1,"availableBedCount":1,"bedCountUnknown":false}]
        """.utf8)
        let hospitals = try JSONDecoder().decode([SceneCandidate].self, from: data)
        XCTAssertEqual(SceneCandidate.firstCallCandidates(hospitals, ktas: 2).map(\.hospitalId), ["road", "far"])
        XCTAssertEqual(SceneCandidate.firstCallCandidates(hospitals, ktas: 1).first?.hospitalId, "far")
        XCTAssertEqual(SceneCandidate.firstCallCandidates(hospitals, ktas: 4).first?.hospitalId, "near")
        XCTAssertTrue(SceneCandidate.firstCallCandidates(hospitals, ktas: nil).isEmpty)
        XCTAssertTrue(SceneCandidate.firstCallCandidates(Array(hospitals.prefix(1)), ktas: 1).isEmpty)
    }
}
