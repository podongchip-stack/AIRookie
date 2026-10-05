import Foundation

/// KLUE RoBERTa 토크나이저(BertTokenizer, WordPiece)를 MF_BERT `tokenizer/tokenizer.json`에서 읽어 그대로 재현한다.
/// chunking.py가 쓰는 `return_offsets_mapping`(원문 글자 구간)까지 필요해 직접 구현했다 — swift-transformers는 오프셋을 주지 않는다.
///
/// tokenizer.json 설정(확인한 값): BertNormalizer(clean_text, handle_chinese_chars, strip_accents=null, lowercase=false)
/// + BertPreTokenizer + WordPiece("##", max_input_chars_per_word=100, [UNK]). 소문자화·악센트 제거가 없어
/// 한글 음절이 분해되지 않는다. 오프셋은 Python과 같은 유니코드 코드포인트 위치다.
public final class WordPieceTokenizer: Sendable {
    public let vocab: [String: Int]
    public let unkId: Int
    public let clsId: Int
    public let sepId: Int
    public let padId: Int
    let maxCharsPerWord: Int
    let prefix: String

    public init(tokenizerJSON url: URL) throws {
        struct File: Decodable {
            struct Model: Decodable {
                let vocab: [String: Int]
                let unk_token: String
                let continuing_subword_prefix: String
                let max_input_chars_per_word: Int
            }
            let model: Model
        }
        let file = try JSONDecoder().decode(File.self, from: Data(contentsOf: url))
        vocab = file.model.vocab
        prefix = file.model.continuing_subword_prefix
        maxCharsPerWord = file.model.max_input_chars_per_word
        unkId = vocab[file.model.unk_token]!
        clsId = vocab["[CLS]"]!
        sepId = vocab["[SEP]"]!
        padId = vocab["[PAD]"]!
    }

    /// 특수 토큰 없이 (토큰 id, (시작, 끝) 코드포인트 구간) 목록
    public func encode(_ text: String) -> (ids: [Int], offsets: [(Int, Int)]) {
        var ids: [Int] = []
        var offsets: [(Int, Int)] = []
        for (word, start) in preTokenize(text) {
            let chars = word.map { String($0) }
            if chars.count > maxCharsPerWord {
                ids.append(unkId); offsets.append((start, start + chars.count)); continue
            }
            var pieces: [(Int, Int, Int)] = []  // id, 시작, 끝
            var begin = 0
            var failed = false
            while begin < chars.count {
                var end = chars.count
                var found: Int?
                while begin < end {
                    var piece = chars[begin..<end].joined()  // 코드포인트 단위(Python·Rust와 같게)
                    if begin > 0 { piece = prefix + piece }
                    if let id = vocab[piece] { found = id; break }
                    end -= 1
                }
                guard let id = found else { failed = true; break }
                pieces.append((id, start + begin, start + end))
                begin = end
            }
            if failed {
                ids.append(unkId); offsets.append((start, start + chars.count))
            } else {
                for p in pieces { ids.append(p.0); offsets.append((p.1, p.2)) }
            }
        }
        return (ids, offsets)
    }

    /// BertNormalizer + BertPreTokenizer: 단어 목록(유니코드 스칼라 배열, 원문 시작 위치).
    /// 제어 문자는 버리고, 공백은 나누는 자리, 문장부호·한자는 한 글자씩 따로 낸다.
    func preTokenize(_ text: String) -> [([Unicode.Scalar], Int)] {
        var words: [([Unicode.Scalar], Int)] = []
        var current: [Unicode.Scalar] = []
        var currentStart = 0
        func flush() {
            if !current.isEmpty { words.append((current, currentStart)) }
            current = []
        }
        for (i, c) in text.unicodeScalars.enumerated() {
            let v = c.value
            if v == 0 || v == 0xFFFD || Self.isControl(c) { continue }  // clean_text
            if Self.isWhitespace(c) { flush(); continue }
            if Self.isPunctuation(c) || Self.isChineseChar(v) {
                flush(); words.append(([c], i)); continue
            }
            if current.isEmpty { currentStart = i }
            current.append(c)
        }
        flush()
        return words
    }

    // HF tokenizers(bert normalizer/pre_tokenizer)와 같은 판정
    static func isWhitespace(_ c: Unicode.Scalar) -> Bool {
        // normalizer가 Zs·\t\n\r을 공백으로 바꾸고, pre-tokenizer는 유니코드 White_Space 전부에서 나눈다
        switch c { case " ", "\t", "\n", "\r": return true; default: return c.properties.isWhitespace }
    }

    static func isControl(_ c: Unicode.Scalar) -> Bool {
        switch c { case "\t", "\n", "\r": return false; default: break }
        switch c.properties.generalCategory {
        case .control, .format, .privateUse, .surrogate, .unassigned: return true
        default: return false
        }
    }

    static func isPunctuation(_ c: Unicode.Scalar) -> Bool {
        let v = c.value
        if (33...47).contains(v) || (58...64).contains(v) || (91...96).contains(v) || (123...126).contains(v) { return true }
        switch c.properties.generalCategory {
        case .connectorPunctuation, .dashPunctuation, .openPunctuation, .closePunctuation,
             .initialPunctuation, .finalPunctuation, .otherPunctuation: return true
        default: return false
        }
    }

    static func isChineseChar(_ v: UInt32) -> Bool {
        (0x4E00...0x9FFF).contains(v) || (0x3400...0x4DBF).contains(v) || (0x20000...0x2A6DF).contains(v)
            || (0x2A700...0x2B73F).contains(v) || (0x2B740...0x2B81F).contains(v) || (0x2B920...0x2CEAF).contains(v)
            || (0xF900...0xFAFF).contains(v) || (0x2F800...0x2FA1F).contains(v)
    }
}
