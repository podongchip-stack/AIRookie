import Foundation

/// voice/MF_BERT/labels.py의 보기 목록. 손으로 옮기지 않고 convert/export_labels.py가 뽑은 labels.json을 읽는다.
public struct Labels: Decodable, Sendable {
    public let undecided: String
    public let majors: [String]
    /// "대분류|소분류"
    public let minors: [String]
    /// 단일 선택 헤드 이름 -> classes(미언급 포함). ktas·med_status는 미언급 보기가 없다
    public let single: [String: [String]]
    /// 다중 선택 헤드 이름 -> 보기
    public let multi: [String: [String]]
    public let spanTypes: [String]
    public let spanTags: [String]

    enum CodingKeys: String, CodingKey {
        case undecided, majors, minors, single, multi
        case spanTypes = "span_types"
        case spanTags = "span_tags"
    }

    public static let shared: Labels = {
        let url = Bundle.module.url(forResource: "labels", withExtension: "json")!
        return try! JSONDecoder().decode(Labels.self, from: Data(contentsOf: url))
    }()

    /// 문장 헤드 이름 전체(단일 + 다중). Core ML 출력 이름과 같다
    public var sentenceHeads: [String] { Array(single.keys) + Array(multi.keys) }
}
