package xyz.goldenlink.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.double
import kotlinx.serialization.json.float
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Assumptions.assumeTrue
import org.junit.jupiter.api.Test
import java.io.File
import kotlin.math.abs
import kotlin.math.sin

/**
 * Python 원본(voice/)과의 일치 검사. 정답은 아이폰과 같은 파일을 쓴다 — dashboard/iphone/convert/make_fixtures.py가 만든
 * fixtures.json(토크나이저·조각·parse·decode·발화 자르기). ASR 정답은 dashboard/android/convert/check_qwen3_asr.py --fixtures가
 * 만든 fixtures/asr_fixtures.json(멜·프롬프트·토큰 풀기·결과 정리)이다.
 */
class ParityTest {
    private val android = File(System.getProperty("user.dir")).let { if (it.name == "core") it.parentFile else it }
    private val fixtures: JsonObject by lazy {
        Json.parseToJsonElement(File(android, "../iphone/GoldenLinkCore/Tests/GoldenLinkCoreTests/Fixtures/fixtures.json").readText()).jsonObject
    }
    private val models = File(android, "Models")

    private fun arr(key: String) = fixtures[key]!!.jsonArray
    private fun ints(v: JsonElement?) = v!!.jsonArray.map { it.jsonPrimitive.int }
    private fun pairs(v: JsonElement?) = v!!.jsonArray.map { ints(it) }
    private fun str(v: JsonElement?) = v!!.jsonPrimitive.content

    private fun tokenizer(): WordPieceTokenizer {
        val candidates = listOfNotNull(
            System.getenv("MF_BERT_TOKENIZER")?.let(::File),
            File(models, "mf_bert_tokenizer.json"),
            File(System.getProperty("user.home"),
                ".cache/huggingface/hub/models--podongchip--MF_BERT/snapshots/f1d3e1dbd41424e1bb32cf4aded891ed48b39df6/tokenizer/tokenizer.json"),
        )
        val file = candidates.firstOrNull { it.isFile }
        assumeTrue(file != null, "tokenizer.json 없음")
        return WordPieceTokenizer(file!!)
    }

    @Test fun numberRegexMatchesPython() = assertEquals(str(fixtures["number_re"]), NUMBER_RE)

    @Test fun tokenizerMatches() {
        val tok = tokenizer()
        for (c in arr("tokenizer")) {
            val o = c.jsonObject
            val (ids, offsets) = tok.encode(str(o["text"]))
            assertEquals(ints(o["ids"]), ids, str(o["text"]))
            assertEquals(pairs(o["offsets"]), offsets.map { it.toList() }, str(o["text"]))
        }
    }

    @Test fun chunkingMatches() {
        val tok = tokenizer()
        for (c in arr("chunks")) {
            val o = c.jsonObject
            val got = chunkText(str(o["text"]), tok, o["chunk_tokens"]!!.jsonPrimitive.int, o["stride"]!!.jsonPrimitive.int)
            assertEquals(pairs(o["chunks"]), got.chunks)
            assertEquals(pairs(o["keep"]), got.keep)
            assertEquals(pairs(o["offsets"]), got.offsets)
        }
    }

    @Test fun parseVitalsMatches() {
        for (c in arr("vitals")) {
            val o = c.jsonObject
            val got = jObj(parseVitals(str(o["text"])))
            assertTrue(jsonEquals(got, o["expected"]!!), "${str(o["text"])}: $got != ${o["expected"]}")
        }
    }

    @Test fun parseAgeMatches() {
        for (c in arr("ages")) {
            val o = c.jsonObject
            val a = parseAge(str(o["text"]))
            val got = jObj("years" to jInt(a.years), "months" to jInt(a.months), "band" to jStr(a.band))
            assertTrue(jsonEquals(got, o["expected"]!!), "${str(o["text"])}: $got != ${o["expected"]}")
        }
    }

    @Test fun parseOnsetMatches() {
        for (c in arr("onsets")) {
            val o = c.jsonObject
            val got = jInt(parseOnset(str(o["text"])))
            assertTrue(jsonEquals(got, o["expected"]!!), "${str(o["text"])}: $got != ${o["expected"]}")
        }
    }

    @Test fun decodeMatches() {
        for ((i, c) in arr("decode").withIndex()) {
            val o = c.jsonObject
            val heads = o["heads"]!!.jsonObject.mapValues { (_, v) ->
                v.jsonArray.map { if (it is JsonNull) Float.NaN else it.jsonPrimitive.float }.toFloatArray()
            }
            val got = decode(str(o["text"]), MFBertLogits(heads, ints(o["tags"]).toIntArray()), pairs(o["offsets"]))
            assertTrue(jsonEquals(got, o["expected"]!!), "decode case $i\n$got\n${o["expected"]}")
        }
    }

    @Test fun segmenterMatches() {
        val s = fixtures["segment"]!!.jsonObject
        for ((i, c) in s["find"]!!.jsonArray.withIndex()) {
            val o = c.jsonObject
            val rms = o["rms"]!!.jsonArray.map { it.jsonPrimitive.float }.toFloatArray()
            val got = findUtteranceEnd(rms, 0.01f, o["hold"]!!.jsonPrimitive.int)
            assertTrue(jsonEquals(jInt(got), o["expected"]!!), "find case $i: $got != ${o["expected"]}")
        }
        val audio = s["frame_audio"]!!.jsonArray.map { it.jsonPrimitive.float }.toFloatArray()
        val expected = s["frame_rms"]!!.jsonArray.map { it.jsonPrimitive.double }
        frameRms(audio).forEachIndexed { k, g -> assertTrue(abs(g - expected[k]) < 1e-6) }
    }

    @Test fun segmenterStream() {
        // 1초 말 + 1초 침묵 + 0.3초 기침 + 2초 침묵 -> 말은 통화 중에 바로 잘리고, 기침은 종료 때 인식(live_transcriber.py와 같은 동작)
        val seg = UtteranceSegmenter()
        val audio = FloatArray(16000 * 4 + 4800)
        for (i in 0 until 16000) audio[i] = 0.1f * sin(i / 5f)
        for (i in 32000 until 36800) audio[i] = 0.1f * sin(i / 5f)
        val outs = ArrayList<Utterance>()
        var start = 0
        while (start < audio.size) {
            seg.append(audio.copyOfRange(start, minOf(start + 8000, audio.size)))
            outs += seg.poll()
            start += 8000
        }
        assertEquals(1, outs.size)
        assertEquals(0.0, outs[0].offsetSec)
        outs += seg.poll(final = true)
        assertEquals(2, outs.size)
    }

    @Test fun splitChunksLikePython() {
        val audio = FloatArray(16000 * 12) { 0.1f }
        for (i in 70000 until 71600) audio[i] = 0f
        val b = splitChunks(audio)
        assertEquals(0 until 70400, b.first())
        assertEquals(audio.size - 1, b.last().last)
        assertTrue(b.all { it.count() <= 16000 * 5 })
    }

    @Test fun callSummaryShape() {
        val msg = buildCallSummary("case-1", listOf(RecognizedSegment(1.2, 3.4, "가"), RecognizedSegment(4.0, 5.0, "나")),
            1_791_000_000_000L, 42.34, jObj("ktas_level" to JsonPrimitive(2)))
        val t = msg["transcript"]!!.jsonObject
        assertEquals("가\n나", t["raw_text"]!!.jsonPrimitive.content)
        assertEquals(42.3, t["duration_sec"]!!.jsonPrimitive.double)
        assertEquals(ANDROID_STT_NAME, msg["model_used"]!!.jsonObject["stt"]!!.jsonPrimitive.content)
        assertTrue(voiceSummaryMessage(msg).toString().startsWith("{\"type\":\"voice_summary\",\"caseId\":\"case-1\""))
    }

    // ── ASR(그래프 밖) — check_qwen3_asr.py --fixtures 정답 ──

    private fun asrFixtures(): JsonArray {
        val f = File(android, "fixtures/asr_fixtures.json")
        assumeTrue(f.isFile && File(models, "asr_tokens.json").isFile, "ASR 정답·토큰 파일 없음")
        return Json.parseToJsonElement(f.readText()).jsonArray
    }

    private fun melFilters(): FloatArray {
        val bytes = File(models, "asr_mel_filters.bin").readBytes()
        val buf = java.nio.ByteBuffer.wrap(bytes).order(java.nio.ByteOrder.LITTLE_ENDIAN).asFloatBuffer()
        return FloatArray(buf.remaining()).also { buf.get(it) }
    }

    @Test fun asrMelPromptAndTokensMatch() {
        val cases = asrFixtures()
        val filters = melFilters()
        val tokens = AsrTokens(File(models, "asr_tokens.json").readText())
        for ((i, c) in cases.withIndex()) {
            val o = c.jsonObject
            val audio = o["audio"]!!.jsonArray.map { it.jsonPrimitive.float }.toFloatArray()
            val mel = melFeatures(audio, filters)
            assertEquals(o["valid_frames"]!!.jsonPrimitive.int, mel.validFrames, "case $i valid")
            // 앞 8프레임 값과 전체 합 — numpy(float64 rfft)와 같은 계산이라 오차는 부동소수 수준
            val head = o["mel_head"]!!.jsonArray
            var worst = 0.0
            for (m in 0 until N_MELS) for (f in 0 until 8) {
                worst = maxOf(worst, abs(mel.features[m * mel.frames + f] - head[m].jsonArray[f].jsonPrimitive.double))
            }
            assertTrue(worst < 1e-4, "case $i mel 오차 $worst")
            val sum = mel.features.sumOf { it.toDouble() }
            assertTrue(abs(sum - o["mel_sum"]!!.jsonPrimitive.double) < 1e-2 * mel.features.size / 1000.0 + 1e-1, "case $i mel 합 $sum")
            val enc = encoderInputs(mel)
            assertEquals(ints(o["valid_index"]), enc.validIndex.map { it.toInt() }, "case $i valid_index")
            assertEquals(ints(o["prompt"]), tokens.prompt(audioTokenCount(mel.validFrames)), "case $i prompt")
            val raw = tokens.decode(ints(o["ids"]))
            assertEquals(str(o["raw"]), raw, "case $i 토큰 풀기")
            assertEquals(str(o["text"]), asrTranscription(raw), "case $i 결과 정리")
        }
    }

    @Test fun repetitionFixLikeTransformers() {
        assertEquals("아", fixRepetitions("아".repeat(25)))
        assertEquals("가나", fixRepetitions("가나".repeat(30)))
        assertEquals("짧은 문장", fixRepetitions("짧은 문장"))
        assertEquals("말씀", asrTranscription("language Korean<asr_text>말씀"))
        assertEquals("", asrTranscription("   "))
    }
}
