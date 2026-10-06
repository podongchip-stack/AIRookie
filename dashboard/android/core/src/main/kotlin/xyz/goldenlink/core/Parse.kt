package xyz.goldenlink.core

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import java.util.concurrent.ConcurrentHashMap
import java.util.regex.Matcher
import java.util.regex.Pattern

// voice/MF_BERT/parse.py를 한 줄씩 옮겼다(아이폰 Parse.swift와 같은 코드) — 모델이 찾은 VITALS·AGE·ONSET 구간을 규칙으로 읽는다(규칙 기반).
// 정규식은 원본과 같은 문자열을 쓴다. java.util.regex는 UNICODE_CHARACTER_CLASS로 \s·\d·\S를 Python(유니코드)과 같게 맞췄다.
// 위치는 UTF-16 단위다 — 통화 텍스트(한글·영숫자)는 전부 BMP라 Python 코드포인트 위치와 같다.

const val CURRENT_YEAR = 2026

private val DIGITS = mapOf('영' to 0, '일' to 1, '이' to 2, '삼' to 3, '사' to 4, '오' to 5, '육' to 6, '륙' to 6, '칠' to 7, '팔' to 8, '구' to 9)
private val UNITS = mapOf('십' to 10, '백' to 100, '천' to 1000)
private val NATIVE_TENS = listOf("열" to 10, "스물" to 20, "스무" to 20, "서른" to 30, "마흔" to 40, "쉰" to 50,
    "예순" to 60, "일흔" to 70, "여든" to 80, "아흔" to 90)
private val NATIVE_ONES = listOf("하나" to 1, "한" to 1, "둘" to 2, "두" to 2, "셋" to 3, "세" to 3, "석" to 3, "넷" to 4,
    "네" to 4, "넉" to 4, "다섯" to 5, "여섯" to 6, "일곱" to 7, "여덟" to 8, "아홉" to 9)
private const val SINO = "영일이삼사오육륙칠팔구십백천"

/** Python `sorted(keys, key=len, reverse=True)`와 같은 순서(같은 길이는 원래 순서 유지 — sortedBy는 안정 정렬) */
private fun alternation(pairs: List<Pair<String, Int>>): String =
    pairs.sortedByDescending { it.first.length }.joinToString("|") { it.first }

val NATIVE_TENS_RE = alternation(NATIVE_TENS)
val NATIVE_ONES_RE = alternation(NATIVE_ONES)

/** 수 하나: 아라비아(소수 포함) | 한자어 수사(띄어쓰기 허용, 점 소수 허용) | 고유어 */
val NUMBER_RE = "(?:\\d+(?:\\.\\d+)?" +
    "|[$SINO](?:\\s?[$SINO])*(?:\\s?점\\s?[$SINO](?:\\s?[$SINO])*)?" +
    "|(?:$NATIVE_TENS_RE)(?:$NATIVE_ONES_RE)?|(?:$NATIVE_ONES_RE))"

// ── 정규식 도우미 (Python re의 search / match / fullmatch / finditer) ──

internal class RxMatch(private val m: Matcher) {
    val start = m.start()
    val end = m.end()
    private val groups = (0..m.groupCount()).map { m.group(it) }
    fun group(i: Int = 0): String? = groups[i]
}

private val rxCache = ConcurrentHashMap<String, Pattern>()
// 안드로이드(ICU 정규식)는 UNICODE_CHARACTER_CLASS를 받지 않고 IllegalArgumentException을 던진다(2026-10-06 실기기에서 구조화가
// 전부 실패) — ICU는 플래그 없이도 \s·\d·\w가 유니코드 기준이라 그때만 플래그를 뺀다. PC(JVM) 테스트는 그대로 플래그를 쓴다.
// ponytail: ICU \s는 \x0b·\x1c~\x1f를 공백으로 안 본다(Python은 본다) — STT 문장엔 안 나오는 제어 문자라 무시
private val rxFlags: Int = runCatching { Pattern.compile("a", Pattern.UNICODE_CHARACTER_CLASS); Pattern.UNICODE_CHARACTER_CLASS }.getOrDefault(0)
private fun rx(pattern: String): Pattern = rxCache.getOrPut(pattern) { Pattern.compile(pattern, rxFlags) }

internal fun search(pattern: String, s: String): RxMatch? = rx(pattern).matcher(s).let { if (it.find()) RxMatch(it) else null }
internal fun match(pattern: String, s: String): RxMatch? = rx(pattern).matcher(s).let { if (it.lookingAt()) RxMatch(it) else null }
internal fun fullmatch(pattern: String, s: String): RxMatch? = rx(pattern).matcher(s).let { if (it.matches()) RxMatch(it) else null }
internal fun finditer(pattern: String, s: String): List<RxMatch> {
    val m = rx(pattern).matcher(s)
    val out = ArrayList<RxMatch>()
    while (m.find()) out += RxMatch(m)
    return out
}

/** Python 슬라이스 s[a:b] (UTF-16 위치, 범위 밖은 잘라냄) */
internal fun slice(s: String, a: Int, b: Int? = null): String {
    val lo = maxOf(0, minOf(a, s.length))
    val hi = maxOf(lo, minOf(b ?: s.length, s.length))
    return s.substring(lo, hi)
}

private fun charAt(s: String, i: Int) = slice(s, i, i + 1)
private fun isHangul(c: String) = match("[가-힣]", c) != null
private fun isDigitString(s: String) = s.isNotEmpty() && s.all { it in '0'..'9' }

// ── 수 읽기 ──

internal fun sinoInt(raw: String): Int? {
    val s = raw.replace(" ", "")
    if (s.isEmpty() || s.any { it !in SINO }) return null
    if (s.length > 1 && s.all { DIGITS[it] != null }) return s.map { DIGITS.getValue(it) }.joinToString("").toInt()  // "구칠" 같은 자릿수 나열
    var total = 0
    var current = 0
    for (c in s) {
        val d = DIGITS[c]
        if (d != null) current = d else { total += (if (current == 0) 1 else current) * UNITS.getValue(c); current = 0 }
    }
    return total + current
}

/** 수 하나를 읽는다. 못 읽으면 null. */
fun toNumber(raw: String): Double? {
    var token = raw.trim()
    if (token.isEmpty()) return null
    if (fullmatch("\\d+(?:\\.\\d+)?", token) != null) return token.toDouble()
    val m = fullmatch("($NATIVE_TENS_RE)?($NATIVE_ONES_RE)?", token)
    if (m != null && (m.group(1) != null || m.group(2) != null)) {
        val tens = m.group(1)?.let { g -> NATIVE_TENS.first { it.first == g }.second } ?: 0
        val ones = m.group(2)?.let { g -> NATIVE_ONES.first { it.first == g }.second } ?: 0
        return (tens + ones).toDouble()
    }
    if ('점' in token) {
        val parts = token.split("점", limit = 2)
        val w = sinoInt(parts[0])
        val f = parts[1].replace(" ", "").mapNotNull { DIGITS[it] }.joinToString("")
        if (w == null || f.isEmpty()) return null
        return "$w.$f".toDouble()
    }
    if (token.length > 1 && token.last() in "이일" && DIGITS[token[token.length - 2]] != null) {  // "구십삼이고"의 "이"는 조사
        token = token.dropLast(1)
    }
    return sinoInt(token)?.toDouble()
}

/** Python _as_int: 정수면 int로, 아니면 소수 그대로 */
internal fun asInt(x: Double): JsonElement =
    if (x == Math.rint(x) && kotlin.math.abs(x) < 1e15) JsonPrimitive(x.toLong()) else JsonPrimitive(x)

/** 글 안의 첫 수. "맥박이 100"의 "이"처럼 낱말에 붙은 한 글자 한자어 수사는 건너뛴다. */
internal fun firstNumber(text: String): RxMatch? {
    for (m in finditer("($NUMBER_RE)", text)) {
        val token = m.group(1)!!
        if (token.length == 1 && !isDigitString(token)) {
            val before = if (m.start > 0) charAt(text, m.start - 1) else " "
            val after = if (m.end < text.length) charAt(text, m.end) else " "
            if (isHangul(before) || isHangul(after)) continue
        }
        return m
    }
    return null
}

// ── 활력징후 ──

const val UNMEASURABLE_RE = "(안\\s?잡|잡히지\\s?않|측정\\S*\\s?(?:안|불가|되지\\s?않)|체크\\S*\\s?안|촉지\\S*\\s?(?:안|않|불가)|안\\s?나와|무맥)"

/** 원본 dict 순서 그대로(키 탐색 순서가 결과에 영향) */
val VITAL_KEYS = listOf(
    "hr" to "(?:맥박|심박수?|HR|펄스|pulse)",
    "rr" to "(?:호흡수?|RR)",
    "spo2" to "(?:산소\\s?포화도|산소\\s?포아도|포화도|새츄레이션|사츄레이션|SpO2|SPO2|산소)",
    "glucose" to "(?:혈당|BST|bst|당\\s?수치)",
    "bt" to "(?:체온|열|BT)",
)
val BP_RE = "(?:혈압|BP)?\\s*(?:은|는|이)?\\s*($NUMBER_RE)\\s*(?:에|/|바이|over)\\s*($NUMBER_RE)"
val VITAL_FIELDS = listOf("sbp", "dbp", "hr", "rr", "bt", "spo2", "glucose")

/** 활력징후 보고 한 묶음 -> [sbp, dbp, hr, rr, bt, spo2, glucose] (없는 값은 JsonNull) */
fun parseVitals(text: String): List<Pair<String, JsonElement>> {
    val out = LinkedHashMap<String, JsonElement>().apply { VITAL_FIELDS.forEach { put(it, JsonNull) } }
    val t = text
    val bpKey = search("(혈압|BP)", t)
    if (bpKey != null && search(UNMEASURABLE_RE, slice(t, bpKey.end, bpKey.end + 12)) != null) {
        out["sbp"] = JsonPrimitive("측정불가"); out["dbp"] = JsonPrimitive("측정불가")
    } else {
        val m = search(BP_RE, t)
        if (m != null) {
            val s = toNumber(m.group(1)!!)
            val d = toNumber(m.group(2)!!)
            if (s != null && d != null && s > d) { out["sbp"] = asInt(s); out["dbp"] = asInt(d) }
        }
    }
    val anyKey = VITAL_KEYS.joinToString("|") { it.second } + "|혈압|BP"
    val number = "($NUMBER_RE)"
    for ((key, pattern) in VITAL_KEYS) {
        for (km in finditer(pattern, t)) {
            val rest = slice(t, km.end, km.end + 30)
            if (key == "rr" && km.group()!!.startsWith("호흡") &&
                match("\\s?(?:곤란|음|기|정지|이\\s|을|이\\s?얕|이\\s?빠)", rest) != null
            ) continue  // 호흡곤란·호흡음 등은 호흡수가 아니다
            val window = search(anyKey, rest)?.let { slice(rest, 0, it.start) } ?: rest  // 다음 활력징후 키워드 앞까지만 본다
            if (search(UNMEASURABLE_RE, slice(window, 0, 20)) != null && search("\\d", slice(window, 0, 20)) == null) {
                out[key] = JsonPrimitive("측정불가")
                break
            }
            var nm: RxMatch? = null
            if (key == "spo2") {  // "산소 15리터에 94%"처럼 다른 수가 끼면 %가 붙은 수가 포화도다
                nm = search("($NUMBER_RE)\\s?(?:%|퍼센트|프로|퍼)", window)
                if (nm == null) {
                    nm = finditer(number, window).firstOrNull { c ->
                        match("\\s?(?:리터|L|l|ℓ)", slice(window, c.end)) == null &&
                            !(c.group(1)!!.length == 1 && !isDigitString(c.group(1)!!))
                    }
                    if (nm != null && nm.start > 15) nm = null
                }
            }
            if (nm == null) {
                // 키워드 뒤 짧은 군말("분당", "재측정 결과는", "실온에서") 다음의 첫 수
                nm = firstNumber(window)
                if (nm == null || nm.start > 15) continue
            }
            var value = toNumber(nm.group(1)!!) ?: continue
            if (key == "bt") {
                val bu = match("\\s?도\\s?($NUMBER_RE)\\s?부?", slice(window, nm.end))
                if (bu != null && value == kotlin.math.truncate(value)) {
                    val frac = toNumber(bu.group(1)!!)
                    if (frac != null && frac < 10) value += frac / 10
                }
                if (value < 30 || value > 43) continue
            }
            out[key] = asInt(value)
            break
        }
    }
    if (out["bt"] is JsonNull) {  // "36.8도로 정상"처럼 키워드 없이
        val m = search("($NUMBER_RE)\\s?도(?:\\s?($NUMBER_RE)\\s?부)?", t)
        if (m != null) {
            val whole = toNumber(m.group(1)!!)
            if (whole != null) {
                val frac = m.group(2)
                val value = if (frac != null) whole + (toNumber(frac) ?: 0.0) / 10 else whole
                if (value in 34.0..42.0) out["bt"] = asInt(value)
            }
        }
    }
    return VITAL_FIELDS.map { it to out.getValue(it) }
}

// ── 나이 ──

data class Age(val years: Int?, val months: Int?, val band: String?)

/** 나이 구간 -> years, months, band. 연령대만 말하면 band만. */
fun parseAge(t: String): Age {
    if (search("10\\s?세\\s?미만", t) != null) return Age(null, null, "10세 미만")
    search("($NUMBER_RE)\\s?년생", t)?.let { m ->
        val n = toNumber(m.group(1)!!)
        if (n != null) {
            val year = if (n < 100) n.toInt() + (if (n > (CURRENT_YEAR % 100).toDouble()) 1900 else 2000) else n.toInt()
            return Age(CURRENT_YEAR - year, null, null)
        }
    }
    val m = search("생후\\s?($NUMBER_RE)\\s?(개월|일|주)", t) ?: search("($NUMBER_RE)\\s?(개월)", t)
    if (m != null) {
        val n = toNumber(m.group(1)!!)
        if (n != null) return Age(null, if (m.group(2) == "개월") n.toInt() else 0, null)
    }
    if (search("(신생아|출생|태어난|갓\\s?난|방금\\s?낳)", t) != null) return Age(null, 0, null)
    for (a in finditer("($NUMBER_RE)\\s?(?:세|살)", t)) {
        val token = a.group(1)!!
        // "여성분이세요"의 "이"처럼 낱말 속 한 글자는 수가 아니다
        if (token.length == 1 && !isDigitString(token) && a.start > 0 && isHangul(charAt(t, a.start - 1))) continue
        val n = toNumber(token)
        if (n != null && n < 130) return Age(n.toInt(), null, null)
    }
    search("($NUMBER_RE)\\s?대", t)?.let { b ->
        val n = toNumber(b.group(1)!!)
        if (n != null && n % 10 == 0.0 && n in 10.0..100.0) return Age(null, null, if (n >= 90) "90대 이상" else "${n.toInt()}대")
    }
    if (search("(애기|아기|영아|유아|남아|여아|신생아)", t) != null) return Age(null, null, "10세 미만")
    return Age(null, null, null)
}

// ── 발생 시점 ──

private val ONSET_UNITS = mapOf("분" to 1.0, "시간" to 60.0, "일" to 1440.0, "주일" to 10080.0, "주" to 10080.0, "달" to 43200.0, "개월" to 43200.0)
private val NATIVE_DAYS = listOf("하루" to 1, "이틀" to 2, "사흘" to 3, "나흘" to 4, "닷새" to 5, "엿새" to 6, "이레" to 7,
    "열흘" to 10, "보름" to 15)

/** 발생 시각 구간 -> 몇 분 전. 계산할 수 없으면 null. */
fun parseOnset(text: String): Int? {
    // 시각(오후 2시 15분)은 경과 시간이 아니다
    var t = rx("($NUMBER_RE)\\s?시\\s?($NUMBER_RE)\\s?분").matcher(text).replaceAll(" ")
    t = t.replace("일주일", "1주일")
    if (search("(방금|막\\s?전)", t) != null) return 0
    if ("반나절" in t) return 720
    if (search("(엊그제|그저께|그제)", t) != null) return 2880
    search("(" + NATIVE_DAYS.joinToString("|") { it.first } + ")(?!\\s?종일)", t)?.let { d ->
        return NATIVE_DAYS.first { it.first == d.group(1) }.second * 1440
    }
    val m = search("($NUMBER_RE)\\s?(시간|분|주일|일|주|달|개월)(?!\\s?(?:후|뒤))(\\s?반)?(?:\\s?($NUMBER_RE)\\s?분)?", t) ?: return null
    val n = toNumber(m.group(1)!!) ?: return null
    val unit = ONSET_UNITS.getValue(m.group(2)!!)
    var minutes = n * unit
    if (m.group(3) != null) minutes += unit / 2
    val extra = m.group(4)
    if (extra != null && m.group(2) == "시간") minutes += toNumber(extra) ?: 0.0
    return minutes.toInt()
}
