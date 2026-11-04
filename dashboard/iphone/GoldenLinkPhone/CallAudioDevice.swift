import AVFoundation
import AudioToolbox
import GoldenLinkCore
import WebRTC

/// WebRTC의 유일한 마이크/재생 소유자. VoiceProcessingIO(AEC)에서 실제 송·수신 PCM을 복사한다.
/// ASR은 별도 큐에서만 실행하며 오디오 렌더 콜백을 기다리게 하지 않는다.
final class CallAudioDevice: NSObject, RTCAudioDevice, @unchecked Sendable {
    private var delegate: RTCAudioDeviceDelegate?
    private var unit: AudioUnit?
    private var inputStorage = UnsafeMutablePointer<Int16>.allocate(capacity: 4096)
    private let audioQueue = DispatchQueue(label: "goldenlink.call-pcm")
    private var mixer = DuplexAudio()
    private var capturing = true
    private let onSamples: @Sendable ([Float]) -> Void
    private let onFailure: @Sendable (String) -> Void
    private var interruption: NSObjectProtocol?
    private let muteLock = NSLock()
    private var muted = false
    var micMuted: Bool {
        get { muteLock.lock(); defer { muteLock.unlock() }; return muted }
        set { muteLock.lock(); muted = newValue; muteLock.unlock() }
    }

    var deviceInputSampleRate: Double { 48_000 }
    var deviceOutputSampleRate: Double { 48_000 }
    var inputIOBufferDuration: TimeInterval { AVAudioSession.sharedInstance().ioBufferDuration }
    var outputIOBufferDuration: TimeInterval { inputIOBufferDuration }
    var inputNumberOfChannels: Int { 1 }
    var outputNumberOfChannels: Int { 1 }
    var inputLatency: TimeInterval { AVAudioSession.sharedInstance().inputLatency }
    var outputLatency: TimeInterval { AVAudioSession.sharedInstance().outputLatency }
    private(set) var isInitialized = false
    private(set) var isPlaying = false
    private(set) var isRecording = false
    var isPlayoutInitialized: Bool { isInitialized }
    var isRecordingInitialized: Bool { isInitialized }

    init(onSamples: @escaping @Sendable ([Float]) -> Void, onFailure: @escaping @Sendable (String) -> Void) {
        self.onSamples = onSamples; self.onFailure = onFailure
        super.init()
    }
    deinit { inputStorage.deallocate(); if let interruption { NotificationCenter.default.removeObserver(interruption) } }

    func initialize(with delegate: RTCAudioDeviceDelegate) -> Bool {
        if isInitialized { return true }
        self.delegate = delegate
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playAndRecord, mode: .voiceChat, options: [.allowBluetoothHFP])
            try session.setPreferredSampleRate(48_000)
            try session.setPreferredIOBufferDuration(0.01)
            try session.setActive(true)
            var description = AudioComponentDescription(componentType: kAudioUnitType_Output,
                componentSubType: kAudioUnitSubType_VoiceProcessingIO, componentManufacturer: kAudioUnitManufacturer_Apple,
                componentFlags: 0, componentFlagsMask: 0)
            guard let component = AudioComponentFindNext(nil, &description) else { throw AudioError.status(-1) }
            try check(AudioComponentInstanceNew(component, &unit))
            guard let unit else { throw AudioError.status(-1) }
            var enabled: UInt32 = 1
            try check(AudioUnitSetProperty(unit, kAudioOutputUnitProperty_EnableIO, kAudioUnitScope_Input, 1, &enabled, 4))
            var format = AudioStreamBasicDescription(mSampleRate: 48_000, mFormatID: kAudioFormatLinearPCM,
                mFormatFlags: kAudioFormatFlagIsSignedInteger | kAudioFormatFlagIsPacked, mBytesPerPacket: 2,
                mFramesPerPacket: 1, mBytesPerFrame: 2, mChannelsPerFrame: 1, mBitsPerChannel: 16, mReserved: 0)
            let size = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
            try check(AudioUnitSetProperty(unit, kAudioUnitProperty_StreamFormat, kAudioUnitScope_Output, 1, &format, size))
            try check(AudioUnitSetProperty(unit, kAudioUnitProperty_StreamFormat, kAudioUnitScope_Input, 0, &format, size))
            var frames: UInt32 = 4096
            try check(AudioUnitSetProperty(unit, kAudioUnitProperty_MaximumFramesPerSlice, kAudioUnitScope_Global, 0, &frames, 4))
            var input = AURenderCallbackStruct(inputProc: { context, flags, time, bus, count, _ in
                Unmanaged<CallAudioDevice>.fromOpaque(context).takeUnretainedValue().record(flags, time, count)
            }, inputProcRefCon: Unmanaged.passUnretained(self).toOpaque())
            var output = AURenderCallbackStruct(inputProc: { context, flags, time, bus, count, data in
                guard let data else { return noErr }
                return Unmanaged<CallAudioDevice>.fromOpaque(context).takeUnretainedValue().play(flags, time, count, data)
            }, inputProcRefCon: Unmanaged.passUnretained(self).toOpaque())
            let callbackSize = UInt32(MemoryLayout<AURenderCallbackStruct>.size)
            try check(AudioUnitSetProperty(unit, kAudioOutputUnitProperty_SetInputCallback, kAudioUnitScope_Global, 1, &input, callbackSize))
            try check(AudioUnitSetProperty(unit, kAudioUnitProperty_SetRenderCallback, kAudioUnitScope_Input, 0, &output, callbackSize))
            try check(AudioUnitInitialize(unit))
            interruption = NotificationCenter.default.addObserver(forName: AVAudioSession.interruptionNotification,
                object: session, queue: nil) { [weak self] note in
                if (note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt) == AVAudioSession.InterruptionType.began.rawValue {
                    self?.onFailure("audio_interrupted")
                }
            }
            isInitialized = true
            return true
        } catch {
            _ = terminateDevice()
            onFailure("통화 오디오 초기화 실패: \(error)")
            return false
        }
    }

    func initializePlayout() -> Bool { isInitialized }
    func initializeRecording() -> Bool { isInitialized }
    func startPlayout() -> Bool { isPlaying = true; return startUnit() }
    func startRecording() -> Bool { isRecording = true; return startUnit() }
    func stopPlayout() -> Bool { isPlaying = false; return stopIfIdle() }
    func stopRecording() -> Bool { isRecording = false; return stopIfIdle() }
    private func startUnit() -> Bool {
        guard let unit else { return false }
        let status = AudioOutputUnitStart(unit)
        if status != noErr { onFailure("통화 오디오 시작 실패: \(status)") }
        return status == noErr
    }
    private func stopIfIdle() -> Bool {
        if !isPlaying && !isRecording, let unit { AudioOutputUnitStop(unit) }
        return true
    }
    func terminateDevice() -> Bool {
        if let unit { AudioOutputUnitStop(unit); AudioUnitUninitialize(unit); AudioComponentInstanceDispose(unit) }
        unit = nil; delegate = nil
        isInitialized = false; isPlaying = false; isRecording = false
        return true
    }

    private func record(_ flags: UnsafeMutablePointer<AudioUnitRenderActionFlags>, _ time: UnsafePointer<AudioTimeStamp>, _ count: UInt32) -> OSStatus {
        guard let unit, let delegate, count <= 4096 else { return kAudio_ParamError }
        var buffer = AudioBufferList(mNumberBuffers: 1,
            mBuffers: AudioBuffer(mNumberChannels: 1, mDataByteSize: count * 2, mData: inputStorage))
        let status = AudioUnitRender(unit, flags, time, 1, count, &buffer)
        guard status == noErr else { return status }
        guard isRecording else { return noErr }
        if micMuted { inputStorage.initialize(repeating: 0, count: Int(count)) }
        tap(inputStorage, count: Int(count), remote: false)
        return delegate.deliverRecordedData(flags, time, 1, count, &buffer, nil, nil)
    }

    private func play(_ flags: UnsafeMutablePointer<AudioUnitRenderActionFlags>, _ time: UnsafePointer<AudioTimeStamp>, _ count: UInt32, _ data: UnsafeMutablePointer<AudioBufferList>) -> OSStatus {
        guard isPlaying, let delegate else {
            for buffer in UnsafeMutableAudioBufferListPointer(data) {
                if let bytes = buffer.mData { memset(bytes, 0, Int(buffer.mDataByteSize)) }
            }
            return noErr
        }
        let status = delegate.getPlayoutData(flags, time, 0, count, data)
        if status == noErr, let bytes = data.pointee.mBuffers.mData {
            tap(bytes.assumingMemoryBound(to: Int16.self), count: Int(count), remote: true)
        }
        return status
    }

    private func tap(_ data: UnsafePointer<Int16>, count: Int, remote: Bool) {
        let samples = (0..<count).map { Float(data[$0]) / 32768 }
        audioQueue.async { [self] in
            guard capturing else { return }
            let output = mixer.append(samples, rate: 48_000, remote: remote)
            if !output.isEmpty { onSamples(output) }
        }
    }

    /// 먼저 오디오 유닛을 정지한 뒤 호출한다. 큐에 들어온 마지막 양방향 샘플까지 한 번 전달한다.
    func finishCapture() {
        audioQueue.sync {
            guard capturing else { return }
            capturing = false
            let tail = mixer.drain(final: true)
            if !tail.isEmpty { onSamples(tail) }
        }
    }

    private enum AudioError: Error { case status(OSStatus) }
    private func check(_ status: OSStatus) throws { if status != noErr { throw AudioError.status(status) } }
}
