package xyz.goldenlink.core

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import kotlin.math.sqrt

/*
 * voice/live_transcriber.py의 무음 감지 발화 자르기(아이폰 UtteranceSegmenter.swift와 같은 코드).
 * 소리 크기(RMS)만 본다 — 현장이 시끄러워 발화가 안 끊기면 silenceRMS를 올리고, 말하는 중에 자꾸 끊기면 holdSec을 늘린다.
 */
const val SAMPLE_RATE = 16000
const val FRAME_SAMPLES = SAMPLE_RATE / 10  // 0.1초 — 무음 판정 단위
private const val MIN_SPEECH_SEC = 0.6  // 이보다 짧은 소리는 발화로 보지 않는다(기침·잡음)
private const val MAX_UTTERANCE_SEC = 12.0  // 쉬지 않고 말하면 여기서 가장 조용한 지점을 찾아 끊는다
private const val KEEP_SILENCE_SEC = 0.5  // 말이 없을 때 버퍼에 남겨 두는 길이

fun frameRms(audio: FloatArray, from: Int = 0, to: Int = audio.size): FloatArray {
    val count = (to - from) / FRAME_SAMPLES
    return FloatArray(count) { i ->
        val lo = from + i * FRAME_SAMPLES
        var sum = 0f
        for (k in lo until lo + FRAME_SAMPLES) sum += audio[k] * audio[k]
        sqrt(sum / FRAME_SAMPLES)
    }
}

/** 버퍼에서 발화가 끝난 지점(샘플 위치). 끊을 곳이 없으면 null. */
fun findUtteranceEnd(rms: FloatArray, threshold: Float, holdFrames: Int): Int? {
    val first = rms.indexOfFirst { it >= threshold }
    val last = rms.indexOfLast { it >= threshold }
    if (first < 0 || last < 0) return null
    if ((last - first + 1) * FRAME_SAMPLES < MIN_SPEECH_SEC * SAMPLE_RATE) return null
    val trailing = rms.size - 1 - last
    if (trailing >= holdFrames) return minOf(last + 1 + holdFrames / 2, rms.size) * FRAME_SAMPLES
    if (rms.size * FRAME_SAMPLES >= MAX_UTTERANCE_SEC * SAMPLE_RATE) {
        val tailStart = maxOf(0, rms.size - 20)
        var quietest = tailStart  // np.argmin: 같으면 앞쪽
        for (i in tailStart until rms.size) if (rms[i] < rms[quietest]) quietest = i
        return (quietest + 1) * FRAME_SAMPLES
    }
    return null
}

class Utterance(
    /** 통화 시작 기준 초 */
    val offsetSec: Double,
    val audio: FloatArray,
)

/** 녹음 버퍼를 들고 있다가(append) 잘라낸 발화를 poll()이 돌려준다. ASR 호출은 하지 않는다(호출한 쪽이 큐로 돌린다). */
class UtteranceSegmenter(val threshold: Float = 0.01f, holdSec: Double = 0.4) {
    private val holdFrames = maxOf(1, Math.rint(holdSec * SAMPLE_RATE / FRAME_SAMPLES).toInt())
    private var buffer = FloatArray(0)
    private var consumed = 0L  // 통화 시작부터 이미 잘라냈거나 무음으로 버린 샘플 수

    fun append(samples: FloatArray) { buffer += samples }

    /** 0.5초마다 부른다(POLL_SEC). final이면 남은 소리에 기준 이상 소리가 있으면 그것도 발화로 낸다. */
    fun poll(final: Boolean = false): List<Utterance> {
        val out = ArrayList<Utterance>()
        while (true) {
            val cut = findUtteranceEnd(frameRms(buffer), threshold, holdFrames) ?: break
            take(cut, out)
        }
        val rms = frameRms(buffer)
        val hasSpeech = rms.any { it >= threshold }
        if (final) {
            if (hasSpeech) take(buffer.size, out)
            buffer = FloatArray(0)
            return out
        }
        // 말이 하나도 없는 버퍼는 끝부분만 남긴다(가만히 있는 동안 버퍼가 계속 커지지 않게)
        val keep = (KEEP_SILENCE_SEC * SAMPLE_RATE).toInt()
        if (rms.isNotEmpty() && !hasSpeech && buffer.size > keep) {
            val drop = buffer.size - keep
            buffer = buffer.copyOfRange(drop, buffer.size)
            consumed += drop
        }
        return out
    }

    private fun take(n: Int, out: MutableList<Utterance>) {
        out += Utterance(consumed.toDouble() / SAMPLE_RATE, buffer.copyOfRange(0, n))
        buffer = buffer.copyOfRange(n, buffer.size)
        consumed += n
    }
}

/** asr.py split_chunks(): 5초를 넘는 발화는 목표 길이 앞 3초 안에서 가장 조용한 0.1초 지점에서 자른다. [start, end) 목록 */
fun splitChunks(audio: FloatArray, chunkSec: Double = 5.0): List<IntRange> {
    val total = audio.size
    val maxLen = (chunkSec * SAMPLE_RATE).toInt()
    if (total <= maxLen) return listOf(0 until total)
    val search = 3 * SAMPLE_RATE
    val bounds = ArrayList<IntRange>()
    var start = 0
    while (total - start > maxLen) {
        val target = start + maxLen
        val lo = maxOf(start + FRAME_SAMPLES, target - search)
        // Python은 (rms, 위치) 튜플의 min — rms가 같으면 앞쪽 위치
        var cut = lo
        var best = Float.POSITIVE_INFINITY
        var p = lo
        while (p < target) {
            val hi = minOf(p + FRAME_SAMPLES, total)
            var sum = 0f
            for (k in p until hi) sum += audio[k] * audio[k]
            val e = sqrt(sum / (hi - p))
            if (e < best) { best = e; cut = p }
            p += FRAME_SAMPLES
        }
        bounds += start until cut
        start = cut
    }
    bounds += start until total
    return bounds
}

// ── 통화 요약 JSON ──

/** 인식된 발화 하나(통화 시작 기준 초) */
data class RecognizedSegment(val start: Double, val end: Double, val text: String)

/** model_used — 서버 처리분과 구분하려고 -android를 붙인다(사후 대조용) */
const val ANDROID_STT_NAME = "qwen3-asr-0.6b-119ko-tiny-android"
const val ANDROID_LLM_NAME = "mf-bert-klue-roberta-large-android"

/** MF_BERT 입력이자 transcript.raw_text — 발화를 줄바꿈으로 잇는다(voice와 같게) */
fun joinedTranscript(segments: List<RecognizedSegment>): String = segments.joinToString("\n") { it.text }

/**
 * voice/transcribe.py build_call_summary_message() + CallSummaryMessage.to_payload()와 같은 JSON(아이폰 CallSummary.swift와 같다).
 * voice는 통화 시작 시각을 "지금 - 길이"로 근사하지만, 앱은 실제 시작 시각을 알아 그대로 쓴다.
 */
fun buildCallSummary(caseId: String, segments: List<RecognizedSegment>, callStartMillis: Long, durationSec: Double,
                     summary: JsonElement): JsonObject {
    val full = joinedTranscript(segments)
    val utc = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss'Z'").withZone(ZoneOffset.UTC)
    val hms = DateTimeFormatter.ofPattern("HH:mm:ss").withZone(ZoneOffset.UTC)  // voice와 같이 UTC 기준 시:분:초
    val turns = segments.map { s ->
        jObj("speaker" to JsonPrimitive("미분리"),
            "timestamp" to JsonPrimitive(hms.format(Instant.ofEpochMilli(callStartMillis + (s.start * 1000).toLong()))),
            "text" to JsonPrimitive(s.text))
    }
    return jObj(
        "caseId" to JsonPrimitive(caseId),
        "transcript" to jObj(
            "raw_text" to JsonPrimitive(full),
            "filtered_text" to JsonPrimitive(full),  // 교정 단계가 없어 raw_text와 같다(계약 필드라 유지)
            "language" to JsonPrimitive("ko"),
            "timestamp" to JsonPrimitive(utc.format(Instant.ofEpochMilli(callStartMillis))),
            "duration_sec" to JsonPrimitive(Math.rint(durationSec * 10) / 10),
            "turns" to jArr(turns),
        ),
        "summary" to summary,
        "source" to JsonPrimitive("ai"),
        "model_used" to jObj("stt" to JsonPrimitive(ANDROID_STT_NAME), "llm" to JsonPrimitive(ANDROID_LLM_NAME)),
    )
}
