package xyz.goldenlink.phone

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.media.Ringtone
import android.media.RingtoneManager
import android.util.Log
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import org.webrtc.AudioSource
import org.webrtc.AudioTrack
import org.webrtc.IceCandidate
import org.webrtc.MediaConstraints
import org.webrtc.MediaStream
import org.webrtc.PeerConnection
import org.webrtc.PeerConnectionFactory
import org.webrtc.RtpReceiver
import org.webrtc.RtpTransceiver
import org.webrtc.SdpObserver
import org.webrtc.SessionDescription
import org.webrtc.DataChannel
import org.webrtc.audio.JavaAudioDeviceModule
import xyz.goldenlink.core.IceServerConfig
import xyz.goldenlink.core.DuplexAudio
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.Executors

/**
 * 실제 양방향 통화(WebRTC, 2026-11-04)의 한 통화 연결 — 구급대 앱(offer 쪽)과 병원 앱(answer 쪽)이 같이 쓴다.
 * 마이크 음성만 주고받는다(영상 없음). 연결 협상 메시지는 hub가 중계하고(call_sessions.py), 음성은 직접 또는 TURN으로 간다.
 *
 * 콜백(Listener)은 WebRTC 스레드에서 불린다 — 호출한 쪽이 메인 스레드로 옮겨 쓴다.
 * "준비 완료(onMediaReady)"는 연결(CONNECTED)과 상대 오디오 트랙 수신을 둘 다 확인했을 때 한 번만 알린다 —
 * 병원이 받았다는 사실만으로, 또는 상대가 조용하다는 이유로 통화 시작을 정하지 않는다(개발계획서 §5·§10).
 */
class RtcSession(context: Context, iceServers: List<IceServerConfig>, private val listener: Listener,
                 onSamples: ((FloatArray) -> Unit)? = null) {
    interface Listener {
        fun onLocalIce(candidate: JsonObject)
        fun onMediaReady()
        fun onFailed(reason: String)
    }

    private val tag = "GoldenLinkRtc"
    private var factory: PeerConnectionFactory? = null
    private var adm: JavaAudioDeviceModule? = null
    private var source: AudioSource? = null
    private var track: AudioTrack? = null
    private var pc: PeerConnection? = null
    private val tap = onSamples?.let { RtcPcmTap(it) }
    private var remoteTrack: AudioTrack? = null
    private val audioSink = org.webrtc.AudioTrackSink { buffer, bits, rate, channels, frames, _ ->
        if (bits == 16 && !closed) tap?.append(buffer, rate, channels, frames, true)
    }
    @Volatile private var muted = false

    @Volatile private var closed = false
    private var remoteSet = false
    private val pendingIce = mutableListOf<IceCandidate>()
    private var connected = false
    private var remoteAudio = false
    private var readyAnnounced = false

    /** 구급대 쪽: offer를 만들어 돌려준다(로컬 설명으로 적용한 뒤) */
    fun createOffer(onSdp: (String) -> Unit) {
        val connection = pc ?: return
        val constraints = MediaConstraints().apply { mandatory.add(MediaConstraints.KeyValuePair("OfferToReceiveAudio", "true")) }
        connection.createOffer(object : Sdp("offer") {
            override fun onCreateSuccess(desc: SessionDescription) {
                connection.setLocalDescription(Sdp("setLocal"), desc)
                onSdp(desc.description)
            }
        }, constraints)
    }

    /** 병원 쪽: 받은 offer를 적용하고 answer를 만들어 돌려준다 */
    fun acceptOffer(sdp: String, onAnswer: (String) -> Unit) {
        val connection = pc ?: return
        connection.setRemoteDescription(object : Sdp("setRemote(offer)") {
            override fun onSetSuccess() {
                remoteDescriptionApplied()
                connection.createAnswer(object : Sdp("answer") {
                    override fun onCreateSuccess(desc: SessionDescription) {
                        connection.setLocalDescription(Sdp("setLocal"), desc)
                        onAnswer(desc.description)
                    }
                }, MediaConstraints())
            }
        }, SessionDescription(SessionDescription.Type.OFFER, sdp))
    }

    /** 구급대 쪽: 병원의 answer를 적용한다 */
    fun applyAnswer(sdp: String) {
        pc?.setRemoteDescription(object : Sdp("setRemote(answer)") {
            override fun onSetSuccess() = remoteDescriptionApplied()
        }, SessionDescription(SessionDescription.Type.ANSWER, sdp))
    }

    /** 상대의 ICE 후보. 상대 설명을 적용하기 전에 온 것은 모아 두었다가 적용 뒤 한꺼번에 넣는다 */
    fun addRemoteIce(candidate: JsonObject) {
        val parsed = parseIce(candidate) ?: return
        synchronized(pendingIce) {
            if (closed) return
            if (remoteSet) pc?.addIceCandidate(parsed) else pendingIce.add(parsed)
        }
    }

    private fun remoteDescriptionApplied() {
        synchronized(pendingIce) {
            remoteSet = true
            pendingIce.forEach { pc?.addIceCandidate(it) }
            pendingIce.clear()
        }
    }

    fun setMicMuted(muted: Boolean) { this.muted = muted; track?.setEnabled(!muted) }

    /** 마이크·연결·오디오를 모두 정리한다. 여러 번 불러도 한 번만 처리한다. 가장 먼저 마이크 트랙을 끈다 */
    fun close() {
        if (closed) return
        closed = true
        runCatching { remoteTrack?.removeSink(audioSink) }; remoteTrack = null
        runCatching { track?.setEnabled(false) }
        runCatching { pc?.close() }
        runCatching { pc?.dispose() }
        runCatching { track?.dispose() }
        runCatching { source?.dispose() }
        runCatching { factory?.dispose() }
        runCatching { adm?.release() }
        pc = null; track = null; source = null; factory = null; adm = null
        tap?.finish()
    }

    private fun maybeAnnounceReady() {
        if (closed || readyAnnounced || !(connected && remoteAudio)) return
        readyAnnounced = true
        listener.onMediaReady()
    }

    private val observer = object : PeerConnection.Observer {
        override fun onIceCandidate(c: IceCandidate) {
            if (closed) return
            listener.onLocalIce(buildJsonObject {
                put("sdpMid", JsonPrimitive(c.sdpMid))
                put("sdpMLineIndex", JsonPrimitive(c.sdpMLineIndex))
                put("candidate", JsonPrimitive(c.sdp))
            })
        }

        override fun onConnectionChange(state: PeerConnection.PeerConnectionState) {
            Log.i(tag, "connection=$state")
            when (state) {
                PeerConnection.PeerConnectionState.CONNECTED -> { connected = true; maybeAnnounceReady() }
                PeerConnection.PeerConnectionState.FAILED -> if (!closed) listener.onFailed("connection_failed")
                else -> Unit  // DISCONNECTED는 일시적일 수 있다 — hub의 유예·종료 규칙에 맡긴다
            }
        }

        override fun onTrack(transceiver: RtpTransceiver) {
            val audio = transceiver.receiver.track() as? AudioTrack
            if (audio != null) {
                if (tap != null && remoteTrack !== audio) {
                    remoteTrack?.removeSink(audioSink)
                    remoteTrack = audio; audio.addSink(audioSink)
                }
                remoteAudio = true; maybeAnnounceReady()
            }
        }

        override fun onSignalingChange(s: PeerConnection.SignalingState?) {}
        override fun onIceConnectionChange(s: PeerConnection.IceConnectionState?) { Log.i(tag, "ice=$s") }
        override fun onIceConnectionReceivingChange(b: Boolean) {}
        override fun onIceGatheringChange(s: PeerConnection.IceGatheringState?) {}
        override fun onIceCandidatesRemoved(c: Array<out IceCandidate>?) {}
        override fun onAddStream(s: MediaStream?) {}
        override fun onRemoveStream(s: MediaStream?) {}
        override fun onDataChannel(d: DataChannel?) {}
        override fun onRenegotiationNeeded() {}
        override fun onAddTrack(r: RtpReceiver?, s: Array<out MediaStream>?) {}
    }

    // 아래 init은 observer(위)를 쓰므로 그보다 뒤에 둔다 — 코틀린은 선언 순서대로 초기화한다
    init {
        initOnce(context.applicationContext)
        val module = JavaAudioDeviceModule.builder(context.applicationContext)
            .setAudioFormat(android.media.AudioFormat.ENCODING_PCM_16BIT)
            .setSamplesReadyCallback { samples ->
                if (!closed && tap != null) {
                    val bytes = if (muted) ByteArray(samples.data.size) else samples.data
                    tap.append(ByteBuffer.wrap(bytes), samples.sampleRate, samples.channelCount,
                        bytes.size / 2 / samples.channelCount, false)
                }
            }
            .setUseHardwareAcousticEchoCanceler(true)
            .setUseHardwareNoiseSuppressor(true)
            .createAudioDeviceModule()
        adm = module
        val f = PeerConnectionFactory.builder().setAudioDeviceModule(module).createPeerConnectionFactory()
        factory = f
        val servers = iceServers.filter { it.urls.isNotEmpty() }.map { cfg ->
            PeerConnection.IceServer.builder(cfg.urls).apply {
                cfg.username?.let { setUsername(it) }
                cfg.credential?.let { setPassword(it) }
            }.createIceServer()
        }
        val config = PeerConnection.RTCConfiguration(servers).apply {
            sdpSemantics = PeerConnection.SdpSemantics.UNIFIED_PLAN
            continualGatheringPolicy = PeerConnection.ContinualGatheringPolicy.GATHER_CONTINUALLY
        }
        val connection = f.createPeerConnection(config, observer) ?: throw IllegalStateException("PeerConnection을 만들지 못했습니다")
        pc = connection
        val audioSource = f.createAudioSource(MediaConstraints())
        source = audioSource
        val audioTrack = f.createAudioTrack("audio0", audioSource)
        track = audioTrack
        connection.addTrack(audioTrack, listOf("stream0"))
    }


    /** SdpObserver 기본 구현 — 실패는 통화 실패로 알린다 */
    private open inner class Sdp(private val what: String) : SdpObserver {
        override fun onCreateSuccess(desc: SessionDescription) {}
        override fun onSetSuccess() {}
        override fun onCreateFailure(error: String?) { fail("$what 생성 실패: $error") }
        override fun onSetFailure(error: String?) { fail("$what 적용 실패: $error") }
    }

    private fun fail(reason: String) {
        Log.w(tag, reason)
        if (!closed) listener.onFailed(reason)
    }

    companion object {
        @Volatile private var initialized = false

        @Synchronized
        private fun initOnce(appContext: Context) {
            if (initialized) return
            PeerConnectionFactory.initialize(PeerConnectionFactory.InitializationOptions.builder(appContext).createInitializationOptions())
            initialized = true
        }

        fun parseIce(candidate: JsonObject): IceCandidate? {
            val sdp = (candidate["candidate"] as? JsonPrimitive)?.content ?: return null
            val mid = (candidate["sdpMid"] as? JsonPrimitive)?.content
            val index = (candidate["sdpMLineIndex"] as? JsonPrimitive)?.content?.toIntOrNull() ?: 0
            return IceCandidate(mid, index, sdp)
        }
    }
}

/** SDK 버퍼는 콜백 안에서 복사한다. 재생 버퍼의 position/내용을 변경하지 않는다. */
private class RtcPcmTap(private val deliver: (FloatArray) -> Unit) {
    private val queue = Executors.newSingleThreadExecutor()
    private val mixer = DuplexAudio()
    @Volatile private var closed = false
    fun append(buffer: ByteBuffer, rate: Int, channels: Int, frames: Int, remote: Boolean) {
        if (closed || channels < 1 || rate <= 0) return
        val copy = buffer.duplicate().order(ByteOrder.LITTLE_ENDIAN).asShortBuffer()
        val count = minOf(frames, copy.remaining() / channels)
        val samples = FloatArray(count) {
            var sum = 0f
            repeat(channels) { sum += copy.get().toFloat() / 32768f }
            sum / channels
        }
        synchronized(this) {
            if (closed) return
            queue.execute { mixer.append(samples, rate, remote).takeIf { it.isNotEmpty() }?.let(deliver) }
        }
    }
    fun finish() {
        synchronized(this) { if (closed) return; closed = true }
        queue.submit { mixer.drain(true).takeIf { it.isNotEmpty() }?.let(deliver) }.get()
        queue.shutdown()
    }
}

/**
 * 통화 중 오디오 경로 — 통신 모드(에코 제거·수화부)로 바꾸고 오디오 포커스를 잡는다. 끝나면 원래대로 돌린다.
 * 기본은 수화부(전화기처럼), 스피커폰은 [setSpeaker]로 켠다.
 */
class CallAudio(context: Context) {
    private val manager = context.applicationContext.getSystemService(Context.AUDIO_SERVICE) as AudioManager
    private var previousMode: Int? = null
    private var focus: AudioFocusRequest? = null

    fun start() {
        if (previousMode != null) return
        previousMode = manager.mode
        val request = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
            .setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
            .build()
        focus = request
        manager.requestAudioFocus(request)
        manager.mode = AudioManager.MODE_IN_COMMUNICATION
        manager.isSpeakerphoneOn = false
    }

    fun setSpeaker(on: Boolean) { manager.isSpeakerphoneOn = on }

    fun stop() {
        val prev = previousMode ?: return
        previousMode = null
        manager.isSpeakerphoneOn = false
        manager.mode = prev
        focus?.let { manager.abandonAudioFocusRequest(it) }
        focus = null
    }
}

/** 수신 벨소리 — 기기 기본 벨소리를 반복한다. 받기·거절·종료 때 반드시 [stop] */
class Ringer(private val context: Context) {
    private var ringtone: Ringtone? = null

    fun start() {
        if (ringtone != null) return
        val uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE) ?: return
        ringtone = RingtoneManager.getRingtone(context.applicationContext, uri)?.apply {
            audioAttributes = AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build()
            isLooping = true
            play()
        }
    }

    fun stop() {
        runCatching { ringtone?.stop() }
        ringtone = null
    }
}
