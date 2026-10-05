package xyz.goldenlink.phone

import android.content.Context
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExecutorCoroutineDispatcher
import kotlinx.coroutines.Job
import kotlinx.coroutines.asCoroutineDispatcher
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonObject
import xyz.goldenlink.core.RecognizedSegment
import xyz.goldenlink.core.SAMPLE_RATE
import xyz.goldenlink.core.Utterance
import xyz.goldenlink.core.UtteranceSegmenter
import xyz.goldenlink.core.buildCallSummary
import xyz.goldenlink.core.joinedTranscript
import java.io.ByteArrayOutputStream
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.Executors

/** 모델 실행은 한 번에 하나(서버 voice의 락과 같다) — 인식·구조화가 이 스레드에서 줄을 선다 */
val modelDispatcher: ExecutorCoroutineDispatcher = Executors.newSingleThreadExecutor { r -> Thread(r, "models") }.asCoroutineDispatcher()

/**
 * 통화 한 건. voice/app.py + live_transcriber.py가 하던 일을 휴대폰 안에서 한다(아이폰 CallSession.swift와 같은 흐름).
 *
 *   마이크 -> (0.5초마다) 무음 감지로 발화 자르기 -> ASR 큐(녹음은 인식에 밀리지 않고 계속 쌓임) -> 이 화면의 자막
 *   [전송] -> 남은 소리 인식 -> 줄바꿈으로 이어 MF_BERT -> 요약 전송(지금 voice와 같은 JSON)
 *   [취소] -> 녹음·인식을 멈추고 버린다(아무것도 보내지 않음)
 *
 * [전송]을 눌러야만 기기 밖으로 나간다 — 통화 중 인식 결과는 이 화면 자막에만 쓴다. 요약은 hub WebSocket으로 보낸다.
 * 서버 STT 모드(모델이 없거나 설정에서 끔)는 웹과 똑같이 PCM을 hub WebSocket으로 흘려보내기만 한다.
 */
class CallSession(
    private val context: Context,
    val caseId: String,
    private val models: ModelStore?,
    private val sendPcm: ((ByteArray) -> Unit)?,
    private val sendSummary: suspend (JsonObject) -> String?,
    silenceRms: Float,
    holdSec: Float,
    private val scope: CoroutineScope,
) {
    sealed interface Stage {
        data object Recording : Stage
        data object Finishing : Stage
        data object Structuring : Stage
        data object Sent : Stage
        data object NoSpeech : Stage
        data object Cancelled : Stage
        data class Failed(val reason: String) : Stage
    }

    val startedAt = System.currentTimeMillis()
    val lines = mutableStateListOf<RecognizedSegment>()
    var stage by mutableStateOf<Stage>(Stage.Recording)
        private set
    var level by mutableFloatStateOf(0f)
        private set

    private val segmenter = UtteranceSegmenter(silenceRms, holdSec.toDouble())
    private val pending = ArrayList<FloatArray>()
    private val allAudio = ByteArrayOutputStream()  // 원본 보존(통화 wav, 16비트) — 108초 통화 ≈ 3.5MB
    private var pollJob: Job? = null
    private var asrChain: Job? = null
    private val mic = MicCapture(
        onSamples = { samples ->
            if (sendPcm != null) sendPcm.invoke(pcm16(samples)) else synchronized(pending) { pending += samples }
        },
        onLevel = { v -> scope.launch(Dispatchers.Main) { level = v } },
    )

    fun start() {
        mic.start()
        CallService.start(context)
        if (models == null) return
        pollJob = scope.launch(Dispatchers.Main) {
            while (isActive) {
                delay(500)  // POLL_SEC
                poll(final = false)
            }
        }
    }

    /** [취소] — 마이크·인식을 멈추고 녹음을 버린다. 요약을 만들지도 보내지도 않는다 */
    fun cancel() {
        mic.stop()
        CallService.stop(context)
        pollJob?.cancel()
        asrChain?.cancel()
        synchronized(pending) { pending.clear() }
        allAudio.reset()
        stage = Stage.Cancelled
    }

    /** [전송] — 마이크를 끄고 남은 처리(인식·구조화)를 마쳐 요약을 보낸다 */
    suspend fun finish() {
        mic.stop()
        CallService.stop(context)
        pollJob?.cancel()
        if (models == null) { stage = Stage.Sent; return }  // 서버 STT: 요약은 중앙 voice가 보낸다
        stage = Stage.Finishing
        poll(final = true)
        asrChain?.join()
        val pcm = allAudio.toByteArray()
        val duration = pcm.size / 2.0 / SAMPLE_RATE
        val segments = lines.toList()
        val text = joinedTranscript(segments)
        if (text.isEmpty()) {  // voice와 같이 인식된 발화가 없으면 요약을 보내지 않는다
            Archive.save(context, caseId, pcm, text, null)
            stage = Stage.NoSpeech
            return
        }
        stage = Stage.Structuring
        try {
            val summary = withContext(modelDispatcher) { models.extract(text) }
            val message = buildCallSummary(caseId, segments, startedAt, duration, summary)
            Archive.save(context, caseId, pcm, text, message)
            val error = sendSummary(message)
            stage = if (error != null) Stage.Failed(error) else Stage.Sent
        } catch (t: Throwable) {
            Archive.save(context, caseId, pcm, text, null)
            stage = Stage.Failed("구조화 실패: ${t.message ?: t}")
        }
    }

    private fun poll(final: Boolean) {
        val samples = synchronized(pending) { val all = pending.toList(); pending.clear(); all }
        for (s in samples) {
            allAudio.write(pcm16(s))
            segmenter.append(s)
        }
        for (u in segmenter.poll(final)) enqueue(u)
    }

    /** 발화를 순서대로 하나씩 인식한다(앞 인식이 끝나야 다음 — 서버의 락과 같다) */
    private fun enqueue(u: Utterance) {
        val models = models ?: return
        val previous = asrChain
        asrChain = scope.launch(Dispatchers.Main) {
            previous?.join()
            val segs = withContext(modelDispatcher) { models.transcribe(u.audio) }
            if (stage == Stage.Cancelled) return@launch
            // 이 화면 자막에만 — [전송] 전엔 기기 밖으로 보내지 않는다
            for (s in segs) lines += RecognizedSegment(u.offsetSec + s.start, u.offsetSec + s.end, s.text)
        }
    }
}

/**
 * 원본 보존(사후 검증·audit trail) — voice가 통화 wav·STT 원문·요약 JSON을 남기는 것과 같다.
 * 앱 전용 폴더 Android/data/xyz.goldenlink.phone/files/calls/<caseId>/ — 다른 앱은 읽을 수 없고(Android 11+ 범위 저장소),
 * 대조할 때 PC에서 adb pull로 꺼낼 수 있다(모델 폴더와 같은 곳). 환자 음성은 네트워크로 나가지 않는다.
 */
object Archive {
    fun save(context: Context, caseId: String, pcm: ByteArray, transcript: String, summary: JsonObject?) {
        runCatching {
            val dir = File(context.getExternalFilesDir(null) ?: context.filesDir, "calls/$caseId").apply { mkdirs() }
            File(dir, "call.wav").writeBytes(wav(pcm))
            File(dir, "transcript.txt").writeText(transcript)
            if (summary != null) File(dir, "call_summary.json").writeText(summary.toString())
        }
    }

    /** 16kHz 모노 16비트 wav */
    private fun wav(pcm: ByteArray): ByteArray {
        val b = ByteBuffer.allocate(44 + pcm.size).order(ByteOrder.LITTLE_ENDIAN)
        b.put("RIFF".toByteArray()); b.putInt(36 + pcm.size); b.put("WAVEfmt ".toByteArray())
        b.putInt(16); b.putShort(1); b.putShort(1); b.putInt(SAMPLE_RATE); b.putInt(SAMPLE_RATE * 2); b.putShort(2); b.putShort(16)
        b.put("data".toByteArray()); b.putInt(pcm.size); b.put(pcm)
        return b.array()
    }
}
