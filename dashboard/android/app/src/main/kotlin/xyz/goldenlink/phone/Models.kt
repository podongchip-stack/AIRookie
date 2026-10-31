package xyz.goldenlink.phone

import kotlinx.serialization.json.JsonObject
import xyz.goldenlink.core.AsrRunner
import xyz.goldenlink.core.MfBertRunner
import xyz.goldenlink.core.RecognizedSegment
import java.io.File

/*
 * 온디바이스 모델 — dashboard/android/convert/가 만든 ONNX(fp32, 양자화 없음)를 onnxruntime(CPU)으로 돌린다.
 * 가중치는 서버 voice와 같은 Hub 저장소·커밋에서 받아 변환했다(Models/mf_bert_meta.json·asr_tokens.json에 기록).
 * 모델 파일(약 4.6GB)은 APK에 넣지 않고 기기의 앱 전용 폴더에 adb로 넣는다 — README "모델 넣기".
 *   /sdcard/Android/data/xyz.goldenlink.phone/files/models/
 */

/** 모델 폴더에 있어야 하는 파일 */
val MODEL_FILES = listOf(
    "asr_audio_encoder.onnx", "asr_audio_encoder.onnx.data", "asr_decoder.onnx", "asr_decoder.onnx.data",
    "asr_mel_filters.bin", "asr_tokens.json",
    "mf_bert_encoder.onnx", "mf_bert_encoder.onnx.data", "mf_bert_heads.onnx", "mf_bert_heads.onnx.data",
    "mf_bert_tokenizer.json", "mf_bert_meta.json",
)

/**
 * 두 모델을 한 번 올려 두고 계속 쓴다(서버 voice와 같은 방식). 한 번에 하나만 돌린다(서버의 락과 같다 — 호출하는 쪽이
 * 단일 스레드 디스패처로 줄을 세운다). 모델 폴더가 비어 있으면 load()가 이유를 돌려주고 앱은 서버 음성 인식으로 동작한다.
 */
class ModelStore(val dir: File) {
    @Volatile var asr: AsrRunner? = null
        private set
    @Volatile var mfBert: MfBertRunner? = null
        private set
    val ready: Boolean get() = asr != null && mfBert != null

    fun missingFiles(): List<String> = MODEL_FILES.filter { !File(dir, it).isFile }

    /** 무거운 작업(수십 초) — 백그라운드 스레드에서 부른다. 실패하면 이유를 돌려준다 */
    fun load(threads: Int = 4): String? {
        val missing = missingFiles()
        if (missing.isNotEmpty()) return "모델 파일 없음: ${missing.joinToString()}"
        return try {
            if (asr == null) asr = AsrRunner(dir, threads)
            if (mfBert == null) mfBert = MfBertRunner(dir, threads)
            null
        } catch (t: Throwable) {
            t.message ?: t.toString()
        }
    }

    fun transcribe(audio: FloatArray): List<RecognizedSegment> = asr?.transcribe(audio) ?: emptyList()
    fun extract(text: String): JsonObject = (mfBert ?: error("MF_BERT 미탑재")).extract(text)
}
