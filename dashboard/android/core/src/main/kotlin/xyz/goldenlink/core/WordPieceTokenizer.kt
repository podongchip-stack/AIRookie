package xyz.goldenlink.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File

/**
 * KLUE RoBERTa 토크나이저(BertTokenizer, WordPiece)를 MF_BERT `tokenizer.json`에서 읽어 그대로 재현한다.
 * 아이폰 GoldenLinkCore/WordPieceTokenizer.swift를 옮겼다 — chunking.py가 쓰는 원문 글자 구간(offsets)까지 필요해 직접 구현.
 *
 * tokenizer.json 설정: BertNormalizer(clean_text, handle_chinese_chars, strip_accents=null, lowercase=false)
 * + BertPreTokenizer + WordPiece("##", max_input_chars_per_word=100, [UNK]). 오프셋은 Python과 같은 유니코드 코드포인트 위치다.
 */
class WordPieceTokenizer(json: String) {
    val vocab: Map<String, Int>
    val unkId: Int
    val clsId: Int
    val sepId: Int
    val padId: Int
    private val maxCharsPerWord: Int
    private val prefix: String

    init {
        val model = Json.parseToJsonElement(json).jsonObject["model"]!!.jsonObject
        vocab = model["vocab"]!!.jsonObject.mapValues { it.value.jsonPrimitive.int }
        prefix = model["continuing_subword_prefix"]!!.jsonPrimitive.content
        maxCharsPerWord = model["max_input_chars_per_word"]!!.jsonPrimitive.int
        unkId = vocab.getValue(model["unk_token"]!!.jsonPrimitive.content)
        clsId = vocab.getValue("[CLS]")
        sepId = vocab.getValue("[SEP]")
        padId = vocab.getValue("[PAD]")
    }

    constructor(file: File) : this(file.readText())

    /** 특수 토큰 없이 (토큰 id 목록, (시작, 끝) 코드포인트 구간 목록) */
    fun encode(text: String): Pair<List<Int>, List<IntArray>> {
        val ids = ArrayList<Int>()
        val offsets = ArrayList<IntArray>()
        for ((word, start) in preTokenize(text)) {
            val chars = word.map { String(Character.toChars(it)) }
            if (chars.size > maxCharsPerWord) {
                ids += unkId; offsets += intArrayOf(start, start + chars.size); continue
            }
            val pieces = ArrayList<IntArray>()  // id, 시작, 끝
            var begin = 0
            var failed = false
            while (begin < chars.size) {
                var end = chars.size
                var found: Int? = null
                while (begin < end) {
                    var piece = chars.subList(begin, end).joinToString("")  // 코드포인트 단위(Python·Rust와 같게)
                    if (begin > 0) piece = prefix + piece
                    val id = vocab[piece]
                    if (id != null) { found = id; break }
                    end -= 1
                }
                if (found == null) { failed = true; break }
                pieces += intArrayOf(found, start + begin, start + end)
                begin = end
            }
            if (failed) {
                ids += unkId; offsets += intArrayOf(start, start + chars.size)
            } else {
                for (p in pieces) { ids += p[0]; offsets += intArrayOf(p[1], p[2]) }
            }
        }
        return ids to offsets
    }

    /** BertNormalizer + BertPreTokenizer: (코드포인트 배열, 원문 시작 위치) 목록 */
    internal fun preTokenize(text: String): List<Pair<IntArray, Int>> {
        val words = ArrayList<Pair<IntArray, Int>>()
        val current = ArrayList<Int>()
        var currentStart = 0
        fun flush() {
            if (current.isNotEmpty()) words += current.toIntArray() to currentStart
            current.clear()
        }
        val cps = text.codePoints().toArray()
        for ((i, c) in cps.withIndex()) {
            if (c == 0 || c == 0xFFFD || isControl(c)) continue  // clean_text
            if (isWhitespace(c)) { flush(); continue }
            if (isPunctuation(c) || isChineseChar(c)) { flush(); words += intArrayOf(c) to i; continue }
            if (current.isEmpty()) currentStart = i
            current += c
        }
        flush()
        return words
    }

    companion object {
        // HF tokenizers(bert normalizer/pre_tokenizer)와 같은 판정
        fun isWhitespace(c: Int): Boolean =
            c == ' '.code || c == '\t'.code || c == '\n'.code || c == '\r'.code || isUnicodeWhiteSpace(c)

        /** 유니코드 White_Space 속성(Swift properties.isWhitespace와 같은 집합) */
        private fun isUnicodeWhiteSpace(c: Int): Boolean =
            c in 0x09..0x0D || c == 0x20 || c == 0x85 || c == 0xA0 || c == 0x1680 || c in 0x2000..0x200A ||
                c == 0x2028 || c == 0x2029 || c == 0x202F || c == 0x205F || c == 0x3000

        fun isControl(c: Int): Boolean {
            if (c == '\t'.code || c == '\n'.code || c == '\r'.code) return false
            return when (Character.getType(c).toByte()) {
                Character.CONTROL, Character.FORMAT, Character.PRIVATE_USE, Character.SURROGATE, Character.UNASSIGNED -> true
                else -> false
            }
        }

        fun isPunctuation(c: Int): Boolean {
            if (c in 33..47 || c in 58..64 || c in 91..96 || c in 123..126) return true
            return when (Character.getType(c).toByte()) {
                Character.CONNECTOR_PUNCTUATION, Character.DASH_PUNCTUATION, Character.START_PUNCTUATION,
                Character.END_PUNCTUATION, Character.INITIAL_QUOTE_PUNCTUATION, Character.FINAL_QUOTE_PUNCTUATION,
                Character.OTHER_PUNCTUATION -> true
                else -> false
            }
        }

        fun isChineseChar(v: Int): Boolean =
            v in 0x4E00..0x9FFF || v in 0x3400..0x4DBF || v in 0x20000..0x2A6DF || v in 0x2A700..0x2B73F ||
                v in 0x2B740..0x2B81F || v in 0x2B920..0x2CEAF || v in 0xF900..0xFAFF || v in 0x2F800..0x2FA1F
    }
}

/** voice/MF_BERT/chunking.py의 chunk_text() 결과 */
data class ChunkedText(
    /** 조각별 토큰 id ([CLS] ... [SEP]) */
    val chunks: List<List<Int>>,
    /** 조각별 남길 토큰 위치(조각 안 인덱스) */
    val keep: List<List<Int>>,
    /** 남긴 토큰의 원문 코드포인트 구간. 특수 토큰은 (0, 0) */
    val offsets: List<List<Int>>,
)

const val CHUNK_TOKENS = 512
const val CHUNK_STRIDE = 128

/** chunking.py chunk_text() 그대로 — 긴 통화를 512토큰 조각(128토큰 겹침)으로 나눈다 */
fun chunkText(text: String, tokenizer: WordPieceTokenizer, chunkTokens: Int = CHUNK_TOKENS, stride: Int = CHUNK_STRIDE): ChunkedText {
    val body = chunkTokens - 2
    require(stride in 0 until body) { "stride must be in [0, $body)" }
    val (ids, offsets) = tokenizer.encode(text)
    val n = ids.size

    val starts = arrayListOf(0)
    while (starts.last() + body < n) starts += starts.last() + body - stride
    val ends = starts.map { minOf(it + body, n) }
    // 조각 i가 맡는 원문 토큰 구간 [owned[i], owned[i + 1])
    val owned = arrayListOf(0)
    for (i in 0 until starts.size - 1) owned += (starts[i + 1] + ends[i]) / 2
    owned += n

    val chunks = ArrayList<List<Int>>()
    val keep = ArrayList<List<Int>>()
    val kept = arrayListOf(listOf(0, 0))
    for (i in starts.indices) {
        val start = starts[i]
        val end = ends[i]
        chunks += listOf(tokenizer.clsId) + ids.subList(start, end) + listOf(tokenizer.sepId)
        var positions = (owned[i] until owned[i + 1]).map { it - start + 1 }
        if (i == 0) positions = listOf(0) + positions
        if (i == starts.size - 1) positions = positions + (end - start + 1)
        keep += positions
        for (j in owned[i] until owned[i + 1]) kept += listOf(offsets[j][0], offsets[j][1])
    }
    kept += listOf(0, 0)
    return ChunkedText(chunks, keep, kept)
}
