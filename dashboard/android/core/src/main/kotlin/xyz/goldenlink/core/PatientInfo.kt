package xyz.goldenlink.core

import kotlinx.serialization.Serializable
import java.time.Instant
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.ln
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

// 환자 정보(통화 요약) 메시지와 표시 규칙. 아이패드 HubMessages.swift의 PatientInfo·Labels, BedReliability.swift와 같은 식이다.

@Serializable
data class Vital(
    val sequence: Int? = null,
    val sbp: Double? = null,
    val dbp: Double? = null,
    val hr: Double? = null,
    val rr: Double? = null,
    val bt: Double? = null,
    val spo2: Double? = null,
    val glucose: Double? = null,
) {
    /** 웹 formatVital과 같은 표기 */
    val text: String
        get() {
            fun n(v: Double?): String? = v?.let { if (it % 1.0 == 0.0) it.toInt().toString() else "%.1f".format(it) }
            val parts = mutableListOf<String>()
            n(sbp)?.let { parts += "BP $it/${n(dbp) ?: "?"}" }
            n(hr)?.let { parts += "HR $it" }
            n(rr)?.let { parts += "RR $it" }
            n(spo2)?.let { parts += "SpO₂ $it%" }
            n(bt)?.let { parts += "BT $it℃" }
            n(glucose)?.let { parts += "혈당 $it" }
            return parts.joinToString(" · ")
        }
}

@Serializable
data class PatientUpdate(val callRound: Int, val expectedDiagnosis: String? = null, val severityTag: String? = null, val ktasLevel: Int? = null)

/** 구급대원이 직접 적어 보낸 추가 정보 한 줄 — hub PatientInfo.extraNotes */
@Serializable
data class ExtraNote(val text: String, val at: String)

@Serializable
data class PatientInfo(
    val injuryStatus: List<String>? = null,
    val expectedDiagnosis: String? = null,
    val severityTag: String? = null,
    val patient: String? = null,
    val treatment: List<String>? = null,
    val ktasLevel: Int? = null,
    val vitals: List<Vital>? = null,
    val consciousness: String? = null,
    val onset: String? = null,
    val chiefComplaint: String? = null,
    val requiredDepartment: String? = null,
    val callRound: Int? = null,
    val previousCalls: List<PatientUpdate>? = null,
    val confirmedBy: String? = null,
    val confirmedAt: String? = null,
    val extraNotes: List<ExtraNote>? = null,
)

/** 병상 정보 신뢰도의 실시간 감쇠 — S(age) = 1 − Φ((ln age − ln m) / σ). dashboard/src/lib/bedReliability.ts·hub/bed_reliability.py와 같은 식.
 *  병원이 "현재 정보 확인"을 눌렀으면 조건부 생존 S(a)/S(u). 파라미터가 없으면 hub가 보낸 스칼라 그대로(정지값) */
object BedLive {
    data class Live(val authority: Double, val rArrive: Double, val live: Boolean, val ageSec: Double?)

    /** erfc(x) — Numerical Recipes erfcc, 상대 오차 1.2e-7 이하(확률을 % 정수로 보이는 데 충분) */
    private fun erfc(x: Double): Double {
        val z = abs(x)
        val t = 1.0 / (1.0 + 0.5 * z)
        val r = t * exp(-z * z - 1.26551223 + t * (1.00002368 + t * (0.37409196 + t * (0.09678418 + t * (-0.18628806 +
            t * (0.27886807 + t * (-1.13520398 + t * (1.48851587 + t * (-0.82215223 + t * 0.17087277)))))))))
        return if (x >= 0) r else 2.0 - r
    }

    fun survival(predT: Double, age: Double, sigma: Double): Double {
        if (age <= 0) return 1.0
        val z = (ln(max(age, 1e-9)) - ln(max(predT, 1e-9))) / (max(sigma, 1e-9) * Math.sqrt(2.0))
        return (0.5 * erfc(z)).coerceIn(0.0, 1.0)
    }

    fun of(br: BedReliability, nowMillis: Long): Live {
        val predT = br.predictedSurvivalSec
        val born = br.bornAt?.let { runCatching { Instant.parse(it).toEpochMilli() }.getOrNull() }
        if (predT == null || born == null) return Live(br.authority ?: 0.0, br.rArrive ?: 0.0, false, null)
        val sigma = br.sigma ?: 1.0
        val age = max((nowMillis - born) / 1000.0, 0.0)
        val sU = br.confirmedAgeSec?.let { max(survival(predT, it, sigma), 1e-12) } ?: 1.0
        return Live(min(survival(predT, age, sigma) / sU, 1.0), min(survival(predT, age + br.horizonSec, sigma) / sU, 1.0), true, age)
    }

    fun pct(p: Double): String = "${(p * 100).roundToInt()}%"
}

/** 화면 표시 문구 — 아이패드 Labels */
object DisplayLabels {
    /** 의식 수준 글자 → A·V·P·U 한 글자. hub는 "통증 반응(P)"처럼 풀어서 보내므로 괄호 안을 본다 */
    fun avpu(text: String?): String? {
        if (text.isNullOrEmpty()) return null
        Regex("\\(([AVPU])\\)").find(text)?.let { return it.groupValues[1] }
        val first = text.take(1).uppercase()
        return if (first in listOf("A", "V", "P", "U")) first else null
    }

    fun status(s: String): String = when (s) {
        "approved" -> "후보 등록"
        "rejected" -> "수용 불가"
        "confirmed" -> "이송 확정"
        else -> "판단 대기"
    }

    fun reject(code: String?): String = when (code) {
        "beds_full", "BEDS_FULL" -> "병상 없음"
        "NO_WARD" -> "병동 없음"
        "NO_DEPARTMENT" -> "진료과 없음"
        "NO_EQUIPMENT" -> "장비 없음"
        "ON_CALL_MISMATCH" -> "당직 불일치"
        "NIGHT_UNAVAILABLE" -> "야간 불가"
        "OR_OCCUPIED" -> "수술실 사용 중"
        "STAFF_BUSY" -> "의료진 바쁨"
        "SEVERITY_EXCEEDED" -> "중증도 초과"
        "AGE_LIMIT" -> "연령 제한"
        "UNSPECIFIED", null -> "사유 없음"
        else -> code
    }

    fun age(sec: Double): String = when {
        sec < 60 -> "방금"
        sec < 3600 -> "${max((sec / 60).roundToInt(), 1)}분 전"
        sec / 3600 < 10 -> "%.1f시간 전".format(sec / 3600)
        else -> "${(sec / 3600).roundToInt()}시간 전"
    }

    fun minutes(sec: Double): String = if (sec < 3600) "${max((sec / 60).roundToInt(), 1)}분" else "%.1f시간".format(sec / 3600)
}
