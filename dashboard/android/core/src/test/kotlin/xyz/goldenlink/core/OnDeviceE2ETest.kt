package xyz.goldenlink.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.float
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Assumptions.assumeTrue
import org.junit.jupiter.api.Test
import java.io.File

/**
 * 앱과 똑같은 Kotlin 코드(OnnxRunners.kt — 멜·인코더·KV 캐시 그리디·토큰 풀기 / 조각 인코딩·헤드·decode)를 실제 변환 모델로
 * 돌려 서버(voice, PyTorch)와 같은 결과가 나오는지 본다. 안드로이드는 onnxruntime-android로 같은 API를 쓴다.
 *
 * 필요: Models/(convert_*.py 결과), fixtures/asr_fixtures.json(check_qwen3_asr.py --fixtures),
 *       fixtures/mf_bert_reference.json(check_mf_bert.py --fixtures). 없으면 건너뛴다.
 *     ./gradlew :core:test --tests '*OnDeviceE2ETest*'
 */
class OnDeviceE2ETest {
    private val android = File(System.getProperty("user.dir")).let { if (it.name == "core") it.parentFile else it }
    private val models = File(android, "Models")

    @Test fun asrMatchesServer() {
        val fixtures = File(android, "fixtures/asr_fixtures.json")
        assumeTrue(fixtures.isFile && File(models, "asr_decoder.onnx").isFile, "ASR 모델·정답 없음")
        val cases = Json.parseToJsonElement(fixtures.readText()).jsonArray
        AsrRunner(models, 4).use { asr ->
            for ((i, c) in cases.withIndex()) {
                val o = c.jsonObject
                val audio = o["audio"]!!.jsonArray.map { it.jsonPrimitive.float }.toFloatArray()
                val started = System.nanoTime()
                val got = asr.transcribe(audio).joinToString(" ") { it.text }
                val ms = (System.nanoTime() - started) / 1_000_000
                val want = o["text"]!!.jsonPrimitive.content
                println("[ASR $i] ${audio.size / 16000.0}초 · ${ms}ms · $got")
                assertEquals(want, got, "ASR case $i")
            }
        }
    }

    @Test fun mfBertMatchesServer() {
        val fixtures = File(android, "fixtures/mf_bert_reference.json")
        assumeTrue(fixtures.isFile && File(models, "mf_bert_encoder.onnx").isFile, "MF_BERT 모델·정답 없음")
        val cases = Json.parseToJsonElement(fixtures.readText()).jsonArray
        MfBertRunner(models, 4).use { mf ->
            for ((i, c) in cases.withIndex()) {
                val o = c.jsonObject
                val started = System.nanoTime()
                val got = mf.extract(o["text"]!!.jsonPrimitive.content)
                println("[MF_BERT $i] ${(System.nanoTime() - started) / 1_000_000}ms · ktas ${got["ktas_level"]}")
                assertTrue(jsonEquals(got, o["summary"]!!), "MF_BERT case $i\n앱: $got\n서버: ${o["summary"]}")
            }
        }
    }
}
