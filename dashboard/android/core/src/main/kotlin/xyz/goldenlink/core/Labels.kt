package xyz.goldenlink.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/** voice/MF_BERT/labels.py의 보기 목록. 손으로 옮기지 않고 아이폰 convert/export_labels.py가 뽑은 labels.json을 읽는다. */
class Labels private constructor(root: JsonObject) {
    val undecided: String = root["undecided"]!!.jsonPrimitive.content
    val majors: List<String> = root["majors"]!!.strings()
    /** "대분류|소분류" */
    val minors: List<String> = root["minors"]!!.strings()
    /** 단일 선택 헤드 이름 -> classes(미언급 포함). ktas·med_status는 미언급 보기가 없다 */
    val single: Map<String, List<String>> = root["single"]!!.jsonObject.mapValues { it.value.strings() }
    /** 다중 선택 헤드 이름 -> 보기 */
    val multi: Map<String, List<String>> = root["multi"]!!.jsonObject.mapValues { it.value.strings() }
    val spanTypes: List<String> = root["span_types"]!!.strings()
    val spanTags: List<String> = root["span_tags"]!!.strings()

    /** 문장 헤드 이름 전체(단일 + 다중). ONNX 헤드 출력 이름과 같다 */
    val sentenceHeads: List<String> get() = single.keys.toList() + multi.keys.toList()

    companion object {
        val shared: Labels by lazy {
            val text = Labels::class.java.getResourceAsStream("/labels.json")!!.bufferedReader(Charsets.UTF_8).readText()
            Labels(Json.parseToJsonElement(text).jsonObject)
        }

        private fun JsonElement.strings() = jsonArray.map { it.jsonPrimitive.content }
    }
}

// ── JSON 도우미: summary(v2 17필드)처럼 모양이 자유로운 JSON은 JsonElement로 그대로 다룬다(voice가 dict로 두는 것과 같은 이유) ──

fun jStr(s: String?): JsonElement = if (s == null) JsonNull else JsonPrimitive(s)
fun jInt(i: Int?): JsonElement = if (i == null) JsonNull else JsonPrimitive(i)
fun jObj(vararg pairs: Pair<String, JsonElement>): JsonObject = JsonObject(linkedMapOf(*pairs))
fun jObj(pairs: List<Pair<String, JsonElement>>): JsonObject = JsonObject(LinkedHashMap<String, JsonElement>().apply { pairs.forEach { put(it.first, it.second) } })
fun jArr(items: List<JsonElement>): JsonArray = JsonArray(items)

/** Python 비교와 같게: 객체는 키 순서 무관, 수는 90 == 90.0 */
fun jsonEquals(a: JsonElement, b: JsonElement): Boolean = when {
    a is JsonNull || b is JsonNull -> a is JsonNull && b is JsonNull
    a is JsonObject && b is JsonObject -> a.keys == b.keys && a.keys.all { jsonEquals(a.getValue(it), b.getValue(it)) }
    a is JsonArray && b is JsonArray -> a.size == b.size && a.indices.all { jsonEquals(a[it], b[it]) }
    a is JsonPrimitive && b is JsonPrimitive -> when {
        a.isString || b.isString -> a.isString == b.isString && a.content == b.content
        else -> {
            val x = a.content.toDoubleOrNull()
            val y = b.content.toDoubleOrNull()
            if (x != null && y != null) x == y else a.content == b.content  // true/false
        }
    }
    else -> false
}
