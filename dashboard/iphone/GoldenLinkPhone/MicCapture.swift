import AVFoundation
import GoldenLinkCore

/// 마이크 -> 16kHz 모노 Float32. voice의 STT 입력과 같은 형식이다.
/// .voiceChat 모드는 자동 이득·잡음 억제가 켜진다(웹의 echoCancellation·noiseSuppression과 비슷) — 무음 기준은 실측해서 맞춘다.
/// Info.plist UIBackgroundModes=audio라 통화 중 화면이 꺼져도 녹음이 이어진다(웹 앱의 가장 큰 한계).
final class MicCapture {
    private let engine = AVAudioEngine()
    private var converter: AVAudioConverter?
    private let target = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: Double(GoldenLinkCore.sampleRate),
                                       channels: 1, interleaved: false)!

    /// 오디오 스레드에서 불린다 — 받는 쪽이 스레드를 넘겨야 한다
    var onSamples: (([Float]) -> Void)?
    /// 화면 레벨 막대용(0~1)
    var onLevel: ((Float) -> Void)?

    static func requestPermission() async -> Bool {
        await AVAudioApplication.requestRecordPermission()
    }

    func start() throws {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .voiceChat, options: [.defaultToSpeaker])
        try session.setActive(true)

        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        converter = AVAudioConverter(from: format, to: target)
        input.installTap(onBus: 0, bufferSize: 4096, format: format) { [weak self] buffer, _ in
            self?.convert(buffer)
        }
        engine.prepare()
        try engine.start()
    }

    func stop() {
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    private func convert(_ buffer: AVAudioPCMBuffer) {
        guard let converter else { return }
        let ratio = target.sampleRate / buffer.format.sampleRate
        let capacity = AVAudioFrameCount(Double(buffer.frameLength) * ratio + 32)
        guard let out = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: capacity) else { return }
        var fed = false
        var error: NSError?
        converter.convert(to: out, error: &error) { _, status in
            if fed { status.pointee = .noDataNow; return nil }
            fed = true
            status.pointee = .haveData
            return buffer
        }
        guard error == nil, let ch = out.floatChannelData?[0], out.frameLength > 0 else { return }
        let samples = Array(UnsafeBufferPointer(start: ch, count: Int(out.frameLength)))
        onSamples?(samples)
        let rms = (samples.reduce(0) { $0 + $1 * $1 } / Float(samples.count)).squareRoot()
        onLevel?(min(1, rms * 8))
    }
}

/// Float32 -> 16비트 정수 PCM(리틀엔디언). 서버 STT 모드에서 hub로 보내는 프레임 — pcm-capture.ts와 같은 변환
func pcm16(_ samples: [Float]) -> Data {
    var data = Data(capacity: samples.count * 2)
    for s in samples {
        let v = max(-1, min(1, s))
        var i = Int16(v < 0 ? v * 0x8000 : v * 0x7FFF).littleEndian
        withUnsafeBytes(of: &i) { data.append(contentsOf: $0) }
    }
    return data
}
