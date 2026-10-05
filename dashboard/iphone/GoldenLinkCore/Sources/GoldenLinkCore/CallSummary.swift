import Foundation

/// 인식된 발화 하나(통화 시작 기준 초)
public struct RecognizedSegment: Sendable, Equatable {
    public let start: Double
    public let end: Double
    public let text: String
    public init(start: Double, end: Double, text: String) { self.start = start; self.end = end; self.text = text }
}

/// model_used — 서버 처리분과 구분하려고 -ios를 붙인다(사후 대조용)
public let iosSTTName = "qwen3-asr-0.6b-119ko-tiny-ios"
public let iosLLMName = "mf-bert-klue-roberta-large-ios"

/// MF_BERT 입력이자 transcript.raw_text — 발화를 줄바꿈으로 잇는다(voice와 같게)
public func joinedTranscript(_ segments: [RecognizedSegment]) -> String {
    segments.map(\.text).joined(separator: "\n")
}

/// voice/transcribe.py build_call_summary_message() + CallSummaryMessage.to_payload()와 같은 JSON.
/// voice는 통화 시작 시각을 "지금 - 길이"로 근사하지만, 앱은 실제 시작 시각을 알아 그대로 쓴다.
public func buildCallSummary(caseId: String, segments: [RecognizedSegment], callStart: Date, durationSec: Double,
                             summary: JSONValue) -> JSONValue {
    let full = joinedTranscript(segments)
    let utc = DateFormatter()
    utc.locale = Locale(identifier: "en_US_POSIX")
    utc.timeZone = TimeZone(identifier: "UTC")
    utc.dateFormat = "yyyy-MM-dd'T'HH:mm:ss'Z'"
    let hms = DateFormatter()
    hms.locale = Locale(identifier: "en_US_POSIX")
    hms.timeZone = TimeZone(identifier: "UTC")  // voice와 같이 UTC 기준 시:분:초
    hms.dateFormat = "HH:mm:ss"
    let turns: [JSONValue] = segments.map { s in
        .object([("speaker", .string("미분리")),
                 ("timestamp", .string(hms.string(from: callStart.addingTimeInterval(s.start)))),
                 ("text", .string(s.text))])
    }
    return .object([
        ("caseId", .string(caseId)),
        ("transcript", .object([
            ("raw_text", .string(full)),
            ("filtered_text", .string(full)),  // 교정 단계가 없어 raw_text와 같다(계약 필드라 유지)
            ("language", .string("ko")),
            ("timestamp", .string(utc.string(from: callStart))),
            ("duration_sec", .double((durationSec * 10).rounded() / 10)),
            ("turns", .array(turns)),
        ])),
        ("summary", summary),
        ("source", .string("ai")),
        ("model_used", .object([("stt", .string(iosSTTName)), ("llm", .string(iosLLMName))])),
    ])
}
