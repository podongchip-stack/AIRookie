package xyz.goldenlink.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.ByteArrayOutputStream
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.sin

/*
 * Qwen3-ASR의 그래프 밖 계산 — dashboard/android/convert/qwen3_asr_split.py의 mel_features / encoder_inputs /
 * audio_token_count / greedy와, check_qwen3_asr.py의 TokenDecoder · transformers _parse_single_output을 옮겼다.
 * 그래프(오디오 인코더·디코더)는 앱이 onnxruntime으로 돌린다. 이 파일은 모델 없이 PC에서 테스트된다.
 */

const val N_FFT = 400
const val HOP = 160
const val N_MELS = 128
private const val MIN_SAMPLES = 8000          // 0.5초보다 짧으면 0으로 채운다
const val CHUNK_FRAMES = 100                  // n_window * 2
const val TOKENS_PER_CHUNK = 13               // 100프레임 -> 합성곱 3층(stride 2) 뒤 13
const val WINDOW_TOKENS = 13 * 8              // n_window_infer 800프레임 = 104토큰 안에서만 서로 본다

class MelResult(
    /** (128, frames) 행 우선 */
    val features: FloatArray,
    val frames: Int,
    val validFrames: Int,
)

/**
 * 16kHz float32 -> log-mel. 서버(voice/asr.py)의 processor.apply_chat_template와 같은 계산 — 특징 추출기가
 * padding="longest"(30초로 채우지 않음)로 돈다: 0.5초 미만은 0으로 채우고, torch.stft(center=True, 실제 오디오 끝에서 reflect,
 * hann periodic, n_fft 400, hop 160, 마지막 프레임 버림) 파워 -> 멜 필터 -> log10(1e-10 하한) -> 최댓값-8 하한 -> (x+4)/4.
 * 유효 프레임 = 샘플수 / 160(내림), 100프레임 배수까지 0으로 채운다.
 * melFilters: (201, 128) 행 우선 — convert_qwen3_asr.py가 저장한 asr_mel_filters.bin.
 */
fun melFeatures(input: FloatArray, melFilters: FloatArray): MelResult {
    val audio = if (input.size < MIN_SAMPLES) input.copyOf(MIN_SAMPLES) else input
    val n = audio.size
    val frames = n / HOP  // stft 프레임 n/HOP + 1개 중 마지막을 버림 = 유효 프레임(마스크)과 같다
    val used = ((frames + CHUNK_FRAMES - 1) / CHUNK_FRAMES) * CHUNK_FRAMES
    val bins = N_FFT / 2 + 1
    val half = N_FFT / 2
    val window = DoubleArray(N_FFT) { 0.5 - 0.5 * cos(2 * PI * it / N_FFT) }  // torch.hann_window(periodic)
    val cosT = Array(bins) { k -> DoubleArray(N_FFT) { t -> cos(2 * PI * ((k.toLong() * t) % N_FFT) / N_FFT) } }
    val sinT = Array(bins) { k -> DoubleArray(N_FFT) { t -> sin(2 * PI * ((k.toLong() * t) % N_FFT) / N_FFT) } }
    fun sample(i: Int): Double {  // 앞뒤 half칸을 reflect로 채운 신호의 i번째
        var j = i - half
        if (j < 0) j = -j
        if (j >= n) j = 2 * (n - 1) - j
        return audio[j].toDouble()
    }
    val logs = Array(N_MELS) { DoubleArray(frames) }
    val x = DoubleArray(N_FFT)
    val power = DoubleArray(bins)
    var maxLog = Double.NEGATIVE_INFINITY
    for (f in 0 until frames) {
        for (t in 0 until N_FFT) x[t] = sample(f * HOP + t) * window[t]
        // 400점 DFT를 직접 계산(2의 거듭제곱이 아니다). 5초 발화 500프레임이면 휴대폰에서도 1초 안쪽
        for (k in 0 until bins) {
            var sr = 0.0
            var si = 0.0
            val c = cosT[k]
            val s = sinT[k]
            for (t in 0 until N_FFT) { sr += x[t] * c[t]; si -= x[t] * s[t] }
            power[k] = sr * sr + si * si
        }
        for (m in 0 until N_MELS) {
            var acc = 0.0
            for (k in 0 until bins) acc += melFilters[k * N_MELS + m].toDouble() * power[k]
            val v = log10(max(acc, 1e-10))
            logs[m][f] = v
            if (v > maxLog) maxLog = v
        }
    }
    val out = FloatArray(N_MELS * used)  // 100프레임 배수까지 남는 칸은 0(특징 추출기와 같다)
    for (m in 0 until N_MELS) for (f in 0 until frames) {
        out[m * used + f] = ((max(logs[m][f], maxLog - 8.0) + 4.0) / 4.0).toFloat()
    }
    return MelResult(out, used, frames)
}

fun audioTokenCount(validFrames: Int): Int {
    val rem = validFrames % CHUNK_FRAMES
    val feat = Math.floorDiv(rem - 1, 2) + 1
    val per = Math.floorDiv(feat - 1, 2) + 1
    return Math.floorDiv(per - 1, 2) + 1 + (validFrames / CHUNK_FRAMES) * TOKENS_PER_CHUNK
}

private fun postCnn(length: Int): Int {
    var l = length
    repeat(3) { l = if (l > 0) (l - 1) / 2 + 1 else 0 }
    return l
}

class EncoderInputs(
    /** (C, 1, 128, 100) 행 우선 */
    val chunks: FloatArray,
    val chunkCount: Int,
    val validIndex: LongArray,
    /** (T, T) — 같은 창이면 0, 아니면 -inf */
    val attnBias: FloatArray,
)

fun encoderInputs(mel: MelResult): EncoderInputs {
    val c = mel.frames / CHUNK_FRAMES
    val chunks = FloatArray(c * N_MELS * CHUNK_FRAMES)
    for (i in 0 until c) for (m in 0 until N_MELS) {
        System.arraycopy(mel.features, m * mel.frames + i * CHUNK_FRAMES, chunks, (i * N_MELS + m) * CHUNK_FRAMES, CHUNK_FRAMES)
    }
    val index = ArrayList<Long>()
    for (i in 0 until c) {
        val inChunk = (mel.validFrames - i * CHUNK_FRAMES).coerceIn(0, CHUNK_FRAMES)
        for (j in 0 until postCnn(inChunk)) index += (i * TOKENS_PER_CHUNK + j).toLong()
    }
    val t = index.size
    val bias = FloatArray(t * t) { k -> if ((k / t) / WINDOW_TOKENS == (k % t) / WINDOW_TOKENS) 0f else Float.NEGATIVE_INFINITY }
    return EncoderInputs(chunks, c, index.toLongArray(), bias)
}

// ── 토큰 ──

class AsrTokens(json: String) {
    val promptBefore: List<Int>
    val promptAfter: List<Int>
    val audioTokenId: Int
    val eosTokenIds: Set<Int>
    val maxNewTokens: Int
    val layers: Int
    val kvHeads: Int
    val headDim: Int
    val hidden: Int
    private val vocab: Map<Int, String>
    private val special: Set<String>

    init {
        val o = Json.parseToJsonElement(json).jsonObject
        fun ints(k: String) = o[k]!!.jsonArray.map { it.jsonPrimitive.int }
        promptBefore = ints("prompt_before")
        promptAfter = ints("prompt_after")
        audioTokenId = o["audio_token_id"]!!.jsonPrimitive.int
        eosTokenIds = ints("eos_token_ids").toSet()
        maxNewTokens = o["max_new_tokens"]!!.jsonPrimitive.int
        layers = o["layers"]!!.jsonPrimitive.int
        kvHeads = o["kv_heads"]!!.jsonPrimitive.int
        headDim = o["head_dim"]!!.jsonPrimitive.int
        hidden = o["hidden"]!!.jsonPrimitive.int
        vocab = o["vocab"]!!.jsonObject.entries.associate { it.key.toInt() to it.value.jsonPrimitive.content }
        special = o["special_tokens"]!!.jsonArray.map { it.jsonPrimitive.content }.toSet()
    }

    fun prompt(audioTokens: Int): List<Int> = promptBefore + List(audioTokens) { audioTokenId } + promptAfter

    /** id 목록 -> 문자열(특수 토큰 제외). GPT-2 바이트 BPE를 바이트로 되돌려 UTF-8로 푼다(깨진 바이트는 U+FFFD) */
    fun decode(ids: List<Int>): String {
        val bytes = ByteArrayOutputStream()
        for (id in ids) {
            val piece = vocab[id] ?: continue
            if (piece in special) continue
            var i = 0
            while (i < piece.length) {
                val cp = piece.codePointAt(i)
                bytes.write(BYTE_OF[cp] ?: error("바이트 BPE 표에 없는 글자: $cp"))
                i += Character.charCount(cp)
            }
        }
        return String(bytes.toByteArray(), Charsets.UTF_8)
    }

    companion object {
        /** GPT-2 바이트 BPE 표(글자 -> 바이트). Qwen 토크나이저도 같다 */
        val BYTE_OF: Map<Int, Int> = run {
            val bs = ArrayList<Int>()
            bs += ('!'.code..'~'.code); bs += ('¡'.code..'¬'.code); bs += ('®'.code..'ÿ'.code)
            val cs = ArrayList(bs)
            var n = 0
            for (b in 0 until 256) if (b !in bs) { bs += b; cs += 256 + n; n += 1 }
            cs.indices.associate { cs[it] to bs[it] }
        }
    }
}

// ── 결과 정리: transformers processing_qwen3_asr._parse_single_output(반복 정리 + <asr_text> 뒤 추출) ──

/** processor.decode(return_format="transcription_only")와 같다 */
fun asrTranscription(decoded: String?): String {
    if (decoded == null || decoded.isBlank()) return ""
    var text = decoded.trim()
    val marker = "assistant\n"
    val ai = text.indexOf(marker)
    if (ai >= 0) text = text.substring(ai + marker.length)
    text = fixRepetitions(text)
    val tag = "<asr_text>"
    val ti = text.indexOf(tag)
    if (ti < 0) return text.trim()
    return text.substring(ti + tag.length).trim()
}

/** _detect_and_fix_repetitions(threshold=20) — 코드포인트 단위(Python 문자열과 같게) */
fun fixRepetitions(text: String, threshold: Int = 20): String {
    val cps = text.codePoints().toArray().toList()
    fun fixCharRepeats(s: List<Int>, thresh: Int): List<Int> {
        val res = ArrayList<Int>()
        var i = 0
        val n = s.size
        while (i < n) {
            var count = 1
            while (i + count < n && s[i + count] == s[i]) count += 1
            if (count > thresh) res += s[i] else res += s.subList(i, i + count)
            i += count
        }
        return res
    }
    fun fixPatternRepeats(s: List<Int>, thresh: Int, maxLen: Int = 20): List<Int> {
        val n = s.size
        val minRepeatChars = thresh * 2
        if (n < minRepeatChars) return s
        var i = 0
        val result = ArrayList<Int>()
        var found = false
        while (i <= n - minRepeatChars) {
            found = false
            for (k in 1..maxLen) {
                if (i + k * thresh > n) break
                val pattern = s.subList(i, i + k)
                var valid = true
                for (rep in 1 until thresh) {
                    val st = i + rep * k
                    if (s.subList(minOf(st, n), minOf(st + k, n)) != pattern) { valid = false; break }
                }
                if (valid) {
                    var endIndex = i + thresh * k
                    while (endIndex + k <= n && s.subList(endIndex, endIndex + k) == pattern) endIndex += k
                    result += pattern
                    result += fixPatternRepeats(s.subList(endIndex, n), thresh, maxLen)
                    i = n
                    found = true
                    break
                }
            }
            if (found) break else { result += s[i]; i += 1 }
        }
        if (!found) result += s.subList(minOf(i, n), n)
        return result
    }
    val out = fixPatternRepeats(fixCharRepeats(cps, threshold), threshold)
    return String(out.toIntArray(), 0, out.size)
}

/** 그리디 생성 — generate(do_sample=False)와 같다: 프롬프트 한 번에 넣고 이후 한 토큰씩, eos가 나오면 멈춤(eos는 결과에 안 넣음) */
fun interface DecoderStep {
    /** ids(1, S)와 지금까지의 KV를 받아 마지막 위치 로짓을 돌려준다. KV는 구현이 들고 있는다 */
    fun next(ids: LongArray): FloatArray
}

fun greedy(step: DecoderStep, prompt: List<Int>, eos: Set<Int>, maxNewTokens: Int): List<Int> {
    val out = ArrayList<Int>()
    var ids = LongArray(prompt.size) { prompt[it].toLong() }
    repeat(maxNewTokens) {
        val logits = step.next(ids)
        var best = 0
        for (i in 1 until logits.size) if (logits[i] > logits[best]) best = i
        if (best in eos) return out
        out += best
        ids = longArrayOf(best.toLong())
    }
    return out
}
