import Foundation
import XCTest
@testable import GoldenLinkCore

/// Python 원본(voice/)과의 일치 검사. 정답은 convert/make_fixtures.py가 만든다.
/// 토크나이저 검사는 MF_BERT tokenizer.json이 필요하다 — MF_BERT_TOKENIZER 환경변수 또는 HF 캐시에서 찾는다.
final class ParityTests: XCTestCase {
    static let fixtures: JSONValue = {
        let url = Bundle.module.url(forResource: "Fixtures/fixtures", withExtension: "json")!
        return try! JSONDecoder().decode(JSONValue.self, from: Data(contentsOf: url))
    }()

    func arr(_ key: String) -> [JSONValue] {
        guard case let .array(a)? = Self.fixtures[key] else { fatalError(key) }
        return a
    }

    func tokenizer() throws -> WordPieceTokenizer {
        let env = ProcessInfo.processInfo.environment["MF_BERT_TOKENIZER"]
        let cache = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(
            ".cache/huggingface/hub/models--podongchip--MF_BERT/snapshots/f1d3e1dbd41424e1bb32cf4aded891ed48b39df6/tokenizer/tokenizer.json")
        let url = env.map(URL.init(fileURLWithPath:)) ?? cache
        try XCTSkipUnless(FileManager.default.fileExists(atPath: url.path), "tokenizer.json 없음: \(url.path)")
        return try WordPieceTokenizer(tokenizerJSON: url)
    }

    func ints(_ v: JSONValue?) -> [Int] {
        guard case let .array(a)? = v else { return [] }
        return a.map { if case let .int(i) = $0 { return i }; fatalError() }
    }

    func pairs(_ v: JSONValue?) -> [[Int]] {
        guard case let .array(a)? = v else { return [] }
        return a.map { ints($0) }
    }

    func floats(_ a: [JSONValue]) -> [Float] {
        a.map { v -> Float in
            switch v { case let .double(d): return Float(d); case let .int(n): return Float(n); default: return .nan }
        }
    }

    func string(_ v: JSONValue?) -> String { if case let .string(s)? = v { return s }; fatalError() }

    func testNumberRegexMatchesPython() {
        XCTAssertEqual(numberRE, string(Self.fixtures["number_re"]))
    }

    func testTokenizer() throws {
        let tok = try tokenizer()
        for c in arr("tokenizer") {
            let (ids, offsets) = tok.encode(string(c["text"]))
            XCTAssertEqual(ids, ints(c["ids"]), string(c["text"]))
            XCTAssertEqual(offsets.map { [$0.0, $0.1] }, pairs(c["offsets"]), string(c["text"]))
        }
    }

    func testChunking() throws {
        let tok = try tokenizer()
        for c in arr("chunks") {
            let got = chunkText(string(c["text"]), tokenizer: tok, chunkTokens: ints(.array([c["chunk_tokens"]!]))[0],
                                stride: ints(.array([c["stride"]!]))[0])
            XCTAssertEqual(got.chunks, pairs(c["chunks"]))
            XCTAssertEqual(got.keep, pairs(c["keep"]))
            XCTAssertEqual(got.offsets, pairs(c["offsets"]))
        }
    }

    func testParseVitals() {
        for c in arr("vitals") {
            XCTAssertEqual(JSONValue.object(parseVitals(string(c["text"]))), c["expected"]!, string(c["text"]))
        }
    }

    func testParseAge() {
        for c in arr("ages") {
            let a = parseAge(string(c["text"]))
            let got = JSONValue.object([("years", a.years.map(JSONValue.int) ?? .null),
                                        ("months", a.months.map(JSONValue.int) ?? .null), ("band", .str(a.band))])
            XCTAssertEqual(got, c["expected"]!, string(c["text"]))
        }
    }

    func testParseOnset() {
        for c in arr("onsets") {
            XCTAssertEqual(parseOnset(string(c["text"])).map(JSONValue.int) ?? .null, c["expected"]!, string(c["text"]))
        }
    }

    func testDecode() {
        for (i, c) in arr("decode").enumerated() {
            guard case let .object(headPairs)? = c["heads"] else { return XCTFail() }
            var heads: [String: [Float]] = [:]
            for (name, v) in headPairs {
                guard case let .array(a) = v else { return XCTFail() }
                heads[name] = floats(a)
            }
            let got = decode(text: string(c["text"]), logits: MFBertLogits(heads: heads, spanTags: ints(c["tags"])),
                             offsets: pairs(c["offsets"]))
            XCTAssertEqual(got, c["expected"]!, "decode case \(i)")
            if got != c["expected"]! { print(String(data: try! JSONEncoder().encode(got), encoding: .utf8)!) }
        }
    }

    func testSegmenter() {
        guard case let .object(seg)? = Self.fixtures["segment"] else { return XCTFail() }
        let s = JSONValue.object(seg)
        guard case let .array(finds)? = s["find"] else { return XCTFail() }
        for (i, c) in finds.enumerated() {
            guard case let .array(r)? = c["rms"] else { return XCTFail() }
            let rms = floats(r)
            let got = findUtteranceEnd(rms, threshold: 0.01, holdFrames: ints(.array([c["hold"]!]))[0])
            XCTAssertEqual(got.map(JSONValue.int) ?? .null, c["expected"]!, "find case \(i)")
        }
        guard case let .array(audio)? = s["frame_audio"], case let .array(expected)? = s["frame_rms"] else { return XCTFail() }
        let got = frameRMS(audio.map { if case let .double(d) = $0 { return Float(d) }; return 0 }[...])
        for (g, e) in zip(got, expected) {
            if case let .double(d) = e { XCTAssertEqual(Double(g), d, accuracy: 1e-6) }
        }
    }

    func testSegmenterStream() {
        // 1초 말 + 1초 침묵 + 0.3초 기침 + 2초 침묵 -> 말은 통화 중에 바로 잘리고, 0.6초 미만인 기침은 통화 중엔
        // 발화로 안 보지만 버퍼에 남아 있다가 종료 때 인식된다(live_transcriber.py와 같은 동작)
        let seg = UtteranceSegmenter()
        var audio = [Float](repeating: 0, count: 16000 * 4 + 4800)
        for i in 0..<16000 { audio[i] = 0.1 * sin(Float(i) / 5) }
        for i in 32000..<36800 { audio[i] = 0.1 * sin(Float(i) / 5) }
        var outs: [Utterance] = []
        for start in stride(from: 0, to: audio.count, by: 8000) {
            seg.append(Array(audio[start..<min(start + 8000, audio.count)]))
            outs += seg.poll()
        }
        XCTAssertEqual(outs.count, 1)
        XCTAssertEqual(outs.first?.offsetSec, 0)
        outs += seg.poll(final: true)
        XCTAssertEqual(outs.count, 2)
    }

    func testSplitChunks() {
        var audio = [Float](repeating: 0.1, count: 16000 * 12)
        for i in 70000..<71600 { audio[i] = 0 }  // 4.4초 근처 조용한 지점
        let b = splitChunks(audio)
        XCTAssertEqual(b.first, 0..<70400)  // 0.1초 프레임 중 조용한 샘플이 가장 많은 곳
        XCTAssertEqual(b.last?.upperBound, audio.count)
        XCTAssertTrue(b.allSatisfy { $0.count <= 16000 * 5 })
    }

    func testCallSummaryShape() throws {
        let start = Date(timeIntervalSince1970: 1_791_000_000)
        let msg = buildCallSummary(caseId: "case-1", segments: [.init(start: 1.2, end: 3.4, text: "가"), .init(start: 4, end: 5, text: "나")],
                                   callStart: start, durationSec: 42.34, summary: .object([("ktas_level", .int(2))]))
        XCTAssertEqual(msg["transcript"]?["raw_text"], .string("가\n나"))
        XCTAssertEqual(msg["transcript"]?["duration_sec"], .double(42.3))
        XCTAssertEqual(msg["model_used"]?["stt"], .string(iosSTTName))
        let data = try JSONEncoder().encode(msg)
        XCTAssertTrue(String(data: data, encoding: .utf8)!.contains("\"caseId\":\"case-1\""))
    }
}
