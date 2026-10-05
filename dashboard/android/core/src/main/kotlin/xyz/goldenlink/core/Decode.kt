package xyz.goldenlink.core

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * MF_BERT 출력(문장 헤드 로짓 + 토큰 태그) -> v2 스키마 summary. voice/MF_BERT/decode.py의 decode()를 옮겼다
 * (아이폰 Decode.swift와 같은 코드). 원본과 다른 점 하나: incidents 순서 — 원본은 파이썬 set을 정렬해 주 사고 다음 순서가
 * 실행마다 달라질 수 있어, 여기서는 주 사고 다음을 labels의 보기 순서로 고정했다(내용은 같다).
 */
class MFBertLogits(
    /** 문장 헤드 이름 -> 보기별 점수(배치 1개) */
    val heads: Map<String, FloatArray>,
    /** 복원한 토큰 줄의 태그(구간 태거 argmax), 길이 = offsets 수 */
    val spanTags: IntArray,
)

/** torch.argmax와 같게 최댓값이 여럿이면 앞쪽 */
fun argmax(v: FloatArray): Int {
    var best = 0
    for (i in 1 until v.size) if (v[i] > v[best]) best = i
    return best
}

data class Span(val start: Int, val end: Int, val type: String)

/** 토큰 태그 -> 글자 구간. 짝 없는 I-는 그 자리에서 새 구간을 연다. */
fun decodeSpans(tags: IntArray, offsets: List<List<Int>>, labels: Labels = Labels.shared): List<Span> {
    val tagO = labels.spanTags.indexOf("O")
    val spans = ArrayList<Span>()
    var current: Span? = null
    for (i in 0 until minOf(tags.size, offsets.size)) {
        val tag = tags[i]
        val start = offsets[i][0]
        val end = offsets[i][1]
        if (start == end || tag == -100 || tag == tagO) { current = null; continue }
        val parts = labels.spanTags[tag].split("-", limit = 2)
        val cur = current
        if (parts[0] == "I" && cur != null && cur.type == parts[1]) {
            current = Span(cur.start, end, cur.type)
            spans[spans.size - 1] = current
            continue
        }
        current = Span(start, end, parts[1])
        spans += current
    }
    return spans
}

private fun String.split2(sep: String): List<String> = split(sep, limit = 2)

fun decode(text: String, logits: MFBertLogits, offsets: List<List<Int>>, labels: Labels = Labels.shared): JsonObject {
    val l = labels
    val undecided = l.undecided
    fun single(name: String): String? {
        val label = l.single.getValue(name)[argmax(logits.heads.getValue(name))]
        return if (label == undecided) null else label
    }
    fun positives(name: String): List<String> {
        val scores = logits.heads.getValue(name)
        return l.multi.getValue(name).filterIndexed { i, _ -> scores[i] > 0 }
    }

    val ktasLevel = l.single.getValue("ktas")[argmax(logits.heads.getValue("ktas"))].toInt()

    // masked_minor: 예측 대분류에 속한 소분류(대분류가 미언급이면 미언급)만 남기고 1위
    val ccMajor = l.single.getValue("cc_major")
    val ccMinor = l.single.getValue("cc_minor")
    val major = argmax(logits.heads.getValue("cc_major"))
    val minorIdx = if (major == ccMajor.indexOf(undecided)) {
        ccMinor.indexOf(undecided)
    } else {
        val minorMajor = l.minors.map { m -> l.majors.indexOf(m.split("|")[0]) } + (-1)
        val raw = logits.heads.getValue("cc_minor")
        argmax(FloatArray(raw.size) { if (minorMajor[it] == major) raw[it] else Float.NEGATIVE_INFINITY })
    }
    val minorLabel = ccMinor[minorIdx]
    val chiefComplaint = if (minorLabel == undecided) {
        jObj("major" to JsonNull, "minor" to JsonNull)
    } else {
        val p = minorLabel.split2("|")
        jObj("major" to JsonPrimitive(p[0]), "minor" to JsonPrimitive(p[1]))
    }

    val sex = single("sex")
    val avpu = single("avpu")
    val medStatus = l.single.getValue("med_status")[argmax(logits.heads.getValue("med_status"))]

    val primaryType = single("primary_incident")
    val incidentTypes = LinkedHashSet(positives("incidents"))
    if (primaryType != null) incidentTypes += primaryType
    val incidentDetail = LinkedHashMap<String, MutableList<String>>()
    for (item in positives("incident_detail")) {
        val p = item.split2("/")
        incidentDetail.getOrPut(p[0]) { ArrayList() } += p[1]
    }
    val order = l.multi.getValue("incidents")
    val sortedTypes = incidentTypes.sortedWith(compareBy<String>({ if (it == primaryType) 0 else 1 }, { order.indexOf(it).let { i -> if (i < 0) Int.MAX_VALUE else i } }))
    val incidents = sortedTypes.map { t ->
        jObj("type" to JsonPrimitive(t), "detail" to jStr(incidentDetail[t]?.firstOrNull()), "primary" to JsonPrimitive(t == primaryType))
    }
    val diseaseCategory = if ("질병" in incidentTypes) single("disease") else null

    val treatDetail = LinkedHashMap<String, MutableList<String>>()
    for (item in positives("treatment_detail")) {
        val p = item.split2("/")
        treatDetail.getOrPut(p[0]) { ArrayList() } += p[1]
    }
    val treatments = positives("treatment").map { item ->
        val p = item.split2("/")
        jObj("category" to JsonPrimitive(p[0]), "status" to JsonPrimitive(p[1]), "detail" to jStr(treatDetail[p[0]]?.firstOrNull()))
    }

    val symptoms = positives("symptoms").map { item ->
        val slash = item.lastIndexOf('/')  // rsplit("/", 1)
        jObj("standard_name" to JsonPrimitive(item.substring(0, slash)), "status" to JsonPrimitive(item.substring(slash + 1)))
    }

    val injurySide = HashMap<String, String>()
    for (item in positives("injury_side")) {
        val p = item.split2("/")
        injurySide[p[0]] = p[1]
    }
    val injuries = positives("injury").map { item ->
        val p = item.split2("/")
        jObj("region" to JsonPrimitive(p[0]), "type" to JsonPrimitive(p[1]), "side" to jStr(injurySide[p[0]]),
            "status" to JsonPrimitive("확인"))
    }

    // 구간: offsets는 코드포인트 위치라 코드포인트 배열로 자른다
    val cps = text.codePoints().toArray()
    val byType = LinkedHashMap<String, MutableList<String>>().apply { l.spanTypes.forEach { put(it, ArrayList()) } }
    for (s in decodeSpans(logits.spanTags, offsets, l)) {
        val lo = maxOf(0, s.start)
        val hi = minOf(s.end, cps.size)
        byType.getValue(s.type) += if (hi > lo) String(cps, lo, hi - lo) else ""
    }

    val vitals = ArrayList<JsonElement>()
    for (spanText in byType.getValue("VITALS")) {
        val values = parseVitals(spanText)
        if (values.any { it.second !is JsonNull }) {
            vitals += jObj(listOf("sequence" to JsonPrimitive(vitals.size + 1)) + values +
                listOf("evidence" to jArr(listOf(JsonPrimitive(spanText)))))
        }
    }

    val ageSpans = byType.getValue("AGE")
    val ageText = ageSpans.joinToString(" ")
    val age = if (ageText.isEmpty()) {
        jObj("years" to JsonNull, "months" to JsonNull, "band" to JsonNull, "evidence" to JsonArray(emptyList()))
    } else {
        val a = parseAge(ageText)
        jObj("years" to jInt(a.years), "months" to jInt(a.months), "band" to jStr(a.band),
            "evidence" to jArr(ageSpans.map { JsonPrimitive(it) }))
    }

    val onsetText = byType.getValue("ONSET").firstOrNull()
    val onset = jObj("text" to jStr(onsetText), "minutes_ago" to jInt(onsetText?.let { parseOnset(it) }))

    return jObj(
        "call_type" to JsonNull,
        "ktas_level" to JsonPrimitive(ktasLevel),
        "ktas_evidence" to JsonNull,
        "chief_complaint" to chiefComplaint,
        "suspected_diagnosis" to jArr(byType.getValue("DX").map { jObj("text" to JsonPrimitive(it)) }),
        "vitals" to jArr(vitals),
        "consciousness" to jArr(if (avpu == null) emptyList() else listOf(jObj("sequence" to JsonPrimitive(1), "avpu" to JsonPrimitive(avpu)))),
        "symptoms" to jArr(symptoms),
        "onset" to onset,
        "incidents" to jArr(incidents),
        "disease_category" to jStr(diseaseCategory),
        "injuries" to jArr(injuries),
        "treatments" to jArr(treatments),
        "age" to age,
        "sex" to jStr(sex),
        "medications" to jObj("status" to JsonPrimitive(medStatus),
            "items" to jArr(byType.getValue("MED").map { jObj("text" to JsonPrimitive(it)) })),
        "notes" to JsonNull,
        "meta" to jObj("not_predicted" to jArr(listOf("call_type", "ktas_evidence", "notes").map { JsonPrimitive(it) })),
    )
}
