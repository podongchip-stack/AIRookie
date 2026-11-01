import XCTest
@testable import GoldenLinkCore

final class HandoverTests: XCTestCase {
    func testTreatmentsFillHandoverWithoutLosingStatus() throws {
        let json = #"{"treatment":["산소투여(비관)","CPR","AED","정맥로 확보","수액공급","지혈","아스피린 투여","척추 고정","부목 고정","상처처치 거부"]}"#
        let patient = try JSONDecoder().decode(PatientInfo.self, from: Data(json.utf8))
        let values = Handover.auto(patient: patient, confirmed: nil, ambulanceName: nil, apid: nil, times: [:], incident: nil, incidentAddress: nil)
        XCTAssertEqual(values["careBreathing"], "산소투여(비관)")
        XCTAssertTrue(values["careCirculation"]!.contains("CPR"))
        XCTAssertTrue(values["careCirculation"]!.contains("지혈"))
        XCTAssertEqual(values["careDrug"], "아스피린 투여")
        XCTAssertTrue(values["careFix"]!.contains("부목 고정"))
        XCTAssertTrue(values["careEtc"]!.contains("거부"))
    }
    func testRoadPathDecodesAndPositionCanOmitIt() throws {
        let phase = #"{"apid":"SEL0001","phase":"dispatching","base":{"lat":37.5,"lng":127.0},"path":[[37.5,127.0],[37.51,127.01],[37.52,127.0]]}"#
        let position = #"{"apid":"SEL0001","phase":"dispatching"}"#
        XCTAssertEqual(try JSONDecoder().decode(AmbulanceSim.self, from: Data(phase.utf8)).path?.count, 3)
        XCTAssertNil(try JSONDecoder().decode(AmbulanceSim.self, from: Data(position.utf8)).path)
        XCTAssertEqual(try JSONDecoder().decode(AmbulanceSim.self, from: Data(phase.utf8)).base?.lat, 37.5)
    }
}
