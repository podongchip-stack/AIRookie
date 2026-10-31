package xyz.goldenlink.core

import kotlinx.serialization.Serializable
import java.time.Instant
import java.time.ZoneId

// [기록] 탭 — 지난 사건과 그 사건의 병원 응답·인계확인서를 기기에 날짜별로 쌓아 두는 기록. 기기 안에만 저장된다.
// 같은 구급차의 여러 기기가 같은 기록을 갖게 하는 동기화는 hub 보관소가 필요하다(계약: dashboard/android/README.md "기록 동기화 계약").

/** 병원이 이 사건에 한 응답 — hub 매칭 결과의 status 그대로 모은다 */
enum class ResponseGroup(val label: String) {
    CONFIRMED("이송 확정"), APPROVED("수용 승인"), REJECTED("거부"), NO_REPLY("무응답");

    companion object {
        /** pending(응답 없음)은 무응답으로 센다. 수용 승인했지만 선택되지 않은 병원은 따로 둔다 */
        fun of(status: String): ResponseGroup = when (status) {
            "confirmed" -> CONFIRMED
            "approved" -> APPROVED
            "rejected" -> REJECTED
            else -> NO_REPLY
        }
    }
}

@Serializable
data class RecordHospital(
    val hospitalId: String,
    val name: String,
    val status: String = "pending",
    val rejectReason: String? = null,
    val distanceKm: Double? = null,
    val etaMin: Double? = null,
) {
    val group: ResponseGroup get() = ResponseGroup.of(status)
}

/** 사건 하나의 기록. `handover`는 자동값에 구급대원이 고친 칸을 얹은 최종 값(칸 id → 값) */
@Serializable
data class CaseRecord(
    val caseId: String,
    val apid: String? = null,
    val ambulanceName: String? = null,
    /** 사건 시작 날짜(KST, yyyy-MM-dd) — 날짜별 목록의 키 */
    val date: String,
    /** 사건 시작 시각(epoch ms) */
    val startedAt: Long,
    val updatedAt: Long,
    val symptom: String? = null,
    val expectedDiagnosis: String? = null,
    val ktasLevel: Int? = null,
    val hospitals: List<RecordHospital> = emptyList(),
    val handover: Map<String, String> = emptyMap(),
    val closed: Boolean = false,
) {
    fun count(group: ResponseGroup): Int = hospitals.count { it.group == group }
}

object RecordDates {
    val zone: ZoneId = ZoneId.of("Asia/Seoul")

    fun of(epochMs: Long): String = Instant.ofEpochMilli(epochMs).atZone(zone).toLocalDate().toString()

    fun timeOf(epochMs: Long): String = Instant.ofEpochMilli(epochMs).atZone(zone).toLocalTime().let { "%02d:%02d".format(it.hour, it.minute) }
}
