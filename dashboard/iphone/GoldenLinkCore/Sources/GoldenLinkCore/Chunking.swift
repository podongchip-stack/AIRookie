/// voice/MF_BERT/chunking.py의 chunk_text() 그대로. 긴 통화를 512토큰 조각(128토큰 겹침)으로 나누고,
/// 조각마다 남길 토큰 위치(keep)와 남긴 토큰들의 원문 구간(offsets)을 낸다.
/// keep대로 각 조각 인코더 출력의 행을 골라 순서대로 이어 붙이면 원문 토큰 줄이 복원된다(MFBertRunner).
public struct ChunkedText: Equatable, Sendable {
    /// 조각별 토큰 id ([CLS] ... [SEP])
    public let chunks: [[Int]]
    /// 조각별 남길 토큰 위치(조각 안 인덱스)
    public let keep: [[Int]]
    /// 남긴 토큰의 원문 코드포인트 구간. 특수 토큰은 (0, 0)
    public let offsets: [[Int]]
}

public let chunkTokens = 512
public let chunkStride = 128

public func chunkText(_ text: String, tokenizer: WordPieceTokenizer,
                      chunkTokens: Int = chunkTokens, stride: Int = chunkStride) -> ChunkedText {
    let body = chunkTokens - 2
    precondition(0 <= stride && stride < body, "stride must be in [0, \(body))")
    let (ids, offsets) = tokenizer.encode(text)
    let n = ids.count

    var starts = [0]
    while starts.last! + body < n { starts.append(starts.last! + body - stride) }
    let ends = starts.map { min($0 + body, n) }
    // 조각 i가 맡는 원문 토큰 구간 [owned[i], owned[i + 1])
    var owned = [0]
    for i in 0..<(starts.count - 1) { owned.append((starts[i + 1] + ends[i]) / 2) }
    owned.append(n)

    var chunks: [[Int]] = []
    var keep: [[Int]] = []
    var kept: [[Int]] = [[0, 0]]
    for (i, (start, end)) in zip(starts, ends).enumerated() {
        chunks.append([tokenizer.clsId] + ids[start..<end] + [tokenizer.sepId])
        var positions = (owned[i]..<owned[i + 1]).map { $0 - start + 1 }
        if i == 0 { positions = [0] + positions }
        if i == starts.count - 1 { positions.append(end - start + 1) }
        keep.append(positions)
        kept += offsets[owned[i]..<owned[i + 1]].map { [$0.0, $0.1] }
    }
    kept.append([0, 0])
    return ChunkedText(chunks: chunks, keep: keep, offsets: kept)
}
