import XCTest
@testable import GoldenLinkCore

final class DuplexAudioTests: XCTestCase {
    func testBothDirectionsKeepOneTimeline() {
        var audio = DuplexAudio()
        XCTAssertTrue(audio.append(Array(repeating: 0.8, count: 4800), rate: 48000, remote: false).isEmpty)
        let mixed = audio.append(Array(repeating: 0.2, count: 1600), rate: 16000, remote: true)
        XCTAssertEqual(mixed.count, 1600) // 100ms, 양쪽 길이를 이어 200ms로 만들지 않는다.
        XCTAssertTrue(mixed.allSatisfy { abs($0 - 0.5) < 0.0001 })
        XCTAssertTrue(audio.drain(final: true).isEmpty)
    }

    func testResamplerCarriesFractionAcrossCallbacksAndFlushesOnce() {
        var audio = DuplexAudio()
        for _ in 0..<10 { _ = audio.append(Array(repeating: 1, count: 441), rate: 44100, remote: false) }
        let tail = audio.drain(final: true)
        XCTAssertEqual(tail.count, 1600)
        XCTAssertTrue(tail.allSatisfy { $0 == 0.5 })
        XCTAssertTrue(audio.drain(final: true).isEmpty)
    }

    func testMissingDirectionDoesNotGrowWithoutBound() {
        var audio = DuplexAudio()
        let samples = audio.append(Array(repeating: 0.3, count: 32000), rate: 16000, remote: false)
        XCTAssertEqual(samples.count + audio.drain(final: true).count, 32000)
    }
}
