package xyz.goldenlink.core

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.FloatBuffer
import java.nio.LongBuffer

/*
 * 온디바이스 모델 실행 — dashboard/android/convert/가 만든 ONNX(fp32, 양자화 없음)를 onnxruntime(CPU)으로 돌린다.
 * onnxruntime의 Java API는 PC(onnxruntime)와 안드로이드(onnxruntime-android)가 같아서, 앱과 똑같은 이 코드를 PC에서
 * 실제 모델로 테스트한다(OnDeviceE2ETest — 서버 voice와 같은 문장·요약이 나오는지).
 */

internal val env: OrtEnvironment by lazy { OrtEnvironment.getEnvironment() }

private fun options(threads: Int) = OrtSession.SessionOptions().apply {
    // 그래프 최적화 수준은 기본값(ALL) 그대로 — PC 대조(check_*.py, onnxruntime 기본값)와 같은 실행이 되게 한다
    setIntraOpNumThreads(threads)
}

/** Qwen3-ASR-0.6B + LoRA(합친 것). voice/asr.py와 같은 규칙: 5초 넘으면 조용한 곳에서 자르고, 구간마다 그리디 인식 */
class AsrRunner(dir: File, threads: Int) : AutoCloseable {
    private val encoder = env.createSession(File(dir, "asr_audio_encoder.onnx").path, options(threads))
    private val decoder = env.createSession(File(dir, "asr_decoder.onnx").path, options(threads))
    private val melFilters: FloatArray = File(dir, "asr_mel_filters.bin").readBytes().let { bytes ->
        val buf = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer()
        FloatArray(buf.remaining()).also { buf.get(it) }
    }
    val tokens = AsrTokens(File(dir, "asr_tokens.json").readText())

    /** 발화 하나 -> 구간들(발화 시작 기준 초). 빈 구간은 버린다 */
    fun transcribe(audio: FloatArray): List<RecognizedSegment> = splitChunks(audio).mapNotNull { r ->
        val text = transcribeChunk(audio.copyOfRange(r.first, r.last + 1))
        if (text.isEmpty()) null else RecognizedSegment(r.first.toDouble() / SAMPLE_RATE, (r.last + 1).toDouble() / SAMPLE_RATE, text)
    }

    private fun transcribeChunk(piece: FloatArray): String {
        val mel = melFeatures(piece, melFilters)
        val inputs = encoderInputs(mel)
        val t = inputs.validIndex.size
        val embeds: FloatArray
        val hidden: Int
        OnnxTensor.createTensor(env, FloatBuffer.wrap(inputs.chunks), longArrayOf(inputs.chunkCount.toLong(), 1, 128, 100)).use { c ->
            OnnxTensor.createTensor(env, LongBuffer.wrap(inputs.validIndex), longArrayOf(t.toLong())).use { idx ->
                OnnxTensor.createTensor(env, FloatBuffer.wrap(inputs.attnBias), longArrayOf(t.toLong(), t.toLong())).use { bias ->
                    encoder.run(mapOf("chunks" to c, "valid_index" to idx, "attn_bias" to bias)).use { out ->
                        val e = out.get(0) as OnnxTensor
                        hidden = e.info.shape[1].toInt()
                        embeds = FloatArray(t * hidden).also { e.floatBuffer.get(it) }
                    }
                }
            }
        }
        check(t == audioTokenCount(mel.validFrames)) { "오디오 토큰 수 불일치 $t" }
        val audioTensor = OnnxTensor.createTensor(env, FloatBuffer.wrap(embeds), longArrayOf(t.toLong(), hidden.toLong()))
        val noAudio = OnnxTensor.createTensor(env, FloatBuffer.allocate(hidden), longArrayOf(1, hidden.toLong()))
        val step = KvDecoder(audioTensor, noAudio)
        try {
            val ids = greedy(step, tokens.prompt(t), tokens.eosTokenIds, tokens.maxNewTokens)
            return asrTranscription(tokens.decode(ids))
        } finally {
            step.close()
            audioTensor.close()
            noAudio.close()
        }
    }

    /** KV 캐시를 들고 한 걸음씩 — 첫 걸음(프롬프트)만 오디오 임베딩을 넣고, 이후엔 오디오 자리가 없어 쓰이지 않는 1행을 넣는다 */
    private inner class KvDecoder(private val audio: OnnxTensor, private val noAudio: OnnxTensor) : DecoderStep, AutoCloseable {
        private val shape0 = longArrayOf(tokens.layers.toLong(), 1, tokens.kvHeads.toLong(), 0, tokens.headDim.toLong())
        private var pastK: OnnxTensor = OnnxTensor.createTensor(env, FloatBuffer.allocate(0), shape0)
        private var pastV: OnnxTensor = OnnxTensor.createTensor(env, FloatBuffer.allocate(0), shape0)
        private var last: OrtSession.Result? = null
        private var first = true

        override fun next(ids: LongArray): FloatArray {
            OnnxTensor.createTensor(env, LongBuffer.wrap(ids), longArrayOf(1, ids.size.toLong())).use { input ->
                val out = decoder.run(mapOf("input_ids" to input, "audio_embeds" to if (first) audio else noAudio,
                    "past_key" to pastK, "past_value" to pastV))
                first = false
                // 앞 걸음의 KV(이전 결과)는 이번 실행에 들어갔으니 닫는다
                if (last == null) { pastK.close(); pastV.close() } else last!!.close()
                last = out
                pastK = out.get("present_key").get() as OnnxTensor
                pastV = out.get("present_value").get() as OnnxTensor
                val logits = out.get("logits").get() as OnnxTensor
                return FloatArray(logits.info.shape[1].toInt()).also { logits.floatBuffer.get(it) }
            }
        }

        override fun close() {
            if (last == null) { pastK.close(); pastV.close() } else last!!.close()
        }
    }

    override fun close() { encoder.close(); decoder.close() }
}

/**
 * MF_BERT 온디바이스(AI 처리, 생성형 아님). 아이폰 MFBertRunner·convert/mf_bert_split.py run_split()과 같은 순서:
 * 조각마다 인코더 -> keep 행만 골라 이어 붙임 -> 헤드 -> decode(규칙 해석 포함)
 */
class MfBertRunner(dir: File, threads: Int) : AutoCloseable {
    private val encoder = env.createSession(File(dir, "mf_bert_encoder.onnx").path, options(threads))
    private val heads = env.createSession(File(dir, "mf_bert_heads.onnx").path, options(threads))
    private val tokenizer = WordPieceTokenizer(File(dir, "mf_bert_tokenizer.json"))
    private val headNames: List<String> = Json.parseToJsonElement(File(dir, "mf_bert_meta.json").readText())
        .jsonObject["heads"]!!.jsonArray.map { it.jsonPrimitive.content }

    /** 통화 텍스트 1건 -> v2 summary */
    fun extract(text: String): JsonObject {
        val c = chunkText(text, tokenizer)
        val total = c.keep.sumOf { it.size }
        var hidden: FloatArray? = null
        var n = 0
        var h = 0
        var t0 = 0
        for ((chunk, keep) in c.chunks.zip(c.keep)) {
            val ids = LongArray(chunk.size) { chunk[it].toLong() }
            OnnxTensor.createTensor(env, LongBuffer.wrap(ids), longArrayOf(1, ids.size.toLong())).use { input ->
                encoder.run(mapOf("input_ids" to input)).use { out ->
                    val layer = out.get(0) as OnnxTensor  // (N, L, H)
                    val shape = layer.info.shape
                    if (hidden == null) {
                        n = shape[0].toInt(); h = shape[2].toInt()
                        hidden = FloatArray(n * total * h)
                    }
                    val l = shape[1].toInt()
                    val src = FloatArray(n * l * h).also { layer.floatBuffer.get(it) }
                    for (layerIdx in 0 until n) for ((j, row) in keep.withIndex()) {
                        System.arraycopy(src, (layerIdx * l + row) * h, hidden!!, (layerIdx * total + t0 + j) * h, h)
                    }
                }
            }
            t0 += keep.size
        }
        val logits = HashMap<String, FloatArray>()
        var tags = IntArray(0)
        OnnxTensor.createTensor(env, FloatBuffer.wrap(hidden!!), longArrayOf(n.toLong(), total.toLong(), h.toLong())).use { input ->
            heads.run(mapOf("hidden" to input)).use { out ->
                for ((i, name) in headNames.withIndex()) {
                    val v = out.get(i) as OnnxTensor
                    val arr = FloatArray(v.info.shape.fold(1L) { a, b -> a * b }.toInt()).also { v.floatBuffer.get(it) }
                    if (name == "spans") {
                        val tagCount = v.info.shape[2].toInt()
                        tags = IntArray(total) { r ->  // 토큰별 argmax(같으면 앞쪽)
                            var best = 0
                            for (k in 1 until tagCount) if (arr[r * tagCount + k] > arr[r * tagCount + best]) best = k
                            best
                        }
                    } else {
                        logits[name] = arr
                    }
                }
            }
        }
        check(Labels.shared.sentenceHeads.all { it in logits }) { "헤드 출력이 모자랍니다" }
        return decode(text, MFBertLogits(logits, tags), c.offsets)
    }

    override fun close() { encoder.close(); heads.close() }
}

