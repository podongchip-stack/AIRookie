import Foundation

/// voice/live_transcriber.py의 무음 감지 발화 자르기. 소리 크기(RMS)만 본다 — 목소리와 소음을 구분하지 못하므로
/// 현장이 시끄러워 발화가 안 끊기면 silenceRMS를 올리고, 말하는 중에 자꾸 끊기면 holdSec을 늘린다(앱 설정에서 조절).
///
/// 녹음 버퍼는 이 타입이 들고 있고(append), 잘라낸 발화는 poll()/finish()가 돌려준다. ASR 호출은 하지 않는다 —
/// 인식은 호출한 쪽이 큐로 돌려 녹음이 인식에 밀리지 않게 한다.
public let sampleRate = 16000
public let frameSamples = sampleRate / 10  // 0.1초 — 무음 판정 단위
let minSpeechSec = 0.6  // 이보다 짧은 소리는 발화로 보지 않는다(기침·잡음)
let maxUtteranceSec = 12.0  // 쉬지 않고 말하면 여기서 가장 조용한 지점을 찾아 끊는다
let keepSilenceSec = 0.5  // 말이 없을 때 버퍼에 남겨 두는 길이

public func frameRMS(_ audio: ArraySlice<Float>) -> [Float] {
    let count = audio.count / frameSamples
    return (0..<count).map { i in
        let lo = audio.startIndex + i * frameSamples
        var sum: Float = 0
        for x in audio[lo..<(lo + frameSamples)] { sum += x * x }
        return (sum / Float(frameSamples)).squareRoot()
    }
}

/// 버퍼에서 발화가 끝난 지점(샘플 위치). 끊을 곳이 없으면 nil.
public func findUtteranceEnd(_ rms: [Float], threshold: Float, holdFrames: Int) -> Int? {
    guard let first = rms.firstIndex(where: { $0 >= threshold }),
          let last = rms.lastIndex(where: { $0 >= threshold }) else { return nil }
    if Double((last - first + 1) * frameSamples) < minSpeechSec * Double(sampleRate) { return nil }
    let trailing = rms.count - 1 - last
    if trailing >= holdFrames {
        return min(last + 1 + holdFrames / 2, rms.count) * frameSamples
    }
    if Double(rms.count * frameSamples) >= maxUtteranceSec * Double(sampleRate) {
        let tailStart = max(0, rms.count - 20)
        let tail = rms[tailStart...]
        let quietest = tail.indices.min { tail[$0] < tail[$1] }!  // np.argmin: 같으면 앞쪽
        return (quietest + 1) * frameSamples
    }
    return nil
}

public struct Utterance: Sendable {
    /// 통화 시작 기준 초
    public let offsetSec: Double
    public let audio: [Float]
}

public final class UtteranceSegmenter {
    public let threshold: Float
    let holdFrames: Int
    private var buffer: [Float] = []
    private var consumed = 0  // 통화 시작부터 이미 잘라냈거나 무음으로 버린 샘플 수

    public init(silenceRMS: Float = 0.01, holdSec: Double = 0.4) {
        threshold = silenceRMS
        holdFrames = max(1, Int((holdSec * Double(sampleRate) / Double(frameSamples)).rounded(.toNearestOrEven)))
    }

    public func append(_ samples: [Float]) { buffer += samples }

    /// 0.5초마다 부른다(POLL_SEC). final이면 남은 소리에 기준 이상 소리가 있으면 그것도 발화로 낸다.
    public func poll(final: Bool = false) -> [Utterance] {
        var out: [Utterance] = []
        while let cut = findUtteranceEnd(frameRMS(buffer[...]), threshold: threshold, holdFrames: holdFrames) {
            take(cut, into: &out)
        }
        let rms = frameRMS(buffer[...])
        let hasSpeech = rms.contains { $0 >= threshold }
        if final {
            if hasSpeech { take(buffer.count, into: &out) }
            buffer.removeAll()
            return out
        }
        // 말이 하나도 없는 버퍼는 끝부분만 남긴다(가만히 있는 동안 버퍼가 계속 커지지 않게)
        let keep = Int(keepSilenceSec * Double(sampleRate))
        if !rms.isEmpty && !hasSpeech && buffer.count > keep {
            let drop = buffer.count - keep
            buffer.removeFirst(drop)
            consumed += drop
        }
        return out
    }

    private func take(_ n: Int, into out: inout [Utterance]) {
        out.append(Utterance(offsetSec: Double(consumed) / Double(sampleRate), audio: Array(buffer[..<n])))
        buffer.removeFirst(n)
        consumed += n
    }
}

/// asr.py split_chunks(): 5초를 넘는 발화는 목표 길이 앞 3초 안에서 가장 조용한 0.1초 지점에서 자른다.
public func splitChunks(_ audio: [Float], chunkSec: Double = 5.0) -> [Range<Int>] {
    let total = audio.count
    let maxLen = Int(chunkSec * Double(sampleRate))
    if total <= maxLen { return [0..<total] }
    let search = 3 * sampleRate
    var bounds: [Range<Int>] = []
    var start = 0
    while total - start > maxLen {
        let target = start + maxLen
        let lo = max(start + frameSamples, target - search)
        // Python은 (rms, 위치) 튜플의 min — rms가 같으면 앞쪽 위치
        var cut = lo, best = Float.infinity
        for p in stride(from: lo, to: target, by: frameSamples) {
            let seg = audio[p..<min(p + frameSamples, total)]
            let e = (seg.reduce(0) { $0 + $1 * $1 } / Float(seg.count)).squareRoot()
            if e < best { best = e; cut = p }
        }
        bounds.append(start..<cut)
        start = cut
    }
    bounds.append(start..<total)
    return bounds
}
