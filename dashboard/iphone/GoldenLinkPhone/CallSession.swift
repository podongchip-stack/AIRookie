import Foundation
import GoldenLinkCore

/// 통화 한 건. voice/app.py + live_transcriber.py가 하던 일을 휴대폰 안에서 한다.
///
///   마이크 -> (0.5초마다) 무음 감지로 발화 자르기 -> ASR 큐(녹음은 인식에 밀리지 않고 계속 쌓임)
///          -> 발화마다 /voice/utterance(실시간 자막)
///   종료 -> 남은 소리 인식 -> 줄바꿈으로 이어 MF_BERT -> /voice/summary (지금 voice와 같은 JSON)
///
/// 서버 STT 모드(온디바이스 모델이 아직 없을 때)는 웹과 똑같이 PCM을 hub WebSocket으로 흘려보내기만 한다.
@MainActor
final class CallSession {
    enum Stage: Equatable { case recording, finishing, structuring, sent, failed(String), noSpeech }

    let caseId: String
    let apid: String
    let startedAt = Date()
    private(set) var lines: [RecognizedSegment] = []
    var onChange: (() -> Void)?
    private(set) var stage: Stage = .recording { didSet { onChange?() } }
    private(set) var level: Float = 0

    private let mic = MicCapture()
    private let models: ModelStore?
    private let sendPCM: ((Data) -> Void)?
    private let segmenter = UtteranceSegmenter(silenceRMS: Settings.silenceRMS, holdSec: Settings.holdSec)
    private let pending = PendingAudio()
    private var allAudio: [Float] = []  // 원본 보존(통화 wav) — 108초 통화 ≈ 7MB
    private var pollTask: Task<Void, Never>?
    private var asrChain: Task<Void, Never>?

    /// models != nil 이면 온디바이스, sendPCM != nil 이면 서버 STT
    init(caseId: String, apid: String, models: ModelStore?, sendPCM: ((Data) -> Void)?) {
        self.caseId = caseId
        self.apid = apid
        self.models = models
        self.sendPCM = sendPCM
    }

    func start() throws {
        let pending = pending, sendPCM = sendPCM
        mic.onSamples = { samples in
            if let sendPCM {
                let data = pcm16(samples)
                Task { @MainActor in sendPCM(data) }
            } else {
                pending.append(samples)
            }
        }
        mic.onLevel = { [weak self] level in Task { @MainActor in self?.level = level; self?.onChange?() } }
        try mic.start()
        guard models != nil else { return }
        pollTask = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(500))  // POLL_SEC
                self?.poll(final: false)
            }
        }
    }

    /// 종료 버튼. 마이크를 끄고 남은 처리를 뒤에서 마친다
    func finish() async {
        mic.stop()
        pollTask?.cancel()
        guard let models else { stage = .sent; return }  // 서버 STT: 요약은 중앙 voice가 보낸다
        stage = .finishing
        poll(final: true)
        await asrChain?.value
        let duration = Double(allAudio.count) / Double(GoldenLinkCore.sampleRate)
        let text = joinedTranscript(lines)
        guard !text.isEmpty else {  // voice와 같이 인식된 발화가 없으면 요약을 보내지 않는다
            Archive.save(caseId: caseId, audio: allAudio, transcript: text, summary: nil)
            stage = .noSpeech
            return
        }
        stage = .structuring
        do {
            let summary = try await models.extract(text)
            let message = buildCallSummary(caseId: caseId, segments: lines, callStart: startedAt,
                                           durationSec: duration, summary: summary)
            Archive.save(caseId: caseId, audio: allAudio, transcript: text, summary: message)
            if let error = await HubHTTP.postSummary(message) { stage = .failed(error) } else { stage = .sent }
        } catch {
            Archive.save(caseId: caseId, audio: allAudio, transcript: text, summary: nil)
            stage = .failed("구조화 실패: \(error.localizedDescription)")
        }
    }

    private func poll(final: Bool) {
        let samples = pending.drain()
        allAudio += samples
        segmenter.append(samples)
        for utterance in segmenter.poll(final: final) { enqueue(utterance) }
    }

    /// 발화를 순서대로 하나씩 인식한다(앞 인식이 끝나야 다음 — 서버의 락과 같다)
    private func enqueue(_ u: Utterance) {
        guard let models else { return }
        let previous = asrChain
        let apid = apid, caseId = caseId
        asrChain = Task { @MainActor [weak self] in
            await previous?.value
            for s in await models.transcribe(u.audio) {
                let seg = RecognizedSegment(start: u.offsetSec + s.start, end: u.offsetSec + s.end, text: s.text)
                self?.lines.append(seg)
                self?.onChange?()
                HubHTTP.postUtterance(UtteranceMessage(apid: apid, caseId: caseId, start: seg.start, end: seg.end, text: seg.text))
            }
        }
    }
}

/// 오디오 스레드 -> 메인 사이 버퍼
final class PendingAudio: @unchecked Sendable {
    private var buffer: [Float] = []
    private let lock = NSLock()
    func append(_ s: [Float]) { lock.lock(); buffer += s; lock.unlock() }
    func drain() -> [Float] { lock.lock(); defer { buffer.removeAll(keepingCapacity: true); lock.unlock() }; return buffer }
}

/// 원본 보존(사후 검증·audit trail) — voice가 통화 wav·STT 원문·요약 JSON을 남기는 것과 같다.
/// 앱 샌드박스 Documents/calls/<caseId>/, 잠금 시 암호화(.complete). 환자 음성은 기기 밖으로 나가지 않는다.
enum Archive {
    static func save(caseId: String, audio: [Float], transcript: String, summary: JSONValue?) {
        let fm = FileManager.default
        guard let docs = fm.urls(for: .documentDirectory, in: .userDomainMask).first else { return }
        let dir = docs.appendingPathComponent("calls/\(caseId)", isDirectory: true)
        try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
        let opts: Data.WritingOptions = [.atomic, .completeFileProtection]
        try? wav(audio).write(to: dir.appendingPathComponent("call.wav"), options: opts)
        try? Data(transcript.utf8).write(to: dir.appendingPathComponent("transcript.txt"), options: opts)
        if let summary, let data = try? JSONEncoder().encode(summary) {
            try? data.write(to: dir.appendingPathComponent("call_summary.json"), options: opts)
        }
    }

    /// 16kHz 모노 16비트 wav
    static func wav(_ samples: [Float]) -> Data {
        let pcm = pcm16(samples)
        var d = Data()
        func u32(_ v: UInt32) { var x = v.littleEndian; withUnsafeBytes(of: &x) { d.append(contentsOf: $0) } }
        func u16(_ v: UInt16) { var x = v.littleEndian; withUnsafeBytes(of: &x) { d.append(contentsOf: $0) } }
        d.append(contentsOf: Array("RIFF".utf8)); u32(UInt32(36 + pcm.count)); d.append(contentsOf: Array("WAVEfmt ".utf8))
        u32(16); u16(1); u16(1); u32(UInt32(GoldenLinkCore.sampleRate)); u32(UInt32(GoldenLinkCore.sampleRate * 2)); u16(2); u16(16)
        d.append(contentsOf: Array("data".utf8)); u32(UInt32(pcm.count)); d.append(pcm)
        return d
    }
}
