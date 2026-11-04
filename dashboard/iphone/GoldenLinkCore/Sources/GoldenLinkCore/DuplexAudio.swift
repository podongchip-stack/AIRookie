import Foundation

/// 단일 오디오 소유자(WebRTC)의 양방향 PCM을 16kHz 모노로 합친다.
/// 각 방향은 독립 리샘플링 상태를 가진다. 100ms 단위, 최대 1초 뒤처짐만 보관한다.
public struct DuplexAudio {
    private var near: [Float] = []
    private var far: [Float] = []
    private var nearPhase = 0.0
    private var farPhase = 0.0
    public init() {}

    public mutating func append(_ samples: [Float], rate: Double, remote: Bool) -> [Float] {
        guard rate > 0 else { return [] }
        var phase = remote ? farPhase : nearPhase
        var resampled: [Float] = []
        for sample in samples {
            phase += 16_000
            while phase >= rate { resampled.append(sample); phase -= rate }
        }
        if remote { far += resampled; farPhase = phase } else { near += resampled; nearPhase = phase }
        return drain(final: false)
    }

    public mutating func drain(final: Bool) -> [Float] {
        let count = final ? max(near.count, far.count)
            : (max(near.count, far.count) > 16_000 ? max(near.count, far.count) - 8_000 : min(near.count, far.count) / 1_600 * 1_600)
        guard count > 0 else { return [] }
        let output = (0..<count).map { i in
            max(-1, min(1, ((i < near.count ? near[i] : 0) + (i < far.count ? far[i] : 0)) * 0.5))
        }
        near.removeFirst(min(count, near.count)); far.removeFirst(min(count, far.count))
        return output
    }
}
