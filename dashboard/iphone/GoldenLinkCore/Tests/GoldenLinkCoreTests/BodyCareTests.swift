import XCTest
@testable import GoldenLinkCore

final class BodyCareTests: XCTestCase {
    func testCareOptionsFitTheRegion() {
        // 팔다리·골반은 부목, 머리·목·등·골반은 척추 고정, 얼굴·목은 기도 처치, 가슴·배는 공통만
        for r in [BodyRegion.arm, .hand, .leg, .foot, .pelvis] { XCTAssertTrue(BodyCare.optionsFor(r).contains("부목 고정")) }
        for r in [BodyRegion.head, .neck, .back, .pelvis] { XCTAssertTrue(BodyCare.optionsFor(r).contains("척추 고정")) }
        for r in [BodyRegion.face, .neck] { XCTAssertTrue(BodyCare.optionsFor(r).contains("기도 흡인") && BodyCare.optionsFor(r).contains("기도 이물 제거")) }
        XCTAssertFalse(BodyCare.optionsFor(.chest).contains("부목 고정"))
        XCTAssertFalse(BodyCare.optionsFor(.arm).contains("척추 고정"))
        // 전신 처치는 어느 부위에도 없다
        let systemic = ["산소투여", "정맥로 확보", "CPR", "AED", "수액공급", "인공호흡", "보온", "냉각", "분만 처치", "아스피린 투여", "기본 기도확보"]
        for r in BodyRegion.allCases { for t in systemic { XCTAssertFalse(BodyCare.optionsFor(r).contains(t), "\(r) \(t)") } }
        // 모든 선택지는 28범주 어휘 안에 있다
        let all = Set(BodyCare.all.map(\.label))
        for r in BodyRegion.allCases { XCTAssertTrue(all.isSuperset(of: BodyCare.optionsFor(r))) }
        XCTAssertEqual(BodyCare.all.count, 28)
    }

    func testMisfitCaresAreDropped() {
        let arm = BodyMark(.arm, .left)
        // 팔에 산소투여·척추 고정은 맞지 않아 적용 때 걸러진다
        let e = BodyEdits().applied(arm, on: true, careList: ["부목 고정", "산소투여", "척추 고정", "지혈"], fromCall: false)
        XCTAssertEqual(e.careLines, ["좌 팔 부목 고정", "좌 팔 지혈"])
        // 이미 들어와 있던 값(다른 기기·예전 값)도 읽을 때 걸러진다
        let stale = BodyEdits(added: [arm], cares: [arm: ["산소 투여", "정맥로 확보", "부목 고정"]])
        XCTAssertEqual(stale.careLines, ["좌 팔 부목 고정"])
        XCTAssertEqual(stale.markCount, 1)
        let onlyMisfit = BodyEdits(cares: [arm: ["산소 투여"]])
        XCTAssertTrue(onlyMisfit.isEmpty)
        XCTAssertEqual(onlyMisfit.markCount, 0)
    }

    func testVocabularyMatchesHub() throws {
        // hub/voice_treatments.py의 한글 이름과 글자까지 같아야 AI가 뽑은 처치와 겹치지 않는다. 저장소 밖에서 돌리면 건너뛴다
        let hubFile = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("hub/voice_treatments.py")
        guard let text = try? String(contentsOf: hubFile, encoding: .utf8) else { throw XCTSkip("hub/voice_treatments.py 없음") }
        guard let start = text.range(of: "['산소투여'"), let end = text.range(of: "'기타 처치']") else { throw XCTSkip("hub 어휘 위치를 못 찾음") }
        let body = String(text[start.lowerBound..<end.upperBound])
        let hub = body.split(separator: "'").enumerated().compactMap { $0.offset % 2 == 1 ? String($0.element) : nil }
        XCTAssertEqual(hub, BodyCare.all.map(\.label))
    }
}
