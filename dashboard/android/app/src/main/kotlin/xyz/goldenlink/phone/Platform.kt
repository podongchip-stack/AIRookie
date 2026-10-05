package xyz.goldenlink.phone

import android.Manifest
import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.content.pm.ServiceInfo
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import kotlinx.serialization.json.JsonElement
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString
import xyz.goldenlink.core.IdentifyMessage
import xyz.goldenlink.core.SAMPLE_RATE
import xyz.goldenlink.core.hubJson
import xyz.goldenlink.core.messageType
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.TimeUnit
import kotlin.math.min
import kotlin.math.sqrt

/** 앱 설정(설정 화면에서 바꾼다). 기기에만 저장된다 — 아이폰 Settings.swift와 같은 항목·기본값 */
class Settings(context: Context) {
    private val p: SharedPreferences = context.getSharedPreferences("goldenlink", Context.MODE_PRIVATE)

    /** hub 주소. 로컬 모드 `http://<PC IP>:5001`, 공개 모드 `https://app.rookie-goldenlink.xyz` */
    var hubBase: String
        get() = p.getString("hubBase", "https://app.rookie-goldenlink.xyz")!!
        set(v) = p.edit().putString("hubBase", v).apply()

    /** 구급차 ID(SEL0001~) 또는 "auto"(출동하는 구급차를 자동으로 따라감 — 웹 P-AUTO) */
    var apid: String
        get() = p.getString("apid", "auto")!!
        set(v) = p.edit().putString("apid", v).apply()

    /** true: 기기 안에서 STT·MF_BERT(온디바이스). false: 웹과 같이 음성을 hub로 보내 중앙 voice가 처리 */
    var onDevice: Boolean
        get() = p.getBoolean("onDevice", true)
        set(v) = p.edit().putBoolean("onDevice", v).apply()

    /** 무음 기준(VOICE_SILENCE_RMS). 휴대폰 마이크는 PC와 음량 특성이 달라 실측해서 맞춘다 */
    var silenceRms: Float
        get() = p.getFloat("silenceRMS", 0.01f)
        set(v) = p.edit().putFloat("silenceRMS", v).apply()

    /** 발화 끝 판정 무음 길이(VOICE_UTTERANCE_HOLD_SEC) */
    var holdSec: Float
        get() = p.getFloat("holdSec", 0.4f)
        set(v) = p.edit().putFloat("holdSec", v).apply()

    val httpBase: String get() = hubBase.trim().trimEnd('/')

    /** http(s)://host -> ws(s)://host/ws/dashboard */
    val wsUrl: String
        get() {
            val base = httpBase
            val rest = base.substringAfter("://", base)
            val host = rest.substringBefore('/')
            return (if (base.startsWith("https")) "wss://" else "ws://") + host + "/ws/dashboard"
        }
}

/**
 * hub WebSocket(순수 WebSocket, socket.io 아님). use-dashboard-socket.ts·아이폰 HubSocket.swift와 같은 규칙:
 * 연결 직후 identify, 끊기면 지수 백오프로 다시 붙고 identify를 다시 보낸다(hub가 진행 중 사건을 따라잡기로 돌려준다).
 * 콜백은 메인 스레드에서 부른다.
 */
class HubSocket(
    private val url: String,
    private val role: String,
    private val id: String,
    private val onMessage: (type: String, text: String) -> Unit,
    private val onState: (State) -> Unit,
) {
    enum class State { CONNECTING, LIVE, RECONNECTING }

    private val main = Handler(Looper.getMainLooper())
    private var ws: WebSocket? = null
    private var retryDelayMs = 1000L
    private var closed = false
    @Volatile var isOpen = false
        private set

    init { connect() }

    fun close() {
        closed = true
        ws?.close(1001, null)
    }

    fun send(json: JsonElement): Boolean = isOpen && ws?.send(json.toString()) == true
    fun sendText(text: String): Boolean = isOpen && ws?.send(text) == true

    /** 서버 STT 모드: 16kHz 모노 16비트 PCM(리틀엔디언) — pcm-capture.ts와 같은 형식 */
    fun sendBinary(data: ByteArray) { if (isOpen) ws?.send(data.toByteString()) }

    private fun connect() {
        if (closed) return
        onState(if (retryDelayMs > 1000) State.RECONNECTING else State.CONNECTING)
        val request = runCatching { Request.Builder().url(url).build() }.getOrNull() ?: return scheduleReconnect()
        ws = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                isOpen = true
                webSocket.send(hubJson.encodeToString(IdentifyMessage.serializer(), IdentifyMessage(role, id)))
                main.post { if (webSocket === ws) { retryDelayMs = 1000; onState(State.LIVE) } }
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                val type = messageType(text) ?: return  // type으로 갈래를 고르고, type이 없으면 예전 hub의 매칭 결과다
                main.post { if (webSocket === ws) onMessage(type, text) }
            }

            override fun onMessage(webSocket: WebSocket, bytes: ByteString) = onMessage(webSocket, bytes.utf8())

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) = lost(webSocket)
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = lost(webSocket)
        })
    }

    private fun lost(webSocket: WebSocket) {
        main.post {
            if (webSocket !== ws) return@post
            isOpen = false
            scheduleReconnect()
        }
    }

    private fun scheduleReconnect() {
        if (closed) return
        onState(State.RECONNECTING)
        val delay = retryDelayMs
        retryDelayMs = min(retryDelayMs * 2, 15_000)
        main.postDelayed({ connect() }, delay)
    }

    companion object {
        val client: OkHttpClient = OkHttpClient.Builder().pingInterval(20, TimeUnit.SECONDS).build()
    }
}

/**
 * 마이크 -> 16kHz 모노 Float32. voice의 STT 입력과 같은 형식이다. VOICE_COMMUNICATION 소스는 자동 이득·잡음 억제가
 * 켜진다(아이폰 .voiceChat, 웹의 echoCancellation·noiseSuppression과 비슷) — 무음 기준은 실측해서 맞춘다.
 * onSamples는 녹음 스레드에서 불린다.
 */
class MicCapture(private val onSamples: (FloatArray) -> Unit, private val onLevel: (Float) -> Unit) {
    private var record: AudioRecord? = null
    private var thread: Thread? = null
    @Volatile private var running = false

    @SuppressLint("MissingPermission")  // 호출 전에 RECORD_AUDIO 권한을 확인한다(PhoneModel.dial)
    private fun open(encoding: Int): AudioRecord? {
        val min = AudioRecord.getMinBufferSize(SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, encoding)
        if (min <= 0) return null
        val rec = AudioRecord(MediaRecorder.AudioSource.VOICE_COMMUNICATION, SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO,
            encoding, maxOf(min, SAMPLE_RATE * 4 / 5 * 2))
        if (rec.state == AudioRecord.STATE_INITIALIZED) return rec
        rec.release()
        return null
    }

    fun start() {
        // float를 못 여는 기기면 16비트로 열어 같은 범위(-1~1)로 바꾼다(pcm-capture.ts와 같은 변환의 역)
        val float = open(AudioFormat.ENCODING_PCM_FLOAT)
        val rec = float ?: open(AudioFormat.ENCODING_PCM_16BIT) ?: error("마이크를 열지 못했습니다")
        record = rec
        running = true
        rec.startRecording()
        thread = Thread({
            val buf = FloatArray(SAMPLE_RATE / 10)  // 0.1초
            val shorts = ShortArray(SAMPLE_RATE / 10)
            while (running) {
                val n = if (float != null) {
                    rec.read(buf, 0, buf.size, AudioRecord.READ_BLOCKING)
                } else {
                    rec.read(shorts, 0, shorts.size, AudioRecord.READ_BLOCKING).also { k ->
                        for (i in 0 until maxOf(k, 0)) buf[i] = if (shorts[i] < 0) shorts[i] / 32768f else shorts[i] / 32767f
                    }
                }
                if (n <= 0) continue
                val samples = buf.copyOf(n)
                onSamples(samples)
                var sum = 0f
                for (x in samples) sum += x * x
                onLevel(minOf(1f, sqrt(sum / n) * 8))
            }
        }, "mic").apply { start() }
    }

    fun stop() {
        running = false
        thread?.join(500)
        record?.run { runCatching { stop() }; release() }
        record = null
    }
}

/** Float32 -> 16비트 정수 PCM(리틀엔디언). 서버 STT 모드에서 hub로 보내는 프레임 — pcm-capture.ts와 같은 변환 */
fun pcm16(samples: FloatArray): ByteArray {
    val b = ByteBuffer.allocate(samples.size * 2).order(ByteOrder.LITTLE_ENDIAN)
    for (s in samples) {
        val v = s.coerceIn(-1f, 1f)
        b.putShort((if (v < 0) v * 0x8000 else v * 0x7FFF).toInt().toShort())
    }
    return b.array()
}

/** 통화 중 화면이 꺼져도 녹음이 이어지게 하는 포그라운드 서비스(마이크). 통화 동안만 켜 둔다 */
class CallService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "통화 녹음", NotificationManager.IMPORTANCE_LOW))
        val notification = Notification.Builder(this, CHANNEL)
            .setContentTitle("골든링크 통화 중")
            .setContentText("통화 음성을 기기 안에서 인식하고 있습니다")
            .setSmallIcon(R.drawable.ic_launcher_fg)
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(1, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        } else {
            startForeground(1, notification)
        }
        return START_NOT_STICKY
    }

    companion object {
        private const val CHANNEL = "call"
        fun start(context: Context) = runCatching { context.startForegroundService(Intent(context, CallService::class.java)) }
        fun stop(context: Context) = runCatching { context.stopService(Intent(context, CallService::class.java)) }
        const val PERMISSION = Manifest.permission.RECORD_AUDIO
    }
}
